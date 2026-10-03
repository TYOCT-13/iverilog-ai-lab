from pathlib import Path

import pytest

from scripts.run_verification_agent import main


def test_dry_run_never_calls_api_or_creates_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_TEST_KEY", "private-test-key")
    def forbidden(*args, **kwargs):
        raise AssertionError("dry run attempted network")
    monkeypatch.setattr("iverilog_ai.ai.provider.OpenAICompatibleProvider.generate", forbidden)
    output = tmp_path / "must-not-exist"
    assert main(["--dry-run", "--endpoint", "https://api.example/v1", "--model", "example", "--api-key-env", "AGENT_TEST_KEY", "--output-dir", str(output)]) == 0
    assert not output.exists()
    assert "private-test-key" not in capsys.readouterr().out


def test_missing_selected_key_does_not_fall_back_to_another_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_MISSING_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-secret")
    assert main(["--execute", "--endpoint", "https://api.example", "--model", "example", "--api-key-env", "AGENT_MISSING_KEY", "--output-dir", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("endpoint", ["http://public.example", "https://user:password@api.example", "https://api.example?key=secret"])
def test_bad_endpoint_refused_even_during_preflight(endpoint):
    assert main(["--dry-run", "--endpoint", endpoint]) == 2


def test_explicit_missing_specification_is_not_silently_ignored(tmp_path):
    assert main(["--dry-run", "--spec", str(tmp_path / "missing.md")]) == 2
