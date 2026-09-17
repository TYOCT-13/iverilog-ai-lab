"""静态审查的 **AI 复核层**：规则命中是事实，AI 只在其上给建议。

为什么这样分层（而不是让 AI 直接读 RTL 出结论）：

- **事实与建议必须分开**。`core/static_review.py` 的 44 条规则是确定性的、可复现的、
  参与质量评分，并由 `tests/core/test_static_review_rules.py` 逐条用"最小反例 + 最小正例"
  钉住；AI 的输出不可复现，也可能编造不存在的问题。因此本模块**只增不改**：
  它绝不修改命中列表、绝不改评分，输出单独存放在 `ai_advice` 里，并标注来源。
- **AI 的价值在于"跨条目的判断"**：把 20 条命中归纳成几条根因、排优先级、指出哪些可能是
  误报、以及对照 44 条规则指出规则**没报但看起来可疑**的地方（`additional_suspects`，
  明确标注"未经规则验证"）。

数据外发口径（与 `docs/competition/opensource_resource_list.md` 一致）：
默认只发**结构化字段**（规则 ID、严重度、行号、规则名、命中的信号名），
**不发 RTL 源码**；调用方显式打开 `include_snippets=True` 时，才把"命中行的单行代码片段"
一并发出——这是为了让建议更具体，属于用户显式选择，页面上有独立勾选项与说明。

AI 输出同样走严格 Schema（未知字段、控制字符、越界长度一律拒绝），并且**幻觉防护**：
AI 引用的规则 ID 必须真的在本次命中集合或规则表里，否则该条被丢弃并记录在 meta 中。
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Mapping, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "AdditionalSuspect",
    "FalsePositiveCandidate",
    "ReviewPriority",
    "StaticReviewAdvice",
    "advise_on_static_review",
    "build_review_prompt",
    "offline_review_advice",
]

_SEVERITY_CN = {"error": "错误", "warn": "警告", "info": "提示"}
_LEVEL_CN = {"must_fix": "必须改", "should_fix": "建议改", "consider": "可选"}


class _ReviewClient(Protocol):
    def generate(self, prompt: str) -> str: ...


def _text(value: Any, name: str, *, max_length: int) -> str:
    """受控文本：必须是可打印字符串且不超长（AI 输出只是数据，不能带控制字符）。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} must be printable")
    return value.strip()


class ReviewPriority(BaseModel):
    """一条针对**已命中**规则的处理建议。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=64)
    line: int | None = Field(default=None, ge=1, le=100_000)
    level: Literal["must_fix", "should_fix", "consider"] = "should_fix"
    why: str = Field(min_length=1, max_length=400)
    fix: str = Field(min_length=1, max_length=400)

    @field_validator("why", "fix")
    @classmethod
    def safe_text(cls, value: str) -> str:
        return _text(value, "advice text", max_length=400)


class FalsePositiveCandidate(BaseModel):
    """AI 认为某条命中可能是误报——只作为**候选**呈现，不改命中事实。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=64)
    line: int | None = Field(default=None, ge=1, le=100_000)
    reason: str = Field(min_length=1, max_length=400)
    confidence: Literal["low", "medium", "high"] = "low"

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        return _text(value, "reason", max_length=400)


class AdditionalSuspect(BaseModel):
    """AI 对照规则表提出的**额外怀疑**：未经本仓库规则验证，单独展示。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str | None = Field(default=None, max_length=64)
    line: int | None = Field(default=None, ge=1, le=100_000)
    signal: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=400)
    confidence: Literal["low", "medium", "high"] = "low"

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        return _text(value, "reason", max_length=400)


class StaticReviewAdvice(BaseModel):
    """AI 复核结果（严格 Schema，未知字段直接拒绝）。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    priorities: list[ReviewPriority] = Field(default_factory=list, max_length=20)
    false_positive_candidates: list[FalsePositiveCandidate] = Field(default_factory=list, max_length=20)
    additional_suspects: list[AdditionalSuspect] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("summary")
    @classmethod
    def safe_summary(cls, value: str) -> str:
        return _text(value, "summary", max_length=600)

    @field_validator("assumptions")
    @classmethod
    def safe_assumptions(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list) or len(value) > 10:
            raise ValueError("assumptions must be a list of at most 10 items")
        return [_text(item, "assumption", max_length=300) for item in value]


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

def _rule_catalog(review: Mapping[str, Any]) -> list[dict[str, Any]]:
    """规则表（44 条）的紧凑形式：AI 用它判断"还该检查什么"。"""

    catalog = []
    for item in review.get("rule_set") or []:
        if not isinstance(item, Mapping):
            continue
        catalog.append(
            {
                "rule_id": str(item.get("rule_id", "")),
                "severity": str(item.get("severity", "")),
                "title": str(item.get("title", "")),
            }
        )
    return catalog


def _hit_payload(review: Mapping[str, Any], *, include_snippets: bool, max_findings: int) -> list[dict[str, Any]]:
    """命中列表的受控表示：默认**不含代码文本**。"""

    hits = []
    for item in (review.get("findings") or [])[:max_findings]:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "rule_id": str(item.get("rule_id", "")),
            "severity": str(item.get("severity", "")),
            "line": item.get("line"),
        }
        if include_snippets:
            # 只有调用方显式允许时才带代码文本（单行），并截断到 200 字符。
            entry["code_line"] = str(item.get("snippet", ""))[:200]
        hits.append(entry)
    return hits


def build_review_prompt(
    review: Mapping[str, Any],
    *,
    include_snippets: bool = False,
    design: str | None = None,
    max_findings: int = 40,
) -> str:
    """拼出静态审查复核提示词（纯函数，便于测试"默认不含源码"）。"""

    counts = review.get("counts") or {}
    hits = _hit_payload(review, include_snippets=include_snippets, max_findings=max_findings)
    payload = {
        "design": design or review.get("filename") or "",
        "is_testbench": bool(review.get("is_testbench")),
        "line_count": review.get("line_count"),
        "quality_score": review.get("quality_score"),
        "counts": {key: counts.get(key, 0) for key in ("error", "warn", "info")},
        "rule_catalog": _rule_catalog(review),
        "rule_hits": hits,
    }
    return (
        "You are reviewing a Verilog RTL file for a Chinese FPGA course project. "
        "Return JSON only, no markdown, no code fences, no executable code, no paths.\n"
        "Rules of engagement:\n"
        "1. `rule_hits` are FACTS produced by a deterministic linter. Do not claim they are wrong "
        "unless you give a concrete reason; never invent extra hits into that list.\n"
        "2. `rule_catalog` is the full rule set of the linter. Use it to point out what the linter "
        "did NOT flag but looks suspicious (list them only in `additional_suspects`).\n"
        "3. Write every natural-language field in Simplified Chinese, concise and specific.\n"
        "4. All `rule_id` values you emit MUST come from `rule_catalog`.\n"
        "5. Never include Verilog code blocks, commands, file paths, or secrets anywhere.\n"
        'Required JSON shape: {"summary": str, "priorities": [{"rule_id": str, "line": int|null, '
        '"level": "must_fix"|"should_fix"|"consider", "why": str, "fix": str}], '
        '"false_positive_candidates": [{"rule_id": str, "line": int|null, "reason": str, '
        '"confidence": "low"|"medium"|"high"}], "additional_suspects": [{"rule_id": str|null, '
        '"line": int|null, "signal": str|null, "reason": str, "confidence": "low"|"medium"|"high"}], '
        '"assumptions": [str]}\n'
        "Limits: priorities<=20, false_positive_candidates<=20, additional_suspects<=10, "
        "assumptions<=10, each text field<=400 characters, summary<=600 characters.\n"
        "Input:\n" + json.dumps(payload, ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# 调用与校验
# ---------------------------------------------------------------------------

def _decode_json_object(raw: str) -> dict[str, Any]:
    """容忍围栏/前后缀的严格 JSON 解析（与 planner 同一套容忍度）。"""

    candidates = [raw.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            last_error = exc
            continue
        if isinstance(data, dict):
            return data
        last_error = TypeError("top-level JSON must be an object")
    assert last_error is not None
    raise last_error


def _validation_summary(exc: Exception) -> str:
    """把 pydantic 的噪声压成一行人话（与 planner 里同样的处理）。"""

    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    parts: list[str] = []
    for item in errors():
        if not isinstance(item, dict):
            continue
        location = ".".join(str(part) for part in item.get("loc", ()) if part != "__root__")
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        parts.append(f"{location}: {message}" if location else message)
    return "；".join(parts) or str(exc)


def _filter_invented_rule_ids(advice: StaticReviewAdvice, known: set[str]) -> tuple[StaticReviewAdvice, list[str]]:
    """丢掉引用了不存在规则的条目，并返回被丢掉的 rule_id（幻觉防护）。"""

    dropped: list[str] = []

    def keep(rule_id: str | None) -> bool:
        if rule_id is None:
            return True
        if rule_id in known:
            return True
        dropped.append(rule_id)
        return False

    filtered = advice.model_copy(
        update={
            "priorities": [item for item in advice.priorities if keep(item.rule_id)],
            "false_positive_candidates": [item for item in advice.false_positive_candidates if keep(item.rule_id)],
            "additional_suspects": [item for item in advice.additional_suspects if keep(item.rule_id)],
        }
    )
    return filtered, sorted(set(dropped))


def advise_on_static_review(
    provider: _ReviewClient,
    review: Mapping[str, Any],
    *,
    include_snippets: bool = False,
    design: str | None = None,
    max_retries: int = 1,
) -> tuple[StaticReviewAdvice, dict[str, Any]]:
    """请 AI 复核静态审查结果；返回 (建议, 元信息)。

    元信息里记录本次实际发出去的内容规模、尝试次数、被丢弃的幻觉规则 ID——报告与页面
    据此如实说明"这层建议是怎么来的"，而不是把它混进事实层。
    """

    if max_retries < 0 or max_retries > 2:
        raise ValueError("max_retries must be between 0 and 2")
    prompt = build_review_prompt(review, include_snippets=include_snippets, design=design)
    known = {str(item.get("rule_id")) for item in _rule_catalog(review)}
    known |= {str(item.get("rule_id")) for item in (review.get("findings") or []) if isinstance(item, Mapping)}
    errors: list[str] = []
    for attempt in range(max_retries + 1):
        try:
            attempt_prompt = prompt
            if attempt:
                attempt_prompt = (
                    prompt
                    + "\nYour previous answer was rejected by strict validation: "
                    + errors[-1]
                    + "\nReturn a corrected JSON object that fixes exactly that problem."
                )
            raw = provider.generate(attempt_prompt)
            if not isinstance(raw, str):
                raise TypeError("provider output must be text")
            advice = StaticReviewAdvice.model_validate(_decode_json_object(raw))
            advice, dropped = _filter_invented_rule_ids(advice, known)
            meta = {
                "source": "ai",
                "attempts": attempt + 1,
                "included_code_snippets": bool(include_snippets),
                "prompt_chars": len(prompt),
                "rule_hits_sent": len(_hit_payload(review, include_snippets=include_snippets, max_findings=40)),
                "dropped_unknown_rule_ids": dropped,
                "review_sha256": review.get("source_sha256"),
            }
            return advice, meta
        except Exception as exc:  # noqa: BLE001 - 统一转成可读信息
            errors.append(_validation_summary(exc))
    raise ValueError("AI 复核输出未通过严格校验：" + " | ".join(errors))


# ---------------------------------------------------------------------------
# 离线兜底：没有密钥时也给出"按规则表排序"的建议（明确标注不是 AI）
# ---------------------------------------------------------------------------

_LEVEL_BY_SEVERITY: dict[str, Literal["must_fix", "should_fix", "consider"]] = {
    "error": "must_fix",
    "warn": "should_fix",
    "info": "consider",
}


def offline_review_advice(review: Mapping[str, Any], *, max_items: int = 20) -> StaticReviewAdvice:
    """"离线建议"：不做任何推理，只按严重度排序并复用规则自带的建议文本。

    存在的意义：页面在无密钥环境下仍要能用。它的文案会明确写清"这不是 AI 输出"，
    以免把规则表的内容误当成模型判断。
    """

    findings = [item for item in (review.get("findings") or []) if isinstance(item, Mapping)]
    counts = review.get("counts") or {}
    ordered = sorted(findings, key=lambda item: ({"error": 0, "warn": 1, "info": 2}.get(str(item.get("severity")), 3), int(item.get("line") or 0)))
    priorities: list[ReviewPriority] = []
    for item in ordered[:max_items]:
        priorities.append(
            ReviewPriority(
                rule_id=str(item.get("rule_id", "unknown")),
                line=int(item["line"]) if item.get("line") else None,
                level=_LEVEL_BY_SEVERITY.get(str(item.get("severity")), "consider"),
                why=str(item.get("message", ""))[:400] or "规则命中",
                fix=str(item.get("suggestion", ""))[:400] or "按规则说明修改",
            )
        )
    summary = (
        f"共 {len(findings)} 条命中：错误 {counts.get('error', 0)} / 警告 {counts.get('warn', 0)} / "
        f"提示 {counts.get('info', 0)}；按严重度从高到低排列，处理顺序即此列表顺序。"
        if findings
        else "当前规则集没有命中任何问题。"
    )
    return StaticReviewAdvice(
        summary=summary,
        priorities=priorities,
        false_positive_candidates=[],
        additional_suspects=[],
        assumptions=["本建议由规则表直接生成（离线模式，非 AI 输出）：未做跨条目归纳，也不判断误报。"],
    )
