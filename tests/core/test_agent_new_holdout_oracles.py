"""两类固定新合约的公开语义/错误合约与真实通用逐拍判据验收。"""
from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract, PortDirection
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.reference_model import (
    AUTHORITATIVE, INPUT_DEFAULTS, ReferenceSamplingError, reference_cycle_expectations,
    reference_expectations, reference_sampling_profile,
)
from iverilog_ai.core.testbench import TestbenchGenerator as Generator
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "benchmarks/agent_new_holdout_20261005"
CASES = ("valid_data_pipeline", "event_accumulator")
TOOLS = locate_tools()


def contract(case: str) -> DutContract:
    return DutContract.from_json((ASSETS / "contracts" / f"{case}_contract.json").read_bytes())


def plan(case: str, vectors: list[dict]) -> Plan:
    return Plan.model_validate({"design": case, "clock_period_ns": 10, "objective": "fixed public contract semantic acceptance", "vectors": vectors})


def rows(table) -> list[dict[str, int]]:
    return [row for sequence in table.values() for row in sequence]


def test_pipeline_correct_manual_table_capture_emit_bubble_flush_and_resume():
    stimulus = plan(CASES[0], [
        {"name": "first", "inputs": {"i_valid": 1, "i_data": "8'hA5"}},
        {"name": "second", "inputs": {"i_data": 0x3C}},
        {"name": "bubble", "inputs": {"i_valid": 0}, "cycles": 2},
        {"name": "flush", "inputs": {"i_flush": 1, "i_valid": 1, "i_data": 0x7E}},
        {"name": "release", "inputs": {"i_flush": 0, "i_valid": 0}},
        {"name": "restart", "inputs": {"i_valid": 1, "i_data": 0x81}},
        {"name": "drain", "inputs": {"i_valid": 0}},
    ])
    original = stimulus.model_dump()
    table = reference_cycle_expectations(stimulus, contract(CASES[0]))
    assert rows(table) == [{"o_valid": valid, "o_data": data} for valid, data in
                           [(0, 0), (1, 0xA5), (1, 0x3C), (0, 0), (0, 0), (0, 0), (0, 0), (1, 0x81)]]
    assert reference_expectations(stimulus, contract=contract(CASES[0])) == {name: values[-1] for name, values in table.items()}
    assert stimulus.model_dump() == original


def test_counter_correct_manual_table_permission_hold_clear_and_mod16_wrap():
    stimulus = plan(CASES[1], [
        {"name": "fill", "inputs": {"i_enable": 1, "i_event": 1}, "cycles": 17},
        {"name": "paused", "inputs": {"i_enable": 0}, "cycles": 2},
        {"name": "clear", "inputs": {"i_clear": 1}},
        {"name": "clear_still", "inputs": {"i_enable": 1}},
        {"name": "resume", "inputs": {"i_clear": 0}, "cycles": 2},
        {"name": "idle", "inputs": {"i_event": 0}},
    ])
    table = reference_cycle_expectations(stimulus, contract(CASES[1]))
    assert [row["o_count"] for row in rows(table)] == list(range(1, 16)) + [0, 1, 1, 1, 0, 0, 1, 2, 2]
    assert reference_expectations(stimulus, contract=contract(CASES[1])) == {name: values[-1] for name, values in table.items()}


@pytest.mark.parametrize("case", CASES)
def test_fixed_profile_implicit_defaults_reset_held_inputs_and_independent_episode(case):
    inputs = {"i_valid": 1, "i_data": 0xA5} if case == CASES[0] else {"i_enable": 1, "i_event": 1}
    stimulus = plan(case, [{"name": "operate", "inputs": inputs, "cycles": 3},
                           {"name": "held", "inputs": {}, "cycles": 2},
                           {"name": "reset", "inputs": {"i_rstn": 0}, "cycles": 2},
                           {"name": "release", "inputs": {"i_rstn": 1}, "cycles": 3}])
    table = reference_cycle_expectations(stimulus, contract(case))
    assert case in AUTHORITATIVE and reference_sampling_profile(contract(case)) == f"builtin-reference-per-cycle-v1:{case}"
    assert INPUT_DEFAULTS[case]["i_rstn"] == 1 and all(value == 0 for key, value in INPUT_DEFAULTS[case].items() if key != "i_rstn")
    if case == CASES[0]:
        assert rows(table) == [{"o_valid": 0, "o_data": 0}] + [{"o_valid": 1, "o_data": 0xA5}] * 4 + [{"o_valid": 0, "o_data": 0}] * 3 + [{"o_valid": 1, "o_data": 0xA5}] * 2
    else:
        assert [row["o_count"] for row in rows(table)] == [1, 2, 3, 4, 5, 0, 0, 1, 2, 3]
    single = plan(case, [{"name": "new", "inputs": inputs}])
    assert rows(reference_cycle_expectations(single, contract(case))) == ([{"o_valid": 0, "o_data": 0}] if case == CASES[0] else [{"o_count": 1}])
    Generator().validate(stimulus, contract(case), reference_sampling="per_cycle", cycle_expectations=table)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("mismatch", ("parameter", "signed", "width", "inout", "extra_port", "clock_edge", "clock_period", "clock_alias", "reset_sync", "reset_polarity", "reset_length", "reset_alias", "initial", "no_clock", "no_reset"))
def test_new_authoritative_values_require_complete_exact_fixed_contract(case, mismatch):
    base = contract(case)
    if mismatch == "parameter": changed = replace(base, parameters={"W": 8})
    elif mismatch == "signed": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], signed=True)))
    elif mismatch == "width": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], width=2)))
    elif mismatch == "inout": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], direction=PortDirection.INOUT)))
    elif mismatch == "extra_port": changed = replace(base, ports=(*base.ports, replace(base.ports[-1], name="extra")))
    elif mismatch == "clock_edge": changed = replace(base, clock=replace(base.clock, edge="negedge"))
    elif mismatch == "clock_period": changed = replace(base, clock=replace(base.clock, period_ns=20))
    elif mismatch == "clock_alias": changed = replace(base, ports=(replace(base.ports[0], name="clk"), *base.ports[1:]), clock=replace(base.clock, signal="clk"))
    elif mismatch == "reset_sync": changed = replace(base, reset=replace(base.reset, synchronous=True))
    elif mismatch == "reset_polarity": changed = replace(base, reset=replace(base.reset, active_level=1))
    elif mismatch == "reset_length": changed = replace(base, reset=replace(base.reset, assert_cycles=1))
    elif mismatch == "reset_alias": changed = replace(base, ports=(base.ports[0], replace(base.ports[1], name="rst_n"), *base.ports[2:]), reset=replace(base.reset, signal="rst_n"))
    elif mismatch == "initial": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], initial=0)))
    elif mismatch == "no_clock": changed = replace(base, clock=None)
    else: changed = replace(base, reset=None)
    stimulus = plan(case, [{"name": "observe", "inputs": {}, "cycles": 2}])
    assert reference_sampling_profile(changed) is None
    assert reference_expectations(stimulus, contract=changed) == {}
    assert reference_expectations(stimulus, contract=changed, authoritative_only=False) == {}
    with pytest.raises(ReferenceSamplingError, match="not supported"):
        reference_cycle_expectations(stimulus, changed)


@pytest.mark.parametrize("case", CASES)
def test_legacy_name_only_and_raw_contract_never_select_new_authority(case):
    stimulus = plan(case, [{"name": "observe", "inputs": {}, "cycles": 2}])
    assert reference_sampling_profile(contract(case).to_dict()) is None
    assert reference_expectations(stimulus) == {}
    assert reference_expectations(stimulus, authoritative_only=False) == {}
    assert reference_expectations(stimulus, contract=contract(case).to_dict()) == {}
    assert reference_expectations(stimulus.model_dump(), contract=contract(case)) == {}


@pytest.mark.parametrize("case", CASES)
def test_before_unknown_and_clock_driving_fail_closed(case):
    before = plan(case, [{"name": "early", "sample_phase": "before", "inputs": {}}])
    assert reference_expectations(before, contract=contract(case)) == {}
    with pytest.raises(ReferenceSamplingError, match="after only"):
        reference_cycle_expectations(before, contract(case))
    data = "i_valid" if case == CASES[0] else "i_event"
    for inputs in ({data: "1'bx"}, {data: "1'bz"}, {"i_clk": 0}, {data: 2}, {"unregistered": 0}):
        invalid = plan(case, [{"name": "bad", "inputs": inputs}])
        assert reference_expectations(invalid, contract=contract(case)) == {}
        with pytest.raises(ReferenceSamplingError):
            reference_cycle_expectations(invalid, contract(case))


def witness(case: str, variant: str) -> Plan:
    if case == CASES[0]:
        vectors = [{"name": "accept", "inputs": {"i_valid": 1, "i_data": 0xA5}}]
        vectors.append({"name": "next", "inputs": {"i_valid": 0, **({"i_flush": 1} if variant == "C" else {})}})
    elif variant == "B":
        vectors = [{"name": "paused", "inputs": {"i_enable": 0, "i_event": 1}}]
    else:
        vectors = [{"name": "accept", "inputs": {"i_enable": 1, "i_event": 1}}, {"name": "clear", "inputs": {"i_enable": 0, "i_event": 0, "i_clear": 1}}]
    return plan(case, vectors)


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("variant", ("A", "B", "C"))
def test_actual_generic_per_cycle_pipeline_correct_and_semantic_mutation_controls(tmp_path, case, variant):
    stimulus = witness(case, "B" if variant == "A" else variant)
    original = stimulus.model_dump()
    result = VerificationPipeline().run(stimulus, contract(case), ASSETS / "targets" / case / variant / f"{case}.v", tmp_path / f"{case}-{variant}",
        reference_sampling="per_cycle", capture_observations=True, emit_vcd=False, iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    assert result.simulation.compile.returncode == 0 and result.simulation.run.returncode == 0
    assert result.simulation.verdict == ("passed" if variant == "A" else "failed_checks")
    assert result.simulation.check_count == sum(vector.cycles for vector in stimulus.vectors) * len(contract(case).outputs)
    assert result.plan is stimulus and stimulus.model_dump() == original
    packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert packet["status"] == "complete" and packet["expected_cycles"] == packet["observed_cycles"] == sum(vector.cycles for vector in stimulus.vectors)
    expected_failures = 0 if variant == "A" else 2 if case == CASES[0] and variant == "B" else 1
    assert result.simulation.summary["failures"] == expected_failures


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("case,variant", [(case, variant) for case in CASES for variant in ("B", "C")])
def test_mutation_non_target_normal_controls_pass(tmp_path, case, variant):
    inputs = {"i_valid": 0, "i_flush": 0} if case == CASES[0] and variant == "B" else {"i_valid": 1, "i_data": 0x3C, "i_flush": 0} if case == CASES[0] else {"i_enable": 1, "i_event": 1, "i_clear": 0} if variant == "B" else {"i_enable": 1, "i_event": 1, "i_clear": 1}
    stimulus = plan(case, [{"name": "normal", "inputs": inputs, "cycles": 4}])
    result = VerificationPipeline().run(stimulus, contract(case), ASSETS / "targets" / case / variant / f"{case}.v", tmp_path / f"{case}-{variant}",
        reference_sampling="per_cycle", emit_vcd=False, iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    assert result.status is ResultStatus.PASSED and result.simulation.summary["failures"] == 0


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("strategy", ("fixed", "random", "protocol_random"))
@pytest.mark.parametrize("seed", (0, 1, 2))
def test_actual_public_baselines_per_cycle_correct_controls_are_eligible(tmp_path, case, strategy, seed):
    module_spec = importlib.util.spec_from_file_location("new_holdout_public_baselines", ASSETS / "baselines.py")
    assert module_spec and module_spec.loader
    baselines = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baselines)
    stimulus = baselines.baseline_factory(case, strategy, seed, contract(case), 24)
    result = VerificationPipeline().run(stimulus, contract(case), ASSETS / "targets" / case / "A" / f"{case}.v", tmp_path / f"{case}-{strategy}-{seed}",
        reference_sampling="per_cycle", capture_observations=True, emit_vcd=False, iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    assert result.status is ResultStatus.PASSED and result.simulation.summary["failures"] == 0
    assert result.simulation.check_count == 24 * len(contract(case).outputs)
    packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert packet["status"] == "complete" and packet["observed_cycles"] == packet["expected_cycles"] == 24
