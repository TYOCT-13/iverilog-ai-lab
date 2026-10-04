import json

import pytest

from scripts.summarize_agent_comparison import build_summary, main, registered_rows, summarize_rows


def row(strategy, seed, variant="d1", detected=False, status="not_started"):
    return {"case": "fifo", "variant": variant, "strategy": strategy, "seed": seed,
            "status": status, "detected": detected, "requests": 0, "rounds": []}


def test_repeat_denominator_is_preserved_and_union_not_mean():
    rows = [row("feedback", seed, variant) for seed in range(3) for variant in ["d1", "d2"]]
    registration = {"rows": rows}
    observed = [dict(r) for r in rows[:-1]]
    observed[0].update(detected=True, status="detected")
    observed[3].update(detected=True, status="detected")
    for r in observed:
        if r["detected"]:
            r["rounds"] = [{"actual": {"status": "passed", "checks": 1, "failures": 1, "expectation_source": "reference_model"},
                            "reference": {"status": "passed", "checks": 1, "failures": 0, "expectation_source": "reference_model"}}]
    filled = registered_rows({"rows": observed}, registration)
    stats = summarize_rows(filled)["feedback"]
    assert len(filled) == 6
    assert stats["registered_defect_samples"] == 6
    assert stats["unique_union_rate"] == 1
    assert stats["repeat_detection_rate_mean"] == pytest.approx(1 / 3)
    assert [r["detection_rate"] for r in stats["per_repeat"]] == [0.5, 0.5, 0]
    assert stats["status_counts"]["missing_result"] == 1


@pytest.mark.parametrize("field,value", [("budget_cycles", 999), ("rtl", "different.v"), ("target", "other")])
def test_registered_immutable_fields_cannot_be_overwritten(field, value):
    base = {**row("feedback", 0), "budget_cycles": 160, "rtl": "rtl/a.v", "target": "a"}
    changed = {**base, field: value, "status": "compile_failed", "detected": True}
    with pytest.raises(ValueError, match="immutable"):
        build_summary({"rows": [changed]}, {"rows": [base]})


@pytest.mark.parametrize("status", ["compile_failed", "detected"])
def test_boolean_without_evidence_never_becomes_detection(status):
    base = {**row("feedback", 0), "budget_cycles": 160}
    report = build_summary({"rows": [{**base, "status": status, "detected": True}],
                            "finished_at": "2026-10-04", "changed_inputs_at_finish": []}, {"rows": [base]})
    assert not report["eligible_for_frozen_comparison"]
    assert report["strategies"]["feedback"]["detected_samples"] == 0
    assert report["strategies"]["feedback"]["incomplete_or_undecidable"] == 1


def test_duplicate_or_extra_result_sample_rejected():
    first = row("feedback", 0)
    with pytest.raises(ValueError, match="duplicate"):
        registered_rows({"rows": [first, first]})
    with pytest.raises(ValueError, match="mismatch"):
        registered_rows({"rows": [first]}, {"rows": []})


def test_usage_missing_and_coverage_pairs_remain_explicit():
    feedback = row("feedback", 0, detected=True, status="detected")
    feedback.update(requests=2, usage_by_decision=[{"request_id": "0:0", "usage": {"total_tokens": 15}}])
    other = row("feedback_no_coverage", 0)
    summary = build_summary({"rows": [feedback, other]})
    assert summary["strategies"]["feedback"]["requests_without_usage"] == 1
    assert summary["strategies"]["feedback"]["usage_numeric_sum"]["total_tokens"] == 15
    assert summary["cost_currency"] is None
    assert summary["coverage_ablation_pairs"][0]["no_coverage_status"] == "not_started"


def test_summary_cli_checks_registration_hash_and_refuses_overwrite(tmp_path):
    import hashlib
    registration = tmp_path / "preregistration.json"
    registration.write_text(json.dumps({"rows": [row("fixed", 0)]}), encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"rows": [], "preregistration_sha256": hashlib.sha256(registration.read_bytes()).hexdigest()}))
    output = tmp_path / "summary.json"
    assert main([str(results), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["registered_rows"] == 1
    with pytest.raises(ValueError, match="exists"):
        main([str(results), "--output", str(output)])
    broken = json.loads(results.read_text())
    broken["run_settings_sha256"] = "0" * 64
    results.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="settings hash"):
        main([str(results), "--output", str(tmp_path / "new-summary.json")])
