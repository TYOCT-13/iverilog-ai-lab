"""v8 field hierarchy and actual port feedback; scripted providers, zero API."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from iverilog_ai.ai.agent import (
    AgentDecision, AgentLimits, AgentObservation, PROMPT_VERSION, SYSTEM_PROMPT,
    decision_shape_constraints, run_verification_agent,
)
from iverilog_ai.ai.schema import TestVector as Vector
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.reference_model import AUTHORITATIVE, INPUT_DEFAULTS, reference_sampling_profile
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()
STUDY_MODULES = (
    "sync_fifo", "uart_tx", "spi_master", "handshake_stage", "credit_guard",
    "rotating_arbiter", "edge_detector", "pulse_stretcher",
)
COVERAGE_MODULES = frozenset({"sync_fifo", "uart_tx", "spi_master", "handshake_stage"})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("v8 integration tests must not use a network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


class Scripted:
    model = "local-v8-feedback-fixture"
    last_finish_reason = "stop"
    last_usage = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
    api_key = "synthetic-v8-fixture-credential-only"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.states = []

    def generate(self, prompt):
        self.states.append(json.loads(prompt.split("STATE_JSON:\n", 1)[1]))
        response = self.responses.pop(0)
        return response if isinstance(response, str) else json.dumps(response)


class CheckedStub:
    """Control-flow fixture; the port helper must never treat this as evidence."""
    reference_policy = "builtin"

    def __init__(self):
        self.plans, self.options = [], []

    def run(self, plan, contract, rtl_path, output, **options):
        self.plans.append(plan)
        self.options.append(dict(options))
        simulation = SimpleNamespace(
            run_id="explicit-checked-stub", status=SimpleNamespace(value="passed"), verdict="passed",
            config={"oracle": {"expectation_source": "reference_model"}}, records=[1], failures=[],
        )
        return SimpleNamespace(simulation=simulation, plan=plan, contract=contract,
                               artifacts={"pipeline_result": str(output / "pipeline_result.json")})


def contract_for(module):
    return DutContract.from_dict(json.loads((ROOT / "examples" / f"{module}_contract.json").read_bytes()))


def proposal(cycles=2, *, inputs=None, count=1):
    return {"action": "append_vectors", "reason": "observe bounded held inputs", "vectors": [
        {"name": f"hold_{index}", "inputs": {} if inputs is None else inputs, "cycles": cycles,
         "sample_phase": "after"} for index in range(count)]}


def stop():
    return {"action": "stop", "reason": "local fixture complete", "vectors": []}


def run(tmp_path, service, *, module="mod10_counter", pipeline=None, contract=None, **options):
    return run_verification_agent(
        provider=service, contract=contract or contract_for(module), rtl_path=ROOT / "rtl" / f"{module}.v",
        output_dir=tmp_path / "agent", objective="local generic feedback integration",
        pipeline=pipeline or CheckedStub(), agent_plan_mode="independent",
        limits=options.pop("limits", AgentLimits(max_rounds=3, max_requests=3, max_total_cycles=16)),
        **options,
    )


def real_options():
    return {"reference_sampling": "per_cycle", "iverilog_path": TOOLS.iverilog, "vvp_path": TOOLS.vvp}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_field_constraints_are_generated_from_actual_models_without_defaults_or_repeated_state_schema(tmp_path):
    shape = decision_shape_constraints(max_new_vectors=2)
    root, vector = AgentDecision.model_json_schema(), Vector.model_json_schema()
    assert shape["root"]["allowed_keys"] == sorted(root["properties"])
    assert shape["root"]["required_keys"] == root["required"]
    assert shape["root"]["action_values"] == root["properties"]["action"]["enum"]
    assert shape["root"]["reason"]["maxLength"] == root["properties"]["reason"]["maxLength"]
    assert shape["vector"]["allowed_keys"] == sorted(vector["properties"])
    assert shape["vector"]["required_keys"] == vector["required"]
    assert shape["vectors"] == {"schema_max_items": root["properties"]["vectors"]["maxItems"],
                                "max_new_items_this_request": 2}
    allowed_constraints = {"type", "enum", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
    assert shape["vector"]["fields"] == {
        name: {key: value for key, value in field.items() if key in allowed_constraints}
        for name, field in vector["properties"].items()
    }
    assert "default" not in json.dumps(shape) and "$defs" not in json.dumps(shape)
    assert shape["root"]["additional_properties"] is shape["vector"]["additional_properties"] is False
    assert shape["agent_policy"]["nonempty_expected_outputs"] == "forbidden"
    encoded = SYSTEM_PROMPT.split("DECISION_SHAPE_FROM_VALIDATORS:", 1)[1].lstrip()
    static_shape, _ = json.JSONDecoder().raw_decode(encoded)
    assert static_shape == decision_shape_constraints()
    assert static_shape["vectors"]["max_new_items_this_request"] == "state.max_new_vectors"
    assert SYSTEM_PROMPT.count("DECISION_SHAPE_FROM_VALIDATORS:") == 1
    service = Scripted(stop())
    result = run(tmp_path, service, limits=AgentLimits(max_vectors=2, max_requests=1))
    assert result.stop_reason == "model_stopped"
    assert service.states[0]["max_new_vectors"] == 2 and "decision_shape" not in service.states[0]
    assert "schema_max_items" not in json.dumps(service.states[0])


@pytest.mark.parametrize("invalid", [-1, 13, True, "2", 1.5])
def test_shape_dynamic_cap_does_not_invent_or_coerce_limits(invalid):
    with pytest.raises(ValueError):
        decision_shape_constraints(max_new_vectors=invalid)


def test_closed_examples_pass_the_strict_validator_and_root_vector_levels_stay_distinct():
    assert PROMPT_VERSION == "verification-agent-v8-bounded-port-feedback"
    for marker in ("Valid append example", "Valid stop example"):
        suffix = SYSTEM_PROMPT.split(marker, 1)[1]
        value, _ = json.JSONDecoder().raw_decode(suffix[suffix.index("{"):])
        assert set(value) == {"action", "reason", "vectors"}
        AgentDecision.model_validate(value)
    valid = proposal()
    for extra in ({"cycles": 2}, {"sample_phase": "after"}, {"type": "json_object"}):
        with pytest.raises(ValidationError) as error:
            AgentDecision.model_validate({**valid, **extra})
        assert any(item["type"] == "extra_forbidden" for item in error.value.errors())
    valid["vectors"][0]["expected"] = {"count": 2}
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(valid)
    assert "Port observations describe only a previous completed episode" in SYSTEM_PROMPT
    assert "Recompute a complete reachable input path" in SYSTEM_PROMPT
    assert "Hold unchanged inputs" in SYSTEM_PROMPT
    assert not any(module in SYSTEM_PROMPT for module in STUDY_MODULES)


@pytest.mark.parametrize("feedback", [True, False])
@pytest.mark.parametrize("kind", ["root_cycles", "vector_unknown", "too_many", "input_unknown", "incomplete_json"])
def test_recovery_hints_are_trusted_hierarchical_and_hidden_without_feedback(tmp_path, feedback, kind):
    raw = proposal()
    if kind == "root_cycles":
        raw["cycles"] = 2
    elif kind == "vector_unknown":
        raw["vectors"][0]["untrusted_unknown_name"] = "untrusted diagnostic message"
    elif kind == "too_many":
        raw = proposal(count=13)
    elif kind == "input_unknown":
        raw["vectors"][0]["inputs"] = {"bad;signal": 1}
    else:
        raw = '{"action":'
    service, stub = Scripted(raw, proposal(1)), CheckedStub()
    result = run(tmp_path, service, pipeline=stub, include_feedback=feedback,
                 limits=AgentLimits(max_rounds=1, max_requests=2, max_vectors=5))
    assert result.stop_reason == "round_budget" and len(stub.plans) == 1
    rejected, accepted = result.trajectory["decisions"]
    assert rejected["schema_validation_status"] == "rejected" and rejected["retry_eligible"] is True
    assert "executed_round" not in rejected and accepted["executed_round"] == 1
    diagnostic = rejected["decision_error"]
    hints = diagnostic["errors"]
    expected_scope = {"root_cycles": "root", "vector_unknown": "vector", "too_many": "vectors",
                      "input_unknown": "inputs", "incomplete_json": "json"}[kind]
    assert hints[0]["scope"] == expected_scope
    if kind == "too_many":
        assert hints[0]["max_items"] == 5
    else:
        fields = {"root": sorted(AgentDecision.model_fields), "json": sorted(AgentDecision.model_fields),
                  "vector": sorted(Vector.model_fields), "inputs": ["enable", "rst_n"]}
        assert hints[0]["allowed_keys"] == fields[expected_scope]
    assert service.states[1]["latest_decision_error"] == (diagnostic if feedback else None)
    assert service.states[1]["observation"] is None and service.states[1]["plan_error"] is None
    model_state = json.dumps(service.states[1])
    assert "untrusted_unknown_name" not in model_state and "untrusted diagnostic message" not in model_state
    assert "bad;signal" not in model_state
    if not feedback:
        assert "allowed_keys" not in model_state and "schema_invalid" not in model_state
    assert result.trajectory["accepted_vectors"] == result.trajectory["stimulus_cycles_executed"] == 1


@pytest.mark.parametrize("module", sorted(AUTHORITATIVE))
@pytest.mark.parametrize("feedback", [True, False])
def test_capture_is_enabled_for_every_supported_builtin_profile_even_without_feedback(tmp_path, module, feedback):
    contract = contract_for(module)
    assert reference_sampling_profile(contract) is not None
    service, stub = Scripted(proposal(1, inputs=INPUT_DEFAULTS[module]), stop()), CheckedStub()
    result = run(tmp_path, service, module=module, contract=contract, pipeline=stub,
                 include_feedback=feedback, execution_options={"reference_sampling": "per_cycle"})
    assert result.stop_reason == "model_stopped" and stub.options[0]["capture_observations"] is True
    assert result.trajectory["port_observation_capture_enabled"] is True
    port_feedback = result.trajectory["rounds"][0]["observation"]["port_observations"]
    assert port_feedback["status"] == "inconclusive" and port_feedback["samples"] == []
    assert port_feedback["reason"] == "unsupported_result_contract"  # Stub is not an actual simulation.
    assert service.states[1]["observation"] is None if not feedback else service.states[1]["observation"] is not None


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("module", STUDY_MODULES)
@pytest.mark.parametrize("feedback", [True, False])
def test_eight_module_matrix_has_bound_actual_samples_and_feedback_ablation(tmp_path, module, feedback):
    contract = contract_for(module)
    service = Scripted(proposal(2, inputs=INPUT_DEFAULTS[module]), stop())
    result = run(tmp_path, service, module=module, contract=contract, pipeline=VerificationPipeline(),
                 include_feedback=feedback, execution_options=real_options())
    assert result.stop_reason == "model_stopped" and result.last_result.verdict == "passed"
    actual, trace = result.last_result, result.trajectory
    assert actual.simulation.check_count == 2 * len(contract.outputs)
    assert trace["record_kind"] == "test_provider" and trace["requests_attempted"] == 2
    assert trace["stimulus_cycles_executed"] == 2 and trace["accepted_vectors"] == 1
    observation = trace["rounds"][0]["observation"]
    port_feedback = observation["port_observations"]
    packet = json.loads(Path(actual.artifacts["observed_samples"]).read_bytes())
    assert packet["status"] == port_feedback["status"] == "complete"
    assert port_feedback["samples"] == packet["samples"] and port_feedback["total_samples"] == 2
    assert port_feedback["returned_samples"] == 2 and port_feedback["omitted_samples"] == 0
    assert all(sample["inputs"]["rst_n"] == "1" for sample in packet["samples"])
    assert port_feedback["sampling_phase"] == "after" and not port_feedback["contains_unknown_bits"]
    provenance = port_feedback["provenance"]
    assert provenance["observed_samples_sha256"] == digest(actual.artifacts["observed_samples"])
    assert provenance["executor_result_sha256"] == digest(actual.artifacts["result_json"])
    assert provenance["run_stdout_sha256"] == hashlib.sha256(actual.simulation.run.stdout.encode()).hexdigest()
    assert provenance["rtl_sha256"] == trace["rtl_sha256"] == digest(ROOT / "rtl" / f"{module}.v")
    assert port_feedback["execution"]["run_id"] == actual.simulation.run_id
    assert set(port_feedback["samples"][0]["outputs"]) == {port.name for port in contract.outputs}
    coverage = trace["rounds"][0]["functional_coverage"]
    assert coverage["status"] == ("measured" if module in COVERAGE_MODULES else "unsupported")
    assert "bins" not in port_feedback and "expected" not in json.dumps(port_feedback)
    if feedback:
        assert service.states[1]["observation"]["port_observations"] == port_feedback
    else:
        assert all(state["observation"] is state["plan_error"] is state["latest_decision_error"] is None
                   for state in service.states)
        assert "port_observations" not in json.dumps(service.states)
    assert trace["port_observation_feedback_enabled"] is feedback


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("feedback", [True, False])
def test_previous_observed_ports_do_not_continue_into_the_next_independent_episode(tmp_path, feedback):
    service = Scripted(proposal(3, inputs={"enable": 1}), proposal(2, inputs={"enable": 0}), stop())
    result = run(tmp_path, service, pipeline=VerificationPipeline(), include_feedback=feedback,
                 execution_options=real_options())
    assert result.stop_reason == "model_stopped"
    first, second = result.trajectory["rounds"]
    previous = first["observation"]["port_observations"]
    subsequent = second["observation"]["port_observations"]
    assert [int(sample["outputs"]["count"], 2) for sample in previous["samples"]] == [1, 2, 3]
    assert [int(sample["outputs"]["count"], 2) for sample in subsequent["samples"]] == [0, 0]
    assert first["plan"]["vectors"][0]["inputs"] == {"enable": 1}
    assert second["plan"]["vectors"][0]["inputs"] == {"enable": 0}
    next_execution = service.states[1]["next_execution"]
    assert next_execution["fresh_dut_instance"] is True and next_execution["circuit_state_continues"] is False
    assert next_execution["prior_vectors_replayed"] is next_execution["prior_input_levels_carried"] is False
    assert next_execution["replay_cycles"] == 0
    assert service.states[1]["observation"] is None if not feedback else service.states[1]["observation"]["port_observations"] == previous
    assert result.trajectory["stimulus_cycles_executed"] == 5
    assert result.trajectory["automatic_reset_cycles_executed"] == 4
    assert first["observation"]["checks"] == 3 and second["observation"]["checks"] == 2


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_disabling_functional_coverage_only_removes_bins_from_model_feedback(tmp_path):
    service = Scripted(proposal(2, inputs=INPUT_DEFAULTS["sync_fifo"]), stop())
    result = run(tmp_path, service, module="sync_fifo", pipeline=VerificationPipeline(),
                 include_feedback=True, include_functional_coverage=False, execution_options=real_options())
    assert result.stop_reason == "model_stopped"
    stored = result.trajectory["rounds"][0]["observation"]
    delivered = service.states[1]["observation"]
    assert stored["functional_coverage"]["status"] == "measured" and stored["functional_coverage"]["bins"]
    assert "functional_coverage" not in delivered and "bins" not in json.dumps(delivered)
    assert delivered["port_observations"] == stored["port_observations"]
    assert result.trajectory["port_observation_feedback_enabled"] is True
    assert result.trajectory["functional_coverage_feedback_enabled"] is False


@pytest.mark.parametrize("feedback", [True, False])
def test_typed_external_observer_preserves_its_contract_without_injecting_port_feedback(tmp_path, monkeypatch, feedback):
    def forbidden_helper(*args, **kwargs):
        raise AssertionError("typed observer must not call the builtin port helper")
    monkeypatch.setattr("iverilog_ai.ai.agent.build_observation_feedback", forbidden_helper)
    candidate_sha = digest(ROOT / "rtl/mod10_counter.v")
    observed = AgentObservation(status="passed", verdict="no_observed_difference",
        expectation_source="qualified_baseline_differential", verification_status="qualified_baseline_differential",
        compared_samples=2, qualified_outputs=["count"], qualification_sha256="a" * 64,
        baseline_sha256="b" * 64, candidate_sha256=candidate_sha)
    service, stub = Scripted(proposal(2), stop()), CheckedStub()
    result = run(tmp_path, service, pipeline=stub, include_feedback=feedback,
                 round_observer=lambda result: observed, simulation_multiplier=2)
    assert result.stop_reason == "model_stopped"
    stored = result.trajectory["rounds"][0]["observation"]
    assert stored == observed.model_dump(mode="json") and "port_observations" not in stored
    assert "capture_observations" not in stub.options[0]
    assert result.trajectory["port_observation_capture_enabled"] is False
    assert result.trajectory["port_observation_feedback_enabled"] is False
    assert result.trajectory["port_observation_policy"] == "external_observer_fields_unchanged"
    assert service.states[1]["observation"] == (stored if feedback else None)


def test_unqualified_reference_policy_does_not_automatically_enable_capture(tmp_path):
    stub = CheckedStub()
    stub.reference_policy = "external"
    service = Scripted(proposal(), stop())
    result = run(tmp_path, service, pipeline=stub)
    assert result.stop_reason == "model_stopped" and "capture_observations" not in stub.options[0]
    assert result.trajectory["port_observation_capture_enabled"] is False


@pytest.mark.parametrize("raw", [
    '{"action":"stop","reason":"one","reason":"two","vectors":[]}',
    '{"action":"stop","reason":"\\u0073ynthetic-v8-fixture-credential-only","vectors":[]}',
    '{"action":"stop","reason":"\\u0073ynthetic-v8-fixture-credential-only',
])
def test_v8_recovery_still_refuses_ambiguous_or_sensitive_responses_without_retry(tmp_path, raw):
    service, stub = Scripted(raw, proposal()), CheckedStub()
    result = run(tmp_path, service, pipeline=stub)
    assert result.stop_reason == "policy_error" and result.trajectory["requests_attempted"] == 1
    assert result.trajectory["stimulus_cycles_executed"] == result.trajectory["accepted_vectors"] == 0
    assert not stub.plans and len(service.responses) == 1
    row = result.trajectory["decisions"][0]
    assert row["retry_eligible"] is False and row["untrusted_response_status"] == "blocked"
    assert "untrusted_response" not in row
    assert row["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert not (result.trajectory_path.parent / "untrusted_decisions").exists()
    assert service.api_key not in result.trajectory_path.read_text(encoding="utf-8")
