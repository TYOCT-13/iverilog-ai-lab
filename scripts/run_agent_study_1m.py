"""Complete registered protocol-priority comparison with a shared 1M token cap."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.agent_study_specs import STUDY_SPEC_PROFILE, render_study_spec
from scripts.agent_token_budget import BudgetedProvider, TokenBudget
from scripts.run_agent_comparison import CASES, execute, preregister, sha
from scripts.run_agent_smoke_comparison import preregister_smoke
from iverilog_ai.ai.local_api_profile import read_key_file

CONFIG = ROOT / "spec/agent_study_1m.json"
PLAN = ROOT / "docs/experiment/agent_study_1m_plan_2026-10-05.md"
INPUTS = ROOT / ".iverilog-ai/agent-study-1m-20261005-inputs"
OUTPUT = ROOT / ".iverilog-ai/agent-study-1m-live-20261005"
STRATEGIES = ("fixed", "random", "protocol_random", "single", "feedback", "no_feedback")


def preregister_study() -> tuple[dict, dict[Path, bytes]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if (config["schema"] != "agent-study-per-round-v1" or config["token_cap"] != 1_000_000
            or config["repeats"] != 3 or config["strategies"] != list(STRATEGIES)
            or config["max_output_tokens_per_request"] != 4096):
        raise ValueError("invalid study scope")
    validated_short = preregister_smoke()
    if config["cycle_budgets"] != {c: validated_short["protocol_config"]["cases"][c]["cycle_budget"] for c in CASES}:
        raise ValueError("cycle budget differs from validated short transactions")
    reg = preregister(strategies=STRATEGIES, repeats=3, profile="v3")
    ranks = {}
    for row in reg["rows"]:
        ranks.setdefault(row["case"], {})
        ranks[row["case"]].setdefault(row["variant"], len(ranks[row["case"]]))
        row["budget_cycles"] = config["cycle_budgets"][row["case"]]
    def order(row):
        case = CASES.index(row["case"])
        rank = ranks[row["case"]][row["variant"]]
        rotation = (row["seed"] + rank + case) % len(STRATEGIES)
        return row["seed"], rank, case, (STRATEGIES.index(row["strategy"])-rotation) % len(STRATEGIES)
    reg["rows"].sort(key=order)
    reg["scope"] = "development_full_protocol_priority_batch_not_independent_holdout"
    reg["study"] = {"name": config["round_name"], "limits": config,
                    "primary": "detected defect tasks out of 24 per strategy, including all failures",
                    "secondary": ["per_repeat", "unique_union", "schema_acceptance", "requests", "tokens", "cycles", "elapsed"],
                    "order": "seed, variant rank(reference first), case; strategy order cyclically rotated by seed+rank+case",
                    "prompt_intervention": STUDY_SPEC_PROFILE,
                    "independent_model_rng": False,
                    "history_not_charged_to_this_batch": True,
                    "prior_results_never_replaced": True,
                    "feedback_caveat": "same shared cycle cap; further reset episodes may not fit a complete transaction; no_feedback also hides plan errors and retains result-driven early stopping"}
    reg["prompt_profile"].update(study=reg["study"], max_rounds=3)
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    generated = {}
    for case in CASES:
        item = reg["protocol_config"]["cases"][case]
        item["cycle_budget"] = config["cycle_budgets"][case]
        original = (ROOT/item["spec_path"]).read_text(encoding="utf-8")
        target = INPUTS/f"{case}_spec.md"
        content = render_study_spec(case, item["cycle_budget"], original).encode("utf-8")
        generated[target] = content
        item["spec_path"] = target.relative_to(ROOT).as_posix()
        reg["code_and_input_sha256"][item["spec_path"]] = hashlib.sha256(content).hexdigest()
    for path in (CONFIG, PLAN, Path(__file__).resolve(), ROOT/"scripts/agent_study_specs.py",
                 ROOT/"scripts/agent_token_budget.py", ROOT/"scripts/run_agent_smoke_comparison.py",
                 ROOT/"spec/agent_smoke_budgets.json"):
        reg["code_and_input_sha256"][path.relative_to(ROOT).as_posix()] = sha(path)
    return reg, generated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-key-file", type=Path)
    args = parser.parse_args(argv)
    try:
        reg, generated = preregister_study()
        print(json.dumps({"mode":"execute" if args.execute else "dry_run", "rows":len(reg["rows"]),
                          "theoretical_requests":reg["theoretical_requests"], "round_token_cap":1_000_000}))
        if not args.execute:
            return 0
        if INPUTS.exists() or OUTPUT.exists() or not args.api_key_file:
            raise ValueError("new inputs/output and credential file required")
        key = read_key_file(args.api_key_file)
        INPUTS.mkdir(parents=True, exist_ok=False)
        for path, content in generated.items():
            with path.open("xb") as stream:
                stream.write(content)
        budget = TokenBudget(1_000_000, OUTPUT/"token_budget.json")
        def factory(count):
            return BudgetedProvider(token_budget=budget,endpoint="https://api.deepseek.com",model="deepseek-flash",
                                    api_key=key,allow_network=True,store=False,reasoning_effort=None,
                                    thinking_mode="disabled",timeout=60,stream=False,request_limit=count,
                                    wire_api="chat_completions",max_output_tokens=4096,force_output_limit=True)
        try:
            execute(reg, OUTPUT, endpoint="https://api.deepseek.com", model="deepseek-flash", key=key,
                    request_cap=reg["theoretical_requests"], max_output_tokens=4096,
                    wire_api="chat_completions", thinking_mode="disabled", iverilog="D:/iverilog/bin/iverilog.exe",
                    vvp="D:/iverilog/bin/vvp.exe", provider_factory=factory,
                    provider_factory_record_kind="api_and_local_simulation")
        finally:
            if OUTPUT.exists():
                budget.save()
        return 0
    except Exception as exc:
        print(f"Token-capped study failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
