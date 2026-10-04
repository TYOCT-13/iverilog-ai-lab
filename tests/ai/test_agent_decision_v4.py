"""Typed wire messages and inert diagnostic artifacts; no real API requests."""
import hashlib
from http.client import RemoteDisconnected
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentDecision, AgentLimits, AgentObservation, SYSTEM_PROMPT, run_verification_agent
from iverilog_ai.ai.provider import OpenAICompatibleProvider, ProviderMessage
from iverilog_ai.core.contracts import DutContract

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "pyproject.toml").is_file())


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def provider(**options):
    return OpenAICompatibleProvider(endpoint="https://api.deepseek.com", model="deepseek-flash",
        api_key="synthetic-v4-test-key-only", allow_network=True, reasoning_effort=None,
        wire_api=options.pop("wire_api", "chat_completions"), request_limit=options.pop("request_limit", 3),
        **options)


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()


def install(monkeypatch, answer, *, finish="stop", wire_api="chat_completions", on_request=None):
    bodies = []
    def transport(request, timeout):
        body = json.loads(request.data)
        bodies.append(body)
        if on_request:
            on_request(len(bodies), body)
        text = answer[len(bodies) - 1] if isinstance(answer, list) else answer
        if wire_api == "responses":
            return Response({"status": "completed", "output_text": text})
        return Response({"choices": [{"message": {"content": text}, "finish_reason": finish}],
                         "usage": {"prompt_tokens": 7, "completion_tokens": 11}})
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    return bodies


class Pipeline:
    def __init__(self):
        self.plans = []
    def run(self, plan, contract, source, output, **options):
        self.plans.append(plan)
        simulation = SimpleNamespace(run_id="stub", status=SimpleNamespace(value="passed"), verdict="passed",
            config={"oracle": {"expectation_source": "reference_model"}}, records=[1], failures=[])
        return SimpleNamespace(simulation=simulation, plan=plan,
            artifacts={"pipeline_result": str(output.resolve() / "pipeline_result.json")})


def run(tmp_path, service, pipeline=None, **options):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    return run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
        output_dir=tmp_path / "agent", objective="Find missing scenarios", pipeline=pipeline or Pipeline(), **options)


def stop(**extra):
    return json.dumps({"action": "stop", "reason": "No further proposal", "vectors": [], **extra})


@pytest.mark.parametrize("wire_api", ["chat_completions", "responses"])
def test_typed_system_user_go_to_actual_wire_and_are_fingerprinted(monkeypatch, wire_api):
    bodies = install(monkeypatch, "{}", wire_api=wire_api)
    service = provider(wire_api=wire_api)
    messages = [ProviderMessage("system", "Return JSON only"), ProviderMessage("user", '{"data":"你好"}')]
    assert service.generate_messages(messages) == "{}"
    key = "messages" if wire_api == "chat_completions" else "input"
    assert bodies[0][key] == [{"role": "system", "content": "Return JSON only"},
                             {"role": "user", "content": '{"data":"你好"}'}]
    assert service.last_messages_sha256 == sha(bodies[0][key])
    assert service.request_count == 1
    assert "synthetic-v4-test-key-only" not in json.dumps(bodies)


@pytest.mark.parametrize("wire_api", ["chat_completions", "responses"])
def test_legacy_generate_preserves_single_prompt_shape(monkeypatch, wire_api):
    bodies = install(monkeypatch, "{}", wire_api=wire_api)
    service = provider(wire_api=wire_api)
    assert service.generate("legacy prompt") == "{}"
    if wire_api == "chat_completions":
        assert bodies[0]["messages"] == [{"role": "user", "content": "legacy prompt"}]
    else:
        assert bodies[0]["input"] == "legacy prompt"
        assert service.last_messages_sha256 is None


@pytest.mark.parametrize("role", ["assistant", "tool", "developer", {}, None])
def test_only_explicit_system_user_roles_are_allowed(role):
    with pytest.raises(ValueError, match="role must be system or user"):
        ProviderMessage(role, "text")


@pytest.mark.parametrize("content", ["", "  ", None, {}])
def test_message_content_must_be_text(content):
    with pytest.raises(ValueError, match="nonempty text"):
        ProviderMessage("user", content)


@pytest.mark.parametrize("messages", [[], [{"role": "system", "content": "text"}], "text"])
def test_untyped_or_empty_messages_fail_before_transport(monkeypatch, messages):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid messages must not use transport")
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", forbidden)
    service = provider()
    with pytest.raises(ValueError, match="typed ProviderMessage"):
        service.generate_messages(messages)
    assert service.request_count == 0


def test_typed_messages_survive_auto_fallback_with_original_request_budget(monkeypatch):
    bodies = []
    def transport(request, timeout):
        body = json.loads(request.data)
        bodies.append(body)
        if len(bodies) == 1:
            raise RemoteDisconnected("closed")
        return Response(b'data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n')
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    service = provider(stream="auto", request_limit=2, thinking_mode="disabled")
    assert service.generate_messages([ProviderMessage("system", "JSON"), ProviderMessage("user", "state")]) == "{}"
    assert len(bodies) == service.request_count == 2
    assert bodies[0]["stream"] is False and bodies[1]["stream"] is True
    assert bodies[0]["messages"] == bodies[1]["messages"]
    assert all(body["thinking"] == {"type": "disabled"} for body in bodies)


def test_system_prompt_literal_examples_pass_the_real_decision_schema():
    for marker in ("Valid append example", "Valid stop example"):
        fragment = SYSTEM_PROMPT.split(marker, 1)[1]
        encoded = fragment[fragment.index("{"):]
        value, _ = json.JSONDecoder().raw_decode(encoded)
        assert set(value) == {"action", "reason", "vectors"}
        assert AgentDecision.model_validate(value)
    assert "never copy type" in SYSTEM_PROMPT


@pytest.mark.parametrize("wire_api", ["chat_completions", "responses"])
def test_agent_uses_real_roles_records_actual_fingerprint_and_saves_inert_bytes(tmp_path, monkeypatch, wire_api):
    raw = stop()
    bodies = install(monkeypatch, raw, wire_api=wire_api)
    result = run(tmp_path, provider(wire_api=wire_api))
    row = result.trajectory["decisions"][0]
    key = "messages" if wire_api == "chat_completions" else "input"
    assert row["message_format"] == "typed_system_user"
    assert row["messages_sha256"] == sha(bodies[0][key])
    assert bodies[0][key][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert json.loads(bodies[0][key][1]["content"]) == row["state"]
    artifact = row["untrusted_response"]
    assert artifact["record_kind"] == "untrusted_model_decision" and artifact["trusted"] is False
    path = result.trajectory_path.parent / artifact["path"]
    assert path.read_bytes() == raw.encode()
    assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert artifact["bytes"] == len(raw.encode())


def test_illegal_type_is_archived_but_still_rejected_without_execution(tmp_path, monkeypatch):
    raw = stop(type="json_object")
    install(monkeypatch, raw)
    pipeline = Pipeline()
    result = run(tmp_path, provider(), pipeline)
    row = result.trajectory["decisions"][0]
    assert result.stop_reason == "policy_error" and not pipeline.plans
    assert row["status"] == "rejected" and "extra_forbidden" in row["validation_error_types"]
    assert row["usage"] == {"prompt_tokens": 7, "completion_tokens": 11}
    assert (result.trajectory_path.parent / row["untrusted_response"]["path"]).read_text() == raw
    assert "action" not in row


@pytest.mark.parametrize("encoded", [False, True])
def test_raw_and_unicode_escaped_active_keys_are_not_archived_or_executed(tmp_path, monkeypatch, encoded):
    service = provider()
    raw = json.dumps({"action": "stop", "reason": service.api_key, "vectors": []})
    if encoded:
        raw = raw.replace("synthetic", "\\u0073ynthetic")
    install(monkeypatch, raw)
    result = run(tmp_path, service)
    assert result.stop_reason == "policy_error"
    assert result.trajectory["decisions"][0]["policy_error_code"] == "credential_in_response"
    assert not (tmp_path / "agent/untrusted_decisions").exists()
    assert service.api_key not in result.trajectory_path.read_text()
    assert "\\u0073ynthetic" not in result.trajectory_path.read_text()


@pytest.mark.parametrize("raw", [
    '{"action":"stop","reason":"\\u0073ynthetic-v4-test-key-only","reason":"safe","vectors":[]}',
    '{"action":"append_vectors","action":"stop","reason":"safe","vectors":[]}',
    '{"action":"stop","reason":"first","reason":"second","vectors":[]}',
    '{"action":"stop","reason":"first","reas\\u006fn":"second","vectors":[]}',
    '{"action":"stop","reason":"safe","vectors":[],"extra":'
    '{"reason":"\\u0073ynthetic-v4-test-key-only","reason":"safe"}}',
    '{"action":"append_vectors","reason":"safe","vectors":[{"name":"attempt","inputs":'
    '{"enable":"\\u0073ynthetic-v4-test-key-only","enable":1},"cycles":1,"sample_phase":"after"}]}',
], ids=["hidden_key", "duplicate_action", "duplicate_reason", "equivalent_decoded_key",
        "nested_hidden_key", "nested_input_duplicate"])
def test_duplicate_decoded_keys_never_archive_or_execute(tmp_path, monkeypatch, raw):
    service = provider()
    install(monkeypatch, raw)
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline)
    row = result.trajectory["decisions"][0]
    assert result.stop_reason == "policy_error" and not pipeline.plans
    assert row["status"] == "rejected" and row["policy_error_code"] == "duplicate_json_key"
    assert row["usage"] == {"prompt_tokens": 7, "completion_tokens": 11}
    assert "action" not in row and "untrusted_response" not in row
    assert not (tmp_path / "agent/untrusted_decisions").exists()
    assert service.api_key not in result.trajectory_path.read_text()
    assert "\\u0073ynthetic" not in result.trajectory_path.read_text()


@pytest.mark.parametrize("secret,location", [
    ('synthetic-"-credential', "reason"),
    ('synthetic-\\-credential', "reason"),
    ('synthetic-"-\\-credential', "nested_value"),
    ('synthetic-"-\\-credential', "object_key"),
], ids=["quote", "backslash", "nested_value", "decoded_key"])
def test_escaped_punctuation_in_active_key_is_checked_as_decoded_text(tmp_path, monkeypatch, secret, location):
    service = provider()
    service.api_key = secret
    response = {"action": "stop", "reason": "safe", "vectors": []}
    if location == "reason":
        response["reason"] = secret
    elif location == "nested_value":
        response["extra"] = {"items": [0, {"nested": secret}]}
    else:
        response[secret] = "safe"
    raw = json.dumps(response)
    assert secret not in raw
    install(monkeypatch, raw)
    pipeline = Pipeline()
    result = run(tmp_path, service, pipeline)
    row = result.trajectory["decisions"][0]
    assert result.stop_reason == "policy_error" and not pipeline.plans
    assert row["policy_error_code"] == "credential_in_response"
    assert "action" not in row and "untrusted_response" not in row
    assert not (tmp_path / "agent/untrusted_decisions").exists()
    assert json.dumps(secret)[1:-1] not in result.trajectory_path.read_text()


def test_escaped_active_key_in_initial_state_is_rejected_before_any_request(tmp_path, monkeypatch):
    service = provider()
    service.api_key = 'synthetic-"-\\-credential'
    bodies = install(monkeypatch, stop())
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    with pytest.raises(ValueError, match="input contains a credential"):
        run_verification_agent(provider=service, contract=contract, rtl_path=ROOT / "rtl/mod10_counter.v",
            output_dir=tmp_path / "agent", objective=service.api_key, pipeline=Pipeline())
    assert not bodies and service.request_count == 0
    assert not (tmp_path / "agent").exists()


def test_escaped_active_key_in_typed_observation_is_never_recorded(tmp_path, monkeypatch):
    service = provider()
    service.api_key = 'synthetic-"-\\-credential'
    raw = json.dumps({"action": "append_vectors", "reason": "safe", "vectors": [
        {"name": "try", "inputs": {"enable": 1}, "cycles": 1, "sample_phase": "after"}]})
    install(monkeypatch, raw)
    def observer(actual):
        return AgentObservation(status="passed", verdict=service.api_key, expectation_source="reference_model")
    result = run(tmp_path, service, round_observer=observer, simulation_multiplier=2)
    assert result.stop_reason == "execution_error"
    assert result.trajectory["rounds"] == []
    assert json.dumps(service.api_key)[1:-1] not in result.trajectory_path.read_text()


@pytest.mark.parametrize("raw,finish", [(stop(), "length"), ("{}" * 32001, "stop"), ('{"action":', "stop"), (stop(), None)],
                         ids=["truncated", "oversized", "malformed", "completion_unknown"])
def test_truncated_oversized_unparseable_or_completion_unknown_outputs_are_not_archived(tmp_path, monkeypatch, raw, finish):
    install(monkeypatch, raw, finish=finish)
    result = run(tmp_path, provider())
    assert not (tmp_path / "agent/untrusted_decisions").exists()
    assert "untrusted_response" not in result.trajectory["decisions"][0]
    if finish == "length":
        assert result.stop_reason == "output_truncated"


def test_existing_diagnostic_file_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "agent/untrusted_decisions/decision-001.json"
    def collide(index, body):
        path.parent.mkdir()
        path.write_text("sentinel")
    install(monkeypatch, stop(), on_request=collide)
    result = run(tmp_path, provider())
    assert result.stop_reason == "policy_error"
    assert path.read_text() == "sentinel"


def test_symlinked_diagnostic_directory_cannot_write_outside_run(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    def redirect(index, body):
        try:
            (tmp_path / "agent/untrusted_decisions").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc.winerror}")
    install(monkeypatch, stop(), on_request=redirect)
    result = run(tmp_path, provider())
    assert result.stop_reason == "policy_error"
    assert not list(outside.iterdir())


def test_archived_raw_and_metadata_never_become_model_observations(tmp_path, monkeypatch):
    first = json.dumps({"action": "append_vectors", "reason": "unique raw diagnostic marker", "vectors": [
        {"name": "try", "inputs": {"enable": 1}, "cycles": 1, "sample_phase": "after"}]})
    bodies = install(monkeypatch, [first, stop()])
    result = run(tmp_path, provider(), limits=AgentLimits(max_rounds=2))
    second = bodies[1]["messages"][1]["content"]
    assert "unique raw diagnostic marker" not in second
    assert "untrusted_decisions" not in second and "untrusted_response" not in second
    assert result.trajectory["decisions"][0]["untrusted_response_status"] == "saved"


def test_v5_preflight_rejection_retains_both_typed_requests_usage_and_inert_actions(tmp_path, monkeypatch):
    invalid = json.dumps({"action": "append_vectors", "reason": "request automatic clock", "vectors": [
        {"name": "try_clock", "inputs": {"clk": 0}, "cycles": 1, "sample_phase": "after"}]})
    valid = json.dumps({"action": "append_vectors", "reason": "correct input selection", "vectors": [
        {"name": "corrected", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 1,
         "sample_phase": "after"}]})
    bodies = install(monkeypatch, [invalid, valid])
    pipeline = Pipeline()
    service = provider(request_limit=2)
    result = run(tmp_path, service, pipeline, agent_plan_mode="independent",
                 limits=AgentLimits(max_rounds=1, max_requests=2))
    assert result.stop_reason == "round_budget"
    assert service.request_count == result.trajectory["requests_attempted"] == 2
    assert len(pipeline.plans) == len(result.trajectory["rounds"]) == 1
    assert len(result.trajectory["failed_attempts"]) == 1
    rows = result.trajectory["decisions"]
    assert [row["status"] for row in rows] == ["validated", "validated"]
    assert [row["plan_validation_status"] for row in rows] == ["rejected", "passed"]
    assert "executed_round" not in rows[0] and rows[1]["executed_round"] == 1
    for row, raw, body in zip(rows, [invalid, valid], bodies):
        assert row["usage"] == {"prompt_tokens": 7, "completion_tokens": 11}
        assert row["messages_sha256"] == sha(body["messages"])
        assert (result.trajectory_path.parent / row["untrusted_response"]["path"]).read_text() == raw
    state = json.loads(bodies[1]["messages"][1]["content"])
    assert state["plan_error"] == {"code": "auto_clock_input", "fields": ["vectors.inputs.clk"]}
    assert state["current_plan"] is None and state["observation"] is None
    assert "request automatic clock" not in bodies[1]["messages"][1]["content"]
    assert service.api_key not in result.trajectory_path.read_text()


def test_bad_per_cycle_configuration_cannot_change_provider_limits_or_use_transport(tmp_path, monkeypatch):
    bodies = install(monkeypatch, stop())
    service = provider(request_limit=7, max_output_tokens=8192, timeout=150)
    before = (service.request_limit, service.max_output_tokens, service.timeout, service.force_output_limit)
    contract_data = json.loads((ROOT / "examples/mod10_counter_contract.json").read_text())
    contract_data["ports"][-1]["width"] = 5
    with pytest.raises(ValueError, match="supported builtin reference"):
        run_verification_agent(provider=service, contract=DutContract.from_dict(contract_data),
            rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "wrong-profile",
            objective="unsupported configuration", pipeline=Pipeline(),
            execution_options={"reference_sampling": "per_cycle"})
    assert (service.request_limit, service.max_output_tokens, service.timeout, service.force_output_limit) == before
    assert service.request_count == 0 and bodies == []
    assert not (tmp_path / "wrong-profile").exists()
