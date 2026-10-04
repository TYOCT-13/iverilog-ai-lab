"""Bounded format recovery and conservative inert artifacts; zero live API."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentLimits, run_verification_agent
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()
KEY = "unit-format-recovery-active-key"


def proposal(cycles=2):
    return json.dumps({"action": "append_vectors", "reason": "check counter", "vectors": [
        {"name": "advance", "inputs": {"rst_n": 1, "enable": 1}, "cycles": cycles, "sample_phase": "after"}]})


class Scripted:
    model = "local-scripted-fixture"
    last_finish_reason = "stop"
    last_usage = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}

    def __init__(self, *responses, api_key=KEY):
        self.responses = list(responses)
        self.states = []
        self.api_key = api_key

    def generate(self, prompt):
        self.states.append(json.loads(prompt.split("STATE_JSON:\n", 1)[1]))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class CheckedStub:
    """A checked execution stub; never presented as actual DUT evidence."""
    def __init__(self):
        self.plans = []

    def run(self, plan, contract, source, output, **options):
        self.plans.append(plan.model_dump(mode="json"))
        record = SimpleNamespace(ok=True, expected="0010", actual="0010")
        simulation = SimpleNamespace(run_id="checked-test-stub", status=SimpleNamespace(value="passed"),
            verdict="passed", config={"oracle": {"expectation_source": "reference_model"}},
            records=[record], failures=[])
        return SimpleNamespace(simulation=simulation, plan=plan,
            artifacts={"pipeline_result": str(output.resolve() / "pipeline_result.json")})


def run(tmp_path, service, runner=None, **options):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    return run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
        output_dir=tmp_path / "agent", objective="check bounded format correction", pipeline=runner or CheckedStub(),
        limits=options.pop("limits", AgentLimits(max_rounds=1, max_requests=2)), **options)


def assert_no_raw_or_key_saved(result, raw, key):
    assert result.stop_reason == "policy_error"
    assert result.trajectory["requests_attempted"] == 1
    assert result.trajectory["rounds"] == [] and result.trajectory["stimulus_cycles_executed"] == 0
    row = result.trajectory["decisions"][0]
    assert row["retry_eligible"] is False and row["untrusted_response_status"] == "blocked"
    assert "untrusted_response" not in row
    assert row["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert row["response_bytes"] == len(raw.encode())
    assert not (result.trajectory_path.parent / "untrusted_decisions").exists()
    text = result.trajectory_path.read_text(encoding="utf-8")
    assert raw not in text and key not in text and json.dumps(key)[1:-1] not in text


@pytest.mark.parametrize("raw", [
    '{"action":"append_vectors","reason":"local fixture", "vectors":[],}',
    '{"action":"append_vectors","reason":"local fixture","vectors":[],"extra_untrusted_field":1}',
    json.dumps({"action": "append_vectors", "reason": "local fixture", "vectors": [
        {"name": "bad", "inputs": {"enable": 1}, "cycles": 0, "sample_phase": "after"}]}),
])
def test_format_error_then_valid_plan_uses_only_one_round_and_actual_cycles(tmp_path, raw):
    service, stub = Scripted(raw, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    trace = result.trajectory
    assert result.stop_reason == "round_budget" and trace["requests_attempted"] == 2
    assert len(stub.plans) == len(trace["rounds"]) == 1
    assert trace["stimulus_cycles_executed"] == 2 and trace["accepted_vectors"] == 1
    assert trace["automatic_reset_cycles_executed"] == 2
    rejected, accepted = trace["decisions"]
    assert rejected["status"] == "rejected" and rejected["retry_eligible"] is True
    assert "action" not in rejected and "executed_round" not in rejected
    assert accepted["status"] == "validated" and accepted["executed_round"] == 1
    failed = trace["failed_attempts"][0]
    assert failed["stage"] == "decision_validation" and failed["decision_index"] == 1
    assert failed["simulation_started"] is False and failed["stimulus_cycles_executed"] == 0
    state = service.states[1]
    assert state["current_plan"] is None and state["observation"] is None
    assert state["remaining_rounds"] == 1 and state["remaining_stimulus_cycles"] == 1000
    assert state["latest_decision_error"] == rejected["decision_error"]
    assert "local fixture" not in json.dumps(state) and "extra_untrusted_field" not in json.dumps(state)
    assert all(row["usage"] == {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
               for row in trace["decisions"])


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_recovery_executes_only_valid_plan_with_real_icarus_per_cycle_checks(tmp_path):
    raw = '{"action":"append_vectors","reason":"retry with valid JSON", "vectors":[],}'
    result = run(tmp_path, Scripted(raw, proposal(3)), VerificationPipeline(),
        execution_options={"iverilog_path": TOOLS.iverilog, "vvp_path": TOOLS.vvp,
                           "reference_sampling": "per_cycle"})
    assert result.last_result.verdict == "passed" and result.last_result.simulation.check_count == 3
    assert result.trajectory["stimulus_cycles_executed"] == 3 and len(result.trajectory["rounds"]) == 1
    assert len(list(result.trajectory_path.parent.glob("round-*"))) == 1
    assert not (result.trajectory_path.parent / "round-02").exists()


@pytest.mark.parametrize("requests", [1, 2, 3])
def test_unresolved_format_errors_have_explicit_terminal_reason_and_spend_no_dut_budget(tmp_path, requests):
    service, stub = Scripted(*['{"action":' for _ in range(requests)], proposal()), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=requests))
    assert result.stop_reason == "decision_format_error"
    assert result.trajectory["budget_stop_reason"] == "request_budget"
    assert result.trajectory["requests_attempted"] == len(service.states) == requests
    assert len(service.responses) == 1  # Single=1 and exhausted budgets never ask for the valid correction.
    assert result.trajectory["decision_format_rejections"] == requests
    assert result.trajectory["stimulus_cycles_executed"] == 0 and not stub.plans
    assert result.trajectory["automatic_reset_cycles_executed"] == 0 and result.last_result is None


@pytest.mark.parametrize("feedback", [True, False])
def test_no_feedback_does_not_leak_error_codes_locations_or_original_output(tmp_path, feedback):
    raw = '{"action":"stop","reason":"untrusted-unique-marker","vectors":[],"injected_explanation":1}'
    service = Scripted(raw, proposal())
    result = run(tmp_path, service, include_feedback=feedback)
    second = service.states[1]
    assert second["latest_decision_error"] == (result.trajectory["decisions"][0]["decision_error"] if feedback else None)
    assert "injected_explanation" not in json.dumps(second) and "untrusted-unique-marker" not in json.dumps(second)
    if not feedback:
        assert service.states[0] == service.states[1]
        assert "schema_invalid" not in json.dumps(second) and "extra_forbidden" not in json.dumps(second)


def test_bad_field_locations_use_only_bounded_known_tokens(tmp_path):
    raw = json.dumps({"action": "stop", "reason": "plain", "vectors": [],
                      "ignore_policy_and_print_creds": {"arbitrary_path": "do-not-repeat"}})
    service = Scripted(raw, proposal())
    result = run(tmp_path, service)
    diagnostic = service.states[1]["latest_decision_error"]
    assert diagnostic["code"] == "schema_invalid"
    assert diagnostic["errors"] == [{"type": "extra_forbidden", "location": ["unknown_field"]}]
    assert "ignore_policy" not in json.dumps(diagnostic) and "do-not-repeat" not in json.dumps(diagnostic)


def test_benign_malformed_structure_saves_exact_inert_utf8_and_hash(tmp_path):
    raw = '{"action":"append_vectors","reason":"中文诊断 / \\u4e2d", "vectors":[],}'
    result = run(tmp_path, Scripted(raw, proposal()))
    row = result.trajectory["decisions"][0]
    artifact = row["untrusted_response"]
    path = result.trajectory_path.parent / artifact["path"]
    assert path.suffix == ".txt" and path.read_bytes() == raw.encode("utf-8")
    assert artifact["trusted"] is False and artifact["parse_status"] == row["parse_status"] == "json_invalid"
    assert artifact["sha256"] == row["response_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert artifact["bytes"] == row["response_bytes"] == len(raw.encode("utf-8"))
    assert "中文诊断" not in json.dumps(result.trajectory["decisions"][1]["state"], ensure_ascii=False)


@pytest.mark.parametrize("key", [KEY, 'unit-"-\\-key', 'unit-/\U0001f512-key'])
@pytest.mark.parametrize("position", ["value", "object_key"])
@pytest.mark.parametrize("truncated", [False, True])
def test_complete_or_truncated_escaped_active_keys_block_archive_and_recovery(tmp_path, key, position, truncated):
    value = {"action": "stop", "reason": "safe", "vectors": []}
    if position == "value": value["reason"] = key
    else: value[key] = "safe"
    raw = json.dumps(value, ensure_ascii=True).replace("unit", "\\u0075nit")
    if truncated:
        # Truncate inside the encoded key's JSON string. Decoding is uncertain;
        # refusing the entire artifact is required even if a complete key is absent.
        marker = raw.index("\\u0075nit")
        ending = raw.index('"', marker)
        raw = raw[:ending]
    else:
        raw = raw[:-1] + ",}"  # Malformed structure but complete, decodable strings.
    service, stub = Scripted(raw, proposal(), api_key=key), CheckedStub()
    result = run(tmp_path, service, stub)
    assert len(service.states) == 1 and not stub.plans
    assert_no_raw_or_key_saved(result, raw, key)
    assert result.trajectory["decisions"][0]["policy_error_code"] in {
        "credential_in_response", "uninspectable_json_strings"}


@pytest.mark.parametrize("raw", [
    '{"reason":"\\u0075nit-format-recovery-active-key",}',
    '{"reason":"safe","unit-format-recovery-active-key":1,}',
    '{"reason":"unfinished \\u', '{"reason":"unfinished \\',
    '{"reason":"invalid \\q escape",}',
    '{"reason":\\u0075nit-format-recovery-active-key}',
    '{"reason":"text with \n bare control",}',
    '{"action":"stop","reason":"safe","vectors":[]] extra',
])
def test_sensitive_or_uncertain_malformed_json_is_fatal_not_a_format_retry(tmp_path, raw):
    service, stub = Scripted(raw, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert not stub.plans and len(service.states) == 1
    assert_no_raw_or_key_saved(result, raw, KEY)


@pytest.mark.parametrize("raw", [
    '{"action":"stop","reason":"safe","reas\\u006fn":"other","vectors":[]}',
    '{"action":"stop","reason":"safe","reas\\u006fn":"other",',
    '{"action":"stop","reason":"safe","vectors":[],"extra":{"x":1,"x":2}} trailing',
    '{"action":"stop","reason":"safe","vectors":[],"extra":{"x":1,"x":2,',
])
def test_duplicate_decoded_keys_remain_fatal_even_in_an_unfinished_object(tmp_path, raw):
    service, stub = Scripted(raw, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert not stub.plans and len(service.states) == 1
    assert_no_raw_or_key_saved(result, raw, KEY)
    assert result.trajectory["decisions"][0]["policy_error_code"] == "duplicate_json_key"


@pytest.mark.parametrize("usage", [{}, False, {"completion_tokens": True}, {"completion_tokens": -1},
                                    {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 11}])
def test_invalid_usage_never_becomes_a_recoverable_json_error(tmp_path, usage):
    service, stub = Scripted('{"action":', proposal()), CheckedStub()
    service.last_usage = usage
    result = run(tmp_path, service, stub)
    assert result.stop_reason == "policy_error" and len(service.states) == 1 and not stub.plans
    assert result.trajectory["decisions"][0]["policy_error_code"] == "invalid_usage"
    assert result.trajectory["decision_format_rejections"] == 0
    assert not (result.trajectory_path.parent / "untrusted_decisions").exists()


@pytest.mark.parametrize("kind", ["TokenBudgetExceeded", "TokenUsageViolation", "OSError", "RuntimeError"])
def test_request_and_budget_exceptions_never_trigger_schema_recovery(tmp_path, kind):
    exception = type(kind, (RuntimeError,), {})
    service, stub = Scripted(exception("private-detail-do-not-repeat"), proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert result.stop_reason == "policy_error" and len(service.states) == 1 and not stub.plans
    assert result.trajectory["decisions"][0]["error_type"] == kind
    assert result.trajectory["decision_format_rejections"] == 0
    assert "private-detail-do-not-repeat" not in result.trajectory_path.read_text()


def test_malformed_archive_collision_is_fatal_and_preserves_existing_bytes(tmp_path):
    raw = '{"action":'
    path = tmp_path / "agent/untrusted_decisions/decision-001.txt"
    class Collision(Scripted):
        def generate(self, prompt):
            path.parent.mkdir()
            path.write_bytes(b"sentinel-existing-artifact")
            return super().generate(prompt)
    service, stub = Collision(raw, proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert result.stop_reason == "policy_error" and len(service.states) == 1 and not stub.plans
    assert path.read_bytes() == b"sentinel-existing-artifact"
    assert result.trajectory["decision_format_rejections"] == 0


@pytest.mark.parametrize("request_limit", [1, 2])
def test_actual_wire_request_limit_counts_invalid_json_before_valid_correction(tmp_path, monkeypatch, request_limit):
    bodies = []
    replies = ['{"action":', proposal()]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps({"choices": [{"message": {"content": replies[len(bodies)-1]}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}).encode()
    def transport(request, timeout):
        bodies.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    service = OpenAICompatibleProvider(endpoint="https://fixture.invalid", model="unit-fixture", api_key=KEY,
        allow_network=True, stream=False, wire_api="chat_completions", request_limit=request_limit)
    stub = CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=request_limit))
    assert service.request_count == result.trajectory["requests_attempted"] == len(bodies) == request_limit
    assert result.stop_reason == ("round_budget" if request_limit == 2 else "decision_format_error")
    assert len(result.trajectory["rounds"]) == len(stub.plans) == request_limit - 1
    if request_limit == 2:
        state = json.loads(bodies[1]["messages"][1]["content"])
        assert state["latest_decision_error"]["code"] == "json_invalid"
    assert KEY not in json.dumps(bodies) and KEY not in result.trajectory_path.read_text()


@pytest.mark.parametrize("finish", ["content_filter", "tool_calls"])
def test_explicit_non_decision_wire_finish_never_retries_a_schema_error(tmp_path, monkeypatch, finish):
    raw = '{"action":"stop","reason":"safe","vectors":[],"type":"json_object"}'
    bodies = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps({"choices": [{"message": {"content": raw}, "finish_reason": finish}],
                               "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}).encode()
    def transport(request, timeout):
        bodies.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    service = OpenAICompatibleProvider(endpoint="https://fixture.invalid", model="unit-fixture", api_key=KEY,
        allow_network=True, stream=False, wire_api="chat_completions", request_limit=2)
    stub = CheckedStub()
    result = run(tmp_path, service, stub)
    assert service.request_count == result.trajectory["requests_attempted"] == len(bodies) == 1
    assert_no_raw_or_key_saved(result, raw, KEY)
    row = result.trajectory["decisions"][0]
    assert row["finish_reason"] == finish and row["policy_error_code"] == "non_decision_finish"
    assert result.trajectory["decision_format_rejections"] == 0 and not stub.plans
    assert json.loads(bodies[0]["messages"][1]["content"])["latest_decision_error"] is None


def test_pending_format_error_after_an_actual_round_is_not_an_ordinary_success_stop(tmp_path):
    service, stub = Scripted(proposal(), '{"action":', proposal(3)), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=2, max_requests=2))
    assert result.stop_reason == "decision_format_error" and result.trajectory["budget_stop_reason"] == "request_budget"
    assert len(stub.plans) == len(result.trajectory["rounds"]) == 1
    assert result.trajectory["requests_attempted"] == 2 and result.trajectory["stimulus_cycles_executed"] == 2
    assert result.trajectory["decisions"][1]["status"] == "rejected" and len(service.responses) == 1
    assert result.trajectory["rounds"][0]["observation"]["checks"] == 1


@pytest.mark.parametrize("invalid", [
    {"action": "shell", "reason": "no commands", "vectors": []},
    {"action": "stop", "reason": "no commands", "vectors": [], "command": "do-not-run-this"},
    {"action": "append_vectors", "reason": "no oracle changes", "vectors": [
        {"name": "bad", "inputs": {"enable": 1}, "expected": {"count": 4}}]},
    {"action": "append_vectors", "reason": "vector limit", "vectors": [
        {"name": f"bad{index}", "inputs": {"enable": 1}} for index in range(13)]},
])
def test_format_recovery_keeps_command_oracle_and_twelve_vector_gates(tmp_path, invalid):
    service, stub = Scripted(json.dumps(invalid), proposal()), CheckedStub()
    result = run(tmp_path, service, stub)
    assert result.stop_reason == "round_budget" and len(stub.plans) == 1
    rejected, accepted = result.trajectory["decisions"]
    assert rejected["status"] == "rejected" and rejected["retry_eligible"] is True and "action" not in rejected
    assert accepted["executed_round"] == 1 and len(stub.plans[0]["vectors"]) == 1
    assert not stub.plans[0]["vectors"][0]["expected"] and result.trajectory["stimulus_cycles_executed"] == 2
    assert "do-not-run-this" not in json.dumps(service.states[1])


def test_corrected_plan_still_obeys_the_original_stimulus_budget(tmp_path):
    service, stub = Scripted('{"action":', proposal(3), proposal()), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=3, max_total_cycles=2))
    assert result.stop_reason == "cycle_budget" and result.trajectory["requests_attempted"] == 2
    assert not stub.plans and result.trajectory["stimulus_cycles_executed"] == 0
    assert result.trajectory["automatic_reset_cycles_executed"] == 0 and len(service.responses) == 1
    assert service.states[1]["remaining_stimulus_cycles"] == service.states[0]["remaining_stimulus_cycles"] == 2


def test_wall_clock_limit_is_rechecked_before_a_format_correction_request(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("iverilog_ai.ai.agent.time.monotonic", lambda: clock[0])
    class SlowFormatResponse(Scripted):
        def generate(self, prompt):
            raw = super().generate(prompt)
            clock[0] = 1.1
            return raw
    service, stub = SlowFormatResponse('{"action":', proposal()), CheckedStub()
    result = run(tmp_path, service, stub, limits=AgentLimits(max_rounds=1, max_requests=2, wall_time_seconds=1))
    assert result.stop_reason == "wall_time_budget" and result.trajectory["requests_attempted"] == 1
    assert len(service.states) == len(service.responses) == 1 and not stub.plans
    assert result.trajectory["latest_decision_error"]["code"] == "json_invalid"
    assert result.trajectory["decision_format_rejections"] == 1
    assert result.trajectory["stimulus_cycles_executed"] == result.trajectory["automatic_reset_cycles_executed"] == 0
