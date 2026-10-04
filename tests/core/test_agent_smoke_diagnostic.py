"""The small post-failure diagnostic must preserve scope, semantics and budget."""
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_agent_smoke_diagnostic as diagnostic


@pytest.fixture(autouse=True)
def isolated_parent_records(monkeypatch):
    """Unit tests need no private live run; live evidence is checked separately."""
    read_text = Path.read_text
    real_sha = diagnostic.sha
    parent = {"finished_at": "unit_fixture_not_live", "requests_attempted": 36,
              "rows": [{"case": case, "variant": variant, "seed": seed, "strategy": "single",
                        "status": status, "requests": 1, "detected": False,
                        "rounds": [{}] if variant == "reference" else []}
                       for case, variant, seed, status in diagnostic.SELECTION]}
    parent_text = json.dumps(parent)
    parent_digest = hashlib.sha256(parent_text.encode()).hexdigest()
    ledger_path = diagnostic.LEDGER
    ledger = json.loads(read_text(ledger_path, encoding="utf-8"))
    ledger["new_record"]["sha256"] = parent_digest
    ledger_text = json.dumps(ledger)
    texts = {diagnostic.PARENT: parent_text, ledger_path: ledger_text}

    def fixture_read(path, *args, **kwargs):
        if path in texts:
            return texts[path]
        return read_text(path, *args, **kwargs)

    def fixture_sha(path):
        if path in texts:
            return hashlib.sha256(texts[path].encode()).hexdigest()
        return real_sha(path)

    monkeypatch.setattr(Path, "read_text", fixture_read)
    monkeypatch.setattr(diagnostic, "sha", fixture_sha)


def test_normalization_removes_only_old_budget_and_preserves_circuit_semantics():
    budgets = {"sync_fifo": 16, "uart_tx": 48, "spi_master": 20, "handshake_stage": 8}
    for case, cycles in budgets.items():
        original = (diagnostic.ROOT / f"spec/{case}_spec.md").read_text(encoding="utf-8")
        normalized = diagnostic.normalize_spec(case, cycles, original)
        assert f"at most {cycles} stimulus cycles" in normalized
        assert "top-level action, reason, vectors" in normalized
        assert diagnostic.OLD_BUDGET_PREFIX[case] not in normalized
        retained = "\n".join(line for line in original.splitlines()
                             if not line.startswith(diagnostic.OLD_BUDGET_PREFIX[case])) + "\n"
        assert normalized.endswith(retained)
        with pytest.raises(ValueError, match="exactly one"):
            diagnostic.normalize_spec(case, cycles, normalized)


def test_selected_scope_has_five_defects_and_one_correct_fresh_control():
    reg, generated = diagnostic.preregister_diagnostic()
    assert len(reg["rows"]) == reg["theoretical_requests"] == 6
    assert sum(r["variant"] != "reference" for r in reg["rows"]) == 5
    assert all(r["status"] == "not_started" and not r["rounds"] and not r["requests"] for r in reg["rows"])
    assert reg["study"]["not_a_new_comparison"] and not reg["independent_holdout"]
    assert len(generated) == 4
    assert all("not_comparison" in reg["scope"] for _ in reg["rows"])


def test_dry_run_does_not_read_key_or_write_files(monkeypatch):
    monkeypatch.setattr(diagnostic, "read_key_file", lambda _: pytest.fail("dry-run read key"))
    monkeypatch.setattr(diagnostic, "execute", lambda *a, **k: pytest.fail("dry-run executed"))
    before = (diagnostic.INPUTS.exists(), diagnostic.OUTPUT.exists())
    assert diagnostic.main(["--api-key-file", "absent"]) == 0
    assert before == (diagnostic.INPUTS.exists(), diagnostic.OUTPUT.exists())


def test_budget_exhaustion_is_rejected_before_credential_read(tmp_path, monkeypatch):
    ledger = json.loads(diagnostic.LEDGER.read_text(encoding="utf-8"))
    ledger.update(reserved_request_upper=360, remaining_after_reservation=0)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "LEDGER", path)
    monkeypatch.setattr(diagnostic, "read_key_file", lambda _: pytest.fail("invalid budget read key"))
    assert diagnostic.main(["--execute", "--api-key-file", "absent"]) == 2


def test_ledger_cannot_bind_a_different_parent_result(tmp_path, monkeypatch):
    ledger = json.loads(diagnostic.LEDGER.read_text(encoding="utf-8"))
    ledger["new_record"]["sha256"] = "0" * 64
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "LEDGER", path)
    monkeypatch.setattr(diagnostic, "read_key_file", lambda _: pytest.fail("wrong parent read key"))
    assert diagnostic.main(["--execute", "--api-key-file", "absent"]) == 2
