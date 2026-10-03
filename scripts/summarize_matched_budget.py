"""Re-score archived strategy rows on a common seed prefix, without model calls.

This is a post-hoc analysis, not a newly executed or preregistered experiment.
The fixed strategy remains its one observed run; it is never duplicated to
pretend that five independent fixed-strategy runs were executed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from iverilog_ai.core.strategy_scoring import budget_for, classify_undecidable, summarize


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("fixed", "random", "ai", "online_ai")
ROW_FIELDS = (
    "strategy", "case", "variant", "seed", "request_id", "budget_cycles",
    "total_cycles", "plan_valid", "plan_sha256", "status", "defects_found",
    "check_count", "warning_failures", "error_failures", "usage", "attempts",
    "model", "undecidable_reason",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count each plan request once, exposing incomplete provider usage."""
    requests: dict[str, dict[str, Any]] = {}
    for row in rows:
        request_id = str(row["request_id"])
        existing = requests.setdefault(request_id, {"usage": None, "valid": True})
        existing["valid"] = existing["valid"] and bool(row.get("plan_valid"))
        usage = row.get("usage")
        if usage:
            if existing["usage"] is not None and existing["usage"] != usage:
                raise ValueError(f"Inconsistent usage for request {request_id}")
            existing["usage"] = usage
    known = [entry["usage"] for entry in requests.values() if entry["usage"]]
    missing = sorted(key for key, entry in requests.items() if not entry["usage"])
    return {
        "plan_requests": len(requests),
        "invalid_plan_requests": sum(not entry["valid"] for entry in requests.values()),
        "requests_with_usage": len(known),
        "requests_without_usage": len(missing),
        "missing_usage_request_ids": missing,
        "known_prompt_tokens": sum(int(usage.get("prompt_tokens") or 0) for usage in known),
        "known_completion_tokens": sum(int(usage.get("completion_tokens") or 0) for usage in known),
        "known_total_tokens": sum(int(usage.get("total_tokens") or 0) for usage in known),
        "known_reasoning_tokens": sum(
            int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            for usage in known
        ),
        "known_cache_hit_tokens": sum(int(usage.get("prompt_cache_hit_tokens") or 0) for usage in known),
        "known_cache_miss_tokens": sum(int(usage.get("prompt_cache_miss_tokens") or 0) for usage in known),
        "usage_scope": "Recorded provider usage deduplicated by request_id; not a billing audit.",
    }


def build_summary(source: dict[str, Any], manifest: dict[str, Any], rounds: int = 5) -> dict[str, Any]:
    """Analyze recorded rows; no file writes, simulation, or API requests."""
    if rounds < 1:
        raise ValueError("rounds must be positive")
    if source.get("partial"):
        raise ValueError("The source archive is incomplete")
    skipped = source.get("skipped_cases", {})
    cases = sorted(str(case) for case in manifest["categories"] if case not in skipped)
    pairs = sorted((str(item["type"]), str(item["id"])) for item in manifest["defects"] if item["type"] in cases)
    if not pairs or len(pairs) != len(set(pairs)):
        raise ValueError("The manifest must contain a nonempty unique defect set")
    pair_set = set(pairs)
    selected = [deepcopy(row) for row in source["runs"] if row["strategy"] in STRATEGIES and
                int(row["seed"]) in (range(1) if row["strategy"] == "fixed" else range(rounds))]
    counts: dict[str, int] = {strategy: 1 if strategy == "fixed" else rounds for strategy in STRATEGIES}
    seen: set[tuple[str, str, str, int]] = set()
    references: set[tuple[str, str, int]] = set()
    budgets: dict[str, dict[str, int]] = {case: {"cycles_per_run": budget_for(case).cycles} for case in cases}
    checked_cycles = 0
    unexecuted_cycles = 0
    for row in selected:
        strategy, case, variant, seed = str(row["strategy"]), str(row["case"]), str(row["variant"]), int(row["seed"])
        key = strategy, case, variant, seed
        if key in seen:
            raise ValueError(f"Duplicate archived run: {key}")
        seen.add(key)
        if case not in cases or (variant not in {"reference", "plan_generation"} and (case, variant) not in pair_set):
            raise ValueError(f"Archived row is outside the manifest: {key}")
        if variant == "reference":
            references.add((strategy, case, seed))
        expected = budgets[case]["cycles_per_run"]
        if row.get("budget_cycles") != expected:
            raise ValueError(f"Declared cycle budget mismatch: {key}")
        actual = row.get("total_cycles")
        if actual == expected:
            checked_cycles += 1
        elif row.get("status") in {"passed", "passed_with_warnings", "failed"}:
            raise ValueError(f"Executed cycle budget mismatch: {key}: {actual} != {expected}")
        elif actual not in {None, 0}:
            raise ValueError(f"Partial/nonmatching cycle budget: {key}: {actual} != {expected}")
        else:
            unexecuted_cycles += 1
    for strategy in STRATEGIES:
        for case in cases:
            for seed in range(counts[strategy]):
                if (strategy, case, seed) not in references:
                    raise ValueError(f"Missing reference row: {(strategy, case, seed)}")
    scores = summarize(selected, pairs=pairs, strategies=STRATEGIES, rounds=counts)
    for strategy in STRATEGIES:
        rows = [row for row in selected if row["strategy"] == strategy]
        item = scores[strategy]
        item["request_usage"] = _request_usage(rows)
        item["status_counts"] = dict(sorted(Counter(str(row.get("status")) for row in rows).items()))
        item["invalid_plan_rows"] = sum(not row.get("plan_valid", False) for row in rows)
        alarming = {(str(row["case"]), int(row["seed"])) for row in rows if row["variant"] == "reference"
                    and (row.get("warning_failures") or row.get("error_failures"))}
        detections: dict[int, set[tuple[str, str]]] = {seed: set() for seed in range(counts[strategy])}
        for row in rows:
            if row["variant"] in {"reference", "plan_generation"}:
                continue
            seed, case = int(row["seed"]), str(row["case"])
            reason = classify_undecidable(
                row.get("status"), defects_found=bool(row.get("defects_found")),
                check_count=row.get("check_count"), variant=str(row["variant"]),
                reference_alarm=(case, seed) in alarming,
            )
            if reason is None and row.get("defects_found"):
                detections[seed].add((case, str(row["variant"])))
        item["per_seed"] = [
            {"seed": seed, "defects_found": len(found), "detection_rate": len(found) / len(pairs),
             "detected_pairs": [list(pair) for pair in sorted(found)]}
            for seed, found in detections.items()
        ]
        union = set().union(*detections.values())
        item["detected_pairs"] = [list(pair) for pair in sorted(union)]
        item["missed_pairs"] = [list(pair) for pair in pairs if pair not in union]
        # The display/export list must obey exactly the same scorer as the metrics.
        if len(union) != item["defects_found"]:
            raise ValueError("Detection inventory disagrees with the scoring policy")
    online = {tuple(pair) for pair in scores["online_ai"]["detected_pairs"]}
    random = {tuple(pair) for pair in scores["random"]["detected_pairs"]}
    random_plans = {(row["case"], row["seed"]): row.get("plan_sha256") for row in selected if row["strategy"] == "random"}
    mock_plans = {(row["case"], row["seed"]): row.get("plan_sha256") for row in selected if row["strategy"] == "ai"}
    return {
        "schema_version": "1.0",
        "analysis_kind": "post_hoc_common_seed_prefix",
        "selection": {"seeds": list(range(rounds)), "fixed_seeds": [0], "strategies": list(STRATEGIES)},
        "case_count": len(cases), "defect_denominator": len(pairs), "cases": cases,
        "skipped_cases": skipped, "selected_row_count": len(selected),
        "historical_seed_sets": (source.get("original_archive") or {}).get("historical_seed_sets") or {
            strategy: sorted({int(row["seed"]) for row in source["runs"] if row["strategy"] == strategy}) for strategy in STRATEGIES
        },
        "historical_summary": (source.get("original_archive") or {}).get("historical_summary") or source.get("summary", {}),
        "budget_audit": {"per_case": budgets, "rows_with_matching_executed_cycles": checked_cycles,
                         "unexecuted_rows": unexecuted_cycles, "missing_variant_rows": sum(item["undecidable_missing"] for item in scores.values())},
        "mock_matches_random_plan_hashes": bool(random_plans) and all(random_plans.values()) and random_plans == mock_plans,
        "summary": scores,
        "online_vs_random": {"net_additional_defects": len(online) - len(random),
                             "online_only_pairs": [list(pair) for pair in sorted(online - random)],
                             "random_only_pairs": [list(pair) for pair in sorted(random - online)]},
    }


def render_report(result: dict[str, Any]) -> str:
    scores = result["summary"]
    rounds = len(result["selection"]["seeds"])
    usage = scores["online_ai"]["request_usage"]
    lines = [
        "# 同轮数、同单次刺激预算：历史数据重汇总", "",
        "这是对已完成实验的**事后共同 seed 子集分析**，不是新实验，也不是预注册验证。没有重新调用模型或运行仿真。",
        f"对 random、ai（MockProvider）、online_ai 一律选择 seed 0–{rounds - 1}，各 {rounds} 轮；选择规则是共同连续前缀，没有按检出率挑轮次。",
        "相同 seed 编号只是历史轮次对齐，不表示在线模型与随机策略使用相同随机源或生成同样激励。原有 10 轮在线记录完整保留。", "",
        f"fixed 是已记录的一轮确定性人工激励参照，不能说成实跑了 {rounds} 轮，也不参与‘{rounds} 轮总刺激预算相同’的比较。", "",
        "## 结果", "",
        "| 策略 | 实际轮数 | 累计检出 | 单轮平均 | 单轮范围 | 不可判定变体行 | 参考告警失效变体（去重） |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"fixed": "人工固定（单轮参照）", "random": "随机", "ai": "Mock 回放随机计划", "online_ai": "在线 deepseek-flash"}
    for strategy in STRATEGIES:
        item = scores[strategy]
        lines.append(f"| {labels[strategy]} | {item['rounds']} | {item['defects_found']}/{item['defects_total']}（{item['detection_rate']:.1%}） | {item['detection_rate_single_round_mean']:.1%} | {item['detection_rate_single_round_min']:.1%}–{item['detection_rate_single_round_max']:.1%} | {item['undecidable_runs']} | {item['plans_excluded_by_reference_alarm']} |")
    online, random, fixed = scores["online_ai"], scores["random"], scores["fixed"]
    relation = "低于" if online["detection_rate_single_round_mean"] < fixed["detection_rate"] else "不低于"
    lines += ["", f"在所选共同子集中，在线模型累计检出 {online['defects_found']}/{online['defects_total']}，随机为 {random['defects_found']}/{random['defects_total']}，净多 {online['defects_found'] - random['defects_found']} 个；单轮平均分别为 {online['detection_rate_single_round_mean']:.1%}、{random['detection_rate_single_round_mean']:.1%}。",
              f"人工固定单轮参照为 {fixed['detection_rate']:.1%}；在线模型单轮平均{relation}该参照。样本仅覆盖这些内置案例和 {rounds} 个历史轮次，不能推广为 AI 普遍优于人工，也没有进行显著性或独立留出集检验。", "",
              "## 计分与预算核对", "",
              "- 分母从 manifest 的参与案例中固定提取；缺失、生成失败、编译失败、超时、无可比检查等按现有 `strategy_scoring.summarize` 记为不可判定且仍留在分母。",
              "- 同一（案例，seed）的参考 RTL 出现功能告警时，相关变体行的检出作废。变体的 `passed_with_warnings` 可表示真实功能差异，不能一律当作执行失败。",
              f"- 本次所选记录的不可判定变体行总数为 {sum(item['undecidable_runs'] for item in scores.values())}；参考告警失效行总数为 {sum(item['undecidable_by_reason'].get('reference_false_alarm', 0) for item in scores.values())}。表格末列按（案例，变体）去重，JSON 同时保留失效行数与告警计划数。",
              f"- 共核对 {result['budget_audit']['rows_with_matching_executed_cycles']} 条执行记录的 `total_cycles == budget_cycles`；缺失变体记录 {result['budget_audit']['missing_variant_rows']}，未执行记录 {result['budget_audit']['unexecuted_rows']}。",
              f"- 三种 {rounds} 轮策略逐案例的单次、累计周期预算相同。Mock 与随机计划哈希一致：{result['mock_matches_random_plan_hashes']}；Mock 回放不是独立的模型能力证据。", "",
              f"| 案例 | 每次周期预算 | 三种 {rounds} 轮策略的每变体累计周期 |", "|---|---:|---:|"]
    for case, budget in result["budget_audit"]["per_case"].items():
        cycles = budget["cycles_per_run"]
        lines.append(f"| {case} | {cycles} | {rounds * cycles} |")
    lines += ["", "## 在线请求记录", "",
              f"所选子集共有 {usage['plan_requests']} 个计划请求，只有 {usage['requests_with_usage']} 个含 provider usage，另有 {usage['requests_without_usage']} 个没有 usage。按 `request_id` 去重，不能把同一请求在多个变体上的记录重复相加。", "",
              f"已记录 prompt tokens：**{usage['known_prompt_tokens']:,}**；completion tokens：**{usage['known_completion_tokens']:,}**；total tokens：**{usage['known_total_tokens']:,}**。",
              f"其中 reasoning tokens 为 **{usage['known_reasoning_tokens']:,}**，是 completion 的子集，不再额外相加。cache hit/miss 分别为 {usage['known_cache_hit_tokens']:,}/{usage['known_cache_miss_tokens']:,}。",
              "这些数值仅汇总保存下来的 usage，不是完整账单、付费 HTTP 调用数量或实付费用；没有 usage 不等于零费用。", "",
              "缺少 usage 的计划请求：", ""]
    lines += [f"- `{request_id}`" for request_id in usage["missing_usage_request_ids"]]
    lines += ["", "## 复现与文件", "",
              "在仓库根目录执行（仅读取本地文件，不联网）：", "", "```powershell",
              "python scripts/summarize_matched_budget.py --rounds 5 --output-dir docs/experiment/matched-budget-2026-10-04",
              "```", "", "也可用随本报告保存的精简输入快照复核到其他目录：", "", "```powershell",
              "python scripts/summarize_matched_budget.py --source docs/experiment/matched-budget-2026-10-04/selected_runs.json --rounds 5 --output-dir .iverilog-ai/matched-budget-replay",
              "```", "",
              "- `summary.json`：完整汇总、逐 seed 检出列表、参考失效/失败统计、预算审计、缺少 usage 的请求及输入 SHA-256。",
              "- `selected_runs.json`：仅保留计分、预算、请求去重所需的原始字段；不含 API 密钥、原始提示或本机仿真路径。它是可独立复核的派生产物，不能代替原始完整实验。",
              "- 原始输入 `.iverilog-ai/strategy-online-flash/strategy_matrix.json` 保持不变；其中未选中的历史记录不能删除或并入本子集统计。", ""]
    history = result.get("historical_summary", {}).get("online_ai")
    if history:
        lines += [f"原始在线历史为 **{history['rounds']} 轮**，累计 **{history['defects_found']}/{history['defects_total']}**、单轮均值 **{history['detection_rate_single_round_mean']:.1%}**；不可判定变体行 **{history['undecidable_runs']}**，其中参考告警失效行 **{history['undecidable_by_reason'].get('reference_false_alarm', 0)}**。与本报告 {rounds} 轮子集是不同统计口径，不能互换。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".iverilog-ai/strategy-online-flash/strategy_matrix.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "benchmarks/manifest.json")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/experiment/matched-budget-2026-10-04")
    args = parser.parse_args()
    source_path, manifest_path, output = args.source.resolve(), args.manifest.resolve(), args.output_dir.resolve()
    if any(path == source_path or path == manifest_path for path in (output / "summary.json", output / "README.md", output / "selected_runs.json")):
        raise ValueError("Output must not overwrite an input file; use a different output directory")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = build_summary(source, manifest, args.rounds)
    result["provenance"] = {
        "input_name": source_path.name, "input_sha256": _sha(source_path), "manifest_sha256": _sha(manifest_path),
        "script_sha256": _sha(Path(__file__)), "scoring_sha256": _sha(ROOT / "src/iverilog_ai/core/strategy_scoring.py"),
        "source_code_revision": source.get("code_revision"), "source_working_tree_dirty": source.get("working_tree_dirty"),
        "source_started_at": source.get("started_at"), "source_finished_at": source.get("finished_at"),
        "original_archive": source.get("original_archive"),
    }
    source_rows = [row for row in source["runs"] if row["strategy"] in STRATEGIES and
                   int(row["seed"]) in (range(1) if row["strategy"] == "fixed" else range(args.rounds))]
    snapshot = {key: source.get(key) for key in ("schema_version", "partial", "code_revision", "working_tree_dirty", "started_at", "finished_at", "skipped_cases")}
    snapshot["original_archive"] = source.get("original_archive") or {
        "sha256": _sha(source_path), "historical_seed_sets": result["historical_seed_sets"],
        "historical_summary": result["historical_summary"],
    }
    snapshot["runs"] = [{key: row[key] for key in ROW_FIELDS if key in row} for row in source_rows]
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "selected_runs.json").write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (output / "README.md").write_text(render_report(result), encoding="utf-8")
    print(f"Wrote matched-budget analysis: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
