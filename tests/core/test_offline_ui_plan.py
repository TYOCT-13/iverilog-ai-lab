"""离线模式的规划结果必须能真正驱动所选案例。

真实事故（用户反馈）：网页选「离线 Mock」+「simple_alu」（组合逻辑，合约里没有
时钟、也没有复位），点「生成测试计划」成功，但点「执行 AI 计划并生成 testbench」
报 ``vectors[0].inputs contains unknown port 'rst_n'``；同一个案例点「执行真实
Icarus 仿真」却是通过的——于是看起来像"离线模式坏了、仿真没问题"。

根因：离线分支接的是 ``MockProvider()`` 的默认返回值，那是一份**写死的演示计划**
（``design="demo"``，向量固定驱动 ``rst_n``），与所选案例毫无关系。它在生成
testbench 时才被下游按合约拒绝——计划本身是"合法 JSON"，严格 Schema 抓不到它。

本文件把"离线模式必须按合约生成激励"钉成回归：
1. 15 个内置案例全部能生成可仿真的 testbench，且向量只触碰合约声明的输入端口；
2. 组合逻辑案例（``simple_alu`` / ``mux4``）绝不出现 ``rst_n`` 之类的凭空复位；
3. 离线"补充测试向量"也必须按合约、且条数留在调用方上限内；
4. ``offline_provider`` 的入参边界；
5. 未知端口的报错必须能自证原因（列出合法端口与计划里的设计名）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.ai import MockProvider, offline_provider, plan_tests, supplement_tests
from iverilog_ai.ai.debug_provider import DeterministicLocalProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.benchmark_cases import CASE_TABLE
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.testbench import TestbenchGenerationError, TestbenchGenerator

ROOT = Path(__file__).resolve().parents[2]

#: 合约里没有时钟、也没有复位的组合逻辑案例（用户的报错就出在第一个）。
COMBINATIONAL_CASES = ("simple_alu", "mux4")


def _contract(case: str) -> DutContract:
    return DutContract.from_json((ROOT / "examples" / f"{case}_contract.json").read_text(encoding="utf-8"))


def _offline_plan(case: str) -> TestPlan:
    return plan_tests(
        "覆盖边界与状态转换",
        case,
        provider=offline_provider(_contract(case)),
        max_retries=0,
    )


@pytest.mark.parametrize("case", sorted(CASE_TABLE))
def test_offline_plan_generates_a_simulatable_testbench(case):
    """离线模式对每个内置案例都必须产出能通过 testbench 生成的计划。"""

    contract = _contract(case)
    plan = _offline_plan(case)
    declared_inputs = {port.name for port in contract.ports if port.is_input}
    stray = sorted({name for vector in plan.vectors for name in vector.inputs if name not in declared_inputs})
    assert not stray, f"{case} 的离线计划驱动了合约里不存在的端口：{stray}"
    assert plan.design == case, f"{case} 的离线计划设计名不对：{plan.design!r}"
    # 生成器会按合约逐条校验端口、位宽与时钟，这里让它真的跑一遍
    TestbenchGenerator().generate(plan, contract, ROOT / ".iverilog-ai" / "offline-plan-test" / case)


@pytest.mark.parametrize("case", COMBINATIONAL_CASES)
def test_offline_plan_for_combinational_cases_never_invents_a_reset(case):
    """组合逻辑案例的合约没有复位端口，离线计划就不该出现任何复位类信号。"""

    contract = _contract(case)
    assert contract.clock is None and contract.reset is None, f"{case} 不再是无时钟无复位的案例，请更新本用例"
    plan = _offline_plan(case)
    reset_like = sorted(
        {name for vector in plan.vectors for name in vector.inputs if "rst" in name.lower() or "reset" in name.lower()}
    )
    assert not reset_like, f"{case} 的离线计划凭空驱动了复位信号：{reset_like}"


def test_canned_mock_plan_is_rejected_for_a_combinational_contract():
    """把写死的演示计划直接喂给组合逻辑合约，必须**报错**而不是静默通过。

    这正是原来的故障路径：报错本身是对的，问题在于网页不该把离线模式接到它上面。
    顺便钉住报错内容——只说"unknown port"不足以定位，必须给出合法端口与设计名。
    """

    contract = _contract("simple_alu")
    canned = TestPlan.model_validate(json.loads(MockProvider().generate("")))
    assert "rst_n" in canned.vectors[0].inputs, "MockProvider 的默认演示计划变了，请重新确认本用例的前提"

    with pytest.raises(TestbenchGenerationError) as excinfo:
        TestbenchGenerator().generate(canned, contract, ROOT / ".iverilog-ai" / "offline-plan-test" / "canned")
    message = str(excinfo.value)
    assert "rst_n" in message
    assert "simple_alu" in message, message
    for port in ("a", "b", "op"):
        assert port in message, message
    assert "demo" in message, "报错应指出计划是为另一个设计（demo）生成的"


def test_unknown_expected_port_lists_the_real_outputs():
    contract = _contract("simple_alu")
    plan = TestPlan.model_validate(
        {
            "design": "simple_alu",
            "objective": "negative",
            "vectors": [{"name": "v1", "inputs": {"a": 1}, "cycles": 1, "expected": {"nonexistent": 1}}],
        }
    )
    with pytest.raises(TestbenchGenerationError) as excinfo:
        TestbenchGenerator().generate(plan, contract, ROOT / ".iverilog-ai" / "offline-plan-test" / "bad-expected")
    message = str(excinfo.value)
    assert "nonexistent" in message
    assert "result" in message and "carry" in message, message


@pytest.mark.parametrize("case", sorted(CASE_TABLE))
def test_offline_supplement_stays_within_the_merge_limit(case):
    """离线模式补向量时，条数必须留在调用方的上限之内。

    离线规划器一次给出整份计划（通用激励 + 该案例的边界激励），如果按默认 24 条再补一次，
    `supplement_tests(max_new_vectors=10)` 会被严格校验直接拒绝——页面按钮报错而不是补上向量。
    网页因此显式传 `vector_count=2`，这里按同一参数钉住所有案例。
    """

    contract = _contract(case)
    plan = plan_tests("覆盖边界", case, provider=offline_provider(contract), max_retries=0)
    merged = supplement_tests(
        plan,
        [{"test_id": "t1", "signal": "out", "expected": 1, "actual": 0, "message": "mismatch", "severity": "warn"}],
        offline_provider(contract, vector_count=2),
        context="DUT contract:\n" + contract.to_json(),
        max_new_vectors=10,
        max_retries=0,
    )
    assert len(merged.vectors) - len(plan.vectors) <= 10
    # 合并后的计划仍必须能生成 testbench（新向量名去重、端口合法）
    TestbenchGenerator().generate(merged, contract, ROOT / ".iverilog-ai" / "offline-plan-test" / f"{case}-supplement")


def test_offline_provider_accepts_contract_objects_and_mappings():
    contract = _contract("pwm")
    from_object = offline_provider(contract)
    from_mapping = offline_provider(contract.to_dict())
    assert isinstance(from_object, DeterministicLocalProvider)
    assert from_object.design == "pwm" and from_mapping.design == "pwm"

    # 显式给出的设计名优先于合约里的模块名（自定义 RTL 场景）
    assert offline_provider(contract, design="custom_top").design == "custom_top"
    # 少量向量：网页"补充测试向量"要在 max_new_vectors 之内
    small = json.loads(offline_provider(contract, vector_count=2).generate(""))
    assert len(small["vectors"]) <= 8, len(small["vectors"])


def test_offline_provider_rejects_values_that_cannot_name_a_design():
    with pytest.raises(TypeError):
        offline_provider(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        offline_provider({"ports": []})
    with pytest.raises(ValueError):
        offline_provider({})
