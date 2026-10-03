"""SYNTHETIC TEST DATA ONLY. No fixture is a real participant or trial result.

Files, when needed, are written only under pytest's tmp_path outside the repo.
The human flag is deliberately exercised to test validation, never published.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("trial_sessions", ROOT / "scripts/summarize_trial_sessions.py")
sessions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sessions)


def fixture_record(session_id="SYNTHETIC-S01", alias="SYNTHETIC-P01"):
    return {
        "_fixture_notice": "SYNTHETIC TEST DATA; NEVER A REAL TRIAL",
        "schema_version": "2.0", "record_kind": "human",
        "session": {"session_id": session_id, "date": "2026-10-04", "participant_alias": alias,
                    "roles": ["novice"], "development_relation": "external", "visit": "first",
                    "previous_session_id": None, "recording_basis": "contemporaneous", "recording_note": ""},
        "build": {"version": "SYNTHETIC-test", "commit": "SYNTHETIC-test", "dirty": False},
        "environment": {"os": "TEST", "python_version": "TEST", "iverilog_version": "TEST", "browser": "TEST",
                        "device": "desktop", "viewport": "1440x900", "execution_mode": "independent_machine", "entry": "ui"},
        "consent": {"anonymous_quote": False, "screen_recording": False},
        "assigned_tasks": ["T02", "T03"], "task_records": [], "overall_feedback": "SYNTHETIC private comment",
    }


def task(task_id="T02", status="completed", seconds=None, method="not_recorded"):
    return {"task_id": task_id, "status": status, "duration_seconds": seconds, "duration_method": method,
            "prompt_count": None, "assistance": [], "objective_result": "SYNTHETIC observed result",
            "subjective_feedback": "SYNTHETIC subjective comment", "reason": "SYNTHETIC reason" if status != "completed" else "",
            "evidence": []}


def test_template_is_blank_and_cannot_be_counted_as_person():
    template = json.loads((ROOT / "docs/trial/forms/session_feedback_template.json").read_text(encoding="utf-8"))
    assert template["assigned_tasks"] == template["task_records"] == []
    assert template["consent"] == {"anonymous_quote": None, "screen_recording": None}
    result = sessions.summarize([template])
    assert result["people"] == result["sessions"] == 0 and result["excluded_nonhuman_records"] == 1
    assert "participant_alias" in template["session"] and "development_relation" in template["session"]


def test_assigned_missing_and_skipped_stay_in_denominator():
    first = fixture_record()
    first["task_records"] = [task("T02", "skipped")]
    second = fixture_record("SYNTHETIC-S02", "SYNTHETIC-P02")
    second["assigned_tasks"] = ["T02"]
    second["task_records"] = [task()]
    result = sessions.summarize([first, second])
    assert result["tasks"]["T02"]["assigned_sessions"] == 2
    assert result["tasks"]["T02"]["completed"] == result["tasks"]["T02"]["skipped"] == 1
    assert result["tasks"]["T03"]["assigned_sessions"] == result["tasks"]["T03"]["missing_record"] == 1
    assert result["tasks"]["T01"]["assigned_sessions"] == 0


def test_same_person_retest_is_one_person_and_separate_session():
    first = fixture_record()
    second = fixture_record("SYNTHETIC-S02")
    second["session"].update(visit="retest", previous_session_id="SYNTHETIC-S01")
    second["task_records"] = [task()]
    result = sessions.summarize([first, second])
    assert result["people"] == 1 and result["sessions"] == 2
    assert result["visits"] == {"first": 1, "retest": 1}
    assert result["tasks_by_visit"]["first"]["T02"]["completed"] == 0
    assert result["tasks_by_visit"]["retest"]["T02"]["completed"] == 1


def test_duplicate_sessions_are_rejected_not_counted_twice():
    record = fixture_record()
    with pytest.raises(sessions.SessionError, match="重复会话"):
        sessions.summarize([record, deepcopy(record)])


def test_measured_completion_times_have_explicit_sample_count():
    records = []
    cases = [("completed", 20, "measured"), ("completed", 40, "measured"), ("completed", 999, "estimated"),
             ("completed", None, "not_recorded"), ("blocked", 500, "measured"), ("partial", 800, "measured")]
    for index, (status, seconds, method) in enumerate(cases):
        record = fixture_record(f"SYNTHETIC-S{index}", f"SYNTHETIC-P{index}")
        record["task_records"] = [task(status=status, seconds=seconds, method=method)]
        records.append(record)
    row = sessions.summarize(records)["tasks"]["T02"]
    assert row["assigned_sessions"] == 6 and row["completed"] == 4
    assert row["completed_measured_duration_median_seconds"] == 30
    assert row["completed_measured_duration_samples"] == 2
    assert row["completed_estimated_duration_samples"] == row["completed_duration_missing"] == 1


def test_no_duration_is_unknown_not_zero_and_help_not_assumed_absent():
    record = fixture_record()
    record["task_records"] = [task()]
    row = sessions.summarize([record])["tasks"]["T02"]
    assert row["completed_measured_duration_median_seconds"] is None
    assert row["completed_without_assistance"] == 0 and row["completed_assistance_unknown"] == 1
    record["task_records"][0].update(prompt_count=0)
    assert sessions.summarize([record])["tasks"]["T02"]["completed_without_assistance"] == 1
    record["task_records"][0]["assistance"] = [{"kind": "operator_action", "detail": "SYNTHETIC assistance"}]
    assert sessions.summarize([record])["tasks"]["T02"]["completed_with_assistance"] == 1


def test_public_excludes_entire_nonconsenting_session_not_just_quote():
    private = fixture_record()
    private["task_records"] = [task(status="blocked")]
    public = fixture_record("SYNTHETIC-S02", "SYNTHETIC-P02")
    public["consent"]["anonymous_quote"] = True
    public["task_records"] = [task()]
    result = sessions.summarize([private, public], public=True)
    text = json.dumps(result)
    assert result["sessions"] == result["people"] == 1 and result["withheld_without_quote_consent"] == 1
    assert result["tasks"]["T02"]["assigned_sessions"] == 1 and result["tasks"]["T02"]["blocked"] == 0
    assert "SYNTHETIC-P01" not in text and "SYNTHETIC-S01" not in text
    assert result["public_feedback"][0]["participant_alias"] == "SYNTHETIC-P02"
    internal = sessions.summarize([private, public])
    assert internal["sessions"] == 2 and internal["public_feedback"] == []


def test_recording_consent_does_not_grant_quote_consent():
    record = fixture_record()
    record["consent"]["screen_recording"] = True
    result = sessions.summarize([record], public=True)
    assert result["sessions"] == 0 and result["public_feedback"] == []


def test_synthetic_records_never_appear_in_real_summary():
    record = fixture_record()
    record["record_kind"] = "synthetic"
    result = sessions.summarize([record], public=True)
    assert result["people"] == 0 and result["excluded_nonhuman_records"] == 1


@pytest.mark.parametrize("change, expected", [
    (lambda p: p["session"].update(session_id=""), "session_id"),
    (lambda p: p["session"].update(roles=[]), "roles"),
    (lambda p: p["session"].update(development_relation=[]), "development_relation"),
    (lambda p: p["session"].update(recording_basis="retrospective", recording_note=""), "recording_note"),
    (lambda p: p["session"].update(visit="retest"), "previous_session_id"),
    (lambda p: p["environment"].update(execution_mode=[]), "execution_mode"),
    (lambda p: p["consent"].update(anonymous_quote=None), "anonymous_quote"),
    (lambda p: p.update(assigned_tasks=[]), "assigned_tasks"),
    (lambda p: p["task_records"].append(task("T12")), "task_id"),
    (lambda p: p["task_records"].extend([task(), task()]), "task_id"),
    (lambda p: p["task_records"].append(task(seconds=True, method="measured")), "duration_seconds"),
    (lambda p: p["task_records"].append(task(seconds=float("nan"), method="measured")), "duration_seconds"),
    (lambda p: p["task_records"].append(task(seconds=20, method="not_recorded")), "duration_method"),
    (lambda p: p["task_records"].append({**task(status="skipped"), "reason": ""}), "reason"),
    (lambda p: p["task_records"].append({**task(), "prompt_count": -1}), "prompt_count"),
    (lambda p: p["task_records"].append({**task(), "prompt_count": 0, "assistance": [{"kind": "hint", "detail": "SYNTHETIC hint"}]}), "prompt_count"),
])
def test_invalid_or_incomplete_fields_do_not_pass(change, expected):
    record = fixture_record()
    change(record)
    with pytest.raises(sessions.SessionError, match=expected):
        sessions.summarize([record])


def test_cli_does_not_overwrite_and_invalid_batch_emits_no_partial_summary(tmp_path, capsys):
    record = fixture_record()
    source = tmp_path / "SYNTHETIC-session.json"
    source.write_text(json.dumps(record), encoding="utf-8")
    output = tmp_path / "SYNTHETIC-summary.md"
    assert sessions.main([str(source), "--output", str(output)]) == 0
    original = output.read_text(encoding="utf-8")
    assert sessions.main([str(source), "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == original
    capsys.readouterr()
    duplicate = tmp_path / "SYNTHETIC-duplicate.json"
    duplicate.write_text(json.dumps(record), encoding="utf-8")
    assert sessions.main([str(source), str(duplicate)]) == 2
    assert capsys.readouterr().out == ""


def test_cli_glob_expands_and_deduplicates_overlapping_paths(tmp_path, capsys):
    source = tmp_path / "SYNTHETIC-session.json"
    source.write_text(json.dumps(fixture_record()), encoding="utf-8")
    assert sessions.main([str(tmp_path / "*.json"), str(source), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sessions"] == 1


def test_cli_glob_with_no_match_fails_without_empty_success(tmp_path, capsys):
    assert sessions.main([str(tmp_path / "nothing-*.json")]) == 2
    result = capsys.readouterr()
    assert result.out == "" and "匹配为空" in result.err
