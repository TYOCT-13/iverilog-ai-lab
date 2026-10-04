"""Short budget study cannot silently overspend or change comparison membership."""
import json

import pytest

from scripts import run_agent_smoke_comparison as smoke


def test_dry_run_does_not_read_credentials_or_create_output(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "read_key_file", lambda _: pytest.fail("dry-run read a credential"))
    monkeypatch.setattr(smoke, "execute", lambda *a, **k: pytest.fail("dry-run executed"))
    output = tmp_path / "not_created"
    assert smoke.main(["--api-key-file", str(tmp_path / "absent"), "--output-dir", str(output)]) == 0
    assert not output.exists()


def test_overspend_or_incomplete_cap_rejected_before_key_read(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "read_key_file", lambda _: pytest.fail("invalid cap read a credential"))
    monkeypatch.setattr(smoke, "execute", lambda *a, **k: pytest.fail("invalid cap executed"))
    for cap in (35, 37, -1):
        assert smoke.main(["--execute", "--total-request-cap", str(cap), "--api-key-file", "absent",
                           "--output-dir", str(tmp_path / "absent")]) == 2


def test_scope_denominators_and_budget_minima_are_frozen():
    reg = smoke.preregister_smoke()
    assert len(reg["rows"]) == 144 and reg["theoretical_requests"] == 36
    assert reg["independent_holdout"] is False
    assert {r["seed"] for r in reg["rows"]} == {0, 1, 2}
    for strategy in smoke.STRATEGIES:
        rows = [r for r in reg["rows"] if r["strategy"] == strategy]
        assert sum(r["variant"] != "reference" for r in rows) == 24
        assert len(rows) == 36
    assert {(r["case"], r["budget_cycles"]) for r in reg["rows"]} == {
        ("sync_fifo", 16), ("uart_tx", 48), ("spi_master", 20), ("handshake_stage", 8)}
    assert "spec/agent_smoke_budgets.json" in reg["code_and_input_sha256"]
    assert len(smoke.preregister_smoke(baselines_only=True)["rows"]) == 108


def test_impossible_transaction_budget_rejected(tmp_path, monkeypatch):
    payload = json.loads(smoke.BUDGETS.read_text(encoding="utf-8"))
    payload["cases"]["uart_tx"]["cycle_budget"] = 10
    config = tmp_path / "invalid.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(smoke, "BUDGETS", config)
    with pytest.raises(ValueError, match="cannot complete"):
        smoke.preregister_smoke()
