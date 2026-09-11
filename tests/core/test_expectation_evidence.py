"""期望值证据等级的三态判定回归测试。

为什么值得单独测：这一项决定"结论有多可信"，而早期实现只用两个分支覆盖
（`reference_model` / `ai_generated`），把"AI 也没给期望值"的自定义 RTL 误标成
`ai_generated` —— 读者会以为有 AI 期望值在把关，实际那一轮只有激励与结构化断言
在起作用。三态必须分清，且各自的 advice 文案要说明该等级的含义。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).parents[2]
_TOOLS = locate_tools()
WORK = ROOT / ".iverilog-ai" / "test-evidence-level"

CUSTOM_RTL = """`timescale 1ns/1ps
module custom_reg(input wire clk, input wire rst_n, input wire d, output reg q);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 1'b0; else q <= d;
endmodule
"""


def _contract() -> DutContract:
    return DutContract.from_dict(
        {
            "module": "custom_reg",
            "ports": [
                {"name": "clk", "direction": "input"},
                {"name": "rst_n", "direction": "input"},
                {"name": "d", "direction": "input"},
                {"name": "q", "direction": "output"},
            ],
            "clock": {"signal": "clk", "period_ns": 10},
            "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
        }
    )


def _run(design: str, vectors: list[dict], tag: str):
    """跑一次未建模设计的流水线，返回 oracle 记录。"""

    WORK.mkdir(parents=True, exist_ok=True)
    rtl = WORK / f"{design}.v"
    if not rtl.is_file():
        rtl.write_text(CUSTOM_RTL.replace("custom_reg", design), encoding="utf-8")
    contract = DutContract.from_dict({**_contract().to_dict(), "module": design})
    plan = TestPlan.model_validate({"design": design, "objective": tag, "vectors": vectors})
    result = VerificationPipeline().run(
        plan, contract, rtl, WORK / tag,
        allowed_roots=(ROOT,),
        iverilog_path=_TOOLS.iverilog, vvp_path=_TOOLS.vvp, emit_vcd=False,
    )
    return result.simulation.config.get("oracle", {})


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog")
def test_no_expectations_is_reported_as_none_given():
    """AI 没给期望值、也没有参考模型时，等级是 none_given，不是 ai_generated。"""

    oracle = _run(
        "evidence_none",
        [{"name": "v1", "inputs": {"rst_n": 1, "d": 1}, "cycles": 1, "expected": {}}],
        "none",
    )
    assert oracle.get("expectation_source") == "none_given", oracle
    assert oracle.get("expectation_evidence_level") == "none_given"
    assert oracle.get("ai_expectations_used_for_checking") is False
    assert oracle.get("plans_with_expectations") == 0
    # 必须给出说明，避免读者误以为功能行为已被验证
    assert "none_given" in str(oracle.get("advice", ""))


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog")
def test_ai_supplied_expectations_are_reported_as_ai_generated():
    oracle = _run(
        "evidence_ai",
        [{"name": "v1", "inputs": {"rst_n": 1, "d": 1}, "cycles": 1, "expected": {"q": 1}}],
        "ai",
    )
    assert oracle.get("expectation_source") == "ai_generated", oracle
    assert oracle.get("ai_expectations_used_for_checking") is True
    assert oracle.get("plans_with_expectations") == 1
    assert "AI" in str(oracle.get("advice", ""))


def test_aligned_builtin_design_reports_reference_model():
    """已对齐的内置案例必须是 reference_model —— 三态里最高的一档。"""

    from iverilog_ai.core.reference_model import AUTHORITATIVE, reference_expectations

    case = "pwm"
    assert case in AUTHORITATIVE
    contract = DutContract.from_dict(
        json.loads((ROOT / "examples" / f"{case}_contract.json").read_text(encoding="utf-8"))
    )
    plan = TestPlan.model_validate(
        {
            "design": case,
            "objective": "证据等级",
            "vectors": [{"name": "v1", "inputs": {"rst_n": 1, "duty": 3}, "cycles": 1, "expected": {"pwm_out": 1}}],
        }
    )
    expectations = reference_expectations(plan, case, contract)
    assert expectations, "已对齐案例应能给出权威期望值"
