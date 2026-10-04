"""Equal short-cycle comparison: three repeats, one API proposal per target."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_agent_comparison import BASELINES, CASES, execute, preregister, sha
from iverilog_ai.ai.local_api_profile import read_key_file

BUDGETS = ROOT / "spec/agent_smoke_budgets.json"
PLAN = ROOT / "docs/experiment/agent_smoke_plan_2026-10-05.md"
STRATEGIES = ("fixed", "random", "protocol_random", "single")


def preregister_smoke(*, baselines_only: bool = False) -> dict:
    """Fix sample membership before simulation; do not select by observed score."""
    budgets = json.loads(BUDGETS.read_text(encoding="utf-8"))
    if budgets.get("schema") != "agent-smoke-budgets-v1" or set(budgets["cases"]) != set(CASES):
        raise ValueError("invalid smoke budget scope")
    strategies = tuple(s for s in STRATEGIES if not baselines_only or s in BASELINES)
    reg = preregister(strategies=strategies, repeats=3, profile="v3")
    protocols = reg["protocol_config"]
    minima = {"sync_fifo": 2 * protocols["cases"]["sync_fifo"]["timing"]["depth"] + 2,
              "uart_tx": protocols["cases"]["uart_tx"]["timing"]["busy_cycles_after_accept"] + 2,
              "spi_master": protocols["cases"]["spi_master"]["timing"]["busy_cycles_after_accept"] + 2,
              "handshake_stage": 5}
    for case in CASES:
        cycles = budgets["cases"][case]["cycle_budget"]
        if type(cycles) is not int or not minima[case] <= cycles <= protocols["cases"][case]["cycle_budget"]:
            raise ValueError("smoke budget cannot complete its registered transaction")
        protocols["cases"][case]["cycle_budget"] = cycles
    for row in reg["rows"]:
        row["budget_cycles"] = protocols["cases"][row["case"]]["cycle_budget"]
    reg["scope"] = budgets["scope"]
    reg["study"] = {"name": "short_budget_first_proposal_v1", "budget_config": budgets,
                    "selection": "same first two development defects as v5, no new holdout",
                    "api": "one proposal and at most one execution; no later failure feedback",
                    "repeats": 3, "random_seed_sequence": [0, 1, 2],
                    "model_rng_paired": False,
                    "primary_metric": "detected task count out of 24 defect tasks per strategy",
                    "secondary_metrics": ["per_repeat", "unique_union", "first_detection", "requests", "elapsed"]}
    reg["prompt_profile"]["max_rounds"] = 1
    reg["prompt_profile"]["study"] = reg["study"]
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    for path in (BUDGETS, PLAN, Path(__file__).resolve()):
        reg["code_and_input_sha256"][path.relative_to(ROOT).as_posix()] = sha(path)
    return reg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--baselines-only", action="store_true")
    parser.add_argument("--total-request-cap", type=int, default=0)
    parser.add_argument("--endpoint", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--iverilog", default="D:/iverilog/bin/iverilog.exe")
    parser.add_argument("--vvp", default="D:/iverilog/bin/vvp.exe")
    args = parser.parse_args(argv)
    try:
        reg = preregister_smoke(baselines_only=args.baselines_only)
        if not 0 <= args.total_request_cap <= reg["theoretical_requests"]:
            raise ValueError("request cap exceeds the registered study")
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "rows": len(reg["rows"]),
                          "repeats": 3, "requests_per_api_task": 1,
                          "theoretical_requests": reg["theoretical_requests"],
                          "budget_cycles": {c: reg["protocol_config"]["cases"][c]["cycle_budget"] for c in CASES}}))
        if not args.execute:
            return 0
        if not args.output_dir or args.total_request_cap != reg["theoretical_requests"]:
            raise ValueError("new output directory and full registered request cap required")
        url = urlsplit(args.endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or not args.model:
            raise ValueError("HTTPS endpoint and model required")
        key = ""
        if reg["theoretical_requests"]:
            if not args.api_key_file:
                raise ValueError("credential file required")
            key = read_key_file(args.api_key_file)
        execute(reg, args.output_dir, endpoint=args.endpoint, model=args.model, key=key,
                request_cap=args.total_request_cap, max_output_tokens=8192,
                wire_api="chat_completions", thinking_mode="disabled", iverilog=args.iverilog, vvp=args.vvp)
        return 0
    except Exception as exc:
        print(f"Smoke comparison failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
