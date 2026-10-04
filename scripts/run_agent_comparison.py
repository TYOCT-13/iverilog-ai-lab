"""Pre-registered bounded Agent pilot. Dry-run by default; never discard failures."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Literal
from urllib.parse import urlsplit

from iverilog_ai.ai.agent import AgentLimits, run_verification_agent
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.strategy_scoring import budget_for, normalize_vectors, plan_cycles, classify_undecidable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_strategy_experiment import _fixed, _plan_with_vectors
CASES = ("sync_fifo", "uart_tx", "spi_master", "handshake_stage")
STRATEGIES = ("fixed", "random", "single", "feedback", "no_feedback")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def preregister(cases=CASES, strategies=STRATEGIES, repeats=1, defects_per_case=2) -> dict:
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text(encoding="utf-8"))
    targets = []
    for case in cases:
        if case not in CASES:
            raise ValueError("case outside registered pilot families")
        targets.append({"case": case, "variant": "reference", "rtl": f"rtl/{case}.v"})
        defects = [d for d in manifest["defects"] if d["type"] == case][:defects_per_case]
        targets.extend({"case": case, "variant": d["id"], "rtl": d["file"]} for d in defects)
    rows = [{**target, "strategy": strategy, "seed": seed, "budget_cycles": budget_for(target["case"]).cycles,
             "status": "not_started", "detected": False, "requests": 0, "rounds": []}
            for target in targets for seed in range(repeats) for strategy in strategies]
    inputs = {"benchmarks/manifest.json", "scripts/run_agent_comparison.py", "scripts/run_strategy_experiment.py",
              "docs/experiment/agent_comparison_protocol.md"}
    inputs.update(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "src/iverilog_ai").rglob("*.py"))
    for target in targets:
        inputs.update([target["rtl"], f"rtl/{target['case']}.v", f"examples/{target['case']}_contract.json",
                       "spec/common_cases.md"])
    return {"schema": "agent-comparison-v1", "scope": "pilot_not_human_trial", "rows": rows,
            "theoretical_requests": sum(1 if r["strategy"] == "single" else 3 if r["strategy"] in {"feedback", "no_feedback"} else 0 for r in rows),
            "code_and_input_sha256": {p: sha(ROOT / p) for p in sorted(inputs)},
            "protocol": {"reference_replay": "every executed plan; any alarm invalidates target sample",
                         "cycles": "cumulative reruns, excluding reset and separately reported reference audit",
                         "denominator": "all registered defects including incomplete samples",
                         "single": "same decision schema and prompt, one API proposal and one simulation",
                         "no_feedback": "same loop and budget, observation withheld; failure stop retained",
                         "selection": "first N manifest defects, selected before execution"}}


def baseline_plan(case: str, strategy: str, seed: int, contract: DutContract, cycles: int) -> TestPlan:
    if strategy == "fixed":
        vectors = [{**v, "expected": {}} for v in _fixed(case)]
    else:
        rng = random.Random(seed)
        excluded = {contract.clock.signal if contract.clock else "", contract.reset.signal if contract.reset else ""}
        inputs = [p for p in contract.ports if p.direction.value == "input" and p.name not in excluded]
        vectors = [{"name": f"random_{i}", "inputs": {p.name: rng.randrange(1 << p.width) for p in inputs},
                    "cycles": 1, "expected": {}} for i in range(cycles)]
    plan = TestPlan.model_validate({"design": case, "objective": "Check contract behavior and protocol boundaries", "vectors": vectors,
                                    "reset": contract.reset.to_dict() if contract.reset else {}})
    return _plan_with_vectors(plan, normalize_vectors(vectors, cycles).vectors)


def observation(result) -> dict:
    sim = result.simulation
    return {"status": sim.status.value, "checks": len(sim.records), "failures": len(sim.failures),
            "expectation_source": sim.config.get("oracle", {}).get("expectation_source"),
            "pipeline_result": str(result.artifacts.get("pipeline_result", ""))}


def classify(row: dict) -> tuple[str, bool]:
    rounds = row["rounds"]
    if not rounds:
        return row.get("stop_reason", "no_records"), False
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
    if not alarm and row.get("stop_reason") in {"policy_error", "output_truncated", "execution_error", "input_changed", "interrupted", "insufficient_evidence"}:
        return row["stop_reason"], False
    return ("reference_false_alarm" if row["variant"] == "reference" and alarm else "detected" if alarm else "not_detected"), bool(alarm and row["variant"] != "reference")


def summarize(rows: list[dict]) -> dict:
    result = {}
    for strategy in dict.fromkeys(r["strategy"] for r in rows):
        selected = [r for r in rows if r["strategy"] == strategy]
        defects = [r for r in selected if r["variant"] != "reference"]
        unique = {(r["case"], r["variant"]) for r in defects}
        found = {(r["case"], r["variant"]) for r in defects if r["detected"]}
        result[strategy] = {"registered_defect_samples": len(defects), "detected_samples": sum(r["detected"] for r in defects),
                            "unique_defects": len(unique), "unique_detected": len(found),
                            "incomplete_or_undecidable": sum(r["status"] not in {"detected", "not_detected"} for r in defects),
                            "reference_false_alarm_samples": sum(r["status"] == "reference_false_alarm" for r in selected),
                            "requests": sum(r["requests"] for r in selected)}
    return result


def execute(registration: dict, output: Path, *, endpoint="", model="", key="", request_cap=0,
            max_output_tokens=4096, wire_api: Literal["chat_completions", "responses"] = "chat_completions",
            iverilog="iverilog", vvp="vvp", provider_factory=None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    write(output / "preregistration.json", registration)
    settings = {"preregistration_sha256": sha(output / "preregistration.json"), "wire_api": wire_api,
                "endpoint_host": urlsplit(endpoint).hostname, "model": model,
                "max_output_tokens": max_output_tokens, "total_request_cap": request_cap,
                "request_timeout_seconds": 60, "stream": False, "iverilog": iverilog, "vvp": vvp}
    write(output / "run_settings.json", settings)
    report = {"preregistration_sha256": sha(output / "preregistration.json"),
              "run_settings_sha256": sha(output / "run_settings.json"), "wire_api": wire_api,
              "started_at": datetime.now(timezone.utc).isoformat(), "endpoint_host": urlsplit(endpoint).hostname,
              "model": model, "total_request_cap": request_cap, "max_output_tokens": max_output_tokens,
              "cost_currency": None, "cost_missing_reason": "provider billing not supplied; usage is not currency",
              "rows": json.loads(json.dumps(registration["rows"])), "requests_attempted": 0,
              "record_kind": "test_provider" if provider_factory else "api_and_local_simulation"}
    def save():
        report["summary"] = summarize(report["rows"])
        write(output / "results.json", report)
    save()
    runner = VerificationPipeline()
    options = {"allowed_roots": (ROOT, output.resolve()), "iverilog_path": iverilog, "vvp_path": vvp, "timeout_seconds": 30}
    try:
        for index, row in enumerate(report["rows"]):
            started = time.monotonic()
            provider = None
            work = output / f"sample-{index:03d}"
            work.mkdir()
            try:
                case = row["case"]
                contract = DutContract.from_dict(json.loads((ROOT / f"examples/{case}_contract.json").read_text()))
                def audit(round_row):
                    plan = TestPlan.model_validate(round_row["plan"])
                    cycles = plan_cycles(plan.model_dump(mode="json")["vectors"])
                    entry = {"round": round_row["round"], "plan": plan.model_dump(mode="json"),
                             "actual": round_row["observation"], "cycles": cycles,
                             "reference": {"status": "not_completed", "checks": 0, "failures": 0,
                                           "expectation_source": None}}
                    row["rounds"].append(entry)
                    row["reference_audit_cycles_attempted"] = row.get("reference_audit_cycles_attempted", 0) + cycles
                    save()
                    reference = runner.run(plan, contract, ROOT / f"rtl/{case}.v", work / f"audit-{round_row['round']}", **options)
                    entry["reference"] = observation(reference)
                    row["reference_audit_cycles"] = row.get("reference_audit_cycles", 0) + cycles
                    save()
                if row["strategy"] in {"fixed", "random"}:
                    plan = baseline_plan(case, row["strategy"], row["seed"], contract, row["budget_cycles"])
                    actual = runner.run(plan, contract, ROOT / row["rtl"], work / "run", **options)
                    audit({"round": 1, "plan": plan.model_dump(mode="json"), "observation": observation(actual)})
                    row["stop_reason"] = "single_run"
                else:
                    remaining = request_cap - report["requests_attempted"]
                    if remaining <= 0:
                        row["status"] = "global_request_budget"
                        continue
                    count = min(1 if row["strategy"] == "single" else 3, remaining)
                    provider = provider_factory(count) if provider_factory else OpenAICompatibleProvider(
                        endpoint=endpoint, model=model, api_key=key, allow_network=True, store=False,
                        reasoning_effort=None, timeout=60, stream=False, request_limit=count, wire_api=wire_api,
                        max_output_tokens=max_output_tokens, force_output_limit=True)
                    result = run_verification_agent(provider=provider, contract=contract, rtl_path=ROOT / row["rtl"],
                        output_dir=work / "agent", objective="Check contract behavior and protocol boundaries",
                        specification="\n".join(line for line in (ROOT / "spec/common_cases.md").read_text(encoding="utf-8").splitlines() if f"`{case}.v`" in line),
                        include_feedback=row["strategy"] != "no_feedback",
                        limits=AgentLimits(max_rounds=1 if row["strategy"] == "single" else 3, max_requests=count,
                                           max_total_cycles=row["budget_cycles"], max_output_tokens=max_output_tokens),
                        execution_options=options, on_round=audit)
                    row["stop_reason"] = result.stop_reason
                    row["record_kind"] = result.trajectory["record_kind"]
                    row["agent_stimulus_cycles"] = result.trajectory["stimulus_cycles_executed"]
                    row["trajectory"] = str(result.trajectory_path)
                    row["usage_by_decision"] = [{"request_id": f"{index}:{n}", "usage": d.get("usage")}
                                                for n, d in enumerate(result.trajectory["decisions"])]
                    row["requests"] = result.trajectory["requests_attempted"]
                row["status"], row["detected"] = classify(row)
            except KeyboardInterrupt:
                row["status"] = "interrupted"
                raise
            except Exception as exc:
                row["status"] = "execution_error"
                row["error_type"] = type(exc).__name__
            finally:
                trace_path = work / "agent/agent_trajectory.json"
                if trace_path.is_file():
                    try:
                        trace = json.loads(trace_path.read_text(encoding="utf-8"))
                        row["agent_stimulus_cycles"] = trace["stimulus_cycles_executed"]
                        row["trajectory"] = str(trace_path)
                        row["requests"] = trace["requests_attempted"]
                        row["stop_reason"] = trace["stop_reason"]
                        row["usage_by_decision"] = [{"request_id": f"{index}:{n}", "usage": d.get("usage")}
                                                    for n, d in enumerate(trace["decisions"])]
                    except (OSError, ValueError, KeyError) as exc:
                        row["trace_recovery_error_type"] = type(exc).__name__
                if provider is not None:
                    row["requests"] = int(getattr(provider, "request_count", row["requests"]))
                report["requests_attempted"] += row["requests"]
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                row["audited_round_search_cycles"] = sum(r["cycles"] for r in row["rounds"])
                row["search_cycles"] = row.get("agent_stimulus_cycles", row["audited_round_search_cycles"])
                row["search_cycle_accounting_gap"] = row["search_cycles"] - row["audited_round_search_cycles"]
                row.setdefault("reference_audit_cycles", 0)
                row["requests_without_usage"] = max(0, row["requests"] - sum(bool(d["usage"]) for d in row.get("usage_by_decision", [])))
                save()
                print(json.dumps({k: row[k] for k in ("case", "variant", "strategy", "status", "requests")}), flush=True)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["changed_inputs_at_finish"] = [p for p, digest in registration["code_and_input_sha256"].items()
                                               if not (ROOT / p).is_file() or sha(ROOT / p) != digest]
        save()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--defects-per-case", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--total-request-cap", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, choices=range(128, 8193), default=4096)
    parser.add_argument("--endpoint", default=os.getenv("IVERILOG_AI_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("IVERILOG_AI_MODEL", ""))
    parser.add_argument("--wire-api", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".iverilog-ai/agent-comparison-pilot")
    parser.add_argument("--iverilog", default="D:/iverilog/bin/iverilog.exe")
    parser.add_argument("--vvp", default="D:/iverilog/bin/vvp.exe")
    args = parser.parse_args(argv)
    try:
        if args.total_request_cap < 0:
            raise ValueError("negative request cap")
        reg = preregister(args.cases, args.strategies, args.repeats, args.defects_per_case)
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "samples": len(reg["rows"]),
                          "theoretical_requests": reg["theoretical_requests"], "authorized_request_cap": args.total_request_cap,
                          "wire_api": args.wire_api, "endpoint_host": urlsplit(args.endpoint).hostname,
                          "model": args.model, "max_output_tokens": args.max_output_tokens}))
        if not args.execute:
            return 0
        key = ""
        if reg["theoretical_requests"] and args.total_request_cap:
            url = urlsplit(args.endpoint)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or not args.model:
                raise ValueError("HTTPS endpoint and model required")
            key = read_key_file(args.api_key_file) if args.api_key_file else os.getenv("IVERILOG_AI_API_KEY", "")
            if not key:
                raise ValueError("credential missing")
        execute(reg, args.output_dir, endpoint=args.endpoint, model=args.model, key=key,
                request_cap=args.total_request_cap, max_output_tokens=args.max_output_tokens,
                wire_api=args.wire_api, iverilog=args.iverilog, vvp=args.vvp)
        return 0
    except Exception as exc:
        print(f"Comparison failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
