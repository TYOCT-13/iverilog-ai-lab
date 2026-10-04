"""参考模型内部一致性：每个"已支持"的设计都必须真的被复算过。

为什么值得单独测：`check_plan_consistency`（诊断路径）与 `reference_expectations`
（权威路径）曾经各有一份**独立的语义实现**，而且诊断路径那份在 `return` 之后
（不可达的死代码）。这类结构的危险不是"算错"，而是**看起来在检查、实际什么都没查**：
只要某个设计在实现里缺一个分支，它就会静默返回空结果，报告却是 `passed`。

本文件用"故意写错的期望值必须被判为不一致"来证明诊断路径真的覆盖到了每个设计：
如果某个设计没有被复算，这个断言就会失败——这正是我们想要的失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import (
    AUTHORITATIVE,
    INPUT_DEFAULTS,
    SUPPORTED,
    _DesignState,
    check_plan_consistency,
    completed_inputs,
    reference_expectations,
)

ROOT = Path(__file__).resolve().parents[2]

#: 每个设计一组"能产生确定可观测输出"的向量（值只求合法，不求覆盖边界）。
PROBE_VECTORS: dict[str, list[dict]] = {
    "mod10_counter": [{"inputs": {"rst_n": 1, "enable": 1}, "cycles": 3}],
    "simple_alu": [{"inputs": {"a": 7, "b": 5, "op": 0}, "cycles": 1}],
    "sequence_101_overlap": [{"inputs": {"rst_n": 1, "bit_in": 1}, "cycles": 3}],
    "traffic_light_emergency": [{"inputs": {"rst_n": 1, "emergency": 0}, "cycles": 3}],
    "sync_fifo": [{"inputs": {"rst_n": 1, "wr_en": 1, "wr_data": 9, "rd_en": 0}, "cycles": 2}],
    "uart_tx": [{"inputs": {"rst_n": 1, "start": 1, "data_in": 85}, "cycles": 3}],
    "spi_master": [{"inputs": {"rst_n": 1, "start": 1, "data_in": 85}, "cycles": 4}],
    "handshake_stage": [{"inputs": {"rst_n": 1, "in_valid": 1, "in_data": 33, "out_ready": 0}, "cycles": 3}],
    "debounce": [{"inputs": {"rst_n": 1, "key_in": 0}, "cycles": 5}],
    "pwm": [{"inputs": {"rst_n": 1, "duty": 3}, "cycles": 3}],
    "mux4": [{"inputs": {"sel": 2, "d2": 42}, "cycles": 1}],
    "sync_reset": [{"inputs": {"ext_rst_n": 1}, "cycles": 3}],
    "johnson_counter": [{"inputs": {"rst_n": 1, "enable": 1}, "cycles": 3}],
    "edge_detector": [{"inputs": {"rst_n": 1, "signal_in": 1}, "cycles": 2}],
    "pulse_stretcher": [{"inputs": {"rst_n": 1, "pulse_in": 1}, "cycles": 2}],
    "credit_guard": [{"inputs": {"rst_n": 1, "acquire": 1, "release_req": 0}, "cycles": 2}],
    "rotating_arbiter": [{"inputs": {"rst_n": 1, "request": 15, "advance": 1}, "cycles": 3}],
}


def _contract(case: str) -> DutContract:
    path = ROOT / "examples" / f"{case}_contract.json"
    return DutContract.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_probe_vectors_cover_every_supported_design():
    """本文件必须与模型声明同步：新增设计时先补探针向量，否则下面几条会漏掉它。"""

    assert set(PROBE_VECTORS) == set(SUPPORTED), (
        "参考模型支持的设计与本文件的探针向量不一致："
        f"缺少 {sorted(set(SUPPORTED) - set(PROBE_VECTORS))}，多余 {sorted(set(PROBE_VECTORS) - set(SUPPORTED))}"
    )


def test_input_defaults_cover_every_supported_design():
    assert set(INPUT_DEFAULTS) == set(SUPPORTED)


@pytest.mark.parametrize("case", sorted(PROBE_VECTORS))
def test_every_supported_design_produces_observable_output(case):
    """每个设计都必须复算出至少一个可观测输出。

    空结果比错结果更危险：调用方会把"没有可比的信号"当成"检查通过"。
    """

    state = _DesignState(case, _contract(case))
    produced: dict = {}
    for vector in PROBE_VECTORS[case]:
        produced.update(state.step(vector["inputs"], vector["cycles"]))
    assert produced, f"{case} 的参考模型没有产出任何可观测输出"


@pytest.mark.parametrize("case", sorted(PROBE_VECTORS))
def test_diagnostic_path_flags_a_deliberately_wrong_expectation(case):
    """诊断路径必须真的比对：把期望值写成一个不可能的值，必须报 plan_inconsistent。"""

    contract = _contract(case)
    vector = PROBE_VECTORS[case][0]
    state = _DesignState(case, contract)
    actual = state.step(vector["inputs"], vector["cycles"])
    assert actual, f"{case} 没有可观测输出，无法构造反例"
    signal = sorted(actual)[0]
    wrong = int(actual[signal]) ^ 1  # 只要与真实值不同即可，未必语义合法
    plan = TestPlan.model_validate(
        {
            "design": case,
            "objective": "诊断路径覆盖探针",
            "vectors": [
                {
                    "name": "probe",
                    "inputs": vector["inputs"],
                    "cycles": vector["cycles"],
                    "expected": {signal: wrong},
                }
            ],
        }
    )
    report = check_plan_consistency(plan, case, contract)
    assert report["status"] == "warn", f"{case} 的故意错误期望值没有被诊断路径发现：{report}"
    assert report["checked_expected"] == 1, f"{case} 诊断路径没有真的比对任何信号：{report}"
    assert report["warnings"][0]["signal"] == signal


@pytest.mark.parametrize("case", sorted(PROBE_VECTORS))
def test_both_paths_agree_on_the_same_vectors(case):
    """权威路径与诊断路径必须给出同一组期望值。"""

    contract = _contract(case)
    vectors = [
        {
            "name": f"v{index}",
            "inputs": vector["inputs"],
            "cycles": vector["cycles"],
            "expected": {},
        }
        for index, vector in enumerate(PROBE_VECTORS[case])
    ]
    plan = TestPlan.model_validate({"design": case, "objective": "两路径一致", "vectors": vectors})
    authoritative = reference_expectations(plan, case, contract, authoritative_only=False)
    state = _DesignState(case, contract)
    for vector in vectors:
        direct = state.step(vector["inputs"], vector["cycles"])
        assert authoritative[vector["name"]] == direct, f"{case} 两条路径结果不同"


def test_authoritative_is_a_subset_of_supported():
    assert AUTHORITATIVE <= SUPPORTED


def test_completed_inputs_never_drops_explicit_values():
    """补全省略输入时不得覆盖向量里显式给出的值。"""

    completed = completed_inputs("debounce", {"key_in": 1})
    assert completed["key_in"] == 1
    assert completed["rst_n"] == INPUT_DEFAULTS["debounce"]["rst_n"]
