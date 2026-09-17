"""AI 静态审查复核层的回归测试。

这一层的设计原则是"**只增不改**"：规则命中是事实（确定性、可复现、参与评分），
AI 只在其上给建议。因此测试要钉住四件事：

1. **默认不发源码**：不勾选时提示词里不能出现命中行的代码文本（披露口径）；
2. **严格 Schema**：未知字段/超长文本/控制字符一律拒绝，失败时带着原因重试一次；
3. **幻觉防护**：AI 引用的规则 ID 必须真实存在，否则该条被丢弃并记录；
4. **离线兜底**：没有密钥时给出确定性建议，并**明确标注不是 AI 输出**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.ai import advise_on_static_review, offline_review_advice
from iverilog_ai.ai.review_advisor import (
    StaticReviewAdvice,
    build_review_prompt,
)
from iverilog_ai.core.static_review import review_rtl_source

ROOT = Path(__file__).resolve().parents[2]

#: 一份会命中多条规则的最小 RTL（异步复位 + 阻塞赋值 + 缺 timescale）。
BAD_RTL = """module m(input wire clk, input wire rst_n, output reg q);
  reg wide_unused_signal;
  always @(posedge clk or negedge rst_n) begin
    q = 1'b0;
  end
endmodule
"""


@pytest.fixture()
def review() -> dict:
    return review_rtl_source(BAD_RTL, filename="m.v")


def _advice_payload(**overrides) -> dict:
    payload = {
        "summary": "优先处理复位同步与赋值风格。",
        "priorities": [
            {
                "rule_id": "async-reset-no-sync",
                "line": 3,
                "level": "must_fix",
                "why": "异步复位没有同步释放，跨时钟域释放会引入亚稳态风险",
                "fix": "改成异步复位、同步释放：加两级同步器后再驱动复位",
            }
        ],
        "false_positive_candidates": [
            {"rule_id": "unused-signal", "line": 2, "reason": "该信号在未展示的 generate 分支里被使用", "confidence": "low"}
        ],
        "additional_suspects": [
            {"rule_id": "missing-default-case", "line": None, "signal": None, "reason": "未看到 default 分支", "confidence": "medium"}
        ],
        "assumptions": ["未提供工程约束文件"],
    }
    payload.update(overrides)
    return payload


class FakeProvider:
    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. 数据外发：默认不带源码
# ---------------------------------------------------------------------------

def test_prompt_excludes_code_text_by_default(review):
    prompt = build_review_prompt(review, include_snippets=False)
    for finding in review["findings"]:
        snippet = str(finding.get("snippet", "")).strip()
        if snippet:
            assert snippet not in prompt, f"默认提示词里出现了源码文本：{snippet}"
    # 但结构化字段必须在（否则 AI 无从判断）
    assert "async-reset-no-sync" in prompt
    assert "rule_catalog" in prompt and "rule_hits" in prompt


def test_prompt_includes_code_text_only_when_opted_in(review):
    prompt = build_review_prompt(review, include_snippets=True)
    snippets = [str(item.get("snippet", "")).strip() for item in review["findings"]]
    assert any(snippet and snippet in prompt for snippet in snippets), "勾选后应带上命中行片段"
    # 片段必须被截断，不能整文件泄出去
    assert len(prompt) < 20_000


def test_prompt_contains_full_rule_catalog_and_json_only_instruction(review):
    prompt = build_review_prompt(review, include_snippets=False, design="mod10_counter")
    assert '"rule_id": "missing-timescale"' in prompt          # 未命中规则也在目录里（供 AI 对照）
    assert review["source_sha256"] not in prompt                # 不外发文件哈希
    assert "Return JSON only" in prompt
    assert "Simplified Chinese" in prompt


# ---------------------------------------------------------------------------
# 2. 严格 Schema 与重试
# ---------------------------------------------------------------------------

def test_unknown_field_is_rejected_and_retried_with_reason(review):
    invalid = json.dumps({"summary": "x", "priorities": [{"rule_id": "unused-signal", "unexpected": True}]})
    provider = FakeProvider(invalid, _advice_payload())
    advice, meta = advise_on_static_review(provider, review, max_retries=1)
    assert meta["attempts"] == 2
    assert len(provider.prompts) == 2
    assert "strict validation" in provider.prompts[1]
    assert "unexpected" in provider.prompts[1] or "Extra inputs" in provider.prompts[1]
    assert advice.priorities and advice.priorities[0].rule_id == "async-reset-no-sync"


def test_invalid_output_raises_readable_error_without_leaking_raw_input(review):
    provider = FakeProvider(json.dumps({"summary": "x", "priorities": [{"rule_id": "a", "why": "y"}]}))
    with pytest.raises(ValueError) as caught:
        advise_on_static_review(provider, review, max_retries=0)
    message = str(caught.value)
    assert "严格校验" in message
    assert "input_value=" not in message and "errors.pydantic.dev" not in message


@pytest.mark.parametrize(
    "broken",
    [
        {"summary": ""},
        {"summary": "x" * 601},
        {"summary": "带控制字符\x07"},
        {"summary": "x", "priorities": [{"rule_id": "a", "why": "y", "fix": "z", "level": "urgent"}]},
        {"summary": "x", "assumptions": ["a"] * 11},
    ],
)
def test_schema_rejects_out_of_contract_values(broken):
    with pytest.raises(Exception):
        StaticReviewAdvice.model_validate(broken)


# ---------------------------------------------------------------------------
# 3. 幻觉防护
# ---------------------------------------------------------------------------

def test_invented_rule_ids_are_dropped_and_recorded(review):
    payload = _advice_payload()
    payload["priorities"].append({"rule_id": "totally-made-up", "line": 1, "level": "consider", "why": "幻觉", "fix": "应被丢弃"})
    payload["additional_suspects"].append({"rule_id": "also-fake", "line": 2, "signal": None, "reason": "幻觉", "confidence": "low"})
    advice, meta = advise_on_static_review(FakeProvider(payload), review, max_retries=0)
    assert [item.rule_id for item in advice.priorities] == ["async-reset-no-sync"]
    assert all(item.rule_id != "also-fake" for item in advice.additional_suspects)
    assert meta["dropped_unknown_rule_ids"] == ["also-fake", "totally-made-up"]


def test_meta_records_what_was_sent(review):
    _, meta = advise_on_static_review(FakeProvider(_advice_payload()), review, include_snippets=False, max_retries=0)
    assert meta["source"] == "ai"
    assert meta["included_code_snippets"] is False
    assert meta["rule_hits_sent"] == len(review["findings"])
    assert meta["review_sha256"] == review["source_sha256"]
    assert meta["prompt_chars"] > 0


# ---------------------------------------------------------------------------
# 4. 离线兜底
# ---------------------------------------------------------------------------

def test_offline_advice_is_deterministic_and_labeled_non_ai(review):
    first = offline_review_advice(review)
    second = offline_review_advice(review)
    assert first.model_dump() == second.model_dump(), "离线建议必须是确定性的"
    assert first.assumptions and "非 AI" in first.assumptions[0]
    assert first.false_positive_candidates == [] and first.additional_suspects == []
    # 按严重度排序：错误 > 警告 > 提示
    order = {"must_fix": 0, "should_fix": 1, "consider": 2}
    levels = [order[item.level] for item in first.priorities]
    assert levels == sorted(levels)
    # 复用规则表自带建议文本，而不是现场编造
    suggestions = {str(item["suggestion"]) for item in review["findings"]}
    assert all(item.fix in suggestions for item in first.priorities)


def test_offline_advice_handles_clean_file():
    clean = review_rtl_source("`timescale 1ns/1ps\nmodule m(input wire clk); endmodule\n", filename="clean.v")
    advice = offline_review_advice(clean)
    assert advice.priorities == []
    assert "没有命中" in advice.summary
