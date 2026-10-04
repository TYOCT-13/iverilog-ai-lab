"""One bounded diagnostic of five rejected proposals and one correct control.

This is selected after failures were observed, not a replacement comparison.
Dry-run neither reads credentials nor creates files. Execution is single-use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_agent_comparison import CASES, execute, sha
from scripts.run_agent_smoke_comparison import preregister_smoke
from iverilog_ai.ai.local_api_profile import read_key_file

PLAN = ROOT / "docs/experiment/agent_smoke_diagnostic_plan_2026-10-05.md"
LEDGER = ROOT / "docs/experiment/agent_smoke_api_budget_2026-10-05.json"
PARENT = ROOT / ".iverilog-ai/agent-smoke-live-20261005/results.json"
INPUTS = ROOT / ".iverilog-ai/agent-smoke-diagnostic-live-20261005-inputs"
OUTPUT = ROOT / ".iverilog-ai/agent-smoke-diagnostic-live-20261005"
# Membership is fixed before the six new requests, using the completed parent.
SELECTION = (
    ("sync_fifo", "fifo_bug_full_off_by_one", 0, "policy_error"),
    ("uart_tx", "uart_bug_msb_first", 0, "policy_error"),
    ("uart_tx", "uart_bug_msb_first", 1, "policy_error"),
    ("uart_tx", "uart_bug_busy_never_clears", 2, "cycle_budget"),
    ("spi_master", "spi_bug_done_missing", 0, "policy_error"),
    ("sync_fifo", "reference", 1, "not_detected"),
)
OLD_BUDGET_PREFIX = {
    "sync_fifo": "- 已验证累计激励预算为 **160 周期**",
    "uart_tx": "累计激励周期上限为 **512**",
    "spi_master": "- 本轮累计激励周期上限 **384**",
    "handshake_stage": "- 本轮多轮共享累计激励预算 **160 周期**",
}


def normalize_spec(case: str, cycles: int, text: str) -> str:
    """Remove exactly the obsolete budget paragraph, retaining all RTL semantics."""
    lines = text.splitlines()
    removed = [line for line in lines if line.startswith(OLD_BUDGET_PREFIX[case])]
    if len(removed) != 1:
        raise ValueError("expected exactly one old budget paragraph")
    prefix = (
        f"# Short-budget first-proposal scope: {cycles} stimulus cycles\n\n"
        f"This episode has at most {cycles} stimulus cycles and one API proposal. "
        "The scenario lists below describe the full regression scope; choose a focused "
        "SUBSET that fits this episode. They are not a requirement to run every scenario. "
        "Do not plan multiple complete frames if they do not fit.\n\n"
        "The contract automatically resets the DUT before the episode; those initial "
        "reset cycles are outside stimulus accounting. Any manual reset vectors count "
        "toward the stimulus budget. Every held-input cycle is checked after its edge. "
        "Compute the sum of vector cycles privately and keep it at or below max_new_cycles.\n\n"
        "The decision JSON has ONLY the existing top-level action, reason, vectors fields. "
        "Do not add summary fields such as vector_count, total_cycles, cycle_sum, "
        "cycles_total or cycles at the top level. Each vector keeps its required cycles "
        "field. Use the existing schema; no new format or executable content.\n\n"
        "The following circuit interface, acceptance rules and timing remain unchanged.\n\n"
    )
    return prefix + "\n".join(line for line in lines if line not in removed) + "\n"


def preregister_diagnostic() -> tuple[dict, dict[Path, bytes]]:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    if (ledger["authorized_total_cap"] != 360 or ledger["reserved_request_upper"] != 354
            or ledger["remaining_after_reservation"] != 6
            or ledger["reserved_request_upper"] + len(SELECTION) > ledger["authorized_total_cap"]):
        raise ValueError("diagnostic would exceed its reserved request budget")
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    if (not parent.get("finished_at") or parent["requests_attempted"] != 36
            or ledger["new_record"]["sha256"] != sha(PARENT)):
        raise ValueError("parent study must be complete")
    reg = preregister_smoke()
    fresh = {(r["case"], r["variant"], r["seed"]): r for r in reg["rows"] if r["strategy"] == "single"}
    old = {(r["case"], r["variant"], r["seed"]): r for r in parent["rows"] if r["strategy"] == "single"}
    rows = []
    for case, variant, seed, status in SELECTION:
        key = (case, variant, seed)
        if old[key]["status"] != status or old[key]["requests"] != 1:
            raise ValueError("parent selection differs from diagnostic plan")
        if variant == "reference" and (old[key]["detected"] or len(old[key]["rounds"]) != 1):
            raise ValueError("correct control must have had a valid execution")
        rows.append(fresh[key])
    reg["rows"] = rows
    reg["theoretical_requests"] = len(SELECTION)
    reg["scope"] = "selected_failure_diagnostic_not_comparison"
    reg["study"] = {
        "name": "short_budget_prompt_clarity_diagnostic_v1",
        "selection": "five parent non-executions plus one correct FIFO seed1 control",
        "selected_after_parent_results": True,
        "parent_results_sha256": sha(PARENT),
        "not_a_new_comparison": True,
        "primary": "schema acceptance and within-budget valid execution of all six proposals",
        "secondary": "five selected defect detections and one correct-control false alarm",
        "caveat": "new stochastic proposals and two prompt clarifications change together; not single-factor causality",
        "original_comparison_unchanged": {"single": "15/24", "random": "16/24"},
    }
    reg["protocol"]["selection"] = reg["study"]["selection"]
    reg["prompt_profile"].update(strategies=["single"], repeats=None, study=reg["study"])
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    generated = {}
    for case in CASES:
        config = reg["protocol_config"]["cases"][case]
        source = ROOT / config["spec_path"]
        target = INPUTS / f"{case}_spec.md"
        content = normalize_spec(case, config["cycle_budget"], source.read_text(encoding="utf-8")).encode("utf-8")
        generated[target] = content
        relative = target.relative_to(ROOT).as_posix()
        config["spec_path"] = relative
        reg["code_and_input_sha256"][relative] = hashlib.sha256(content).hexdigest()
    for source in (Path(__file__).resolve(), PLAN, LEDGER, PARENT):
        reg["code_and_input_sha256"][source.relative_to(ROOT).as_posix()] = sha(source)
    return reg, generated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-key-file", type=Path)
    args = parser.parse_args(argv)
    try:
        reg, generated = preregister_diagnostic()
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "rows": len(reg["rows"]),
                          "requests": reg["theoretical_requests"], "new_comparison": False,
                          "output": str(OUTPUT)}))
        if not args.execute:
            return 0
        if OUTPUT.exists() or INPUTS.exists():
            raise ValueError("single-use diagnostic output or inputs already exist")
        if not args.api_key_file:
            raise ValueError("credential file required")
        key = read_key_file(args.api_key_file)
        INPUTS.mkdir(parents=True, exist_ok=False)
        for path, content in generated.items():
            with path.open("xb") as stream:
                stream.write(content)
        execute(reg, OUTPUT, endpoint="https://api.deepseek.com", model="deepseek-flash", key=key,
                request_cap=6, max_output_tokens=8192, wire_api="chat_completions", thinking_mode="disabled",
                iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
        return 0
    except Exception as exc:
        print(f"Diagnostic failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
