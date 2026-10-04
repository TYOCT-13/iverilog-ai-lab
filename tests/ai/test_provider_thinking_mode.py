"""思考模式只控制显式HTTP字段，不推定第三方服务行为。"""
import json
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.provider import OpenAICompatibleProvider


def _provider(**options):
    return OpenAICompatibleProvider(
        endpoint=options.pop("endpoint", "https://api.deepseek.com"),
        model="deepseek-flash", api_key="synthetic-key-for-test-only",
        wire_api=options.pop("wire_api", "chat_completions"), allow_network=True,
        request_limit=1, max_output_tokens=512, force_output_limit=True,
        **options,
    )


@pytest.mark.parametrize("mode", [None, "enabled", "disabled"])
def test_actual_http_body_sends_only_explicit_thinking_mode(monkeypatch, mode):
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}).encode()
    def transport(request, timeout):
        seen.append((request.full_url, json.loads(request.data)))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=transport))
    provider = _provider(thinking_mode=mode)
    assert provider.generate("Return JSON only") == "{}"
    url, body = seen[0]
    assert url == "https://api.deepseek.com/chat/completions"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 512 and body["stream"] is False
    if mode is None:
        assert "thinking" not in body
    else:
        assert body["thinking"] == {"type": mode}
    diagnostic = provider.request_diagnostics()
    assert ("thinking" in diagnostic["request_fields"]) is (mode is not None)
    assert diagnostic["thinking_mode"] == mode
    assert provider.request_count == 1
    assert "synthetic-key-for-test-only" not in json.dumps(body)
    assert "synthetic-key-for-test-only" not in json.dumps(diagnostic)


@pytest.mark.parametrize("endpoint", ["https://api.deepseek.com", "https://provider.example"])
@pytest.mark.parametrize("wire_api", ["chat_completions", "responses"])
def test_default_mode_never_guesses_service_policy(endpoint, wire_api):
    provider = _provider(endpoint=endpoint, wire_api=wire_api)
    assert provider.thinking_mode is None
    assert "thinking" not in provider._build_body("JSON", streaming=False)
    assert provider.request_diagnostics()["thinking_mode"] is None


@pytest.mark.parametrize("mode", ["auto", "none", "Disabled", "disable", True, False, 1, 0, {}, ["disabled"]])
def test_invalid_modes_are_rejected_with_static_secret_free_errors(mode):
    with pytest.raises(ValueError, match="thinking_mode must be enabled, disabled or None"):
        _provider(thinking_mode=mode)


@pytest.mark.parametrize("mode", ["enabled", "disabled"])
def test_responses_rejects_chat_only_mode_at_construction(mode):
    with pytest.raises(ValueError, match="supported only by chat_completions"):
        _provider(wire_api="responses", thinking_mode=mode)


def test_mutated_wire_cannot_send_chat_extension_to_responses(monkeypatch):
    provider = _provider(thinking_mode="disabled")
    provider.wire_api = "responses"
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported mode must fail before transport")
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", forbidden)
    with pytest.raises(ValueError, match="Responses uses reasoning.effort"):
        provider.generate("JSON")
    with pytest.raises(ValueError, match="Responses uses reasoning.effort"):
        provider.request_diagnostics()
    assert provider.request_count == 0


def test_explicit_selection_on_another_chat_endpoint_is_not_auto_detection():
    # The caller may select a documented extension; a successful local body
    # build does not claim that an arbitrary service accepts or obeys it.
    provider = _provider(endpoint="https://provider.example", thinking_mode="enabled")
    assert provider._build_body("JSON", streaming=False)["thinking"] == {"type": "enabled"}
