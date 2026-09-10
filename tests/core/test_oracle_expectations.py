"""权威预言机与多周期期望值语义的回归测试。

这些测试锁定的是本次修复的三个具体缺陷：

1. 多周期向量的 expected 只在最后一个周期检查（否则合法的中间状态会被判失败）；
2. 内置案例的期望值由参考模型复算值决定，AI 猜错数字不能伪造失败；
3. 参考模型建模的输出即使 AI 没写期望值也必须被检查（否则缺陷可以漏检）。
"""

from __future__ import annotations

import pytest

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import (
    check_plan_consistency,
    override_plan_expectations,
    reference_expectations,
)
from iverilog_ai.core.testbench import TestbenchGenerator

COUNTER_CONTRACT = {
    "module": "mod10_counter",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "enable", "direction": "input", "width": 1},
        {"name": "count", "direction": "output", "width": 4, "initial": 0},
    ],
    "clock": {"signal": "clk", "period_ns": 10},
    "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
}


def _plan(**overrides) -> TestPlan:
    payload = {
        "schema_version": "1.0",
        "design": "mod10_counter",
        "objective": "oracle regression",
        "clock_period_ns": 10,
        "reset": {"active_low": True},
        "vectors": [
            {"name": "hold", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 7, "expected": {"count": 9}},
        ],
    }
    payload.update(overrides)
    return TestPlan.model_validate(payload)


# --------------------------------------------------------------------------
# 1. 多周期期望值语义
# --------------------------------------------------------------------------
def test_multi_cycle_vector_checks_expectation_only_at_final_cycle(tmp_path):
    """7 周期向量只能产生一条检查记录，而不是 7 条。"""

    plan = _plan()
    contract = DutContract.from_dict(COUNTER_CONTRACT)
    path = TestbenchGenerator().generate(plan, contract, tmp_path)
    source = path.read_text(encoding="utf-8")
    checks = source.count("checks = checks + 1;")
    assert checks == 1, "multi-cycle vector must be checked once, at its final cycle"
    # 期望值来自计划中的 AI 数字（此测试直接调用生成器，未经过预言机）。
    assert source.count("if (count !== 4'b1001)") == 1

    # 每一个周期仍然必须施加激励：7 次 enable 赋值。
    assert source.count("enable = 1'b1;") == 7


def test_single_cycle_vector_still_checked_every_vector(tmp_path):
    plan = _plan(
        vectors=[
            {"name": "a", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 1, "expected": {"count": 1}},
            {"name": "b", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 1, "expected": {"count": 2}},
        ]
    )
    contract = DutContract.from_dict(COUNTER_CONTRACT)
    path = TestbenchGenerator().generate(plan, contract, tmp_path)
    assert path.read_text(encoding="utf-8").count("checks = checks + 1;") == 2


# --------------------------------------------------------------------------
# 2. 参考模型作为权威预言机
# --------------------------------------------------------------------------
def test_reference_expectations_reproduce_multi_cycle_end_state():
    plan = _plan()
    expectations = reference_expectations(plan, "mod10_counter", COUNTER_CONTRACT)
    assert expectations == {"hold": {"count": 7}}


def test_consistency_diagnoses_ai_expectation_mismatch():
    report = check_plan_consistency(_plan(), "mod10_counter", COUNTER_CONTRACT)
    assert report["status"] == "warn"
    assert report["checked_expected"] == 1
    assert report["matched_expected"] == 0
    assert report["warnings"][0]["reference"] == 7
    assert report["warnings"][0]["expected"] == 9
    assert report["evidence_level"] == "reference_model"


def test_override_replaces_ai_numbers_with_reference_values():
    plan = _plan()
    expectations = reference_expectations(plan, "mod10_counter", COUNTER_CONTRACT)
    authoritative = override_plan_expectations(plan, expectations)
    assert authoritative.vectors[0].expected == {"count": 7}
    # 原始计划必须保持不变，便于审计 AI 与参考模型的差异。
    assert plan.vectors[0].expected == {"count": 9}


def test_override_fills_outputs_the_ai_left_unchecked():
    """AI 少写期望值不能让检查静默消失，否则缺陷会漏检。"""

    plan = _plan(vectors=[{"name": "hold", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 3, "expected": {}}])
    expectations = reference_expectations(plan, "mod10_counter", COUNTER_CONTRACT)
    authoritative = override_plan_expectations(plan, expectations)
    assert authoritative.vectors[0].expected == {"count": 3}

    # 显式关闭填充时才允许保留空洞。
    preserved = override_plan_expectations(plan, expectations, fill_missing=False)
    assert preserved.vectors[0].expected == {}


def test_reference_expectations_skip_unsupported_design():
    plan = _plan(design="not_a_bundled_design")
    assert reference_expectations(plan, "not_a_bundled_design", COUNTER_CONTRACT) == {}
    report = check_plan_consistency(plan, "not_a_bundled_design", COUNTER_CONTRACT)
    assert report["status"] == "skipped"


# --------------------------------------------------------------------------
# 3. 复位前初值观测
# --------------------------------------------------------------------------
def test_pre_reset_sampling_uses_contract_initial(tmp_path):
    plan = _plan(
        sample_before_reset=True,
        pre_reset_expected={},
        vectors=[{"name": "hold", "inputs": {"rst_n": 1, "enable": 0}, "cycles": 1, "expected": {"count": 0}}],
    )
    contract = DutContract.from_dict(COUNTER_CONTRACT)
    path = TestbenchGenerator().generate(plan, contract, tmp_path)
    source = path.read_text(encoding="utf-8")
    assert '\\"test_id\\":\\"pre_reset\\"' in source
    assert "if (count !== 4'b0000)" in source


def test_pre_reset_sampling_observes_without_asserting_when_undeclared(tmp_path):
    import copy

    contract = copy.deepcopy(COUNTER_CONTRACT)
    for port in contract["ports"]:
        port.pop("initial", None)
    plan = _plan(
        sample_before_reset=True,
        pre_reset_expected={},
        vectors=[{"name": "hold", "inputs": {"rst_n": 1, "enable": 0}, "cycles": 1, "expected": {"count": 0}}],
    )
    path = TestbenchGenerator().generate(plan, DutContract.from_dict(contract), tmp_path)
    source = path.read_text(encoding="utf-8")
    # 只观测、不断言：pre_reset 记录为 ok=true 且没有 expected/actual 字段。
    assert '\\"test_id\\":\\"pre_reset\\",\\"cycle\\":%0d}' in source
    assert 'pre_reset\\",\\"cycle\\":%0d,\\"signal' not in source


def test_port_initial_must_fit_width():
    from iverilog_ai.core.contracts import ContractValidationError

    with pytest.raises(ContractValidationError):
        DutContract.from_dict(
            {
                "module": "m",
                "ports": [
                    {"name": "clk", "direction": "input", "width": 1},
                    {"name": "count", "direction": "output", "width": 4, "initial": 16},
                ],
            }
        )


def test_contract_round_trip_keeps_initial_only_when_declared():
    contract = DutContract.from_dict(COUNTER_CONTRACT)
    payload = contract.to_dict()
    count = next(port for port in payload["ports"] if port["name"] == "count")
    assert count["initial"] == 0
    minimal = DutContract.from_dict(
        {"module": "m", "ports": [{"name": "y", "direction": "output", "width": 1}]}
    )
    assert "initial" not in minimal.to_dict()["ports"][0]
