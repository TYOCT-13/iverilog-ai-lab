"""内部合成留出基线：只读正确规格、显式合约与种子，不读 RTL/标签/成绩。"""
from __future__ import annotations

from pathlib import Path
import random
from typing import Any

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract

CASES = ("valid_data_pipeline", "event_accumulator")
STRATEGIES = ("fixed", "random", "protocol_random")
SPEC_ROOT = Path(__file__).resolve().parents[2] / "spec/agent_new_holdout_20261005"


def _validate(case: str, contract: DutContract) -> None:
    if not isinstance(contract, DutContract) or contract.module != case:
        raise ValueError("baseline_contract_module")
    business = {"i_flush": 1, "i_valid": 1, "i_data": 8} if case == CASES[0] else {"i_enable": 1, "i_event": 1, "i_clear": 1}
    outputs = {"o_valid": 1, "o_data": 8} if case == CASES[0] else {"o_count": 4}
    expected = {(name, "input", width, False, None) for name, width in {"i_clk": 1, "i_rstn": 1, **business}.items()}
    expected.update((name, "output", width, False, None) for name, width in outputs.items())
    actual = {(port.name, port.direction.value, port.width, port.signed, port.initial) for port in contract.ports}
    if actual != expected or len(contract.ports) != len(expected):
        raise ValueError("baseline_contract_ports")
    if contract.parameters:
        raise ValueError("baseline_default_parameters")
    if contract.clock is None or (contract.clock.signal, contract.clock.edge, contract.clock.period_ns) != ("i_clk", "posedge", 10):
        raise ValueError("baseline_clock")
    if contract.reset is None or (contract.reset.signal, contract.reset.active_level, contract.reset.synchronous, contract.reset.assert_cycles) != ("i_rstn", 0, False, 2):
        raise ValueError("baseline_reset")


def _protocol(case: str, strategy: str, rng: random.Random) -> list[tuple[dict[str, int], int]]:
    if case == CASES[0]:
        if strategy == "fixed":
            return [({"i_valid": 0, "i_data": 0, "i_flush": 0}, 2),
                    ({"i_valid": 1, "i_data": 0xA5, "i_flush": 0}, 4),
                    ({"i_valid": 0, "i_data": 0, "i_flush": 0}, 2),
                    ({"i_valid": 1, "i_data": 0x3C, "i_flush": 0}, 4),
                    ({"i_valid": 1, "i_data": 0x7E, "i_flush": 1}, 2),
                    ({"i_valid": 0, "i_data": 0, "i_flush": 0}, 2),
                    ({"i_valid": 1, "i_data": 0x81, "i_flush": 0}, 4),
                    ({"i_valid": 0, "i_data": 0, "i_flush": 0}, 4)]
        portions = [({"i_valid": 0, "i_data": 0, "i_flush": 0}, rng.choice((1, 2))),
                    ({"i_valid": 1, "i_data": rng.randrange(256), "i_flush": 0}, rng.choice((3, 4, 5))),
                    ({"i_valid": 0, "i_data": rng.randrange(256), "i_flush": 0}, rng.choice((1, 2))),
                    ({"i_valid": 1, "i_data": rng.randrange(256), "i_flush": 0}, rng.choice((2, 3, 4))),
                    ({"i_valid": rng.randrange(2), "i_data": rng.randrange(256), "i_flush": 1}, rng.choice((1, 2))),
                    ({"i_valid": 0, "i_data": 0, "i_flush": 0}, 2),
                    ({"i_valid": 1, "i_data": rng.randrange(256), "i_flush": 0}, rng.choice((2, 3, 4)))]
        portions.append(({"i_valid": 0, "i_data": 0, "i_flush": 0}, 24 - sum(duration for _, duration in portions)))
        return portions
    if strategy == "fixed":
        return [({"i_enable": 0, "i_event": 0, "i_clear": 0}, 1),
                ({"i_enable": 1, "i_event": 1, "i_clear": 0}, 17),
                ({"i_enable": 0, "i_event": 1, "i_clear": 0}, 2),
                ({"i_enable": 0, "i_event": 0, "i_clear": 1}, 1),
                ({"i_enable": 1, "i_event": 1, "i_clear": 0}, 2),
                ({"i_enable": 0, "i_event": 0, "i_clear": 0}, 1)]
    portions = [({"i_enable": 0, "i_event": 0, "i_clear": 0}, 1),
                ({"i_enable": 1, "i_event": 1, "i_clear": 0}, rng.choice((16, 17))),
                ({"i_enable": 0, "i_event": rng.randrange(2), "i_clear": 0}, 2),
                ({"i_enable": 0, "i_event": rng.randrange(2), "i_clear": 1}, 1),
                ({"i_enable": 1, "i_event": 1, "i_clear": 0}, 2)]
    portions.append(({"i_enable": 0, "i_event": 0, "i_clear": 0}, 24 - sum(duration for _, duration in portions)))
    return portions


def baseline_factory(case: str, strategy: str, seed: int, contract: DutContract, cycles: int) -> TestPlan:
    """同输入资源与 seed 决定单 episode 计划，固定 24 拍且 ≤12 段。"""
    if not isinstance(case, str) or case not in CASES:
        raise ValueError("baseline_case")
    if not isinstance(strategy, str) or strategy not in STRATEGIES:
        raise ValueError("baseline_strategy")
    if type(seed) is not int or seed < 0:
        raise ValueError("baseline_seed")
    if type(cycles) is not int or cycles != 24:
        raise ValueError("baseline_cycle_scope")
    _validate(case, contract)
    specification = (SPEC_ROOT / f"{case}_spec.md").read_text(encoding="utf-8")
    if not specification.strip():
        raise ValueError("baseline_spec_missing")
    rng = random.Random(seed)
    vectors: list[dict[str, Any]] = []
    if strategy == "random":
        business = {port.name: port.width for port in contract.ports if port.direction.value == "input" and port.name not in {"i_clk", "i_rstn"}}
        for index in range(12):
            inputs = {"i_rstn": 1, **{name: rng.randrange(2 ** width) for name, width in business.items()}}
            vectors.append({"name": f"random_{index}", "inputs": inputs, "cycles": 2, "sample_phase": "after", "expected": {}})
    else:
        for inputs, duration in _protocol(case, strategy, rng):
            driven = {"i_rstn": 1, **inputs}
            if vectors and vectors[-1]["inputs"] == driven:
                vectors[-1]["cycles"] += duration
            else:
                vectors.append({"name": f"{strategy}_{len(vectors)}", "inputs": driven, "cycles": duration, "sample_phase": "after", "expected": {}})
    if len(vectors) > 12 or sum(vector["cycles"] for vector in vectors) != cycles:
        raise ValueError("baseline_internal_scope")
    return TestPlan.model_validate({"design": case, "objective": "Verify correct default interface behavior and ordinary multi-cycle operations",
                                    "clock_period_ns": 10, "reset": contract.reset.to_dict() if contract.reset else {}, "vectors": vectors})
