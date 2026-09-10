import pytest
import json
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.error import URLError
from iverilog_ai.ai import MockProvider, PlanningError, plan_tests, supplement_tests
def test_mock_is_deterministic_and_validated():
    plan=plan_tests("find reset bug", "counter", MockProvider())
    assert plan.schema_version == "1.0" and plan.vectors[0].cycles == 2
class Bad:
    def __init__(self): self.calls=0
    def generate(self,prompt): self.calls += 1; return '{"unexpected": 1}'
def test_invalid_output_rejected_after_bounded_retries():
    provider=Bad()
    with pytest.raises(PlanningError): plan_tests("x","d",provider,max_retries=2)
    assert provider.calls == 3
def test_provider_network_is_opt_in(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    monkeypatch.delenv("IVERILOG_AI_ALLOW_NETWORK", raising=False)
    with pytest.raises(RuntimeError, match="network disabled"): OpenAICompatibleProvider().generate("x")

def test_responses_provider_extracts_output_text(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"output_text": "{\"ok\":true}"}).encode()
    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setattr("iverilog_ai.ai.provider.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        endpoint="https://provider.example",
        model="test-model",
        api_key="test-secret",
        reasoning_effort="low",
    )
    assert provider.generate("plan") == '{"ok":true}'
    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["body"]["reasoning"] == {"effort": "low"}
    assert "test-secret" not in json.dumps(captured["body"])

def test_model_list_is_sorted_and_deduplicated(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return b'{"data":[{"id":"model-b"},{"id":"model-a"},{"id":"model-a"}]}'
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setattr("iverilog_ai.ai.provider.urlopen", lambda request, timeout: Response())
    provider = OpenAICompatibleProvider(endpoint="https://provider.example/v1/models", model="x", api_key="secret")
    assert provider.list_models() == ("model-a", "model-b")

def test_planner_includes_contract_context():
    class Capture:
        prompt = ""
        def generate(self, prompt):
            self.prompt = prompt
            return MockProvider().generate(prompt)
    provider = Capture()
    plan_tests("verify", "demo", provider, context="ports: a, result")
    assert "ports: a, result" in provider.prompt

def test_http_429_is_reported_without_plan_wrapper_or_secret(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    headers = Message()
    headers["Retry-After"] = "12"
    def rate_limited(request, timeout):
        raise HTTPError(request.full_url, 429, "limited", headers, None)
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setattr("iverilog_ai.ai.provider.urlopen", rate_limited)
    provider = OpenAICompatibleProvider(endpoint="https://provider.example", model="model", api_key="never-show-me")
    with pytest.raises(RuntimeError, match="HTTP 429") as caught:
        plan_tests("verify", "demo", provider, max_retries=2)
    assert "invalid test plan" not in str(caught.value)
    assert "never-show-me" not in str(caught.value)
    assert "12" in str(caught.value)

def test_connection_close_is_reported_without_plan_wrapper(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setattr("iverilog_ai.ai.provider.urlopen", lambda request, timeout: (_ for _ in ()).throw(URLError("Remote end closed connection without response")))
    provider = OpenAICompatibleProvider(endpoint="https://provider.example", model="model", api_key="secret", wire_api="chat_completions", allow_network=True)
    with pytest.raises(RuntimeError, match="连接失败") as caught:
        plan_tests("verify", "demo", provider)
    assert "invalid test plan" not in str(caught.value)

def test_duplicate_vector_names_are_deterministically_suffixed():
    payload = {
        "schema_version": "1.0",
        "design": "demo",
        "objective": "verify",
        "vectors": [
            {"name": "normal", "inputs": {"a": 0}, "expected": {"y": 0}},
            {"name": "normal", "inputs": {"a": 1}, "expected": {"y": 1}},
            {"name": "normal", "inputs": {"a": 2}, "expected": {"y": 2}}
        ]
    }
    plan = plan_tests("verify", "demo", MockProvider(payload), max_retries=0)
    assert [vector.name for vector in plan.vectors] == ["normal", "normal_2", "normal_3"]

def test_prompt_explicitly_requires_unique_names():
    class Capture:
        def generate(self, prompt):
            self.prompt = prompt
            return MockProvider().generate(prompt)
    provider = Capture()
    plan_tests("verify", "demo", provider)
    assert "vector.name MUST be unique" in provider.prompt

def test_request_diagnostics_are_final_and_secret_free():
    from iverilog_ai.ai import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(
        endpoint="https://provider.example/v1/responses",
        model="model-x",
        api_key="  never-show-me  ",
        reasoning_effort=None,
        allow_network=True,
    )
    diagnostic = provider.request_diagnostics()
    assert diagnostic["url"] == "https://provider.example/v1/responses"
    assert diagnostic["request_fields"] == ["model", "input", "stream"]
    assert diagnostic["has_api_key"] is True
    assert "never-show-me" not in json.dumps(diagnostic)

def test_deepseek_uses_official_paths(monkeypatch):
    from iverilog_ai.ai import OpenAICompatibleProvider
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
    def fake(request, timeout):
        seen.append(request.full_url)
        return Response()
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setattr("iverilog_ai.ai.provider.urlopen", fake)
    provider = OpenAICompatibleProvider(endpoint="https://api.deepseek.com", model="deepseek-chat", api_key="secret", wire_api="chat_completions")
    provider.generate("x")
    assert seen == ["https://api.deepseek.com/chat/completions"]
    assert provider.request_diagnostics()["url"] == "https://api.deepseek.com/chat/completions"

def test_planner_accepts_fenced_json():
    class Fenced:
        def generate(self, prompt):
            payload = MockProvider().generate(prompt)
            return "```json\n" + payload + "\n```"
    assert plan_tests("verify", "demo", Fenced(), max_retries=0).schema_version == "1.0"


def test_supplement_tests_merges_and_validates_unique_names():
    plan = plan_tests("verify", "demo", MockProvider(), max_retries=0)
    class Supplement:
        def generate(self, prompt):
            assert "Observed failures" in prompt
            return json.dumps({"vectors": [
                {"name": "reset", "inputs": {"rst_n": 1}, "expected": {"out": 0}},
                {"name": "edge", "inputs": {"rst_n": 0}, "expected": {}},
            ]})
    updated = supplement_tests(plan, [{"test_id": "reset", "cycle": 2, "signal": "out", "expected": 1, "actual": 0}], Supplement())
    assert [v.name for v in updated.vectors] == ["reset", "reset_2", "edge"]


def test_supplement_tests_rejects_empty_and_bounds_retry():
    plan = plan_tests("verify", "demo", MockProvider(), max_retries=0)
    with pytest.raises(ValueError, match="at least one"):
        supplement_tests(plan, [], MockProvider())
    class Bad:
        calls = 0
        def generate(self, prompt):
            self.calls += 1
            return '{"vectors": [{"name": "x", "unexpected": true}]}'
    provider = Bad()
    with pytest.raises(PlanningError):
        supplement_tests(plan, [{"message": "bad"}], provider, max_retries=1)
    assert provider.calls == 2


def test_supplement_tests_bounds_failure_prompt():
    plan = plan_tests("verify", "demo", MockProvider(), max_retries=0)
    with pytest.raises(ValueError, match="at most 50"):
        supplement_tests(plan, [{"message": "x"}] * 51, MockProvider())
