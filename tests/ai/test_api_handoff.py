"""The API handoff defaults to offline and bounds actual transport requests."""

import importlib.util
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from iverilog_ai.ai.debug_server import create_server
from iverilog_ai.ai.provider import OpenAICompatibleProvider, ProviderHTTPError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_online_api", ROOT / "scripts/check_online_api.py")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


@pytest.fixture
def local_server():
    server = create_server("127.0.0.1", 0, vector_count=6)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_default_preflight_never_connects_or_creates_artifacts(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "1")
    monkeypatch.setenv("HANDOFF_TEST_KEY", "do-not-log-this-test-credential")
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run must not generate through the online provider")
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", forbidden)
    output = tmp_path / "new-run"
    assert handoff.main([
        "--endpoint", "https://provider.example/private-tenant/v1", "--model", "model",
        "--api-key-env", "HANDOFF_TEST_KEY", "--output-dir", str(output),
    ]) == 0
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["mode"] == "dry_run" and result["planned_requests"] == 1
    assert result["has_api_key"] and result["automatic_retries"] == 0
    assert result["max_output_tokens_for_batch"] == 2048
    assert "do-not-log-this-test-credential" not in raw and "private-tenant" not in raw
    assert result["inputs"][0]["prompt_sha256"] and not output.exists()


def test_oversized_batch_is_rejected_before_network(monkeypatch):
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", lambda *a: pytest.fail("unexpected request"))
    with pytest.raises(SystemExit) as error:
        handoff.main(["--execute", "--cases", "simple_alu", "mod10_counter", "--max-requests", "1"])
    assert error.value.code == 2


def test_selected_missing_key_does_not_fall_back_to_other_environment(monkeypatch, capsys):
    monkeypatch.delenv("MISSING_HANDOFF_TEST_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    with pytest.raises(SystemExit) as error:
        handoff.main(["--execute", "--endpoint", "https://provider.example", "--model", "model", "--api-key-env", "MISSING_HANDOFF_TEST_KEY"])
    assert error.value.code == 2
    assert "unrelated-test-key" not in capsys.readouterr().out


@pytest.mark.parametrize("wire_api, field", [("responses", "max_output_tokens"), ("chat_completions", "max_tokens")])
def test_budgeted_provider_sends_even_the_default_output_cap(wire_api, field):
    provider = OpenAICompatibleProvider(wire_api=wire_api, force_output_limit=True, max_output_tokens=4096)
    assert provider._build_body("test", streaming=False)[field] == 4096
    assert field in provider.request_diagnostics()["request_fields"]


def test_actual_transport_stops_at_request_limit(local_server):
    provider = OpenAICompatibleProvider(endpoint=local_server, model="debug-local", request_limit=1)
    assert provider.list_models()
    with pytest.raises(RuntimeError, match="budget exhausted"):
        provider.list_models()
    assert provider.request_count == 1


def test_redirect_cannot_create_uncounted_request():
    visits = []
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            visits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleProvider(endpoint=f"http://127.0.0.1:{server.server_address[1]}", model="debug-local", request_limit=1)
        with pytest.raises(ProviderHTTPError) as error:
            provider.list_models()
        assert error.value.status == 302
        assert visits == ["/v1/models"] and provider.request_count == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("wire_api", ["responses", "chat_completions"])
def test_local_end_to_end_plan_and_simulation(local_server, tmp_path, wire_api):
    output = tmp_path / wire_api
    assert handoff.main([
        "--execute", "--endpoint", local_server, "--model", "debug-local",
        "--wire-api", wire_api, "--simulate", "--output-dir", str(output),
    ]) == 0
    report = json.loads((output / "api_check.json").read_text(encoding="utf-8"))
    assert report["request_attempts"] == 1
    assert report["purpose"] == "api_smoke_check_not_benchmark"
    row = report["runs"][0]
    assert row["status"] == "plan_valid" and row["checks"] > 0 and row["failures"] == 0
    assert (output / "simple_alu/0/plan.json").exists()
    with pytest.raises(SystemExit) as error:
        handoff.main(["--execute", "--endpoint", local_server, "--model", "debug-local", "--output-dir", str(output)])
    assert error.value.code == 2


def test_failure_stops_batch_and_does_not_log_secret(monkeypatch, capsys, local_server, tmp_path):
    secret = "never-log-test-bearer"
    monkeypatch.setenv("HANDOFF_TEST_KEY", secret)
    calls = []
    def fail(self, prompt):
        calls.append(prompt)
        self.request_count += 1
        raise ValueError("gateway echoed " + secret)
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", fail)
    output = tmp_path / "failed"
    assert handoff.main([
        "--execute", "--endpoint", local_server, "--model", "debug-local",
        "--api-key-env", "HANDOFF_TEST_KEY", "--repeats", "2", "--max-requests", "2",
        "--output-dir", str(output),
    ]) == 1
    raw = (output / "api_check.json").read_text(encoding="utf-8")
    assert len(calls) == 1 and secret not in raw and secret not in capsys.readouterr().out
    assert json.loads(raw)["runs"][0]["status"] == "failed"
