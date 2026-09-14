"""Safe planner orchestration with bounded validation retries."""
import json
import re
from .provider import MockProvider, Provider, ProviderHTTPError, ProviderConnectionError
from .schema import ASSERTION_FIELDS, TestPlan, json_schema

#: 发给模型的上下文长度上限。测试会断言真实上下文不超这个值——
#: 曾经因为把 36KB 的实测约定 JSON 原文拼进上下文而撞上它、导致流水线报错。
CONTEXT_LIMIT = 20_000
class PlanningError(ValueError): pass


def _failure_payload(failure: object) -> dict:
    """Return a bounded, JSON-safe failure representation for the model prompt.

    Failure records can come from either the dataclass model or the UI's plain
    dictionaries.  We deliberately copy only diagnostic fields; command lines,
    paths and raw process output are never sent to the provider.
    """
    if isinstance(failure, dict):
        source = failure
        return {
            key: source.get(key)
            for key in ("test_id", "cycle", "signal", "expected", "actual", "message", "severity")
            if key in source
        }
    result: dict = {}
    for key in ("test_id", "cycle", "signal", "expected", "actual", "message", "severity"):
        if hasattr(failure, key):
            result[key] = getattr(failure, key)
    return result


def _merge_additional_vectors(plan: TestPlan, additions: list[dict], *, max_new_vectors: int) -> TestPlan:
    """Merge model-proposed vectors while preserving existing vector names.

    New names are made unique deterministically (``foo_2``/``foo_3``), and the
    final object is passed through the same strict Pydantic validator as an
    initial plan.  This keeps the feedback loop from bypassing the TestPlan
    safety boundary.
    """
    if len(additions) > max_new_vectors:
        raise ValueError(f"model proposed {len(additions)} vectors; limit is {max_new_vectors}")
    data = plan.model_dump(mode="json")
    vectors = list(data.get("vectors", []))
    used = {item.get("name") for item in vectors if isinstance(item, dict)}
    counters: dict[str, int] = {}
    normalized: list[dict] = []
    for raw in additions:
        if not isinstance(raw, dict):
            raise TypeError("additional vector must be an object")
        item = dict(raw)
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("additional vector.name must be a non-empty string")
        base = raw_name.strip()
        candidate = base
        index = counters.get(base, 1)
        while candidate in used:
            index += 1
            candidate = f"{base}_{index}"
        counters[base] = index
        item["name"] = candidate
        used.add(candidate)
        normalized.append(item)
    data["vectors"] = vectors + normalized
    return TestPlan.model_validate(data)

def _decode_plan_json(raw: str) -> dict:
    """Decode strict JSON while tolerating a fenced JSON answer from a model."""
    candidates = [raw.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    # Some gateways prepend a short sentence despite the JSON-only instruction.
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            raise TypeError("top-level JSON must be an object")
        except (json.JSONDecodeError, TypeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error

def _unique_vector_names(data: dict) -> dict:
    """确定性修复模型常见的重复向量名，不改变激励或期望值。"""
    vectors = data.get("vectors")
    if not isinstance(vectors, list):
        return data
    seen: dict[str, int] = {}
    normalized = dict(data)
    normalized_vectors = []
    for index, raw in enumerate(vectors, start=1):
        if not isinstance(raw, dict):
            normalized_vectors.append(raw)
            continue
        item = dict(raw)
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            base = name.strip()
            count = seen.get(base, 0) + 1
            seen[base] = count
            if count > 1:
                item["name"] = f"{base}_{count}"
        normalized_vectors.append(item)
    normalized["vectors"] = normalized_vectors
    return normalized

def _normalize_reset(data: dict) -> dict:
    """Normalize common model reset shorthand into the strict reset schema."""
    reset = data.get("reset")
    if not isinstance(reset, dict):
        return data
    allowed = {"signal", "active_level", "active_low", "synchronous", "assert_cycles"}
    extra = [key for key in reset if key not in allowed]
    if not extra:
        return data
    normalized = dict(data)
    clean = {key: value for key, value in reset.items() if key in allowed}
    # Models sometimes emit {"sys_rst_n": 0, "active_level": 0, ...}.
    # Infer the signal only when exactly one safe-looking extra key exists.
    if "signal" not in clean and len(extra) == 1 and isinstance(extra[0], str):
        clean["signal"] = extra[0]
    normalized["reset"] = clean
    return normalized

#: 发给模型的受控断言模板清单。**由 `schema.ASSERTION_FIELDS` 渲染**，不手写：
#: 手写那一版曾经把 `signal_implies` 写成 `signal_implies{kind,signal,when_signal,then_signal}`，
#: 而校验器不接受 `signal`——模型严格照提示词写，却被我们自己的严格校验拒绝
#: （r10 实验里 130 次请求有 5 次栽在这个自相矛盾上，还被误记成"模型能力问题"）。
def assertion_templates_text() -> str:
    """渲染形如 ``signal_equals{kind,signal,value}`` 的模板清单（供提示词使用）。"""

    return ", ".join(f"{kind}{{{','.join(fields)}}}" for kind, fields in ASSERTION_FIELDS.items())


def _build_plan_prompt(design: str, objective: str, context: str | None) -> str:
    """拼出发给模型的计划提示词（纯函数，便于用测试钉住"提示词 == 校验器"）。"""

    return (
        "Return JSON only. No markdown, commands, paths, or executable code. "
        "Create concrete input vectors and expected outputs that obey the DUT contract. "
        "Every checked behavior must use expected output fields. "
        "Every vector.name MUST be unique; use short ASCII identifiers such as reset_1, normal_1, boundary_1. "
        "Reset MUST be an object with only signal, active_level or active_low, synchronous, and assert_cycles; "
        "put the reset port name in reset.signal (for example signal=sys_rst_n), never as a separate reset key. "
        "You may include an assertions array using only these templates: "
        + ", ".join(ASSERTION_FIELDS)
        + "; never include Verilog/SVA code. "
        "Each assertion object must use exactly the fields allowed for its kind, no more and no fewer: "
        + assertion_templates_text()
        + ". signal_implies has NO signal field: it needs when_signal and then_signal, and it only checks "
        "anything if you also give when_value and then_value (a missing value never matches a sampled signal). "
        "signal_sequence may omit cycles or set it equal to the number of values. "
        "Do not invent other kind names or fields. "
        "Design: %s Objective: %s DUT context: %s Schema: %s"
        % (design, objective, context or "not supplied", json.dumps(json_schema()))
    )


def _validation_summary(exc: Exception) -> str:
    """把 pydantic 的校验噪声压成一行人话。

    原始信息是一整段 ``1 validation error for TestPlan ... [type=value_error, input_value=[...],
    input_type=list] For further information visit https://errors.pydantic.dev/...``——用户读不出
    到底哪里错了。这里只保留 "字段路径: 原因"，并去掉文档链接与原始输入片段。
    """

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


def plan_tests(
    objective: str,
    design: str,
    provider: Provider | None = None,
    max_retries: int = 2,
    *,
    context: str | None = None,
) -> TestPlan:
    """向 provider 请求一份严格校验过的测试计划。

    ``provider=None`` 时用 :class:`MockProvider` 的默认返回值——那是一份**写死的演示
    计划**（``design="demo"``，向量驱动 ``rst_n``），只适合"最小可运行示例"。要按真实
    设计生成计划，请显式传入 provider：真实模型用 ``OpenAICompatibleProvider``，无密钥
    离线场景用 ``ai.debug_provider.offline_provider(contract)``（网页离线模式走的就是它）。
    拿演示计划去驱动一个没有 ``rst_n`` 的组合逻辑设计，会在生成 testbench 时被合约拒绝。

    重试会**把上一次的拒绝原因追加到提示词**里再问一次，因此偶尔一次格式失误能被真正纠正，
    而不是靠重新抽一次样碰运气。
    """

    if max_retries < 0 or max_retries > 5: raise ValueError("max_retries must be between 0 and 5")
    if context is not None and (not isinstance(context, str) or len(context) > CONTEXT_LIMIT):
        raise ValueError(f"context must be text of at most {CONTEXT_LIMIT} characters")
    prompt = _build_plan_prompt(design, objective, context)
    # 每次尝试的**拒绝原因**（人话版）：既用于最终报错，也在重试时发回给模型。
    errors: list[str] = []
    for attempt in range(max_retries+1):
        try:
            attempt_prompt = prompt
            if attempt:
                attempt_prompt = (
                    prompt
                    + "\nYour previous answer was rejected by strict validation: "
                    + errors[-1]
                    + "\nReturn a corrected JSON plan that fixes exactly that problem."
                )
            raw=(provider or MockProvider()).generate(attempt_prompt)
            if not isinstance(raw,str): raise TypeError("provider output must be text")
            data = _decode_plan_json(raw)
            return TestPlan.model_validate(_normalize_reset(_unique_vector_names(data)))
        except (ProviderHTTPError, ProviderConnectionError):
            # 认证、额度和限流问题不是测试计划格式错误；立即向上层报告，
            # 避免自动重试产生更多请求或费用。
            raise
        except Exception as exc: errors.append(_validation_summary(exc))
    raise PlanningError(
        f"模型返回了内容，但未通过严格校验（共 {len(errors)} 次尝试）：" + " | ".join(errors)
    )


def supplement_tests(
    plan: TestPlan,
    failures: list[object] | tuple[object, ...],
    provider: Provider | None = None,
    *,
    context: str | None = None,
    max_new_vectors: int = 20,
    max_retries: int = 0,
) -> TestPlan:
    """Ask the model for bounded additional vectors after a failed simulation.

    This is an explicit, one-shot operation; callers decide whether to run the
    returned plan again.  No automatic pipeline retry is performed here.
    """
    if not isinstance(plan, TestPlan):
        raise TypeError("plan must be an ai.schema.TestPlan")
    if not isinstance(failures, (list, tuple)):
        raise TypeError("failures must be a list or tuple")
    if not failures:
        raise ValueError("at least one simulation failure is required")
    if len(failures) > 50:
        raise ValueError("failures must contain at most 50 records")
    if not 1 <= max_new_vectors <= 100:
        raise ValueError("max_new_vectors must be between 1 and 100")
    if not 0 <= max_retries <= 2:
        raise ValueError("max_retries must be between 0 and 2")
    failure_items = [_failure_payload(item) for item in failures]
    prompt = (
        "Return JSON only in the form {\"vectors\":[...]} with additional "
        "test vectors that target the observed failures. Do not return the full "
        "plan, prose, commands, paths, or executable code. Every vector.name "
        "must be unique and must not reuse existing names. Keep vectors within "
        f"the schema and propose at most {max_new_vectors} vectors.\n"
        "Existing TestPlan:\n" + json.dumps(plan.model_dump(mode="json"), ensure_ascii=False) +
        "\nObserved failures (diagnostic fields only):\n" + json.dumps(failure_items, ensure_ascii=False, default=str) +
        "\nAdditional DUT context:\n" + (context or "not supplied") +
        "\nVector schema:\n" + json.dumps(json_schema().get("$defs", {}).get("TestVector", {}), ensure_ascii=False)
    )
    errors: list[str] = []
    for attempt in range(max_retries + 1):
        try:
            raw = (provider or MockProvider()).generate(prompt)
            if not isinstance(raw, str):
                raise TypeError("provider output must be text")
            data = _decode_plan_json(raw)
            additions = data.get("vectors")
            if not isinstance(additions, list) or not additions:
                raise ValueError("provider response must contain a non-empty vectors array")
            return _merge_additional_vectors(plan, additions, max_new_vectors=max_new_vectors)
        except (ProviderHTTPError, ProviderConnectionError):
            raise
        except Exception as exc:
            errors.append("attempt %d: %s" % (attempt + 1, exc))
    raise PlanningError("AI 补充测试计划严格校验失败：" + " | ".join(errors))
