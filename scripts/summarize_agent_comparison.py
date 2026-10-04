"""Summarize registered comparison samples without dropping failures or repeats."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any


from iverilog_ai.core.strategy_scoring import classify_undecidable

def classify(row: dict) -> tuple[str, bool]:
    rounds = row["rounds"]
    token_errors = {d.get("error_type") for d in row.get("usage_by_decision", [])}
    token_status = ("token_budget" if "TokenBudgetExceeded" in token_errors
                    else "token_accounting_error" if "TokenUsageViolation" in token_errors else None)
    if not rounds:
        return token_status or row.get("stop_reason", "no_records"), False
    for item in rounds:
        ref = item["reference"]
        if ref["failures"]:
            return "reference_false_alarm", False
        if ref["status"] not in {"passed", "passed_with_warnings"} or not ref["checks"] or ref["expectation_source"] != "reference_model":
            return "reference_unverified", False
        actual = item["actual"]
        reason = classify_undecidable(actual["status"], check_count=actual["checks"])
        if reason or actual["status"] not in {"passed", "passed_with_warnings"}:
            return reason or "execution_failed", False
        if actual["expectation_source"] != "reference_model":
            return "unverified_oracle", False
    alarm = any(r["actual"]["failures"] for r in rounds)
    if not alarm and token_status:
        return token_status, False
    if not alarm and row.get("stop_reason") in {"policy_error", "decision_format_error", "output_truncated", "execution_error", "input_changed", "interrupted", "insufficient_evidence"}:
        return row["stop_reason"], False
    return ("reference_false_alarm" if row["variant"] == "reference" and alarm else "detected" if alarm else "not_detected"), bool(alarm and row["variant"] != "reference")


def sample_key(row: dict) -> tuple:
    return row["case"], row["variant"], row["strategy"], row["seed"]


def freeze_pipeline_evidence(path: str) -> dict:
    """Record existing immutable result, inputs and tool logs without rewriting them."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    files = {"pipeline_result": path}
    for key in ("testplan", "dut_contract", "testbench", "result_json"):
        files[key] = payload["artifacts"][key]
    if payload["artifacts"].get("reference_samples"):
        for key in ("authoritative_plan", "reference_samples"):
            if payload["artifacts"].get(key):
                files[key] = payload["artifacts"][key]
    for key in ("compile_stdout", "compile_stderr", "run_stdout", "run_stderr"):
        files[key] = payload["simulation"]["artifacts"][key]
    return {key: {"path": str(value), "sha256": hashlib.sha256(Path(value).read_bytes()).hexdigest()}
            for key, value in files.items()}


def verify_per_cycle_evidence(raw: dict, frozen: dict, registration: dict, case: str) -> None:
    """Require the scheduled reference values to match actual RESULT records."""
    sim = raw["simulation"]
    oracle = sim["config"]["oracle"]
    if sim["config"].get("reference_sampling") != "per_cycle" or oracle.get("reference_sampling") != "per_cycle":
        raise ValueError("reference_sampling_mismatch")
    packet = json.loads(Path(frozen["reference_samples"]["path"]).read_text(encoding="utf-8"))
    metadata = oracle["reference_samples"]
    if metadata.get("sha256") != frozen["reference_samples"]["sha256"] or {
            key: value for key, value in metadata.items() if key != "sha256"} != {
            key: value for key, value in packet.items() if key != "samples"}:
        raise ValueError("reference_sample_metadata_mismatch")
    contract_hash = hashlib.sha256(json.dumps(raw["contract"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if contract_hash != registration["contract_profile_sha256"][case]:
        raise ValueError("registered_contract_mismatch")
    if json.loads(Path(frozen["testplan"]["path"]).read_text(encoding="utf-8")) != raw["plan"] or \
            json.loads(Path(frozen["dut_contract"]["path"]).read_text(encoding="utf-8")) != raw["contract"]:
        raise ValueError("saved_input_payload_mismatch")
    bindings = {"plan_sha256": frozen["testplan"]["sha256"],
                "contract_sha256": frozen["dut_contract"]["sha256"],
                "testbench_sha256": frozen["testbench"]["sha256"],
                "rtl_sha256": sim["config"]["rtl_sha256"],
                "reference_model_sha256": registration["code_and_input_sha256"]["src/iverilog_ai/core/reference_model.py"]}
    if packet.get("provenance") != bindings or packet.get("source") != "independent_reference_model" \
            or packet.get("status") != "generated" or packet.get("reference_sampling") != "per_cycle":
        raise ValueError("reference_sample_provenance_mismatch")
    outputs = {p["name"]: p["width"] for p in raw["contract"]["ports"] if p["direction"] == "output"}
    expected = {}
    cycle = 0
    for vector in raw["plan"]["vectors"]:
        for _ in range(vector.get("cycles", 1)):
            sample = packet["samples"][cycle]
            if sample["cycle"] != cycle or sample["test_id"] != vector["name"] or sample["sample_phase"] != "after" \
                    or set(sample["expected"]) != set(outputs):
                raise ValueError("reference_sample_schedule_mismatch")
            for signal, width in outputs.items():
                bits = sample["expected"][signal]
                if not isinstance(bits, str) or len(bits) != width or set(bits) - {"0", "1"}:
                    raise ValueError("reference_sample_width_mismatch")
                expected[(vector["name"], cycle, signal)] = bits
            cycle += 1
    if len(packet["samples"]) != cycle or packet.get("expected_cycles") != cycle \
            or packet.get("expected_checks") != len(expected) or sim["summary"].get("checks") != len(expected):
        raise ValueError("reference_sample_check_count_mismatch")
    records = {(r.get("test_id"), r.get("cycle"), r.get("signal")): r for r in sim["records"]}
    if len(records) != len(sim["records"]) or set(records) != set(expected):
        raise ValueError("actual_check_schedule_mismatch")
    for key, bits in expected.items():
        record = records[key]
        if record.get("expected") != bits or record.get("ok") is not (record.get("actual") == bits):
            raise ValueError("actual_check_value_mismatch")
    from iverilog_ai.core.models import FailureRecord, ResultRecord
    stdout = Path(frozen["run_stdout"]["path"]).read_text(encoding="utf-8")
    logged_records = [ResultRecord.from_dict(json.loads(line[len("IVERILOG_AI_RESULT"):].strip()))
                      for line in stdout.splitlines() if line.startswith("IVERILOG_AI_RESULT")]
    logged = [record.to_dict() for record in logged_records]
    if logged != sim["records"]:
        raise ValueError("actual_records_disagree_with_stdout")
    failures = [FailureRecord.from_result(record).to_dict() for record in logged_records if not record.ok]
    if failures != sim["failures"] or sim["summary"].get("failures") != len(failures):
        raise ValueError("failures_disagree_with_actual_records")
    executed = json.loads(Path(frozen["result_json"]["path"]).read_text(encoding="utf-8"))
    if frozen["testbench"]["sha256"] != sim["config"].get("testbench_sha256") \
            or sim["config"].get("testbench_sha256") != executed["config"].get("testbench_sha256") \
            or sim["config"].get("rtl_sha256") != executed["config"].get("rtl_sha256"):
        raise ValueError("executed_source_hash_mismatch")
    for execution_field in ("run_id", "status", "compile", "run", "records", "failures", "summary", "started_at", "finished_at"):
        if executed.get(execution_field) != sim.get(execution_field):
            raise ValueError("pipeline_disagrees_with_execution_result")
    for process in (sim["compile"], sim["run"]):
        if process is None or process.get("status") != "passed" or process.get("returncode") != 0 \
                or process.get("timed_out") or process.get("output_truncated") or process.get("error"):
            raise ValueError("actual_execution_incomplete")


def verify_frozen_inputs(report: dict, registration: dict, evidence_root: Path | None) -> bool:
    if evidence_root is None:
        return False
    try:
        entry = report["frozen_inputs"]
        manifest_path = (evidence_root / entry["path"]).resolve(strict=True)
        if not manifest_path.is_relative_to(evidence_root.resolve()) or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != entry["sha256"]:
            return False
        files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        if len(files) != entry["file_count"] or len({item["path"] for item in files}) != len(files) \
                or {item["path"]: item["sha256"] for item in files} != registration["code_and_input_sha256"]:
            return False
        for item in files:
            path = (evidence_root / item["copy"]).resolve(strict=True)
            if not path.is_relative_to(evidence_root.resolve()):
                return False
            raw = path.read_bytes()
            if len(raw) != item["size_bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                return False
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False


def verify_row_evidence(row: dict, registration: dict | None) -> dict:
    """Never let a stored boolean or missing simulation evidence increase detection."""
    result = dict(row)
    result["reported_status"] = row["status"]
    result["reported_detected"] = row.get("detected")
    result["detected"] = False
    result["evidence_verified"] = False
    if not row.get("rounds"):
        if row.get("detected") or row["status"] in {"detected", "not_detected"}:
            result.update(status="evidence_unknown", evidence_error="missing_rounds")
        return result
    try:
        if registration is None or not registration.get("code_and_input_sha256"):
            raise ValueError("missing_preregistration_input_hashes")
        if registration.get("profile") == "v3" and row["strategy"] not in {"fixed", "random", "protocol_random"}:
            trace_path = Path(row["trajectory"])
            trace_bytes = trace_path.read_bytes()
            if hashlib.sha256(trace_bytes).hexdigest() != row.get("trajectory_sha256"):
                raise ValueError("trajectory_hash_mismatch")
            trace = json.loads(trace_bytes)
            if trace.get("agent_plan_mode") != "independent" or trace.get("reference_sampling") != "per_cycle":
                raise ValueError("agent_execution_mode_mismatch")
            if trace.get("stimulus_cycles_executed") != sum(entry["cycles"] for entry in row["rounds"]) \
                    or [entry["plan"] for entry in trace["rounds"]] != [entry["plan"] for entry in row["rounds"]]:
                raise ValueError("agent_episode_accounting_mismatch")
        total_cycles = 0
        for entry in row["rounds"]:
            cycles = sum(v.get("cycles", 1) for v in entry["plan"]["vectors"])
            total_cycles += cycles
            if cycles != entry["cycles"] or total_cycles > row["budget_cycles"]:
                raise ValueError("round_cycle_budget_mismatch")
            for side in ("actual", "reference"):
                observed = entry[side]
                frozen = observed.get("evidence_files")
                if not frozen or freeze_pipeline_evidence(observed["pipeline_result"]) != frozen:
                    raise ValueError("missing_or_changed_evidence_files")
                raw = json.loads(Path(observed["pipeline_result"]).read_text(encoding="utf-8"))
                sim = raw["simulation"]
                expected_path = row["rtl"] if side == "actual" else row.get("reference_rtl", f"rtl/{row['case']}.v")
                if sim["config"]["rtl_sha256"] != registration["code_and_input_sha256"][expected_path]:
                    raise ValueError("rtl_hash_mismatch")
                if raw["plan"] != entry["plan"]:
                    raise ValueError("round_plan_mismatch")
                if registration.get("profile") == "v3":
                    verify_per_cycle_evidence(raw, frozen, registration, row["case"])
                actual = {"status": sim["status"], "checks": sim["summary"].get("checks", 0),
                          "failures": len(sim["failures"]), "records": len(sim["records"]),
                          "failure_cycles": [f["cycle"] for f in sim["failures"] if isinstance(f.get("cycle"), int)],
                          "expectation_source": sim["config"].get("oracle", {}).get("expectation_source")}
                if any(observed.get(k) != v for k, v in actual.items()):
                    raise ValueError("observation_disagrees_with_result")
        status, detected = classify(row)
        if status != row["status"]:
            raise ValueError("status_disagrees_with_evidence")
        result.update(status=status, detected=detected, evidence_verified=True)
        result["first_detection_elapsed_seconds"] = None
        result["first_detection_available_elapsed_seconds"] = None
        result["first_detection_cycle"] = None
        result["first_detection_search_budget"] = None
        previous = 0
        if detected:
            for entry in row["rounds"]:
                if entry["actual"]["failures"]:
                    cycles = entry["actual"]["failure_cycles"]
                    cycle = min(cycles) if cycles else None
                    result["first_detection_cycle"] = cycle
                    result["first_detection_search_budget"] = previous + cycle + 1 if cycle is not None else None
                    result["first_detection_available_elapsed_seconds"] = entry.get("result_available_elapsed_seconds")
                    break
                previous += entry["cycles"]
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        result.update(status="evidence_unknown", evidence_error=str(exc), evidence_verified=False)
    return result


def registered_rows(report: dict, registration: dict | None = None) -> list[dict]:
    observed = {}
    for row in report["rows"]:
        key = sample_key(row)
        if key in observed:
            raise ValueError("duplicate result sample")
        observed[key] = row
    if registration is None:
        return list(observed.values())
    keys = [sample_key(row) for row in registration["rows"]]
    if len(set(keys)) != len(keys) or set(observed) - set(keys):
        raise ValueError("registration/result sample mismatch")
    mutable_initial = {"status", "detected", "requests", "rounds", "first_detection_cycle",
                       "first_detection_search_budget", "first_detection_elapsed_seconds"}
    for registered in registration["rows"]:
        current = observed.get(sample_key(registered))
        if current is not None and any(key not in mutable_initial and current.get(key) != value
                                       for key, value in registered.items()):
            raise ValueError("immutable preregistration row field mismatch")
    return [{**row, **observed.get(sample_key(row), {}),
             **({"status": "missing_result", "detected": False} if sample_key(row) not in observed else {})}
            for row in registration["rows"]]


def summarize_rows(rows: list[dict]) -> dict:
    safe_rows = []
    for original in rows:
        row = dict(original)
        try:
            status, detected = classify(row)
            row["detected"] = detected and status == row["status"]
        except (KeyError, TypeError, ValueError):
            row["detected"] = False
        safe_rows.append(row)
    rows = safe_rows
    result = {}
    for strategy in dict.fromkeys(r["strategy"] for r in rows):
        selected = [r for r in rows if r["strategy"] == strategy]
        defects = [r for r in selected if r["variant"] != "reference"]
        unique = {(r["case"], r["variant"]) for r in defects}
        found = {(r["case"], r["variant"]) for r in defects if r.get("detected", False)}
        repetitions = []
        for seed in sorted({r["seed"] for r in selected}):
            part = [r for r in defects if r["seed"] == seed]
            n = sum(bool(r.get("detected")) for r in part)
            repetitions.append({"repeat": seed, "registered_defects": len(part), "detected": n,
                "detection_rate": n / len(part) if part else None,
                "incomplete_or_undecidable": sum(r["status"] not in {"detected", "not_detected"} for r in part)})
        rates = [r["detection_rate"] for r in repetitions if r["detection_rate"] is not None]
        usage: Counter = Counter()
        decisions: dict[str, Any] = {}
        for row in selected:
            for item in row.get("usage_by_decision", []):
                key = item["request_id"]
                if key in decisions:
                    raise ValueError("duplicate request usage identity")
                decisions[key] = item.get("usage")
                for field, value in (item.get("usage") or {}).items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[field] += value
        requests = sum(r.get("requests", 0) for r in selected)
        result[strategy] = {
            "registered_defect_samples": len(defects), "detected_samples": sum(bool(r.get("detected")) for r in defects),
            "unique_defects": len(unique), "unique_detected": len(found),
            "unique_union_rate": len(found) / len(unique) if unique else None,
            "incomplete_or_undecidable": sum(r["status"] not in {"detected", "not_detected"} for r in defects),
            "reference_false_alarm_samples": sum(r["status"] == "reference_false_alarm" for r in selected),
            "reference_target_false_alarms": sum(r["status"] == "reference_false_alarm" and r["variant"] == "reference" for r in selected),
            "variant_reference_audit_rejections": sum(r["status"] == "reference_false_alarm" and r["variant"] != "reference" for r in selected),
            "status_counts": dict(Counter(r["status"] for r in selected)), "per_repeat": repetitions,
            "repeat_detection_rate_mean": mean(rates) if rates else None,
            "repeat_detection_rate_min": min(rates) if rates else None,
            "repeat_detection_rate_max": max(rates) if rates else None,
            "requests": requests, "usage_numeric_sum": dict(usage),
            "requests_with_usage": sum(bool(v) for v in decisions.values()),
            "requests_without_usage": max(0, requests - sum(bool(v) for v in decisions.values())),
            "search_cycles_recorded": sum(r.get("search_cycles", 0) for r in selected),
            "reference_audit_cycles_recorded": sum(r.get("reference_audit_cycles", 0) for r in selected),
            "reference_audit_cycles_attempted": sum(r.get("reference_audit_cycles_attempted", 0) for r in selected),
            "checks_recorded": sum(round_.get("actual", {}).get("checks", 0) or 0 for r in selected for round_ in r.get("rounds", [])),
            "elapsed_seconds_recorded": sum(r.get("elapsed_seconds", 0) for r in selected),
            "missing_elapsed_samples": sum("elapsed_seconds" not in r for r in selected),
            "first_detection": [{"case": r["case"], "variant": r["variant"], "repeat": r["seed"],
                                 "cycle": r.get("first_detection_cycle"), "search_budget": r.get("first_detection_search_budget"),
                                 "elapsed_seconds": None,
                                 "result_available_elapsed_seconds": r.get("first_detection_available_elapsed_seconds")}
                                for r in defects if r.get("detected")],
        }
    return result


def build_summary(report: dict, registration: dict | None = None, *, evidence_root: Path | None = None) -> dict:
    if registration is not None and report.get("profile", "legacy") != registration.get("profile", "legacy"):
        raise ValueError("comparison_profile_mismatch")
    rows = [verify_row_evidence(r, registration) for r in registered_rows(report, registration)]
    pairs = []
    lookup = {sample_key(r): r for r in rows}
    for row in rows:
        if row["strategy"] != "feedback" or row["variant"] == "reference":
            continue
        other = lookup.get((row["case"], row["variant"], "feedback_no_coverage", row["seed"]))
        if other:
            pairs.append({"case": row["case"], "variant": row["variant"], "repeat": row["seed"],
                          "feedback_status": row["status"], "no_coverage_status": other["status"],
                          "feedback_detected": bool(row.get("detected")), "no_coverage_detected": bool(other.get("detected")),
                          "feedback_requests": row.get("requests", 0), "no_coverage_requests": other.get("requests", 0),
                          "feedback_search_cycles": row.get("search_cycles"), "no_coverage_search_cycles": other.get("search_cycles"),
                          "feedback_first_detection_budget": row.get("first_detection_search_budget"),
                          "no_coverage_first_detection_budget": other.get("first_detection_search_budget"),
                          "feedback_coverage_by_round": [r.get("actual", {}).get("functional_coverage") for r in row.get("rounds", [])],
                          "no_coverage_coverage_by_round": [r.get("actual", {}).get("functional_coverage") for r in other.get("rounds", [])]})
    frozen_ok = (verify_frozen_inputs(report, registration, evidence_root) if registration and report.get("profile") == "v3" else None)
    return {"schema": "agent-comparison-summary-v2", "profile": report.get("profile", "legacy"),
            "frozen_input_snapshot_verified": frozen_ok,
            "denominator_source": "preregistration" if registration else "results_rows_only",
            "registered_rows": len(rows), "finished_at": report.get("finished_at"),
            "changed_inputs_at_finish": report.get("changed_inputs_at_finish"),
            "eligible_for_frozen_comparison": bool(report.get("finished_at")) and report.get("changed_inputs_at_finish") == []
                and registration is not None
                and frozen_ok is not False
                and all(r.get("evidence_verified") for r in rows)
                and all(r["status"] not in {"not_started", "interrupted", "missing_result", "global_request_budget", "evidence_unknown", "token_budget", "token_accounting_error"} for r in rows),
            "strategies": summarize_rows(rows), "coverage_ablation_pairs": pairs,
            "coverage_ablation_note": "same registered tasks, independent stochastic API proposals; not paired model RNG",
            "scope": (registration.get("scope", "development_modules_not_independent_holdout")
                      if registration else "development_modules_not_independent_holdout"), "cost_currency": None,
            "rows": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError("summary output already exists")
    report = json.loads(args.results.read_text(encoding="utf-8"))
    if report.get("run_settings_sha256"):
        settings_path = args.results.parent / "run_settings.json"
        if not settings_path.is_file() or hashlib.sha256(settings_path.read_bytes()).hexdigest() != report["run_settings_sha256"]:
            raise ValueError("run settings hash mismatch")
    registration_path = args.registration or args.results.parent / "preregistration.json"
    raw = registration_path.read_bytes()
    if report.get("preregistration_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("registration hash mismatch")
    result = build_summary(report, json.loads(raw), evidence_root=args.results.parent)
    result["source_results_sha256"] = hashlib.sha256(args.results.read_bytes()).hexdigest()
    result["source_preregistration_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"rows": result["registered_rows"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
