"""Separate v8 full-batch gates; never read a key or call a live service."""
import copy
import hashlib
import json

import pytest

from scripts import run_agent_feedback_study as study
from scripts.run_agent_comparison import execute
from scripts.summarize_agent_comparison import build_summary


def forbidden(*args, **kwargs):
    pytest.fail("unit test initialized a credential or API provider")


def test_full_scope_is_unchanged_v7_membership_and_truthfully_previously_exposed():
    reg = study.preregister_feedback_study()
    old = json.loads(study.PRIOR_REGISTRATION.read_text(encoding="utf-8"))
    assert len(reg["rows"]) == 432 and reg["theoretical_requests"] == 504
    assert reg["study"]["all_modules_previously_agent_exposed"]
    assert reg["study"]["new_holdout_modules"] == []
    assert not reg["independent_holdout"] and not reg["external_independent_holdout"]
    for current, previous in zip(reg["rows"], old["rows"], strict=True):
        assert {k: v for k, v in current.items() if k != "cohort"} == {
            k: v for k, v in previous.items() if k != "cohort"}
    for strategy in study.STRATEGIES:
        rows = [r for r in reg["rows"] if r["strategy"] == strategy]
        assert len(rows) == 72 and sum(r["variant"] != "reference" for r in rows) == 48
    assert reg["study"]["unchanged_v7_scope"]["no_historical_results_read"]
    for path in ("src/iverilog_ai/core/observation_feedback.py", "tests/core/test_observation_feedback.py",
                 "tests/core/test_agent_feedback_v8.py", "scripts/run_agent_feedback_study.py"):
        assert path in reg["code_and_input_sha256"]
    assert reg["prompt_profile_sha256"] == hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()


def test_dry_run_has_no_credential_provider_or_output_side_effect(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "read_key_file", forbidden)
    monkeypatch.setattr(study, "BudgetedProvider", forbidden)
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "absent")
    assert study.main(["--api-key-file", str(tmp_path / "missing")]) == 0
    assert not study.OUTPUT.exists()


@pytest.mark.parametrize("field,value", [("token_cap", True), ("registered_rows", 431),
    ("repeats", 2), ("max_vectors_per_proposal", 13), ("max_output_tokens_per_request", 8192)])
def test_resource_drift_rejected_before_registration(monkeypatch, tmp_path, field, value):
    data = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    data[field] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="scope"):
        study.preregister_feedback_study()


def test_altered_old_scope_refused_without_creating_output(monkeypatch, tmp_path):
    path = tmp_path / "previous.json"
    path.write_bytes(study.PRIOR_REGISTRATION.read_bytes() + b"\n")
    monkeypatch.setattr(study, "PRIOR_REGISTRATION", path)
    with pytest.raises(ValueError, match="previous preregistered scope bytes changed"):
        study.preregister_feedback_study()


def test_changed_membership_or_baseline_cannot_sneak_into_new_batch(monkeypatch):
    reg = study.preregister_feedback_study()
    changed = copy.deepcopy(reg)
    changed["rows"][0]["budget_cycles"] += 1
    with pytest.raises(ValueError, match="membership or order"):
        study._bind_unchanged_v7_scope(changed)
    baseline = study.ROOT / "scripts/agent_budget_study_baselines.py"
    real_sha = study.sha
    monkeypatch.setattr(study, "sha", lambda path: "0" * 64 if path == baseline else real_sha(path))
    with pytest.raises(ValueError, match="baseline bytes changed"):
        study._bind_unchanged_v7_scope(reg)


def test_zero_requests_retains_complete_agent_failure_denominators(tmp_path):
    reg = study.preregister_feedback_study()
    reg["rows"] = [r for r in reg["rows"] if r["strategy"] in study.STRATEGIES[3:]]
    destination = tmp_path / "zero"
    result = execute(reg, destination, request_cap=0, provider_factory=forbidden)
    summary = build_summary(result, reg, evidence_root=destination)
    assert len(result["rows"]) == 216 and result["requests_attempted"] == 0
    assert summary["frozen_input_snapshot_verified"] and not summary["eligible_for_frozen_comparison"]
    assert all(summary["strategies"][s]["registered_defect_samples"] == 48 for s in study.STRATEGIES[3:])
    assert all(r["status"] == "global_request_budget" and not r["rounds"] for r in result["rows"])


@pytest.mark.parametrize("pending,finished", [(True, True), (False, False)])
def test_previous_live_batch_cannot_overlap_new_calls(monkeypatch, tmp_path, pending, finished):
    folder = tmp_path / ".iverilog-ai/agent-budget-study-live-20261005"
    folder.mkdir(parents=True)
    (folder / "token_budget.json").write_text(json.dumps({"records": [
        {"status": "pending" if pending else "known_usage"}], "totals": {}}), encoding="utf-8")
    (folder / "results.json").write_text(json.dumps({"finished_at": "finished" if finished else None}), encoding="utf-8")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="pending or unfinished"):
        study.previous_batch_accounting()


def test_previous_unknown_usage_is_retained_but_never_deducted_from_new_cap(monkeypatch, tmp_path):
    folder = tmp_path / ".iverilog-ai/agent-budget-study-live-20261005"
    folder.mkdir(parents=True)
    totals = {"reported_tokens": 10, "unknown_reserved_tokens": 50, "conservative_total": 60}
    (folder / "token_budget.json").write_text(json.dumps({"records": [{"status": "unknown_usage"}],
        "totals": totals}), encoding="utf-8")
    (folder / "results.json").write_text(json.dumps({"finished_at": "finished"}), encoding="utf-8")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    record = study.previous_batch_accounting()[-1]
    assert record["tokens"] == totals and record["pending_requests"] == 0
    assert record["historical_usage_charged_to_this_batch"] is False
