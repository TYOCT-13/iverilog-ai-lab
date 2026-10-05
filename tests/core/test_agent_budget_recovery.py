"""Bounded proposal-budget recovery; synthetic providers and real local Icarus."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentLimits, AgentObservation, PROMPT_VERSION, run_verification_agent
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()
FAKE_KEY = "unit-budget-recovery-key-only"
USAGE = {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17}


def proposal(cycles=1, *, vectors=1, reason="bounded budget exercise", inputs=None):
    return json.dumps({"action": "append_vectors", "reason": reason, "vectors": [
        {"name": f"original_{index}", "inputs": {"rst_n": 1, "enable": 1} if inputs is None else inputs,
         "cycles": cycles, "sample_phase": "after"} for index in range(vectors)]})


class Scripted:
    model = "local-budget-recovery-fixture"
    last_finish_reason = "stop"
    last_usage = USAGE
    api_key = FAKE_KEY

    def __init__(self, *responses):
        self.responses = list(responses)
        self.states = []

    def generate(self, prompt):
        self.states.append(json.loads(prompt.split("STATE_JSON:\n", 1)[1]))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class CheckedStub:
    """Controlled execution fixture; no actual DUT evidence is inferred from it."""
    def __init__(self):
        self.plans = []

    def run(self, plan, contract, source, output, **options):
        self.plans.append(plan.model_dump(mode="json"))
        record = SimpleNamespace(ok=True, actual="0000", expected="0000")
        simulation = SimpleNamespace(run_id="checked-budget-stub", status=SimpleNamespace(value="passed"),
            verdict="passed", config={"oracle": {"expectation_source": "reference_model"}},
            records=[record], failures=[])
        return SimpleNamespace(simulation=simulation, plan=plan,
            artifacts={"pipeline_result": str(output.resolve() / "pipeline_result.json")})


def run(tmp_path, service, runner=None, **options):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    return run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
        output_dir=tmp_path / "agent", objective="bounded proposal budget admission", pipeline=runner or CheckedStub(),
        agent_plan_mode=options.pop("agent_plan_mode", "independent"),
        limits=options.pop("limits", AgentLimits(max_total_cycles=16)), **options)


def assert_archived_original(result, index, raw):
    row = result.trajectory["decisions"][index]
    metadata = row["untrusted_response"]
    data = (result.trajectory_path.parent / metadata["path"]).read_bytes()
    assert data == raw.encode("utf-8")
    assert metadata["trusted"] is False and metadata["sha256"] == row["response_sha256"] == hashlib.sha256(data).hexdigest()
    assert metadata["bytes"] == row["response_bytes"] == len(data)
    assert row["usage"] == USAGE


def assert_budget_rejection(row, *, code):
    assert row["status"] == "validated" and row["schema_validation_status"] == "passed"
    assert row["plan_validation_status"] == "rejected" and row["plan_error"]["code"] == code
    assert row["retry_eligible"] is True and "executed_round" not in row
    assert all(isinstance(value, int) and not isinstance(value, bool)
               for key, value in row["plan_error"].items() if key != "code")


def test_first_schema_valid_eighteen_cycle_proposal_is_rejected_without_trimming_then_sixteen_runs(tmp_path):
    bad, good = proposal(18), proposal(16)
    service, stub = Scripted(bad, good), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=2, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["requests_attempted"] == 2
    assert trace["stimulus_cycles_executed"] == 16 and trace["accepted_vectors"] == 1
    assert trace["automatic_reset_cycles_executed"] == 2 and len(stub.plans) == len(trace["rounds"]) == 1
    rejected, accepted = trace["decisions"]
    assert_budget_rejection(rejected, code="stimulus_budget_exceeded")
    assert rejected["action"]["vectors"][0]["cycles"] == 18
    assert stub.plans[0]["vectors"][0]["cycles"] == accepted["action"]["vectors"][0]["cycles"] == 16
    assert service.states[1]["current_plan"] is None and service.states[1]["observation"] is None
    assert service.states[1]["remaining_rounds"] == 1 and service.states[1]["remaining_stimulus_cycles"] == 16
    assert service.states[1]["plan_error"] == {
        "code": "stimulus_budget_exceeded", "requested_stimulus_cycles": 18,
        "remaining_stimulus_cycles": 16, "requested_new_cycles": 18, "max_new_cycles": 16,
        "replay_cycles": 0, "simulation_multiplier": 1}
    assert trace["latest_plan_error"] is None and trace["plan_budget_rejections"] == 1
    failed = trace["failed_attempts"][0]
    assert failed["stage"] == "plan_budget" and failed["decision_index"] == 1
    assert failed["simulation_started"] is False and failed["stimulus_cycles_executed"] == failed["accepted_vectors_added"] == 0
    assert_archived_original(result, 0, bad)
    assert_archived_original(result, 1, good)


@pytest.mark.parametrize("feedback", [True, False])
def test_seven_executed_then_eleven_over_remaining_nine_preserves_evidence_then_five_runs(tmp_path, feedback):
    bad = proposal(11, reason="private-budget-rejection-marker")
    service, stub = Scripted(proposal(7), bad, proposal(5)), CheckedStub()
    result = run(tmp_path, service, stub, include_feedback=feedback,
        limits=AgentLimits(max_rounds=2, max_requests=3, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["requests_attempted"] == 3
    assert len(stub.plans) == len(trace["rounds"]) == 2
    assert trace["stimulus_cycles_executed"] == 12 and trace["accepted_vectors"] == 2
    assert trace["automatic_reset_cycles_executed"] == 4 and trace["plan_budget_rejections"] == 1
    rejected = trace["decisions"][1]
    assert_budget_rejection(rejected, code="stimulus_budget_exceeded")
    assert rejected["plan_error"]["requested_stimulus_cycles"] == 11
    assert rejected["plan_error"]["remaining_stimulus_cycles"] == rejected["plan_error"]["max_new_cycles"] == 9
    before, after = service.states[1:]
    assert after["current_plan"] == before["current_plan"] == stub.plans[0]
    assert after["remaining_stimulus_cycles"] == before["remaining_stimulus_cycles"] == 9
    assert after["max_new_vectors"] == before["max_new_vectors"] == 12
    assert after["remaining_rounds"] == before["remaining_rounds"] == 1
    assert after["observation"] == before["observation"]
    assert after["plan_error"] == (rejected["plan_error"] if feedback else None)
    assert after["latest_decision_error"] is None
    if not feedback:
        assert after["observation"] is None and before == after
        assert "stimulus_budget_exceeded" not in json.dumps(after)
    assert "private-budget-rejection-marker" not in json.dumps(after)
    assert_archived_original(result, 1, bad)


@pytest.mark.parametrize("requests", [1, 2, 3])
def test_identical_never_accepted_over_budget_proposals_use_only_original_request_cap(tmp_path, requests):
    bad = proposal(18)
    service, stub = Scripted(*([bad] * requests), proposal()), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=3, max_requests=requests, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "request_budget" and trace["requests_attempted"] == len(service.states) == requests
    assert trace["plan_budget_rejections"] == requests and len(service.responses) == 1
    assert not stub.plans and trace["rounds"] == [] and result.last_result is None
    assert trace["accepted_vectors"] == trace["stimulus_cycles_executed"] == trace["automatic_reset_cycles_executed"] == 0
    assert all(state["current_plan"] is None and state["remaining_stimulus_cycles"] == 16 for state in service.states)
    for index, row in enumerate(trace["decisions"]):
        assert_budget_rejection(row, code="stimulus_budget_exceeded")
        assert_archived_original(result, index, bad)


@pytest.mark.parametrize("cycles", [5, 11])
def test_already_accepted_proposal_repetition_remains_fatal_before_any_budget_retry(tmp_path, cycles):
    repeated = proposal(cycles)
    service, stub = Scripted(repeated, repeated, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert result.stop_reason == "repeated_action" and result.trajectory["requests_attempted"] == 2
    assert result.trajectory["plan_budget_rejections"] == 0 and len(service.responses) == 1
    assert len(stub.plans) == 1 and result.trajectory["stimulus_cycles_executed"] == cycles
    assert result.trajectory["decisions"][1]["status"] == "rejected_repetition"


@pytest.mark.parametrize("format_first", [True, False])
@pytest.mark.parametrize("requests", [2, 3])
def test_format_and_budget_rejections_share_one_request_limit(tmp_path, format_first, requests):
    first_two = ['{"action":', proposal(18)]
    if not format_first:
        first_two.reverse()
    service, stub = Scripted(*first_two, proposal(4)), CheckedStub()
    result = run(tmp_path, service, stub,
        limits=AgentLimits(max_rounds=1, max_requests=requests, max_total_cycles=16))
    trace = result.trajectory
    assert trace["requests_attempted"] == len(service.states) == requests
    assert trace["decision_format_rejections"] == trace["plan_budget_rejections"] == 1
    assert all(row["usage"] == USAGE for row in trace["decisions"])
    assert all(item["simulation_started"] is False and item["stimulus_cycles_executed"] == 0
               for item in trace["failed_attempts"])
    assert trace["stimulus_cycles_executed"] == (4 if requests == 3 else 0)
    assert trace["accepted_vectors"] == len(stub.plans) == (1 if requests == 3 else 0)
    if requests == 3:
        assert result.stop_reason == "round_budget" and service.responses == []
        assert trace["latest_plan_error"] is None and trace["latest_decision_error"] is None
    else:
        assert result.stop_reason == ("request_budget" if format_first else "decision_format_error")
        assert len(service.responses) == 1


@pytest.mark.parametrize("first_vectors,max_vectors", [(0, 1), (2, 3)])
def test_cumulative_accepted_vector_limit_rejects_excess_without_counting_or_clipping_it(tmp_path, first_vectors, max_vectors):
    bad, good = proposal(3, vectors=2), proposal(2)
    prefix = [proposal(1, vectors=first_vectors)] if first_vectors else []
    service, stub = Scripted(*prefix, bad, good), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=len(prefix)+1,
        max_requests=len(prefix)+2, max_vectors=max_vectors, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["accepted_vectors"] == max_vectors
    assert trace["requests_attempted"] == len(prefix)+2 and trace["stimulus_cycles_executed"] == first_vectors + 2
    row = trace["decisions"][len(prefix)]
    assert_budget_rejection(row, code="accepted_vector_budget_exceeded")
    assert row["plan_error"] == {"code": "accepted_vector_budget_exceeded",
        "requested_new_vectors": 2, "remaining_accepted_vectors": 1}
    assert len(row["action"]["vectors"]) == 2 and len(stub.plans[-1]["vectors"]) == 1
    assert trace["failed_attempts"][0]["accepted_vectors_added"] == 0
    assert_archived_original(result, len(prefix), bad)


def test_append_at_two_hundred_vector_ceiling_rejects_before_plan_assembly_then_accepts_remaining_two(tmp_path):
    initial = Plan.model_validate({"design": "mod10_counter", "objective": "existing caller plan", "vectors": [
        {"name": f"initial_{index:03d}", "inputs": {"enable": 1}, "cycles": 1} for index in range(198)]})
    original = initial.model_dump(mode="json")
    bad, good = proposal(vectors=3), proposal(vectors=2)
    service, stub = Scripted(bad, good), CheckedStub()
    result = run(tmp_path, service, stub, initial_plan=initial, agent_plan_mode="append",
        limits=AgentLimits(max_rounds=2, max_requests=2, max_vectors=200, max_total_cycles=500))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["requests_attempted"] == 2
    assert [len(item["vectors"]) for item in stub.plans] == [198, 200]
    assert trace["accepted_vectors"] == 200 and trace["stimulus_cycles_executed"] == 398
    assert_budget_rejection(trace["decisions"][0], code="accepted_vector_budget_exceeded")
    assert trace["decisions"][0]["plan_error"]["requested_new_vectors"] == 3
    assert service.states[1]["max_new_vectors"] == 2 and service.states[1]["current_plan"] == stub.plans[0]
    assert initial.model_dump(mode="json") == original
    assert_archived_original(result, 0, bad)


def test_append_budget_diagnostic_pays_for_replay_and_accepted_plan_reaches_exact_total(tmp_path):
    service, stub = Scripted(proposal(7), proposal(11), proposal(2)), CheckedStub()
    result = run(tmp_path, service, stub, agent_plan_mode="append",
        limits=AgentLimits(max_rounds=2, max_requests=3, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["stimulus_cycles_executed"] == 16
    assert [sum(vector["cycles"] for vector in item["vectors"]) for item in stub.plans] == [7, 9]
    error = trace["decisions"][1]["plan_error"]
    assert error["requested_new_cycles"] == 11 and error["requested_stimulus_cycles"] == 18
    assert error["remaining_stimulus_cycles"] == 9 and error["replay_cycles"] == 7 and error["max_new_cycles"] == 2
    assert trace["accepted_vectors"] == 2 and len(trace["rounds"]) == 2


def test_paired_budget_recovery_counts_both_runs_and_keeps_reset_separate(tmp_path):
    candidate_sha = hashlib.sha256((ROOT / "rtl/mod10_counter.v").read_bytes()).hexdigest()
    def observer(actual):
        return AgentObservation(status="passed", verdict="qualified-observer-stub",
            expectation_source="qualified_baseline_differential", verification_status="qualified_baseline_differential",
            compared_samples=8, qualified_outputs=["count"], qualification_sha256="a"*64,
            baseline_sha256="b"*64, candidate_sha256=candidate_sha)
    service, stub = Scripted(proposal(9), proposal(8)), CheckedStub()
    result = run(tmp_path, service, stub, round_observer=observer, simulation_multiplier=2,
        limits=AgentLimits(max_rounds=1, max_requests=2, max_total_cycles=16))
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["stimulus_cycles_executed"] == 16
    assert trace["candidate_stimulus_cycles_executed"] == trace["baseline_stimulus_cycles_executed"] == 8
    assert trace["automatic_reset_cycles_executed"] == 4 and len(stub.plans) == 1
    error = trace["decisions"][0]["plan_error"]
    assert error["requested_stimulus_cycles"] == 18 and error["simulation_multiplier"] == 2 and error["max_new_cycles"] == 8


@pytest.mark.parametrize("budget,expected", [("cycles", "cycle_budget"), ("vectors", "vector_budget")])
def test_actually_exhausted_stimulus_or_vector_budget_never_requests_a_correction(tmp_path, budget, expected):
    limits = AgentLimits(max_total_cycles=16, max_vectors=1 if budget == "vectors" else 64)
    cycles = 16 if budget == "cycles" else 1
    service, stub = Scripted(proposal(cycles), proposal()), CheckedStub()
    result = run(tmp_path, service, stub, limits=limits)
    assert result.stop_reason == expected and result.trajectory["requests_attempted"] == 1
    assert result.trajectory["plan_budget_rejections"] == 0 and len(service.responses) == len(stub.plans) == 1


@pytest.mark.parametrize("bad", [
    '{"action":"stop","reason":"first","reason":"second","vectors":[]}',
    '{"action":"stop","reason":"\\u0075nit-budget-recovery-key-only","vectors":[]}',
    '{"reason":"uncertain \\u',
    RuntimeError("private-budget-transport-detail"),
])
def test_budget_retry_does_not_retry_malicious_or_transport_failures(tmp_path, bad):
    service, stub = Scripted(proposal(18), bad, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    trace = result.trajectory
    assert result.stop_reason == "policy_error" and trace["requests_attempted"] == 2
    assert trace["plan_budget_rejections"] == 1 and len(service.responses) == 1
    assert not stub.plans and trace["stimulus_cycles_executed"] == trace["accepted_vectors"] == 0
    last = trace["decisions"][-1]
    assert last["retry_eligible"] is False and "untrusted_response" not in last
    text = result.trajectory_path.read_text(encoding="utf-8")
    assert FAKE_KEY not in text and "private-budget-transport-detail" not in text


def test_wall_time_is_rechecked_before_budget_correction_request(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("iverilog_ai.ai.agent.time.monotonic", lambda: clock[0])
    class SlowBudgetResponse(Scripted):
        def generate(self, prompt):
            raw = super().generate(prompt)
            clock[0] = 1.1
            return raw
    service, stub = SlowBudgetResponse(proposal(18), proposal()), CheckedStub()
    result = run(tmp_path, service, stub,
        limits=AgentLimits(max_requests=3, max_total_cycles=16, wall_time_seconds=1))
    assert result.stop_reason == "wall_time_budget" and result.trajectory["requests_attempted"] == 1
    assert result.trajectory["plan_budget_rejections"] == 1 and not stub.plans and len(service.responses) == 1


def test_caller_initial_plan_over_budget_is_preserved_and_not_replaced_by_api(tmp_path):
    initial = Plan.model_validate({"design": "mod10_counter", "objective": "caller plan", "vectors": [
        {"name": "caller", "inputs": {"enable": 1}, "cycles": 18}]})
    original = initial.model_dump(mode="json")
    service, stub = Scripted(proposal()), CheckedStub()
    result = run(tmp_path, service, stub, initial_plan=initial)
    assert result.stop_reason == "cycle_budget" and result.trajectory["requests_attempted"] == 0
    assert not service.states and not stub.plans and initial.model_dump(mode="json") == original


@pytest.mark.parametrize("provider_limit,agent_limit,expected_requests,executed", [(2, 2, 2, True), (1, 3, 1, False)])
def test_actual_wire_budget_recovery_respects_native_request_cap_and_preserves_usage(
        tmp_path, monkeypatch, provider_limit, agent_limit, expected_requests, executed):
    replies, bodies = [proposal(18), proposal(4)], []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps({"choices": [{"message": {"content": replies[len(bodies)-1]}, "finish_reason": "stop"}],
                "usage": USAGE}).encode()
    def transport(request, timeout):
        bodies.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    service = OpenAICompatibleProvider(endpoint="https://fixture.invalid", model="unit-budget-fixture", api_key=FAKE_KEY,
        allow_network=True, stream=False, wire_api="chat_completions", request_limit=provider_limit)
    stub = CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=agent_limit, max_total_cycles=16))
    trace = result.trajectory
    assert service.request_limit == provider_limit
    assert service.request_count == trace["requests_attempted"] == len(bodies) == expected_requests
    assert result.stop_reason == ("round_budget" if executed else "request_budget")
    assert len(stub.plans) == trace["accepted_vectors"] == int(executed)
    assert trace["stimulus_cycles_executed"] == (4 if executed else 0)
    assert trace["plan_budget_rejections"] == 1
    if executed:
        assert json.loads(bodies[1]["messages"][1]["content"])["plan_error"]["max_new_cycles"] == 16
    for index in range(expected_requests):
        assert_archived_original(result, index, replies[index])
    assert all(row["usage"] == USAGE for row in result.trajectory["decisions"])
    assert FAKE_KEY not in json.dumps(bodies) and FAKE_KEY not in result.trajectory_path.read_text()


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("sequence,rounds,checks,expected_final", [([18, 16], 1, 16, 6), ([7, 11, 5], 2, 12, 5)])
def test_real_icarus_only_accepted_episodes_run_and_have_fresh_reset(tmp_path, sequence, rounds, checks, expected_final):
    service = Scripted(*(proposal(cycles) for cycles in sequence))
    result = run(tmp_path, service, VerificationPipeline(),
        limits=AgentLimits(max_rounds=rounds, max_requests=len(sequence), max_total_cycles=16),
        execution_options={"reference_sampling": "per_cycle", "iverilog_path": TOOLS.iverilog,
            "vvp_path": TOOLS.vvp, "max_output_chars": 2_000_000})
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["requests_attempted"] == len(sequence)
    assert trace["stimulus_cycles_executed"] == checks and trace["accepted_vectors"] == rounds
    assert sum(row["observation"]["checks"] for row in trace["rounds"]) == checks
    assert trace["automatic_reset_cycles_executed"] == 2*rounds and trace["plan_budget_rejections"] == 1
    assert len(list(result.trajectory_path.parent.glob("round-*"))) == rounds
    assert result.last_result.simulation.verdict == "passed" and not result.last_result.simulation.failures
    assert int(result.last_result.simulation.records[-1].actual, 2) == expected_final
    for decision in trace["decisions"]:
        if decision.get("plan_validation_status") == "rejected":
            assert "executed_round" not in decision
    assert PROMPT_VERSION == trace["prompt_version"] == "verification-agent-v7-bounded-budget-recovery"
