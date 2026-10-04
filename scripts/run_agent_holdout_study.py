"""New modules after Agent freeze; one complete preregistered token-capped cohort."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
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
from scripts.run_agent_comparison import BASELINES, execute, registered_source_path, sha, write
from scripts.summarize_agent_comparison import build_summary

CONFIG = ROOT / "spec/agent_holdout_study_1m.json"
MANIFEST = ROOT / "benchmarks/agent_holdout_20261005/manifest.json"
PLAN = ROOT / "docs/experiment/agent_holdout_study_plan_2026-10-05.md"
OUTPUT = ROOT / ".iverilog-ai/agent-holdout-study-live-20261005"
CASES = ("credit_guard", "rotating_arbiter")
STRATEGIES = ("fixed", "random", "protocol_random", "single", "feedback", "no_feedback")
_TRANSPORT = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
              "wire_api": "chat_completions", "thinking_mode": "disabled", "stream": False,
              "timeout_seconds": 60, "automatic_transport_retry": False}


def holdout_baseline(case: str, strategy: str, seed: int, contract: DutContract, cycles: int) -> TestPlan:
    """Read only the public contract; no target source, variant, witness or output."""
    if case not in CASES or strategy not in BASELINES or cycles != 16:
        raise ValueError("baseline outside the registered holdout scope")
    rng = random.Random(seed)
    if strategy == "random":
        excluded = {contract.clock.signal if contract.clock else "", contract.reset.signal if contract.reset else ""}
        ports = [port for port in contract.inputs if port.name not in excluded]
        # The same 12-vector proposal cap as the frozen Agent, with 16 samples.
        vectors: list[dict[str, Any]] = [{"name": f"random_{index}",
                    "inputs": {port.name: rng.randrange(1 << port.width) for port in ports},
                    "cycles": 2 if index < 4 else 1, "sample_phase": "after", "expected": {}}
                   for index in range(12)]
        return TestPlan.model_validate({"design": case, "objective": "Check contract behavior and protocol boundaries",
            "reset": contract.reset.to_dict() if contract.reset else {}, "vectors": vectors})
    inputs: list[dict[str, int]]
    if case == "credit_guard":
        if strategy == "fixed":
            pairs = [(0, 0)] + [(1, 0)] * 4 + [(0, 1)] * 8 + [(1, 1), (0, 0), (1, 0)]
        elif rng.randrange(2):
            pairs = [(0, 1)] * 5 + [(1, 1)] * 2 + [(1, 0)] * 8 + [(0, 0)]
        else:
            pairs = [(1, 0)] * 4 + [(0, 1)] * 8 + [(1, 1)] * 2 + [(0, 0)] * 2
        inputs = [{"acquire": acquire, "release_req": release} for acquire, release in pairs]
    else:
        if strategy == "fixed":
            pairs = [(15, 1)] * 4 + [(15, 0)] * 4
            pairs += [(0, 1), (1, 1), (2, 1), (4, 1), (8, 1), (5, 0), (10, 1), (15, 1)]
        else:
            # Rotation, a held priority, and sparse contenders are specification scenarios.
            pairs = [(15, 1)] * 4 + [(15, 0)] * 3 + [(0, rng.randrange(2))]
            pairs += [(rng.choice((1, 2, 4, 8)), rng.randrange(2)) for _ in range(4)]
            pairs += [(rng.randrange(1, 16), rng.randrange(2)) for _ in range(4)]
        inputs = [{"request": request, "advance": advance} for request, advance in pairs]
    assert len(inputs) == cycles
    vectors = []
    for values in inputs:
        if vectors and vectors[-1]["inputs"] == values:
            vectors[-1]["cycles"] += 1
        else:
            vectors.append({"name": f"{strategy}_{len(vectors)}", "inputs": values, "cycles": 1,
                            "sample_phase": "after", "expected": {}})
    assert len(vectors) <= 12
    return TestPlan.model_validate({"design": case, "objective": "Check contract behavior and protocol boundaries",
        "reset": contract.reset.to_dict() if contract.reset else {},
        "vectors": vectors})


def preregister_holdout() -> dict:
    """No credential, directory creation or network access in registration/dry-run."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if (config.get("schema") != "agent-new-module-holdout-per-round-v1"
            or type(config.get("token_cap")) is not int or config["token_cap"] != 1_000_000
            or config.get("max_output_tokens_per_request") != 4096 or config.get("repeats") != 3
            or config.get("max_vectors_per_proposal") != 12 or config.get("max_accepted_vectors_total") != 64
            or config.get("strategies") != list(STRATEGIES)
            or config.get("cycle_budgets") != {case: 16 for case in CASES}
            or config.get("registered_rows") != 108 or config.get("theoretical_request_cap") != 126
            or config.get("transport") != _TRANSPORT
            or any(type(config.get(field)) is not int for field in
                   ("max_output_tokens_per_request", "max_vectors_per_proposal", "max_accepted_vectors_total",
                    "repeats", "registered_rows", "theoretical_request_cap"))
            or any(type(value) is not int for value in config.get("cycle_budgets", {}).values())
            or type(config.get("transport", {}).get("stream")) is not bool
            or type(config.get("transport", {}).get("automatic_transport_retry")) is not bool
            or type(config.get("transport", {}).get("timeout_seconds")) is not int):
        raise ValueError("invalid full holdout scope")
    agent_path = ROOT / "src/iverilog_ai/ai/agent.py"
    baseline_agent = subprocess.check_output(["git", "show", config["agent_frozen_from_revision"] +
                                              ":src/iverilog_ai/ai/agent.py"], cwd=ROOT)
    if (sha(agent_path) != config["agent_sha256"]
            or hashlib.sha256(baseline_agent).hexdigest() != config["agent_sha256"]
            or hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() != config["system_prompt_sha256"]):
        raise ValueError("frozen Agent or system prompt changed")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "agent-holdout-modules-v1" or set(manifest.get("cases", {})) != set(CASES):
        raise ValueError("holdout membership changed")
    rows = []
    protocols: dict[str, dict] = {}
    contracts = {}
    inputs = {CONFIG.relative_to(ROOT).as_posix(), MANIFEST.relative_to(ROOT).as_posix(),
              PLAN.relative_to(ROOT).as_posix(), Path(__file__).relative_to(ROOT).as_posix(),
              "scripts/agent_token_budget.py", "scripts/run_agent_comparison.py",
              "scripts/run_strategy_experiment.py", "scripts/summarize_agent_comparison.py",
              "tests/core/test_agent_holdout_study.py", "tests/core/test_agent_holdout_assets.py",
              "tests/core/test_agent_holdout_oracles.py"}
    inputs.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "src/iverilog_ai").rglob("*.py"))
    for folder in (ROOT / "benchmarks/agent_holdout_20261005", ROOT / "spec/agent_holdout_20261005"):
        inputs.update(path.relative_to(ROOT).as_posix() for path in folder.rglob("*")
                      if path.is_file() and path.suffix in {".py", ".v", ".json", ".md", ".svg", ".json5"})
    for case in CASES:
        item = manifest["cases"][case]
        resource_paths = [item[key] for key in ("reference_rtl", "contract_path", "spec_path")]
        resource_paths.extend(target["rtl"] for target in item["targets"])
        resources = {relative: registered_source_path(relative) for relative in resource_paths}
        contract = DutContract.from_dict(json.loads(resources[item["contract_path"]].read_text(encoding="utf-8")))
        if contract.module != case or reference_sampling_profile(contract) is None or contract.parameters:
            raise ValueError("unvalidated holdout contract")
        specification = resources[item["spec_path"]].read_text(encoding="utf-8")
        if not specification.strip() or len(specification) > 16000:
            raise ValueError("specification outside the bounded context")
        targets = item["targets"]
        if len(targets) != 3 or [target["variant"] for target in targets] != ["reference", "mutation_b", "mutation_c"]:
            raise ValueError("fixed target denominator changed")
        for target in targets:
            if sha(resources[target["rtl"]]) != target["sha256"]:
                raise ValueError("holdout target changed")
            if target["variant"] == "reference" and target["sha256"] != sha(resources[item["reference_rtl"]]):
                raise ValueError("reference target and independent audit source disagree")
            for seed in range(3):
                for strategy in STRATEGIES:
                    rows.append({"case": case, "variant": target["variant"], "rtl": target["rtl"],
                        "contract_path": item["contract_path"], "reference_rtl": item["reference_rtl"],
                        "strategy": strategy, "seed": seed, "budget_cycles": 16,
                        "status": "not_started", "detected": False, "requests": 0, "rounds": [],
                        "first_detection_cycle": None, "first_detection_search_budget": None,
                        "first_detection_elapsed_seconds": None})
        protocols[case] = {"spec_path": item["spec_path"], "cycle_budget": 16, "default_parameters": {}}
        contracts[case] = hashlib.sha256(json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        inputs.update(resource_paths)
    def order(row: dict) -> tuple:
        case_rank = CASES.index(row["case"])
        variant_rank = ("reference", "mutation_b", "mutation_c").index(row["variant"])
        rotation = (row["seed"] + variant_rank + case_rank) % len(STRATEGIES)
        return row["seed"], variant_rank, case_rank, (STRATEGIES.index(row["strategy"]) - rotation) % len(STRATEGIES)
    rows.sort(key=order)
    study = {"name": config["round_name"], "limits": config,
        "primary": "detected defect tasks / 12 per strategy, all failures retained",
        "secondary": ["per_repeat", "unique_union", "schema_recovery", "requests", "tokens", "cycles", "elapsed"],
        "selection": "two new families created after Agent freeze; all four preregistered single-point mutations",
        "order": "seed, variant rank, case; strategy rotation by seed+rank+case",
        "holdout_level": "post-freeze disjoint synthetic modules; internal authors, not an external blinded benchmark",
        "independent_model_rng": False, "history_not_charged_to_this_batch": True,
        "baseline_factory": "scripts.run_agent_holdout_study.holdout_baseline",
        "functional_coverage": "existing analyzer only; unsupported/unknown for new modules, no new coverage hints",
        "feedback_caveat": "no_feedback hides observations, plan errors and format diagnostics; executor early stopping remains",
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "prior_results_never_replaced": True}
    prompt = {"agent_prompt_version": PROMPT_VERSION, "system_prompt_sha256": config["system_prompt_sha256"],
              "profile": "v3", "strategies": list(STRATEGIES), "repeats": 3,
              "reference_sampling": "per_cycle", "agent_plan_mode": "independent", "max_rounds": 3,
              "api_request_limit_per_sample": {"single": 1, "feedback": 3, "no_feedback": 3}, "study": study}
    assert len(rows) == 108
    return {"schema": "agent-comparison-v3", "profile": "v3",
        "scope": "post_freeze_new_synthetic_modules_internal_holdout",
        "independent_holdout": True, "external_independent_holdout": False,
        "study": study, "rows": rows, "protocol_config": {"schema_version": "agent-holdout-protocols-v1", "cases": protocols},
        "contract_profile_sha256": contracts, "prompt_profile": prompt,
        "prompt_profile_sha256": hashlib.sha256(json.dumps(prompt, sort_keys=True).encode()).hexdigest(),
        "theoretical_requests": 126, "code_and_input_sha256": {relative: sha(registered_source_path(relative)) for relative in sorted(inputs)},
        "protocol": {"denominator": "all four mutations, three repeats = 12 defect tasks per strategy, plus 6 correct controls",
                     "cycles": "same 16 cumulative stimulus cap; independent reset episodes; reset/audit reported separately",
                     "reference_replay": "every actually executed episode; all outputs checked every after-edge sample",
                     "single": "same prompt and action schema; one request and at most one episode",
                     "no_feedback": study["feedback_caveat"]}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-key-file", type=Path)
    args = parser.parse_args(argv)
    try:
        reg = preregister_holdout()
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "registered_rows": 108,
                          "defect_tasks_per_strategy": 12, "correct_tasks_per_strategy": 6,
                          "theoretical_requests": 126, "round_token_cap": 1_000_000}))
        if not args.execute:
            return 0
        if OUTPUT.exists() or OUTPUT.is_symlink() or not args.api_key_file:
            raise ValueError("fresh output and credential file required")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
            raise ValueError("source must be committed and clean before API execution")
        key = read_key_file(args.api_key_file)
        budget = TokenBudget(1_000_000, OUTPUT / "token_budget.json")
        def factory(count):
            return BudgetedProvider(token_budget=budget, endpoint="https://api.deepseek.com", model="deepseek-flash",
                api_key=key, allow_network=True, store=False, reasoning_effort=None, thinking_mode="disabled",
                timeout=60, stream=False, request_limit=count, wire_api="chat_completions",
                max_output_tokens=4096, force_output_limit=True)
        try:
            report = execute(reg, OUTPUT, endpoint="https://api.deepseek.com", model="deepseek-flash", key=key,
                request_cap=126, max_output_tokens=4096, wire_api="chat_completions", thinking_mode="disabled",
                iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe", provider_factory=factory,
                provider_factory_record_kind="api_and_local_simulation", baseline_factory=holdout_baseline)
            summary = build_summary(report, reg, evidence_root=OUTPUT)
            write(OUTPUT / "strict_summary.json", summary)
        finally:
            if OUTPUT.exists():
                budget.save()
        return 0
    except Exception as exc:
        print(f"New-module holdout failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
