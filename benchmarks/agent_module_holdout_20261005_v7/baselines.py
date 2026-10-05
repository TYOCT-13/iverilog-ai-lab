"""仅由正确功能规格和显式合约构建的离线基线，不读取目标或结果。"""

from __future__ import annotations

from pathlib import Path
import random
from typing import Any

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract

CASES = ("edge_detector", "pulse_stretcher")
STRATEGIES = ("fixed", "random", "protocol_random")
SPEC_ROOT = Path(__file__).resolve().parents[2] / "spec/agent_module_holdout_20261005_v7"


def _validate_contract(case: str, contract: DutContract) -> None:
    """拒绝非原默认参数、端口形状或时钟复位语义。"""
    if not isinstance(contract, DutContract) or contract.module != case:
        raise ValueError("baseline_contract_module")
    data_input, output = ("signal_in", "rising") if case == "edge_detector" else ("pulse_in", "pulse_out")
    actual_ports = {(port.name, port.direction.value, port.width, port.signed, port.initial) for port in contract.ports}
    expected_ports = {(name, "input", 1, False, None) for name in ("clk", "rst_n", data_input)}
    expected_ports.add((output, "output", 1, False, None))
    if actual_ports != expected_ports or len(contract.ports) != 4:
        raise ValueError("baseline_contract_ports")
    expected_parameters = {} if case == "edge_detector" else {"WIDTH": 4}
    if contract.parameters != expected_parameters or any(type(value) is not int for value in contract.parameters.values()):
        raise ValueError("baseline_default_parameters")
    if (contract.clock is None or contract.clock.signal != "clk" or contract.clock.edge != "posedge"
            or contract.clock.period_ns != 10):
        raise ValueError("baseline_clock")
    if (contract.reset is None or contract.reset.signal != "rst_n" or contract.reset.active_level != 0
            or contract.reset.synchronous or contract.reset.assert_cycles != 2):
        raise ValueError("baseline_reset")


def _segments(case: str, strategy: str, rng: random.Random, width: int) -> list[tuple[int, int]]:
    """普通空闲、保持、触发和窗口边界；随机协议选择改变持续时间。"""
    if case == "edge_detector":
        if strategy == "fixed":
            return [(0, 2), (1, 3), (0, 2), (1, 1), (0, 1), (1, 2), (0, 3), (1, 1), (0, 1)]
        high_first, high_second = rng.choice((2, 3)), rng.choice((2, 3))
        body = [(0, 2), (1, high_first), (0, 2), (1, 1), (0, 1), (1, high_second)]
    else:
        if strategy == "fixed":
            return [(0, 2), (1, 1), (0, width), (1, 2), (0, width), (1, 1), (0, 2)]
        body = [(0, rng.choice((1, 2))), (1, 1), (0, width), (1, rng.choice((1, 2))),
                (0, rng.choice((1, 2))), (1, 1)]
    body.append((0, 16 - sum(duration for _, duration in body)))
    return body


def baseline_factory(case: str, strategy: str, seed: int, contract: DutContract, cycles: int) -> TestPlan:
    """同一输入资源和种子确定一个计划，固定16拍且最多12向量。"""
    if not isinstance(case, str) or case not in CASES:
        raise ValueError("baseline_case")
    if not isinstance(strategy, str) or strategy not in STRATEGIES:
        raise ValueError("baseline_strategy")
    if type(seed) is not int or seed < 0:
        raise ValueError("baseline_seed")
    if type(cycles) is not int or cycles != 16:
        raise ValueError("baseline_cycle_scope")
    _validate_contract(case, contract)
    # 唯一文件输入为正确功能规格，不读取 manifest、RTL、标签或运行原件。
    specification = (SPEC_ROOT / f"{case}_spec.md").read_text(encoding="utf-8")
    if not specification.strip():
        raise ValueError("baseline_spec_missing")
    rng = random.Random(seed)
    data_input = "signal_in" if case == "edge_detector" else "pulse_in"
    vectors: list[dict[str, Any]] = []
    if strategy == "random":
        # 十二段均匀独立业务输入；保持自动复位释放值，不随机打断协议。
        for index in range(12):
            vectors.append({"name": f"random_{index}", "inputs": {"rst_n": 1, data_input: rng.randrange(2)},
                            "cycles": 2 if index < 4 else 1, "sample_phase": "after", "expected": {}})
    else:
        width = int(contract.parameters["WIDTH"]) if case == "pulse_stretcher" else 0
        for value, duration in _segments(case, strategy, rng, width):
            inputs = {"rst_n": 1, data_input: value}
            if vectors and vectors[-1]["inputs"] == inputs:
                vectors[-1]["cycles"] += duration
            else:
                vectors.append({"name": f"{strategy}_{len(vectors)}", "inputs": inputs, "cycles": duration,
                                "sample_phase": "after", "expected": {}})
    if len(vectors) > 12 or sum(vector["cycles"] for vector in vectors) != cycles:
        raise ValueError("baseline_internal_scope")
    return TestPlan.model_validate({"design": case, "objective": "Verify default interface behavior and ordinary protocol timing",
                                    "clock_period_ns": 10, "reset": contract.reset.to_dict() if contract.reset else {},
                                    "vectors": vectors})
