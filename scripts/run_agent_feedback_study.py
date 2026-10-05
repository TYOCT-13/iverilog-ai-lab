"""One complete 432-task v8 comparison on eight previously exposed modules."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iverilog_ai.ai.agent import PROMPT_VERSION, SYSTEM_PROMPT
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import reference_sampling_profile
from scripts.agent_budget_study_baselines import (CASES, CYCLE_BUDGETS, DEVELOPMENT_CASES,
    PRIOR_INTERNAL_CASES, MODULE_HOLDOUT_CASES, budget_baseline)
from scripts.agent_token_budget import BudgetedProvider, TokenBudget
from scripts import run_agent_study_1m as parent
from scripts.run_agent_comparison import execute, registered_source_path, sha, write
from scripts.summarize_agent_comparison import build_summary

CONFIG = ROOT / "spec/agent_feedback_study_1m.json"
PLAN = ROOT / "docs/experiment/agent_feedback_study_plan_2026-10-05.md"
SPECS = ROOT / "spec/agent_budget_study_20261005"
OUTPUT = ROOT / ".iverilog-ai/agent-feedback-study-live-20261005"
PRIOR_REGISTRATION = ROOT / "docs/experiment/agent-budget-study-live-2026-10-05/preregistration.json"
PRIOR_REGISTRATION_SHA256 = "0ae79dbc7eba99c8de665f3e11c4af0c5f87a886057d6b04a4b7290c27416435"
STRATEGIES = ("fixed", "random", "protocol_random", "single", "feedback", "no_feedback")
COHORTS = {"development": list(DEVELOPMENT_CASES), "previous_internal_modules": list(PRIOR_INTERNAL_CASES),
           "previous_module_set_holdout": list(MODULE_HOLDOUT_CASES)}
TRANSPORT = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
    "wire_api": "chat_completions", "thinking_mode": "disabled", "stream": False,
    "timeout_seconds": 60, "automatic_transport_retry": False}


def previous_batch_accounting() -> list[dict]:
    """Refuse overlap with the previous registered live batches, without keys."""
    records = []
    for name in ("agent-study-1m-live-20261005", "agent-recovery-study-live-20261005",
                 "agent-holdout-study-live-20261005", "agent-budget-study-live-20261005"):
        folder = ROOT / ".iverilog-ai" / name
        journal, report = folder / "token_budget.json", folder / "results.json"
        if not folder.exists():
            records.append({"batch": name, "local_private_records": "absent",
                            "historical_usage_charged_to_this_batch": False})
            continue
        if not journal.is_file() or not report.is_file():
            raise ValueError("previous local batch has incomplete accounting")
        data = json.loads(journal.read_text(encoding="utf-8"))
        result = json.loads(report.read_text(encoding="utf-8"))
        pending = sum(item.get("status") == "pending" for item in data["records"])
        if pending or not result.get("finished_at"):
            raise ValueError("previous registered batch is pending or unfinished")
        records.append({"batch": name, "finished_at": result["finished_at"],
            "pending_requests": pending, "tokens": data["totals"],
            "historical_usage_charged_to_this_batch": False})
    return records


def _bind_unchanged_v7_scope(reg: dict) -> None:
    """Use only the old *preregistration*, never historical results or witnesses."""
    if sha(PRIOR_REGISTRATION) != PRIOR_REGISTRATION_SHA256:
        raise ValueError("previous preregistered scope bytes changed")
    previous = json.loads(PRIOR_REGISTRATION.read_text(encoding="utf-8"))
    fields = ("case", "variant", "rtl", "contract_path", "reference_rtl",
              "strategy", "seed", "budget_cycles")
    identity = lambda row: tuple(row.get(key) for key in fields)
    if ([identity(row) for row in reg["rows"]] != [identity(row) for row in previous["rows"]]
            or any(row["status"] != "not_started" or row["rounds"] or row["requests"]
                   or row["detected"] for row in previous["rows"])):
        raise ValueError("previous target membership or order changed")
    unchanged = {path: digest for path, digest in previous["code_and_input_sha256"].items()
                 if path.startswith(("spec/", "rtl/", "examples/", "benchmarks/"))}
    unchanged.update({path: previous["code_and_input_sha256"][path] for path in (
        "scripts/agent_budget_study_baselines.py", "scripts/run_agent_holdout_study.py")})
    if any(sha(registered_source_path(path)) != digest for path, digest in unchanged.items()):
        raise ValueError("previous specification, target, contract or baseline bytes changed")
    reg["study"]["unchanged_v7_scope"] = {
        "preregistration_sha256": PRIOR_REGISTRATION_SHA256,
        "bound_asset_count": len(unchanged), "bound_assets": unchanged,
        "no_historical_results_read": True,
    }
    reg["code_and_input_sha256"][PRIOR_REGISTRATION.relative_to(ROOT).as_posix()] = PRIOR_REGISTRATION_SHA256


def preregister_feedback_study() -> dict:
    """Read public frozen inputs only; never initialize credentials or providers."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    integer_fields = {"token_cap": 1_000_000, "max_output_tokens_per_request": 4096,
        "max_vectors_per_proposal": 12, "max_accepted_vectors_total": 64,
        "repeats": 3, "registered_rows": 432, "theoretical_request_cap": 504}
    if (config.get("schema") != "agent-port-feedback-full-batch-v1"
            or any(type(config.get(k)) is not int or config[k] != value for k, value in integer_fields.items())
            or config.get("strategies") != list(STRATEGIES) or config.get("cohorts") != COHORTS
            or config.get("cycle_budgets") != CYCLE_BUDGETS
            or any(type(v) is not int for v in config.get("cycle_budgets", {}).values())
            or config.get("transport") != TRANSPORT
            or type(config.get("transport", {}).get("stream")) is not bool
            or type(config.get("transport", {}).get("automatic_transport_retry")) is not bool
            or type(config.get("transport", {}).get("timeout_seconds")) is not int):
        raise ValueError("invalid complete budget study scope")
    if (PROMPT_VERSION != "verification-agent-v8-bounded-port-feedback"
            or sha(ROOT / "src/iverilog_ai/ai/agent.py") != config["agent_sha256"]
            or hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() != config["system_prompt_sha256"]):
        raise ValueError("frozen v8 Agent or system prompt changed")
    reg, generated = parent.preregister_study()
    for old_path, content in generated.items():
        relative = old_path.relative_to(ROOT).as_posix()
        reg["code_and_input_sha256"].pop(relative)
        target = SPECS / old_path.name
        if target.read_bytes() != content:
            raise ValueError("development specification changed from the prior registered scope")
        case = old_path.stem.removesuffix("_spec")
        reg["protocol_config"]["cases"][case]["spec_path"] = target.relative_to(ROOT).as_posix()
        reg["code_and_input_sha256"][target.relative_to(ROOT).as_posix()] = sha(target)
    for row in reg["rows"]:
        row["cohort"] = "development"
    for cohort, cases, manifest_path, schema in (
        ("previous_internal_modules", PRIOR_INTERNAL_CASES, ROOT / "benchmarks/agent_holdout_20261005/manifest.json", "agent-holdout-modules-v1"),
        ("previous_module_set_holdout", MODULE_HOLDOUT_CASES, ROOT / "benchmarks/agent_module_holdout_20261005_v7/manifest.json", "agent-module-set-holdout-v1"),
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != schema or set(manifest.get("cases", {})) != set(cases):
            raise ValueError("module cohort membership changed")
        reg["code_and_input_sha256"][manifest_path.relative_to(ROOT).as_posix()] = sha(manifest_path)
        for case in cases:
            item = manifest["cases"][case]
            paths = [item[k] for k in ("reference_rtl", "contract_path", "spec_path")]
            paths += [candidate["rtl"] for candidate in item["targets"]]
            resources = {p: registered_source_path(p) for p in paths}
            contract = DutContract.from_dict(json.loads(resources[item["contract_path"]].read_text(encoding="utf-8")))
            if (contract.module != case or reference_sampling_profile(contract) is None
                    or contract.parameters != item["default_parameters"]):
                raise ValueError("unqualified cohort contract")
            text = resources[item["spec_path"]].read_text(encoding="utf-8")
            if not text.strip() or len(text) > 16000:
                raise ValueError("cohort specification outside bounded context")
            if [t["variant"] for t in item["targets"]] != ["reference", "mutation_b", "mutation_c"]:
                raise ValueError("cohort target denominator changed")
            for candidate in item["targets"]:
                if sha(resources[candidate["rtl"]]) != candidate["sha256"]:
                    raise ValueError("cohort target bytes changed")
                if candidate["variant"] == "reference" and candidate["sha256"] != sha(resources[item["reference_rtl"]]):
                    raise ValueError("control disagrees with independent audit source")
                for seed in range(3):
                    for strategy in STRATEGIES:
                        reg["rows"].append({"case": case, "cohort": cohort, "variant": candidate["variant"],
                            "rtl": candidate["rtl"], "contract_path": item["contract_path"], "reference_rtl": item["reference_rtl"],
                            "strategy": strategy, "seed": seed, "budget_cycles": CYCLE_BUDGETS[case],
                            "status": "not_started", "detected": False, "requests": 0, "rounds": [],
                            "first_detection_cycle": None, "first_detection_search_budget": None,
                            "first_detection_elapsed_seconds": None})
            reg["protocol_config"]["cases"][case] = {"spec_path": item["spec_path"],
                "cycle_budget": CYCLE_BUDGETS[case], "default_parameters": contract.parameters}
            reg["contract_profile_sha256"][case] = hashlib.sha256(json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            reg["code_and_input_sha256"].update({p: sha(path) for p, path in resources.items()})
    ranks: dict[str, dict[str, int]] = {case: {} for case in CASES}
    for row in reg["rows"]:
        ranks[row["case"]].setdefault(row["variant"], len(ranks[row["case"]]))
    def order(row: dict) -> tuple:
        case_rank = CASES.index(row["case"])
        rank = ranks[row["case"]][row["variant"]]
        rotation = (row["seed"] + rank + case_rank) % len(STRATEGIES)
        return row["seed"], rank, case_rank, (STRATEGIES.index(row["strategy"]) - rotation) % len(STRATEGIES)
    reg["rows"].sort(key=order)
    source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    study = {"name": config["round_name"], "limits": config,
        "source_revision": source_revision, "source_parent_revision": config["source_parent_revision"],
        "primary": "detected defect tasks / 48 per strategy; all paid and execution failures retained",
        "cohorts": COHORTS, "new_holdout_modules": [], "all_modules_previously_agent_exposed": True,
        "previous_module_set_holdout_previously_offline_tested": True,
        "external_blind_holdout": False, "created_after_v8_freeze": False,
        "secondary": ["per_cohort", "per_case", "per_repeat", "unique_union", "schema_and_budget_recovery", "requests", "tokens", "cycles", "elapsed"],
        "order": "seed, variant rank, case; strategy rotation by seed+rank+case",
        "baseline_factory": "scripts.agent_budget_study_baselines.budget_baseline",
        "baseline_intervention": "unchanged v7 baselines and target/spec/order/cycle limits; at most 12 proposal vectors for every strategy",
        "history_comparison_caveat": "v8 format shape, generic reset planning guidance and verified port observations change together; same-batch feedback/no_feedback is the ablation; historical deltas are descriptive, not single-factor causal estimates",
        "functional_coverage": "existing analyzer only; unsupported modules remain unknown; no target-specific hints",
        "port_observations": "generic verified stdout-bound endpoint/equispaced samples, at most 12; no expected values, paths or custom protocol bins",
        "feedback_caveat": "no_feedback hides functional coverage, port observations and all plan/decision diagnostics; actual capture is identical; executor early stopping and own remaining budget remain",
        "independent_model_rng": False, "history_not_charged_to_this_batch": True,
        "prior_results_never_replaced": True}
    reg.update(scope="eight_known_module_port_feedback_full_batch_not_new_holdout",
        independent_holdout=False, external_independent_holdout=False, study=study, theoretical_requests=504)
    reg["prompt_profile"].update(study=study, max_rounds=3)
    reg["protocol"].update(denominator="16 distinct defects x three repeats = 48 defect tasks per strategy; 24 correct controls; every failure retained",
        selection="exactly the previously registered v7 eight-module target membership, without reselection; no new unseen-module claim",
        no_feedback=study["feedback_caveat"])
    extra_files = [CONFIG, PLAN, Path(__file__).resolve(), ROOT / "scripts/agent_budget_study_baselines.py",
        ROOT / "scripts/run_agent_holdout_study.py",
        ROOT / "tests/core/test_agent_feedback_study.py", ROOT / "tests/core/test_agent_feedback_v8.py",
        ROOT / "tests/core/test_observation_feedback.py", ROOT / "tests/core/test_agent_budget_recovery.py",
        ROOT / "tests/core/test_agent_module_holdout_assets.py", ROOT / ".gitattributes"]
    for folder in (ROOT / "benchmarks/agent_module_holdout_20261005_v7", ROOT / "spec/agent_module_holdout_20261005_v7"):
        extra_files.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix in {".py", ".v", ".json", ".md", ".log"})
    for path in extra_files:
        reg["code_and_input_sha256"][path.relative_to(ROOT).as_posix()] = sha(path)
    _bind_unchanged_v7_scope(reg)
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    if len(reg["rows"]) != 432 or sum(0 if r["strategy"] in STRATEGIES[:3] else 1 if r["strategy"] == "single" else 3 for r in reg["rows"]) != 504:
        raise ValueError("complete batch denominator changed")
    return reg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-key-file", type=Path)
    args = parser.parse_args(argv)
    try:
        reg = preregister_feedback_study()
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "rows": 432,
            "defect_tasks_per_strategy": 48, "correct_tasks_per_strategy": 24,
            "theoretical_requests": 504, "shared_token_cap": 1_000_000}), flush=True)
        if not args.execute:
            return 0
        if OUTPUT.exists() or OUTPUT.is_symlink() or not args.api_key_file:
            raise ValueError("fresh output and credential file required")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
            raise ValueError("source must be committed and clean before API execution")
        previous = previous_batch_accounting()
        reg["pre_execution_previous_accounting"] = previous
        key = read_key_file(args.api_key_file)
        budget = TokenBudget(1_000_000, OUTPUT / "token_budget.json")
        def factory(count):
            return BudgetedProvider(token_budget=budget, endpoint="https://api.deepseek.com", model="deepseek-flash",
                api_key=key, allow_network=True, store=False, reasoning_effort=None, thinking_mode="disabled",
                timeout=60, stream=False, request_limit=count, wire_api="chat_completions",
                max_output_tokens=4096, force_output_limit=True)
        try:
            report = execute(reg, OUTPUT, endpoint="https://api.deepseek.com", model="deepseek-flash", key=key,
                request_cap=504, max_output_tokens=4096, wire_api="chat_completions", thinking_mode="disabled",
                iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe", provider_factory=factory,
                provider_factory_record_kind="api_and_local_simulation", baseline_factory=budget_baseline)
            write(OUTPUT / "previous_batch_accounting.json", previous)
            write(OUTPUT / "strict_summary.json", build_summary(report, reg, evidence_root=OUTPUT))
        finally:
            if OUTPUT.exists():
                budget.save()
        return 0
    except Exception as exc:
        print(f"Complete port-feedback study failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
