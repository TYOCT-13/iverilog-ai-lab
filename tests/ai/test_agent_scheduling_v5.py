"""Episode scheduling, recoverable plan errors and real reset evidence; zero API."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.core.toolchain import locate_tools as _locate_test_tools
TEST_TOOLS = _locate_test_tools()

from iverilog_ai.ai.agent import AgentLimits, AgentObservation, PROMPT_VERSION, run_verification_agent
from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import PipelineValidationError

ROOT = Path(__file__).resolve().parents[2]


class Scripted:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.states = []

    def generate(self, prompt):
        self.states.append(json.loads(prompt.split("STATE_JSON:\n", 1)[1]))
        return json.dumps(self.answers.pop(0))


class Pipeline:
    def __init__(self):
        self.plans = []
        self.options = []

    def run(self, plan, contract, source, output, **options):
        self.plans.append(plan.model_dump(mode="json"))
        self.options.append(options)
        simulation = SimpleNamespace(run_id="test-only", status=SimpleNamespace(value="passed"),
            verdict="passed", config={"oracle": {"expectation_source": "reference_model"}},
            records=[1], failures=[])
        return SimpleNamespace(simulation=simulation, plan=plan,
            artifacts={"pipeline_result": str(output.resolve() / "pipeline_result.json")})


def proposal(cycles=1, inputs=None):
    return {"action": "append_vectors", "reason": "test input boundaries", "vectors": [
        {"name": "attempt", "inputs": {"enable": 1} if inputs is None else inputs,
         "cycles": cycles, "sample_phase": "after"}]}


def run(tmp_path, service, pipeline=None, **options):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    return run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
        output_dir=tmp_path / "agent", objective="observe reset and input boundaries",
        pipeline=pipeline or Pipeline(), **options)


@pytest.mark.parametrize("mode,total,replay,next_cycles,plan_lengths", [
    ("append", 4, 1, 2, [1, 2]), ("independent", 3, 0, 3, [1, 1])])
def test_real_plan_size_and_available_budget_match_each_mode(tmp_path, mode, total, replay, next_cycles, plan_lengths):
    service = Scripted(proposal(1), proposal(2))
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline, agent_plan_mode=mode,
                 limits=AgentLimits(max_rounds=2, max_total_cycles=4))
    assert result.stop_reason == "round_budget"
    assert [len(plan["vectors"]) for plan in pipeline.plans] == plan_lengths
    assert result.trajectory["stimulus_cycles_executed"] == total
    assert result.trajectory["automatic_reset_cycles_executed"] == 4
    assert service.states[1]["next_execution"]["replay_cycles"] == replay
    assert service.states[1]["max_new_cycles"] == next_cycles
    assert service.states[1]["remaining_stimulus_cycles"] == 3
    assert service.states[1]["next_execution"]["circuit_state_continues"] is False
    assert service.states[1]["next_execution"]["prior_vectors_replayed"] is (mode == "append")
    assert service.states[1]["next_execution"]["automatic_reset_cycles_in_stimulus_budget"] is False
    assert result.trajectory["rounds"][0]["plan"] == pipeline.plans[0]
    assert service.states[1]["current_plan"] == pipeline.plans[0]
    assert all(row["fresh_dut_instance"] for row in result.trajectory["rounds"])


def test_library_defaults_keep_append_and_vector_end_compatibility(tmp_path):
    pipeline = Pipeline()
    result = run(tmp_path, Scripted(proposal()), pipeline, limits=AgentLimits(max_rounds=1))
    assert result.trajectory["agent_plan_mode"] == "append"
    assert result.trajectory["reference_sampling"] == "vector_end"
    assert pipeline.options[0]["reference_sampling"] == "vector_end"
    assert result.trajectory["prompt_version"] == PROMPT_VERSION
    assert PROMPT_VERSION == "verification-agent-v8-bounded-port-feedback"


def test_append_does_not_request_when_replay_leaves_no_new_cycle(tmp_path):
    service = Scripted(proposal(2))
    result = run(tmp_path, service, limits=AgentLimits(max_rounds=2, max_total_cycles=4))
    assert result.stop_reason == "cycle_budget"
    assert len(service.states) == 1
    assert result.trajectory["stimulus_cycles_executed"] == 2


def test_independent_reuses_remaining_budget_instead_of_replaying_old_plan(tmp_path):
    service = Scripted(proposal(2), proposal(1))
    result = run(tmp_path, service, agent_plan_mode="independent",
                 limits=AgentLimits(max_rounds=2, max_total_cycles=3))
    assert result.stop_reason == "round_budget"
    assert service.states[1]["max_new_cycles"] == 1
    assert result.trajectory["stimulus_cycles_executed"] == 3


def test_independent_vector_limit_counts_all_accepted_episodes(tmp_path):
    service = Scripted(proposal(1), proposal(2))
    result = run(tmp_path, service, agent_plan_mode="independent", limits=AgentLimits(max_vectors=2))
    assert result.stop_reason == "vector_budget"
    assert result.trajectory["accepted_vectors"] == 2
    assert len(service.states) == 2
    assert all(len(row["plan"]["vectors"]) == 1 for row in result.trajectory["rounds"])


def test_independent_paired_execution_charges_both_new_episodes(tmp_path):
    candidate_sha = hashlib.sha256((ROOT / "rtl/mod10_counter.v").read_bytes()).hexdigest()
    def observe(actual):
        return AgentObservation(status="passed", verdict="no_observed_difference",
            expectation_source="qualified_baseline_differential",
            verification_status="qualified_baseline_differential", compared_samples=2,
            qualified_outputs=["count"], qualification_sha256="a" * 64,
            baseline_sha256="b" * 64, candidate_sha256=candidate_sha)
    service = Scripted(proposal(1), proposal(2))
    result = run(tmp_path, service, agent_plan_mode="independent", round_observer=observe,
                 simulation_multiplier=2, limits=AgentLimits(max_rounds=2, max_total_cycles=6))
    assert result.stop_reason == "round_budget"
    assert result.trajectory["stimulus_cycles_executed"] == 6
    assert result.trajectory["candidate_stimulus_cycles_executed"] == 3
    assert result.trajectory["baseline_stimulus_cycles_executed"] == 3
    assert result.trajectory["reference_sampling"] == "vector_end"
    assert service.states[1]["remaining_candidate_cycles"] == 2
    assert service.states[1]["max_new_cycles"] == 2
    assert service.states[1]["next_execution"]["prior_vectors_replayed"] is False


@pytest.mark.parametrize("mode", [None, "unknown", {}, True])
def test_invalid_episode_mode_fails_before_output_or_request(tmp_path, mode):
    service = Scripted()
    with pytest.raises(ValueError, match="agent_plan_mode"):
        run(tmp_path, service, agent_plan_mode=mode)
    assert service.states == []
    assert not (tmp_path / "agent").exists()


@pytest.mark.parametrize("feedback", [True, False])
def test_recoverable_clock_error_does_not_spend_a_simulation_round(tmp_path, feedback):
    service = Scripted(proposal(inputs={"clk": 0}), proposal(inputs={"rst_n": 1, "enable": 1}))
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline, agent_plan_mode="independent", include_feedback=feedback,
                 limits=AgentLimits(max_rounds=1, max_requests=2))
    assert result.stop_reason == "round_budget"
    assert result.trajectory["requests_attempted"] == 2
    assert len(pipeline.plans) == len(result.trajectory["rounds"]) == 1
    assert result.trajectory["stimulus_cycles_executed"] == 1
    assert result.trajectory["accepted_vectors"] == 1
    error = {"code": "auto_clock_input", "fields": ["vectors.inputs.clk"]}
    rejected = result.trajectory["decisions"][0]
    assert rejected["status"] == "validated" and rejected["plan_validation_status"] == "rejected"
    assert rejected["plan_error"] == error and "executed_round" not in rejected
    assert result.trajectory["decisions"][1]["plan_validation_status"] == "passed"
    failed = result.trajectory["failed_attempts"][0]
    assert failed["simulation_started"] is False and failed["stimulus_cycles_executed"] == 0
    assert failed["decision_index"] == 1 and failed["error"] == error
    assert service.states[1]["remaining_rounds"] == 1
    assert service.states[1]["remaining_stimulus_cycles"] == 1000
    assert service.states[1]["plan_error"] == (error if feedback else None)
    assert service.states[0]["auto_driven_inputs"] == ["clk"]
    assert service.states[0]["allowed_driven_inputs"] == ["enable", "rst_n"]
    assert not (tmp_path / "agent/round-02").exists()


@pytest.mark.parametrize("inputs,code,fields", [
    ({"count": 0}, "output_port_input", ["vectors.inputs.count"]),
    ({"untrusted_field_with_message": 0}, "unknown_input_port", ["vectors.inputs"]),
    ({"enable": 2}, "plan_contract_invalid", ["vectors.inputs.enable"]),
    ({"enable": "untrusted-value-do-not-feed-back"}, "plan_contract_invalid", ["vectors.inputs.enable"]),
])
def test_plan_error_feedback_uses_only_fixed_codes_and_contract_fields(tmp_path, inputs, code, fields):
    service = Scripted(proposal(inputs=inputs), proposal())
    result = run(tmp_path, service, agent_plan_mode="independent",
                 limits=AgentLimits(max_rounds=1, max_requests=2))
    assert result.stop_reason == "round_budget"
    assert service.states[1]["plan_error"] == {"code": code, "fields": fields}
    prompt_data = json.dumps(service.states[1])
    assert "untrusted_field_with_message" not in prompt_data
    assert "untrusted-value-do-not-feed-back" not in prompt_data
    assert service.states[1]["current_plan"] is None
    assert result.trajectory["failed_attempts"][0]["plan"]["vectors"][0]["inputs"] == inputs


def test_all_preflight_failures_leave_no_round_or_simulation_evidence(tmp_path):
    pipeline = Pipeline()
    result = run(tmp_path, Scripted(proposal(inputs={"clk": 0})), pipeline,
                 limits=AgentLimits(max_requests=1), agent_plan_mode="independent")
    assert result.stop_reason == "request_budget"
    assert result.last_result is None
    assert not pipeline.plans and not result.trajectory["rounds"]
    assert result.trajectory["stimulus_cycles_executed"] == 0
    assert result.trajectory["automatic_reset_cycles_executed"] == 0
    assert len(result.trajectory["failed_attempts"]) == 1
    assert not list((tmp_path / "agent").glob("round-*"))


@pytest.mark.parametrize("mode,total,final_length,max_new", [("append", 4, 2, 2), ("independent", 3, 1, 3)])
def test_invalid_supplement_preserves_last_evidence_and_remaining_replay_budget(tmp_path, mode, total, final_length, max_new):
    service = Scripted(proposal(1), proposal(inputs={"clk": 0}), proposal(2))
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline, agent_plan_mode=mode,
                 limits=AgentLimits(max_rounds=2, max_requests=3, max_total_cycles=4))
    assert result.stop_reason == "round_budget"
    assert len(result.trajectory["rounds"]) == len(pipeline.plans) == 2
    assert result.trajectory["requests_attempted"] == 3
    assert result.trajectory["stimulus_cycles_executed"] == total
    assert result.trajectory["rounds"][0]["plan"] == pipeline.plans[0]
    assert len(pipeline.plans[1]["vectors"]) == final_length
    failed = result.trajectory["failed_attempts"][0]
    assert failed["decision_index"] == 2 and failed["simulation_started"] is False
    assert service.states[2]["current_plan"] == pipeline.plans[0]
    assert service.states[2]["observation"] is not None
    assert service.states[2]["remaining_stimulus_cycles"] == 3
    assert service.states[2]["max_new_cycles"] == max_new
    assert service.states[2]["remaining_rounds"] == 1
    assert result.trajectory["accepted_vectors"] == 2


def test_invalid_initial_plan_is_not_silently_replaced_by_model(tmp_path):
    initial = Plan.model_validate({"design": "mod10_counter", "objective": "caller plan", "vectors": [
        {"name": "caller", "inputs": {"clk": 0}, "cycles": 1}]})
    service = Scripted(proposal())
    original = initial.model_dump(mode="json")
    result = run(tmp_path, service, initial_plan=initial, agent_plan_mode="independent")
    assert result.stop_reason == "execution_error"
    assert result.trajectory["error_type"] == "TestbenchGenerationError"
    assert result.trajectory["requests_attempted"] == 0 and service.states == []
    assert result.trajectory["rounds"] == [] and result.last_result is None
    assert result.trajectory["failed_attempts"][0]["decision_index"] is None
    assert initial.model_dump(mode="json") == original


def test_execution_errors_after_preflight_do_not_trigger_plan_recovery(tmp_path):
    class Broken(Pipeline):
        def run(self, *args, **options):
            raise RuntimeError("arbitrary-private-exception")
    service = Scripted(proposal(), proposal(2))
    result = run(tmp_path, service, Broken(), agent_plan_mode="independent")
    assert result.stop_reason == "execution_error"
    assert result.trajectory["error_type"] == "RuntimeError"
    assert result.trajectory["failed_attempts"] == []
    assert len(service.states) == 1 and result.trajectory["rounds"] == []
    assert "arbitrary-private-exception" not in result.trajectory_path.read_text()


def icarus_options(tmp_path):
    compiler = Path(TEST_TOOLS.iverilog or "")
    runtime = Path(TEST_TOOLS.vvp or "")
    if not compiler.is_file() or not runtime.is_file():
        pytest.skip("Icarus unavailable")
    return {"allowed_roots": (ROOT, tmp_path), "iverilog_path": compiler,
            "vvp_path": runtime, "reference_sampling": "per_cycle"}


@pytest.mark.parametrize("mode,final_count,total", [("append", 7, 33), ("independent", 0, 17)])
def test_real_icarus_resets_between_runs_and_holds_inputs_only_inside_an_episode(tmp_path, mode, final_count, total):
    service = Scripted(proposal(16), proposal(1, inputs={}))
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    result = run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
        output_dir=tmp_path / "real", objective="reset boundary", agent_plan_mode=mode,
        limits=AgentLimits(max_rounds=2, max_total_cycles=40), execution_options=icarus_options(tmp_path))
    assert result.stop_reason == "round_budget"
    assert len(result.trajectory["rounds"]) == 2
    assert result.trajectory["stimulus_cycles_executed"] == total
    assert not result.last_result.simulation.failures
    records = result.last_result.simulation.records
    assert int(records[-1].actual, 2) == int(records[-1].expected, 2) == final_count
    assert len(records) == (17 if mode == "append" else 1)
    assert result.last_result.testbench_path.is_file()
    assert result.trajectory["automatic_reset_cycles_executed"] == 4
    assert service.states[1]["next_execution"]["automatic_reset"] == contract.reset.to_dict()
    assert service.states[1]["next_execution"]["fresh_dut_instance"] is True


@pytest.mark.parametrize("bad_kind,error_code,fields", [
    ("before", "unsupported_sample_phase", ["vectors.sample_phase"]),
    ("x", "reference_plan_invalid", ["vectors.inputs.enable"]),
    ("z", "reference_plan_invalid", ["vectors.inputs.enable"]),
])
@pytest.mark.parametrize("feedback", [True, False])
def test_per_cycle_input_errors_can_be_corrected_before_actual_icarus(tmp_path, bad_kind, error_code, fields, feedback):
    action = proposal(2)
    if bad_kind == "before":
        action["vectors"][0]["sample_phase"] = "before"
    else:
        action["vectors"][0]["inputs"]["enable"] = f"1'b{bad_kind}"
    service = Scripted(action, proposal(2))
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    result = run_verification_agent(provider=service, contract=contract,
        rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "before",
        objective="unsupported reference inputs", agent_plan_mode="independent", include_feedback=feedback,
        limits=AgentLimits(max_rounds=1, max_requests=2),
        execution_options=icarus_options(tmp_path))
    assert result.stop_reason == "round_budget"
    assert result.trajectory["requests_attempted"] == 2
    assert len(result.trajectory["failed_attempts"]) == len(result.trajectory["rounds"]) == 1
    assert result.trajectory["failed_attempts"][0]["error_type"] == "ReferenceSamplingError"
    assert result.trajectory["failed_attempts"][0]["simulation_started"] is False
    assert result.trajectory["stimulus_cycles_executed"] == 2
    assert result.last_result.simulation.check_count == 2
    assert [int(record.actual, 2) for record in result.last_result.simulation.records] == [1, 2]
    assert not result.last_result.simulation.failures
    expected_error = {"code": error_code, "fields": fields}
    assert result.trajectory["decisions"][0]["plan_error"] == expected_error
    assert result.trajectory["decisions"][0]["plan_validation_status"] == "rejected"
    assert result.trajectory["decisions"][1]["plan_validation_status"] == "passed"
    assert service.states[1]["plan_error"] == (expected_error if feedback else None)
    assert service.states[1]["input_values_policy"] == "known_binary"
    assert service.states[1]["supported_sample_phases"] == ["after"]
    assert service.states[1]["current_plan"] is None
    assert service.states[1]["remaining_rounds"] == 1
    assert "1'bx" not in json.dumps(service.states[1])
    assert "1'bz" not in json.dumps(service.states[1])


@pytest.mark.parametrize("bad_kind", ["before", "x"])
def test_per_cycle_invalid_initial_inputs_are_not_model_rewritten(tmp_path, bad_kind):
    action = proposal(2)
    if bad_kind == "before":
        action["vectors"][0]["sample_phase"] = "before"
    else:
        action["vectors"][0]["inputs"]["enable"] = "1'bx"
    plan = Plan.model_validate({"design": "mod10_counter", "objective": "caller data",
                                "vectors": action["vectors"]})
    service = Scripted(proposal(2))
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline, initial_plan=plan, agent_plan_mode="independent",
                 execution_options={"reference_sampling": "per_cycle"})
    assert result.stop_reason == "execution_error"
    assert result.trajectory["error_type"] == "ReferenceSamplingError"
    assert result.trajectory["requests_attempted"] == 0
    assert service.states == [] and not pipeline.plans
    assert result.trajectory["rounds"] == [] and result.last_result is None
    assert result.trajectory["failed_attempts"][0]["decision_index"] is None
    assert not list((tmp_path / "agent").glob("round-*"))


@pytest.mark.parametrize("fault", ["module", "port_width", "parameters", "disabled_policy"])
def test_unsupported_per_cycle_configuration_is_rejected_before_requests_and_output(tmp_path, fault):
    data = json.loads((ROOT / "examples/mod10_counter_contract.json").read_text())
    pipeline = Pipeline()
    if fault == "module":
        data["module"] = "unsupported_counter"
    elif fault == "port_width":
        data["ports"][-1]["width"] = 5
    elif fault == "parameters":
        data["parameters"] = {"unsupported_parameter": 1}
    else:
        pipeline.reference_policy = "disabled"
    service = Scripted()
    with pytest.raises(PipelineValidationError, match="supported builtin reference"):
        run_verification_agent(provider=service, contract=DutContract.from_dict(data),
            rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "unsupported",
            objective="caller configuration", pipeline=pipeline,
            execution_options={"reference_sampling": "per_cycle"})
    assert service.states == [] and not pipeline.plans
    assert not (tmp_path / "unsupported").exists()


@pytest.mark.parametrize("value", ["1'bx", "1'bz"])
def test_legacy_vector_end_does_not_inherit_per_cycle_unknown_input_restriction(tmp_path, value):
    pipeline = Pipeline()
    result = run(tmp_path, Scripted(proposal(inputs={"enable": value})), pipeline,
                 limits=AgentLimits(max_rounds=1), execution_options={"reference_sampling": "vector_end"})
    assert result.stop_reason == "round_budget"
    assert result.trajectory["failed_attempts"] == []
    assert pipeline.plans[0]["vectors"][0]["inputs"]["enable"] == value


def old_uart_clock_action():
    """Saved v4 sample-023 action, unchanged including its invalid clock input.

    Source trajectory SHA256:
    2a046e26df92d22d601a60ec627e1c730c75ec08444dac9b883b71feffdc5174.
    Replay is synthetic-provider execution, not a new online API result.
    """
    entries = [
        ("frame_A_0x96_start_pulse", {"clk": 0, "rst_n": 1, "start": 1, "data_in": 150}, 1),
        ("frame_A_hold_idle_through_E40", {"start": 0}, 40),
        ("busy_period_start_request_ignored", {"start": 1, "data_in": 90}, 1),
        ("mid_frame_reset_abort", {"rst_n": 0, "start": 0, "data_in": 0}, 2),
        ("recovery_frame_B_0x3A", {"rst_n": 1, "start": 1, "data_in": 58}, 1),
        ("frame_B_complete_tail", {"start": 0}, 40),
    ]
    return {"action": "append_vectors", "reason": "Drive a full frame, a busy-period start request, "
        "a mid-frame reset abort, and recovery frame to cover acceptance, LSB order, busy-rejection, "
        "abort, and restart boundaries.", "vectors": [
        {"name": name, "inputs": inputs, "cycles": cycles, "sample_phase": "after",
         "expected": {}, "rationale": ""} for name, inputs, cycles in entries]}


def test_saved_v4_uart_clock_action_is_recoverable_with_actual_icarus(tmp_path):
    invalid = old_uart_clock_action()
    corrected = deepcopy(invalid)
    del corrected["vectors"][0]["inputs"]["clk"]
    corrected["reason"] = "Remove the automatically driven clock; retain UART stimulus"
    service = Scripted(invalid, corrected)
    contract = DutContract.from_dict(json.loads((ROOT / "examples/uart_tx_contract.json").read_text()))
    result = run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/uart_tx.v",
        output_dir=tmp_path / "uart-replay", objective="recover saved invalid clock proposal",
        agent_plan_mode="independent", limits=AgentLimits(max_rounds=1, max_requests=2, max_total_cycles=512),
        execution_options=icarus_options(tmp_path))
    assert result.stop_reason == "round_budget"
    assert result.trajectory["record_kind"] == "test_provider"
    assert result.trajectory["requests_attempted"] == 2
    assert len(result.trajectory["failed_attempts"]) == len(result.trajectory["rounds"]) == 1
    assert result.trajectory["stimulus_cycles_executed"] == 85
    assert result.last_result.simulation.check_count == 170
    assert not result.last_result.simulation.failures
    assert service.states[1]["plan_error"]["code"] == "auto_clock_input"
    assert service.states[1]["current_plan"] is None
