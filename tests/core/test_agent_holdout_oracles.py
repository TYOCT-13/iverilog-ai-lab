"""New module holdouts: public-contract semantics, no API or defect-label inputs."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract, PortDirection
from iverilog_ai.core.functional_coverage import functional_coverage_profile
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.reference_model import (
    AUTHORITATIVE, INPUT_DEFAULTS, PER_CYCLE_PROFILE_VERSION, _DesignState,
    ReferenceSamplingError, reference_cycle_expectations, reference_expectations,
    reference_sampling_profile,
)
from iverilog_ai.core.testbench import TestbenchGenerator as Generator
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()
HOLDOUTS = ("credit_guard", "rotating_arbiter")


def contract(design: str) -> DutContract:
    data_inputs = {"acquire": 1, "release_req": 1} if design == "credit_guard" else {"request": 4, "advance": 1}
    output, width = ("credits", 3) if design == "credit_guard" else ("grant", 4)
    return DutContract.from_dict({"module": design, "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        *[{"name": name, "direction": "input", "width": bits} for name, bits in data_inputs.items()],
        {"name": output, "direction": "output", "width": width}],
        "clock": {"signal": "clk", "edge": "posedge", "period_ns": 10},
        "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
        "parameters": {}})


def plan(design: str, vectors: list[dict]) -> Plan:
    return Plan.model_validate({"design": design, "objective": "new module public contract regression", "vectors": vectors})


def flatten(table: dict[str, tuple[dict[str, int], ...]], signal: str) -> list[int]:
    return [row[signal] for rows in table.values() for row in rows]


# Columns: hold, acquire only, release only, simultaneous requests.
# Values explicitly enumerate the eight states and both saturating boundaries.
CREDIT_TRANSITIONS = (
    (0, 0, 1, 0), (1, 0, 2, 1), (2, 1, 3, 2), (3, 2, 4, 3),
    (4, 3, 5, 4), (5, 4, 6, 5), (6, 5, 7, 6), (7, 6, 7, 7),
)
REQUESTS = ((0, 0), (1, 0), (0, 1), (1, 1))


@pytest.mark.parametrize("credits", range(8))
@pytest.mark.parametrize("operation", range(4))
def test_credit_all_state_and_request_transitions_are_saturating(credits, operation):
    state = _DesignState("credit_guard")
    state.credits = credits
    acquire, release = REQUESTS[operation]
    actual = state.step({"rst_n": 1, "acquire": acquire, "release_req": release}, 1)
    assert actual == {"credits": CREDIT_TRANSITIONS[credits][operation]}


# Rows are the old pointer, columns the sixteen possible request masks.
# This truth table is independent of the model's list-based selection algorithm.
ARBITER_GRANTS = (
    (0, 1, 2, 1, 4, 1, 2, 1, 8, 1, 2, 1, 4, 1, 2, 1),
    (0, 1, 2, 2, 4, 4, 2, 2, 8, 8, 2, 2, 4, 4, 2, 2),
    (0, 1, 2, 1, 4, 4, 4, 4, 8, 8, 8, 8, 4, 4, 4, 4),
    (0, 1, 2, 1, 4, 1, 2, 1, 8, 8, 8, 8, 8, 8, 8, 8),
)


@pytest.mark.parametrize("pointer", range(4))
@pytest.mark.parametrize("request_mask", range(16))
@pytest.mark.parametrize("advance", (0, 1))
def test_arbiter_complete_truth_table_uses_old_pointer_then_updates(pointer, request_mask, advance):
    state = _DesignState("rotating_arbiter")
    state.arbiter_pointer = pointer
    expected = ARBITER_GRANTS[pointer][request_mask]
    assert state.step({"rst_n": 1, "request": request_mask, "advance": advance}, 1) == {"grant": expected}
    assert state.arbiter_pointer == (expected.bit_length() % 4 if advance and expected else pointer)
    assert expected == 0 or expected & (expected - 1) == 0


def test_credit_multicycle_state_reset_priority_and_omitted_inputs_hold():
    stimulus = plan("credit_guard", [
        {"name": "deplete", "inputs": {"acquire": 1}, "cycles": 6, "expected": {"credits": 7}},
        {"name": "fill", "inputs": {"acquire": 0, "release_req": 1}, "cycles": 9},
        {"name": "both", "inputs": {"acquire": 1}, "cycles": 2},
        {"name": "held", "inputs": {}, "cycles": 2},
        {"name": "reset", "inputs": {"rst_n": 0}, "cycles": 2},
        {"name": "resume", "inputs": {"rst_n": 1, "acquire": 0}, "cycles": 2},
    ])
    original = stimulus.model_dump(mode="json")
    table = reference_cycle_expectations(stimulus, contract("credit_guard"))
    assert [row["credits"] for row in table["deplete"]] == [2, 1, 0, 0, 0, 0]
    assert [row["credits"] for row in table["fill"]] == [1, 2, 3, 4, 5, 6, 7, 7, 7]
    assert [row["credits"] for row in table["both"] + table["held"]] == [7, 7, 7, 7]
    assert [row["credits"] for row in table["reset"]] == [3, 3]
    assert [row["credits"] for row in table["resume"]] == [4, 5]
    assert reference_expectations(stimulus, contract=contract("credit_guard")) == {
        name: rows[-1] for name, rows in table.items()}
    assert stimulus.model_dump(mode="json") == original


def test_arbiter_rotation_hold_empty_request_reset_and_priority_wrap():
    stimulus = plan("rotating_arbiter", [
        {"name": "rotate", "inputs": {"request": 15, "advance": 1}, "cycles": 6},
        {"name": "hold", "inputs": {"advance": 0}, "cycles": 3},
        {"name": "empty", "inputs": {"request": 0, "advance": 1}, "cycles": 2},
        {"name": "wrap", "inputs": {"request": 9}, "cycles": 3},
        {"name": "reset", "inputs": {"rst_n": 0, "request": 15}, "cycles": 2},
        {"name": "resume", "inputs": {"rst_n": 1}, "cycles": 2},
    ])
    table = reference_cycle_expectations(stimulus, contract("rotating_arbiter"))
    assert [row["grant"] for row in table["rotate"]] == [1, 2, 4, 8, 1, 2]
    assert [row["grant"] for row in table["hold"]] == [4, 4, 4]
    assert [row["grant"] for row in table["empty"]] == [0, 0]
    assert [row["grant"] for row in table["wrap"]] == [8, 1, 8]
    assert [row["grant"] for row in table["reset"]] == [0, 0]
    assert [row["grant"] for row in table["resume"]] == [1, 2]
    assert reference_expectations(stimulus, contract=contract("rotating_arbiter")) == {
        name: rows[-1] for name, rows in table.items()}


@pytest.mark.parametrize("design", HOLDOUTS)
def test_each_episode_starts_a_new_implicitly_reset_model(design):
    inputs = {"acquire": 1} if design == "credit_guard" else {"request": 15, "advance": 1}
    first = plan(design, [{"name": "first", "inputs": inputs, "cycles": 2}])
    second = plan(design, [{"name": "second", "inputs": inputs, "cycles": 1}])
    signal = "credits" if design == "credit_guard" else "grant"
    assert flatten(reference_cycle_expectations(first, contract(design)), signal) == ([2, 1] if design == "credit_guard" else [1, 2])
    assert flatten(reference_cycle_expectations(second, contract(design)), signal) == ([2] if design == "credit_guard" else [1])
    assert reference_cycle_expectations(first, contract(design)) == reference_cycle_expectations(first, contract(design))


@pytest.mark.parametrize("design", HOLDOUTS)
def test_512_cycle_table_preserves_one_original_plan_vector(design):
    inputs = {"acquire": 1} if design == "credit_guard" else {"request": "4'hf", "advance": 1}
    stimulus = plan(design, [{"name": "long_hold", "inputs": inputs, "cycles": 512}])
    original = stimulus.model_dump(mode="json")
    table = reference_cycle_expectations(stimulus, contract(design))
    assert len(stimulus.vectors) == 1 and len(table["long_hold"]) == 512
    signal, expected = ("credits", [2, 1] + [0] * 510) if design == "credit_guard" else ("grant", [1, 2, 4, 8] * 128)
    assert flatten(table, signal) == expected
    Generator().validate(stimulus, contract(design), reference_sampling="per_cycle", cycle_expectations=table)
    assert stimulus.model_dump(mode="json") == original


@pytest.mark.parametrize("design", HOLDOUTS)
@pytest.mark.parametrize("mismatch", ("parameter", "signed", "width", "direction", "extra_port", "clock_edge", "reset_type", "reset_polarity", "no_reset", "no_clock"))
def test_holdout_oracle_requires_exact_unsigned_parameterless_clock_reset_contract(design, mismatch):
    base = contract(design)
    if mismatch == "parameter": changed = replace(base, parameters={"WIDTH": 4})
    elif mismatch == "signed": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], signed=True)))
    elif mismatch == "width": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], width=2)))
    elif mismatch == "direction": changed = replace(base, ports=(*base.ports[:-1], replace(base.ports[-1], direction=PortDirection.INPUT)))
    elif mismatch == "extra_port": changed = replace(base, ports=(*base.ports, replace(base.ports[-1], name="extra")))
    elif mismatch == "clock_edge": changed = replace(base, clock=replace(base.clock, edge="negedge"))
    elif mismatch == "reset_type": changed = replace(base, reset=replace(base.reset, synchronous=True))
    elif mismatch == "reset_polarity": changed = replace(base, reset=replace(base.reset, active_level=1))
    elif mismatch == "no_reset": changed = replace(base, reset=None)
    else: changed = replace(base, clock=None)
    stimulus = plan(design, [{"name": "observe", "inputs": {}, "cycles": 2}])
    assert reference_sampling_profile(changed) is None
    assert reference_expectations(stimulus, contract=changed) == {}
    assert reference_expectations(stimulus, contract=changed, authoritative_only=False) == {}
    with pytest.raises(ReferenceSamplingError, match="not supported"):
        reference_cycle_expectations(stimulus, changed)


@pytest.mark.parametrize("design", HOLDOUTS)
def test_holdout_name_alone_or_other_module_contract_never_selects_an_authoritative_model(design):
    stimulus = plan(design, [{"name": "observe", "inputs": {}, "cycles": 1}])
    other = contract("rotating_arbiter" if design == "credit_guard" else "credit_guard")
    assert reference_expectations(stimulus) == {}
    assert reference_expectations(stimulus, contract=contract(design).to_dict()) == {}
    assert reference_expectations(stimulus, contract=other) == {}
    assert design in AUTHORITATIVE
    assert reference_sampling_profile(contract(design)) == f"{PER_CYCLE_PROFILE_VERSION}:{design}"
    assert functional_coverage_profile(contract(design)) is None


@pytest.mark.parametrize("design,inputs", [
    ("credit_guard", {"acquire": "1'bx"}), ("credit_guard", {"release_req": "1'bz"}),
    ("rotating_arbiter", {"request": "4'bx001"}), ("rotating_arbiter", {"advance": 2}),
    ("rotating_arbiter", {"request": 16}), ("credit_guard", {"clk": 1}),
    ("rotating_arbiter", {"grant": 1}), ("credit_guard", {"undeclared": 1}),
])
def test_unknown_or_illegal_inputs_cannot_generate_holdout_oracle_numbers(design, inputs):
    stimulus = plan(design, [{"name": "bad", "inputs": inputs, "cycles": 1}])
    with pytest.raises(ReferenceSamplingError):
        reference_cycle_expectations(stimulus, contract(design))


@pytest.mark.parametrize("design", HOLDOUTS)
def test_before_samples_do_not_claim_known_clocked_holdout_values(design):
    stimulus = plan(design, [{"name": "before", "inputs": {}, "sample_phase": "before", "cycles": 2}])
    assert reference_expectations(stimulus, contract=contract(design)) == {}
    with pytest.raises(ReferenceSamplingError, match="after only"):
        reference_cycle_expectations(stimulus, contract(design))


def test_old_fifteen_default_maps_and_profile_identities_remain_unchanged():
    # Freeze the original cohort itself. New adapters must not dilute the
    # historical defaults checksum or expand its denominator.
    old_designs = sorted({
        "mod10_counter", "simple_alu", "sequence_101_overlap",
        "traffic_light_emergency", "sync_fifo", "uart_tx", "spi_master",
        "handshake_stage", "debounce", "pwm", "mux4", "sync_reset",
        "johnson_counter", "edge_detector", "pulse_stretcher",
    })
    assert set(old_designs) <= AUTHORITATIVE
    assert len(old_designs) == 15
    defaults = {name: INPUT_DEFAULTS[name] for name in old_designs}
    encoded = json.dumps(defaults, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "ac346ec7bcf7d39850c0db5b40d05ef0c05d4c845f2d24078725670317306918"
    for design in old_designs:
        payload = json.loads((ROOT / f"examples/{design}_contract.json").read_text(encoding="utf-8"))
        assert reference_sampling_profile(DutContract.from_dict(payload)) == f"builtin-reference-per-cycle-v1:{design}"


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("design", HOLDOUTS)
def test_actual_holdout_per_cycle_results_check_every_cycle_and_preserve_artifact_identity(tmp_path, design):
    inputs = {"acquire": 1, "release_req": 0} if design == "credit_guard" else {"request": 15, "advance": 1}
    stimulus = plan(design, [
        {"name": "operate", "inputs": inputs, "cycles": 6},
        {"name": "hold_inputs", "inputs": {}, "cycles": 3},
        {"name": "clear", "inputs": {"rst_n": 0}, "cycles": 2},
        {"name": "resume", "inputs": {"rst_n": 1}, "cycles": 2},
    ])
    original = stimulus.model_dump(mode="json")
    result = VerificationPipeline().run(stimulus, contract(design), ROOT / f"rtl/{design}.v", tmp_path / design,
        reference_sampling="per_cycle", capture_observations=True, emit_vcd=False,
        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp, max_output_chars=2_000_000)
    assert result.status is ResultStatus.PASSED and result.simulation.check_count == 13
    assert result.plan is stimulus and stimulus.model_dump(mode="json") == original
    packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert packet["status"] == "complete" and packet["observed_cycles"] == packet["expected_cycles"] == 13
    metadata = result.simulation.config["oracle"]["reference_samples"]
    artifact = Path(result.artifacts["reference_samples"])
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == metadata["sha256"]
    reference = json.loads(artifact.read_text(encoding="utf-8"))
    assert reference["provenance"]["plan_sha256"] == hashlib.sha256(Path(result.artifacts["testplan"]).read_bytes()).hexdigest()
    assert len(reference["samples"]) == 13
