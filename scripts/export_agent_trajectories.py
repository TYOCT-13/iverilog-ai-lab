"""将 API 轨迹导出为待人工筛选的 SFT 候选数据；不训练、不上传。"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from iverilog_ai.ai.agent import AgentDecision, PROMPT_VERSION, decision_messages


def export(paths: list[Path], output: Path, holdout: set[str]) -> dict[str, Any]:
    if output.exists():
        raise ValueError("output directory already exists")
    examples: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
    seen: set[str] = set()
    rejected: dict[str, int] = {}
    sources = []
    families: dict[str, set[str]] = {"train": set(), "validation": set()}
    for path in sorted(set(p.resolve() for p in paths)):
        raw = path.read_bytes()
        trace = json.loads(raw)
        if trace.get("schema_version") != "1.0" or trace.get("prompt_version") != PROMPT_VERSION or trace.get("record_kind") != "api":
            rejected["non_api_or_unknown_version"] = rejected.get("non_api_or_unknown_version", 0) + 1
            continue
        family = trace["design_family"]
        split = "validation" if family in holdout else "train"
        rounds = {row["round"]: row for row in trace["rounds"]}
        sources.append({"sha256": hashlib.sha256(raw).hexdigest(), "family": family,
                        "rtl_sha256": trace["rtl_sha256"], "split": split})
        for row in trace["decisions"]:
            executed = rounds.get(row.get("executed_round"))
            if row.get("status") != "validated" or not executed:
                rejected["not_executed"] = rejected.get("not_executed", 0) + 1
                continue
            observation = executed["observation"]
            if observation["expectation_source"] != "reference_model" or not observation["checks"] or observation["status"] not in {"passed", "passed_with_warnings"}:
                rejected["unverified_execution"] = rejected.get("unverified_execution", 0) + 1
                continue
            action = AgentDecision.model_validate(row["action"]).model_dump(mode="json")
            messages = decision_messages(row["state"])
            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            identity = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            families[split].add(family)
            examples[split].append({"messages": messages, "design_family": family,
                                    "source_trace_sha256": sources[-1]["sha256"],
                                    "review_status": "pending", "observed_verdict": observation["verdict"]})
    if not all(examples.values()):
        raise ValueError("both train and validation need executed API examples from distinct design families")
    assert not families["train"] & families["validation"]
    # 同一 RTL 内容即使改名也不能跨集合。
    hashes = {split: {s["rtl_sha256"] for s in sources if s["split"] == split} for split in examples}
    if hashes["train"] & hashes["validation"]:
        raise ValueError("RTL content overlaps between train and validation")
    manifest = {"schema_version": "1.0", "purpose": "sft_candidates_pending_human_review",
                "prompt_version": PROMPT_VERSION, "counts": {k: len(v) for k, v in examples.items()},
                "families": {k: sorted(v) for k, v in families.items()}, "excluded": rejected,
                "sources": sources, "limitations": ["No model training or upload performed", "Execution validity is not evidence of useful new coverage", "Related modules with different names require manual grouping before training"]}
    output.mkdir(parents=True, exist_ok=False)
    for split, records in examples.items():
        (output / f"{split}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--holdout-designs", nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths: list[Path] = []
        for pattern in args.inputs:
            matched = glob.glob(pattern, recursive=True)
            if not matched:
                raise ValueError("input pattern matched no files")
            paths.extend(Path(x) for x in matched)
        manifest = export(paths, args.output_dir, set(args.holdout_designs))
        print(json.dumps({"counts": manifest["counts"], "families": manifest["families"], "excluded": manifest["excluded"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Export refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
