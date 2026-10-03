"""The post-hoc report must not gain detections by changing its denominator/budget."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.summarize_matched_budget import build_summary


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = {"categories": ["pwm"], "defects": [{"type": "pwm", "id": "a"}, {"type": "pwm", "id": "b"}]}


def fixture_source():
    rows = []
    for strategy in ("fixed", "random", "ai", "online_ai"):
        for seed in range(1 if strategy == "fixed" else 3):
            for variant in ("reference", "a", "b"):
                rows.append({
                    "strategy": strategy, "case": "pwm", "variant": variant,
                    "seed": seed, "request_id": f"{strategy}-pwm-{seed}",
                    "budget_cycles": 32, "total_cycles": 32, "plan_valid": True,
                    "status": "passed", "defects_found": variant == "a",
                    "check_count": 3, "warning_failures": 0, "error_failures": 0,
                    "plan_sha256": f"plan-{seed}",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
                    if strategy == "online_ai" and seed == 0 else None,
                })
    return {"partial": False, "skipped_cases": {}, "runs": rows}


def test_common_prefix_excludes_later_detections_and_does_not_clone_fixed():
    source = fixture_source()
    next(row for row in source["runs"] if row["strategy"] == "online_ai" and row["seed"] == 2 and row["variant"] == "b")["defects_found"] = True
    before = deepcopy(source)
    result = build_summary(source, MANIFEST, rounds=2)
    assert result["summary"]["online_ai"]["defects_found"] == 1
    assert result["summary"]["online_ai"]["rounds"] == 2
    assert result["historical_seed_sets"]["online_ai"] == [0, 1, 2]
    assert result["summary"]["fixed"]["rounds"] == 1
    assert result["summary"]["fixed"]["runs"] == 3
    assert source == before


def test_usage_is_deduplicated_and_missing_usage_is_not_zero_cost():
    result = build_summary(fixture_source(), MANIFEST, rounds=2)
    usage = result["summary"]["online_ai"]["request_usage"]
    assert usage["plan_requests"] == 2
    assert usage["requests_with_usage"] == 1
    assert usage["known_total_tokens"] == 30  # Not 90 for three variants of one plan.
    assert usage["missing_usage_request_ids"] == ["online_ai-pwm-1"]


def test_missing_variant_stays_in_fixed_manifest_denominator():
    source = fixture_source()
    source["runs"] = [row for row in source["runs"] if not (
        row["strategy"] == "online_ai" and row["seed"] == 0 and row["variant"] == "a"
    )]
    item = build_summary(source, MANIFEST, rounds=2)["summary"]["online_ai"]
    assert item["defects_total"] == 2
    assert item["undecidable_missing"] == 1
    assert item["detection_rate_single_round_mean"] == 0.25


def test_reference_alarm_excludes_that_case_round_but_keeps_denominator():
    source = fixture_source()
    ref = next(row for row in source["runs"] if row["strategy"] == "online_ai" and row["seed"] == 0 and row["variant"] == "reference")
    ref["warning_failures"] = 1
    item = build_summary(source, MANIFEST, rounds=2)["summary"]["online_ai"]
    assert item["alarming_plans"] == 1
    assert item["undecidable_by_reason"]["reference_false_alarm"] == 2
    assert item["detection_rate_single_round_mean"] == 0.25
    assert [row["defects_found"] for row in item["per_seed"]] == [0, 1]


@pytest.mark.parametrize("field,value", [("budget_cycles", 31), ("total_cycles", 33)])
def test_different_stimulus_budget_cannot_be_called_matched(field, value):
    source = fixture_source()
    source["runs"][0][field] = value
    with pytest.raises(ValueError, match="budget mismatch"):
        build_summary(source, MANIFEST, rounds=2)


def test_duplicate_rows_and_missing_reference_cannot_silently_score():
    source = fixture_source()
    source["runs"].append(deepcopy(source["runs"][0]))
    with pytest.raises(ValueError, match="Duplicate archived run"):
        build_summary(source, MANIFEST, rounds=2)
    source = fixture_source()
    source["runs"].pop(0)
    with pytest.raises(ValueError, match="Missing reference row"):
        build_summary(source, MANIFEST, rounds=2)


def test_archived_failure_is_undecidable_and_keeps_its_denominator():
    source = fixture_source()
    row = next(row for row in source["runs"] if row["strategy"] == "online_ai" and row["seed"] == 0 and row["variant"] == "a")
    row.update(status="compile_failed", total_cycles=0, defects_found=False, check_count=0)
    item = build_summary(source, MANIFEST, rounds=2)["summary"]["online_ai"]
    assert item["defects_total"] == 2
    assert item["undecidable_by_reason"]["compile_failed"] == 1
    assert item["detection_rate_single_round_mean"] == 0.25


def test_committed_snapshot_reproduces_report_without_private_archive():
    directory = ROOT / "docs/experiment/matched-budget-2026-10-04"
    source = json.loads((directory / "selected_runs.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    actual = build_summary(source, manifest, rounds=5)
    assert actual["summary"] == expected["summary"]
    assert actual["budget_audit"] == expected["budget_audit"]
    assert actual["online_vs_random"] == expected["online_vs_random"]
    assert actual["summary"]["online_ai"]["defects_found"] == 61
    assert actual["summary"]["online_ai"]["request_usage"]["requests_without_usage"] == 2
    assert actual["budget_audit"]["rows_with_matching_executed_cycles"] == 1280
