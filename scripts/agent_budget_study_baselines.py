"""Specification-only baselines with the same 12-vector proposal ceiling."""
from __future__ import annotations

import random
from typing import Any

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import reference_sampling_profile

CYCLE_BUDGETS = {"sync_fifo": 16, "uart_tx": 48, "spi_master": 20,
                 "handshake_stage": 8, "credit_guard": 16, "rotating_arbiter": 16,
                 "edge_detector": 16, "pulse_stretcher": 16}
DEVELOPMENT_CASES = ("sync_fifo", "uart_tx", "spi_master", "handshake_stage")
PRIOR_INTERNAL_CASES = ("credit_guard", "rotating_arbiter")
MODULE_HOLDOUT_CASES = ("edge_detector", "pulse_stretcher")
CASES = DEVELOPMENT_CASES + PRIOR_INTERNAL_CASES + MODULE_HOLDOUT_CASES
STRATEGIES = ("fixed", "random", "protocol_random")


def budget_baseline(case: str, strategy: str, seed: int, contract: DutContract,
                    cycles: int) -> TestPlan:
    """Uses only case, contract, fixed public protocol timing, budget and seed."""
    if (case not in CASES or strategy not in STRATEGIES or type(seed) is not int
            or seed not in (0, 1, 2) or type(cycles) is not int
            or cycles != CYCLE_BUDGETS[case] or contract.module != case
            or reference_sampling_profile(contract) is None):
        raise ValueError("baseline outside registered contract or budget")
    if case in PRIOR_INTERNAL_CASES and strategy != "random":
        from scripts.run_agent_holdout_study import holdout_baseline
        return holdout_baseline(case, strategy, seed, contract, cycles)
    if case in MODULE_HOLDOUT_CASES and strategy != "random":
        from benchmarks.agent_module_holdout_20261005_v7.baselines import baseline_factory
        return baseline_factory(case, strategy, seed, contract, cycles)
    rng = random.Random(seed)
    excluded = {contract.clock.signal if contract.clock else "",
                contract.reset.signal if contract.reset else ""}
    ports = {p.name: p for p in contract.inputs if p.name not in excluded}
    defaults = {name: 0 for name in ports}
    vectors: list[dict[str, Any]] = []
    used = 0

    def emit(values: dict[str, int], count: int = 1) -> None:
        nonlocal used
        if type(count) is not int or count < 1 or used + count > cycles:
            raise ValueError("baseline exceeded registered cycle cap")
        complete = {**defaults, **values}
        if (set(complete) != set(ports) or any(type(value) is not int
                or not 0 <= value < (1 << ports[name].width) for name, value in complete.items())):
            raise ValueError("baseline input outside contract")
        if vectors and vectors[-1]["inputs"] == complete:
            vectors[-1]["cycles"] += count
        else:
            vectors.append({"name": f"{strategy}_{len(vectors)}", "inputs": complete,
                            "cycles": count, "sample_phase": "after", "expected": {}})
        used += count

    def data(name: str, fixed: int) -> int:
        return (rng.randrange(1 << ports[name].width) if strategy == "protocol_random"
                else fixed & ((1 << ports[name].width) - 1))

    if strategy == "random":
        segments = min(cycles, 12)
        # No coalescing here: keep precisely the registered independent draws.
        vectors = [{"name": f"random_{i}",
                    "inputs": {name: rng.randrange(1 << port.width) for name, port in ports.items()},
                    "cycles": cycles // segments + int(i < cycles % segments),
                    "sample_phase": "after", "expected": {}} for i in range(segments)]
        used = cycles
    elif case == "sync_fifo":
        depth = int(contract.parameters["DEPTH"])
        if depth != 4:
            raise ValueError("unregistered FIFO depth")
        emit({"wr_en": 0, "rd_en": 1, "wr_data": 0})
        for value in (0x12, 0x34, 0x56, 0x9A):
            emit({"wr_en": 1, "rd_en": 0, "wr_data": data("wr_data", value)})
        overflow = 1 + rng.randrange(2) if strategy == "protocol_random" else 2
        emit({"wr_en": 1, "rd_en": 0, "wr_data": data("wr_data", 0xA5)}, overflow)
        emit({"wr_en": 1, "rd_en": 1, "wr_data": data("wr_data", 0x3C)})
        emit({"wr_en": 0, "rd_en": 1, "wr_data": 0}, depth + 1)
        simultaneous = 1 + rng.randrange(2) if strategy == "protocol_random" else 2
        emit({"wr_en": 1, "rd_en": 1, "wr_data": data("wr_data", 0xC3)}, simultaneous)
        emit(defaults, cycles - used)
    elif case in ("uart_tx", "spi_master"):
        first = data("data_in", 0x69)
        during_busy = data("data_in", 0xC3)
        second = data("data_in", 0x96)
        # Accepted E0, bounded request during busy, frame completion, idle, next request.
        busy = 10 * int(contract.parameters["CLKS_PER_BIT"]) if case == "uart_tx" else 2 * int(contract.parameters["WIDTH"]) - 1
        probe = 1 + rng.randrange(2) if strategy == "protocol_random" else 1
        emit({"start": 1, "data_in": first})
        emit({"start": 1, "data_in": during_busy}, probe)
        emit({"start": 0, "data_in": during_busy}, busy - probe)
        emit({"start": 0, "data_in": second})
        emit({"start": 1, "data_in": second})
        emit({"start": 0, "data_in": second}, cycles - used)
    elif case == "handshake_stage":
        first, second, third = [data("in_data", value) for value in (0x12, 0xA5, 0x3C)]
        hold = 1 + rng.randrange(2) if strategy == "protocol_random" else 2
        emit({"in_valid": 1, "in_data": first, "out_ready": 0})
        emit({"in_valid": 1, "in_data": second, "out_ready": 0}, hold)
        emit({"in_valid": 1, "in_data": second, "out_ready": 1})
        emit({"in_valid": 0, "in_data": second, "out_ready": 0})
        emit({"in_valid": 0, "in_data": second, "out_ready": 1})
        emit({"in_valid": 1, "in_data": third, "out_ready": 1})
        emit({"in_valid": 0, "in_data": third, "out_ready": 1})
        if used < cycles:
            emit({"in_valid": 0, "in_data": third, "out_ready": 1}, cycles - used)
    else:
        raise ValueError("missing specification baseline")
    if used != cycles or not 1 <= len(vectors) <= 12:
        raise ValueError("baseline outside registered proposal shape")
    return TestPlan.model_validate({"design": case,
        "objective": "Check contract behavior and protocol boundaries",
        "clock_period_ns": int(contract.clock.period_ns) if contract.clock else 10,
        "reset": contract.reset.to_dict() if contract.reset else {}, "vectors": vectors})
