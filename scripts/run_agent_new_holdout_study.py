"""Register the complete v8 internal synthetic module holdout; dry-run by default."""
from __future__ import annotations

import argparse
import hashlib
from importlib import import_module
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iverilog_ai.ai.agent import PROMPT_VERSION, SYSTEM_PROMPT
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import reference_sampling_profile
from scripts.agent_token_budget import BudgetedProvider, TokenBudget
from scripts.run_agent_comparison import execute, registered_source_path, sha, write
from scripts.summarize_agent_comparison import build_summary

CONFIG = ROOT / "spec/agent_new_holdout_study_1m_v8.json"
ASSETS = "benchmarks/agent_new_holdout_20261005"
SPECS = "spec/agent_new_holdout_20261005"
MANIFEST = ROOT / ASSETS / "manifest.json"
PLAN = ROOT / "docs/experiment/agent_new_holdout_study_plan_2026-10-05.md"
OUTPUT = ROOT / ".iverilog-ai/agent-new-holdout-study-live-20261005"
CASES = ("valid_data_pipeline", "event_accumulator")
VARIANTS = ("reference", "mutation_b", "mutation_c")
STRATEGIES = ("fixed", "random", "protocol_random", "single", "feedback", "no_feedback")
PREVIOUS_BATCHES = ("agent-study-1m-live-20261005", "agent-recovery-study-live-20261005",
    "agent-holdout-study-live-20261005", "agent-budget-study-live-20261005",
    "agent-feedback-study-live-20261005")
FROZEN_REVISION = "a96933786c17986a739fc2da515db3294d6e8044"
FROZEN_SOURCES = {
    "src/iverilog_ai/ai/agent.py": "bf8422840a97ed3360f0dac0ee0621fd605970d658521ce7bec0d57f3c8016ff",
    "src/iverilog_ai/core/observation_feedback.py": "3586fa13bd2ab82668188dac48b1a3055a935ff87d66d6accd600938e1b621d6",
}
SYSTEM_PROMPT_SHA256 = "3dd3f86f6f15b2367dc8f0913c5f3c7fe646782258093a148170f60200d6a26a"
TRANSPORT = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
    "wire_api": "chat_completions", "thinking_mode": "disabled", "stream": False,
    "store": False, "timeout_seconds": 60, "automatic_transport_retry": False}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def _load_config(*, require_frozen: bool = False) -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    integers = {"token_cap": 1_000_000, "max_output_tokens_per_request": 4096,
        "max_vectors_per_proposal": 12, "max_accepted_vectors_total": 64,
        "repeats": 3, "registered_rows": 108, "theoretical_request_cap": 126}
    pins = {"schema": "agent-new-internal-module-holdout-v8-v1",
        "round_name": "v8_new_internal_synthetic_module_holdout_20261005",
        "agent_frozen_from_revision": FROZEN_REVISION,
        "agent_prompt_version": "verification-agent-v8-bounded-port-feedback",
        "agent_sha256": FROZEN_SOURCES["src/iverilog_ai/ai/agent.py"],
        "observation_feedback_sha256": FROZEN_SOURCES["src/iverilog_ai/core/observation_feedback.py"],
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "strategies": list(STRATEGIES), "cycle_budgets": {case: 24 for case in CASES},
        "transport": TRANSPORT}
    allowed = set(integers) | set(pins) | {"freeze_status", "manifest_sha256", "token_scope"}
    if (not isinstance(config, dict) or set(config) != allowed
            or any(type(config.get(key)) is not int or config[key] != value for key, value in integers.items())
            or any(config.get(key) != value for key, value in pins.items())
            or any(type(value) is not int for value in config["cycle_budgets"].values())
            or any(type(config["transport"][field]) is not bool for field in
                   ("stream", "store", "automatic_transport_retry"))
            or type(config["transport"]["timeout_seconds"]) is not int
            or not isinstance(config["token_scope"], str) or not config["token_scope"].strip()):
        raise ValueError("invalid complete new holdout scope or frozen Agent pins")
    frozen = config["freeze_status"] == "FROZEN"
    digest = config["manifest_sha256"]
    if not ((frozen and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest))
            or (config["freeze_status"] == "UNFROZEN" and digest is None)):
        raise ValueError("invalid freeze lifecycle")
    if require_frozen and not frozen:
        raise ValueError("new holdout is UNFROZEN; execute is forbidden")
    return config


def validate_frozen_agent() -> None:
    """Compare current bytes and Git blobs; import the schema-built SYSTEM_PROMPT."""
    for relative, digest in FROZEN_SOURCES.items():
        if sha(registered_source_path(relative)) != digest or _digest(_git("show", FROZEN_REVISION + ":" + relative)) != digest:
            raise ValueError("frozen v8 Agent or observation helper changed")
    if PROMPT_VERSION != "verification-agent-v8-bounded-port-feedback" or _digest(SYSTEM_PROMPT.encode("utf-8")) != SYSTEM_PROMPT_SHA256:
        raise ValueError("frozen v8 imported prompt changed")


def holdout_baseline(case: str, strategy: str, seed: int, contract: DutContract, cycles: int) -> TestPlan:
    """Delegate exclusively to the registered public-spec/contract/seed baseline."""
    plan = import_module("benchmarks.agent_new_holdout_20261005.baselines").baseline_factory(
        case, strategy, seed, contract, cycles)
    if not isinstance(plan, TestPlan):
        raise ValueError("baseline did not return a bounded TestPlan")
    return plan


def _asset_files() -> set[str]:
    return {path.relative_to(ROOT).as_posix() for folder in (ROOT / ASSETS, ROOT / SPECS)
        for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts
        and path != ROOT / ASSETS / "manifest.json"}


def _load_manifest(config: dict[str, Any]) -> dict[str, Any]:
    if config["freeze_status"] == "FROZEN" and sha(MANIFEST) != config["manifest_sha256"]:
        raise ValueError("frozen manifest original bytes changed")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "agent-holdout-modules-v1" or set(manifest.get("cases", {})) != set(CASES):
        raise ValueError("new holdout membership changed")
    members = manifest.get("members")
    if not isinstance(members, dict) or set(members) != _asset_files():
        raise ValueError("manifest members are not the complete closed asset set")
    if any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
           or sha(registered_source_path(relative)) != digest for relative, digest in members.items()):
        raise ValueError("manifest member original bytes changed")

    def bind(relative: str, digest: str) -> None:
        if members.get(relative) != digest:
            raise ValueError("manifest resource disagrees with members")

    for key, name in (("baseline_factory", "baselines.py"), ("reference_functions", "reference_models.py"),
                      ("prior_membership", "prior_module_membership.json")):
        if manifest.get(key + "_path") != f"{ASSETS}/{name}":
            raise ValueError("manifest public resource path changed")
        bind(manifest[key + "_path"], manifest[key + "_sha256"])
    for item in manifest.get("private_metadata", []):
        if item.get("API_visible") is not False:
            raise ValueError("private metadata cannot be API-visible")
        bind(item["path"], item["sha256"])
    for case in CASES:
        item = manifest["cases"][case]
        expected = {"reference_rtl": f"{ASSETS}/targets/{case}/A/{case}.v",
            "contract_path": f"{ASSETS}/contracts/{case}_contract.json",
            "spec_path": f"{SPECS}/{case}_spec.md", "default_parameters": {},
            "cycle_budget": 24, "max_vectors_per_proposal": 12, "max_accepted_vectors_total": 64,
            "clock": {"signal": "i_clk", "period_ns": 10, "edge": "posedge"},
            "reset": {"signal": "i_rstn", "active_level": 0, "synchronous": False, "assert_cycles": 2},
            "sampling": "per_cycle_after", "episodes": "fresh_automatic_reset_no_state_continuation"}
        if any(item.get(key) != value for key, value in expected.items()) or any(
                type(item.get(field)) is not int for field in ("cycle_budget", "max_vectors_per_proposal", "max_accepted_vectors_total")):
            raise ValueError("fixed case contract or episode scope changed")
        for path_key, hash_key in (("reference_rtl", "reference_sha256"), ("contract_path", "contract_sha256"), ("spec_path", "spec_sha256")):
            bind(item[path_key], item[hash_key])
        targets = item["targets"]
        if len(targets) != 3 or [target["variant"] for target in targets] != list(VARIANTS):
            raise ValueError("fixed target denominator changed")
        for target, label in zip(targets, "ABC", strict=True):
            if target["rtl"] != f"{ASSETS}/targets/{case}/{label}/{case}.v":
                raise ValueError("fixed target path changed")
            bind(target["rtl"], target["sha256"])
    return manifest


def preregister_new_holdout(*, require_frozen: bool = False) -> dict[str, Any]:
    """Read-only registration; no credential, provider, DUT or output directory."""
    config = _load_config(require_frozen=require_frozen)
    validate_frozen_agent()
    manifest = _load_manifest(config)
    rows: list[dict[str, Any]] = []
    protocols, contracts = {}, {}
    for case in CASES:
        item = manifest["cases"][case]
        contract = DutContract.from_dict(json.loads(registered_source_path(item["contract_path"]).read_text(encoding="utf-8")))
        if contract.module != case or contract.parameters or reference_sampling_profile(contract) is None:
            raise ValueError("new holdout Oracle is not validated for the complete fixed contract")
        specification = registered_source_path(item["spec_path"]).read_text(encoding="utf-8")
        if not specification.strip() or len(specification) > 16000:
            raise ValueError("public specification outside bounded context")
        # Geometry only: build the public plans, without initializing a simulator.
        for strategy in STRATEGIES[:3]:
            for seed in range(3):
                plan = holdout_baseline(case, strategy, seed, contract, 24)
                if (plan.design != case or len(plan.vectors) > 12 or sum(vector.cycles for vector in plan.vectors) != 24
                        or any(vector.expected or vector.sample_phase != "after" for vector in plan.vectors)):
                    raise ValueError("public baseline geometry changed")
        for target in item["targets"]:
            for seed in range(3):
                for strategy in STRATEGIES:
                    rows.append({"case": case, "variant": target["variant"], "rtl": target["rtl"],
                        "contract_path": item["contract_path"], "reference_rtl": item["reference_rtl"],
                        "strategy": strategy, "seed": seed, "budget_cycles": 24,
                        "status": "not_started", "detected": False, "requests": 0, "rounds": [],
                        "first_detection_cycle": None, "first_detection_search_budget": None,
                        "first_detection_elapsed_seconds": None})
        protocols[case] = {"spec_path": item["spec_path"], "cycle_budget": 24, "default_parameters": {}}
        contracts[case] = _digest(json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True).encode())

    def order(row: dict[str, Any]) -> tuple[int, int, int, int]:
        case_rank, variant_rank = CASES.index(row["case"]), VARIANTS.index(row["variant"])
        rotation = (row["seed"] + variant_rank + case_rank) % len(STRATEGIES)
        return row["seed"], variant_rank, case_rank, (STRATEGIES.index(row["strategy"]) - rotation) % len(STRATEGIES)

    rows.sort(key=order)
    theoretical = sum(0 if row["strategy"] in STRATEGIES[:3] else 1 if row["strategy"] == "single" else 3 for row in rows)
    if len(rows) != 108 or theoretical != 126:
        raise ValueError("complete new holdout denominator changed")
    feedback_caveat = "no_feedback hides port observations, coverage and all format/plan diagnostics; executor early stop and own remaining budget remain"
    study = {"name": config["round_name"], "limits": config,
        "source_revision": _git("rev-parse", "HEAD").decode().strip(),
        "agent_frozen_from_revision": FROZEN_REVISION, "manifest_sha256": sha(MANIFEST),
        "primary": "detected defect tasks / 12 per strategy; every failed or unexecuted task retained",
        "secondary": ["per_case", "per_repeat", "unique_union", "schema_and_budget_recovery", "requests", "tokens", "cycles", "elapsed"],
        "new_holdout_modules": list(CASES), "all_modules_previously_agent_exposed": False,
        "created_after_v8_freeze": True, "external_blind_holdout": False, "independent_human_review": False,
        "holdout_level": "internal new synthetic module set; not an external blind benchmark or pretraining novelty claim",
        "order": "seed, variant rank, case; strategy rotation by seed+rank+case",
        "baseline_factory": "scripts.run_agent_new_holdout_study.holdout_baseline",
        "baseline_intervention": "public spec/contract/seed only; random is 12 independent uniform segments of two cycles",
        "functional_coverage": "unchanged analyzer; new modules unsupported/unknown, no custom bins or hints",
        "feedback_caveat": feedback_caveat, "independent_model_rng": False,
        "history_not_charged_to_this_batch": True, "prior_results_never_replaced": True,
        "previous_failed_v8_tasks_not_retried": True}
    prompt = {"agent_prompt_version": PROMPT_VERSION, "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "profile": "v3", "strategies": list(STRATEGIES), "repeats": 3, "max_rounds": 3,
        "reference_sampling": "per_cycle", "agent_plan_mode": "independent",
        "api_request_limit_per_sample": {"single": 1, "feedback": 3, "no_feedback": 3}, "study": study}
    inputs = set(manifest["members"]) | {path.relative_to(ROOT).as_posix() for path in
        (CONFIG, MANIFEST, PLAN, Path(__file__).resolve(), ROOT / ".gitattributes")}
    inputs.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "src").rglob("*.py"))
    inputs.update({"scripts/agent_token_budget.py", "scripts/run_agent_comparison.py",
        "scripts/run_strategy_experiment.py", "scripts/summarize_agent_comparison.py",
        "tests/core/test_agent_new_holdout_study.py", "tests/core/test_agent_new_holdout_assets.py",
        "tests/core/test_agent_new_holdout_oracles.py"})
    return {"schema": "agent-comparison-v3", "profile": "v3",
        "scope": "post_v8_freeze_new_internal_synthetic_module_set_holdout",
        "independent_holdout": True, "external_independent_holdout": False,
        "internal_controlled_module_set_holdout": True,
        "independent_holdout_meaning": "new module membership disjoint from five earlier controlled API batches; same-team synthetic designs/mutations; no external blindness",
        "study": study, "rows": rows, "protocol_config": {"schema_version": "agent-new-holdout-protocols-v1", "cases": protocols},
        "contract_profile_sha256": contracts, "prompt_profile": prompt,
        "prompt_profile_sha256": _digest(json.dumps(prompt, sort_keys=True).encode()),
        "theoretical_requests": theoretical,
        "code_and_input_sha256": {relative: sha(registered_source_path(relative)) for relative in sorted(inputs)},
        "protocol": {"denominator": "four distinct mutations x three repeats = 12 defect tasks per strategy, plus six correct controls",
            "cycles": "24 cumulative stimulus cycles; independent reset episodes; reset/audit reported separately",
            "reference_replay": "every actual episode independently replayed on correct RTL; all outputs checked every after-edge sample",
            "single": "same frozen prompt/action schema; one shared request and at most one actual episode",
            "no_feedback": feedback_caveat}}


def previous_batch_accounting() -> list[dict[str, Any]]:
    """Only inspect original accounting; missing local records cannot pass admission."""
    records = []
    absent = []
    for name in PREVIOUS_BATCHES:
        folder = ROOT / ".iverilog-ai" / name
        journal, report = folder / "token_budget.json", folder / "results.json"
        if not folder.exists():
            absent.append(name)
            continue
        if not journal.is_file() or not report.is_file():
            raise ValueError("previous local batch has incomplete accounting: " + name)
        journal_raw, report_raw = journal.read_bytes(), report.read_bytes()
        data, result = json.loads(journal_raw), json.loads(report_raw)
        # Constructor validates persisted records and never writes the old journal.
        old_budget = TokenBudget(data["limit"], journal)
        totals = old_budget.totals()
        if old_budget.data != data or data.get("totals") != totals:
            raise ValueError("previous local ledger totals or original bytes disagree: " + name)
        pending = sum(item["status"] == "pending" for item in data["records"])
        if pending or not isinstance(result.get("finished_at"), str) or not result["finished_at"].strip():
            raise ValueError("previous registered batch is pending or unfinished: " + name)
        records.append({"batch": name, "local_private_records": "verified_present", "finished_at": result["finished_at"],
            "pending_requests": pending, "unknown_usage_requests": sum(item["status"] == "unknown_usage" for item in data["records"]),
            "unknown_usage_records": [item for item in data["records"] if item["status"] == "unknown_usage"],
            "tokens": data["totals"], "journal_sha256": _digest(journal_raw), "results_sha256": _digest(report_raw),
            "historical_usage_charged_to_this_batch": False})
    if absent:
        raise ValueError("previous local accounting absent; execution refused: " + ", ".join(absent))
    return records


def execution_admission(registration: dict[str, Any], key_file: Path | None) -> list[dict[str, Any]]:
    """Complete all gates before any credential read, provider or output creation."""
    if registration["study"]["limits"]["freeze_status"] != "FROZEN":
        raise ValueError("new holdout is UNFROZEN; execute is forbidden")
    if OUTPUT.exists() or OUTPUT.is_symlink() or key_file is None:
        raise ValueError("fresh output and explicit --api-key-file required")
    if _git("status", "--porcelain"):
        raise ValueError("source must be committed and clean before API execution")
    tracked = set(_git("ls-files", "-z").decode("utf-8").split("\0"))
    if set(registration["code_and_input_sha256"]) - tracked or _git("rev-parse", "HEAD").decode().strip() != registration["study"]["source_revision"]:
        raise ValueError("all registered inputs must be committed at the registered source revision")
    if any(sha(registered_source_path(relative)) != digest for relative, digest in registration["code_and_input_sha256"].items()):
        raise ValueError("registered original bytes changed before credential access")
    return previous_batch_accounting()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-key-file", type=Path)
    args = parser.parse_args(argv)
    credential_access_started = False
    try:
        reg = preregister_new_holdout(require_frozen=args.execute)
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "freeze_status": reg["study"]["limits"]["freeze_status"],
            "registered_rows": 108, "defect_tasks_per_strategy": 12, "correct_tasks_per_strategy": 6,
            "theoretical_requests": 126, "shared_token_cap": 1_000_000}), flush=True)
        if not args.execute:
            return 0
        previous = execution_admission(reg, args.api_key_file)
        reg["pre_execution_previous_accounting"] = previous
        credential_access_started = True
        key = read_key_file(args.api_key_file)
        budget = TokenBudget(1_000_000, OUTPUT / "token_budget.json")

        def factory(count: int) -> BudgetedProvider:
            return BudgetedProvider(token_budget=budget, endpoint="https://api.deepseek.com", model="deepseek-flash",
                api_key=key, allow_network=True, store=False, reasoning_effort=None, thinking_mode="disabled",
                timeout=60, stream=False, request_limit=count, wire_api="chat_completions",
                max_output_tokens=4096, force_output_limit=True)

        try:
            report = execute(reg, OUTPUT, endpoint="https://api.deepseek.com", model="deepseek-flash", key=key,
                request_cap=126, max_output_tokens=4096, wire_api="chat_completions", thinking_mode="disabled",
                iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe", provider_factory=factory,
                provider_factory_record_kind="api_and_local_simulation", baseline_factory=holdout_baseline)
        finally:
            if OUTPUT.exists():
                budget.save()
                write(OUTPUT / "previous_batch_accounting.json", previous)
        write(OUTPUT / "strict_summary.json", build_summary(report, reg, evidence_root=OUTPUT))
        return 0
    except Exception as exc:
        detail = "" if credential_access_started else ": " + str(exc)
        print(f"New internal holdout failed: {type(exc).__name__}{detail}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
