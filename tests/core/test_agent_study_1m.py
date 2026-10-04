"""Per-batch scope and no private-run dependency are fixed before real requests."""
import pytest

from scripts import run_agent_study_1m as study
from scripts.summarize_agent_comparison import classify


def test_scope_cycle_caps_and_fixed_rotation():
    reg, generated = study.preregister_study()
    assert len(reg["rows"]) == 216 and reg["theoretical_requests"] == 252
    assert reg["study"]["limits"]["token_cap"] == 1000000
    assert len(generated) == 4 and not reg["independent_holdout"]
    for strategy in study.STRATEGIES:
        rows = [r for r in reg["rows"] if r["strategy"] == strategy]
        assert len(rows) == 36 and sum(r["variant"] != "reference" for r in rows) == 24
        assert all(not r["rounds"] and r["requests"] == 0 for r in rows)
    again, _ = study.preregister_study()
    assert reg["rows"] == again["rows"]
    assert reg["prompt_profile"]["max_rounds"] == 3


def test_dry_run_never_reads_key_or_creates_inputs_output(monkeypatch):
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dry-run read key"))
    monkeypatch.setattr(study, "execute", lambda *a, **k: pytest.fail("dry-run executed"))
    before = (study.INPUTS.exists(), study.OUTPUT.exists())
    assert study.main(["--api-key-file", "absent"]) == 0
    assert before == (study.INPUTS.exists(), study.OUTPUT.exists())


@pytest.mark.parametrize("kind,status", [("TokenBudgetExceeded", "token_budget"),
                                        ("TokenUsageViolation", "token_accounting_error")])
def test_token_denial_keeps_a_distinct_unexecuted_status(kind, status):
    assert classify({"rounds": [], "stop_reason": "policy_error", "usage_by_decision": [{"error_type": kind}]}) == (status,False)
