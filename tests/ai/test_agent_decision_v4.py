"""Typed wire messages and inert diagnostic artifacts; no real API requests."""
import hashlib
from http.client import RemoteDisconnected
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentDecision, AgentLimits, SYSTEM_PROMPT, run_verification_agent
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
    assert not (tmp_path / "agent/untrusted_decisions").exists()
    assert service.api_key not in result.trajectory_path.read_text()
    assert "\\u0073ynthetic" not in result.trajectory_path.read_text()


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
