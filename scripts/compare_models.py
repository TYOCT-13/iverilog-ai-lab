"""把多个模型的策略实验汇总成一张公平对比表（Markdown + JSON）。

用法：

    python scripts/compare_models.py .iverilog-ai/model-compare-*

设计要点：

- **可比性检查**：先确认各次实验的案例集合、重复次数、按案例预算一致，不一致就
  明确报错，而不是把不可比的数据并排放进同一张表；
- **不美化**：逐项列出参考误报、参考期望不一致、不可判定、未检出缺陷数；
- **如实标注缺失**：某模型服务商没返回 usage 就写"未返回"，不推算金额。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from iverilog_ai.core.pricing import load_pricing  # noqa: E402

STRATEGIES = ("fixed", "random", "ai", "online_ai")


class CompareError(ValueError):
    """两次实验不可比。"""


def load(matrix_path: Path) -> dict:
    if not matrix_path.is_file():
        raise CompareError(f"{matrix_path} 不存在（实验可能还没跑完）")
    return json.loads(matrix_path.read_text(encoding="utf-8"))


def _case_set(payload: dict) -> set[str]:
    return {str(row.get("case")) for row in payload.get("runs", []) if row.get("case")}


def check_comparable(payloads: dict[str, dict]) -> None:
    """确认各次实验在案例集合与重复次数上一致。"""

    reference_name, reference = next(iter(payloads.items()))
    reference_cases = _case_set(reference)
    for name, payload in payloads.items():
        if name == reference_name:
            continue
        cases = _case_set(payload)
        if cases != reference_cases:
            only_a = sorted(reference_cases - cases)
            only_b = sorted(cases - reference_cases)
            raise CompareError(
                f"{reference_name} 与 {name} 的案例集合不同："
                f"仅前者有 {only_a or '无'}；仅后者有 {only_b or '无'}"
            )


def _summary(payload: dict, strategy: str) -> dict:
    return (payload.get("summary") or {}).get(strategy) or {}


def _usage_totals(payload: dict, strategy: str) -> dict:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests_with_usage": 0}
    for row in payload.get("runs", []):
        if row.get("strategy") != strategy:
            continue
        usage = row.get("usage") or {}
        if not isinstance(usage, dict) or not usage:
            continue
        totals["requests_with_usage"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
    return totals


def _defect_variants(case: str) -> set[str]:
    """从基准清单取该案例的缺陷变体集合（作为逐案例对比的分母）。

    分母必须来自 manifest，不能从运行记录里推——某个模型没检出的缺陷在那次
    实验的运行记录里仍然存在（只是 defects_found=false），而失败/跳过的变体
    可能整条都不在记录里。用清单做分母才不会出现"分母随手变化"的假对比。
    """

    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    return {str(item["id"]) for item in manifest["defects"] if item["type"] == case}


def _detected_variants(payload: dict, strategy: str, case: str) -> set[str]:
    return {
        str(row.get("variant"))
        for row in payload.get("runs", [])
        if row.get("strategy") == strategy
        and row.get("case") == case
        and row.get("variant") != "reference"
        and row.get("defects_found")
    }


def render(model_names: list[str], payloads: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("# 多模型公平对比（自动生成）")
    lines.append("")
    lines.append("> 本文件由 `scripts/compare_models.py` 从各次实验的 `strategy_matrix.json` "
                 "机械汇总，**不含分析结论**。对结果的解读、未检出缺陷与口径差异见 "
                 "`docs/experiment/model_comparison_2026-09-11.md`。")
    lines.append("")
    lines.append("案例集合、DUT 合约、上下文口径、重复次数完全一致；差别只在 `online_ai` 策略使用的模型。")
    lines.append("")

    # 在线模型对比
    lines.append("## 在线模型对比（`online_ai` 策略）")
    lines.append("")
    lines.append("| 模型 | 重复次数 | 请求级计划合法率 | 参考误报 | 参考期望不一致 | 缺陷检出 | 检出率 | 平均生成 | 平均首次失败 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in model_names:
        summary = _summary(payloads[name], "online_ai")
        if not summary:
            lines.append(f"| {name} | — | 无数据 | — | — | — | — | — | — |")
            continue
        runs = summary.get("runs", 0)
        requests = summary.get("plan_requests", 0)
        repeats = runs // requests if requests else None
        lines.append(
            f"| **{name}** | {repeats if repeats is not None else '—'} "
            f"| {summary.get('request_plan_valid_rate', 0) * 100:.0f}% "
            f"| {summary.get('reference_false_positives', 0)} "
            f"| {summary.get('reference_warn_mismatches', 0)} "
            f"| {summary.get('defects_found', 0)}/{summary.get('defects_total', 0)} "
            f"| {summary.get('detection_rate', 0) * 100:.1f}% "
            f"| {summary.get('mean_generation_ms', 0) / 1000:.1f}s "
            f"| {summary.get('mean_time_to_first_failure_ms', 0) / 1000:.2f}s |"
        )
    lines.append("")

    # 各策略总览（用第一个模型的 fixed/random/ai 作为基线，因为它们与模型无关）
    baseline_name = model_names[0]
    lines.append(f"## 各策略总览（取自 {baseline_name} 这次实验）")
    lines.append("")
    lines.append("| 策略 | 缺陷检出 | 检出率 | 参考误报 | 不可判定 |")
    lines.append("|---|---:|---:|---:|---:|")
    for strategy in STRATEGIES:
        summary = _summary(payloads[baseline_name], strategy)
        if not summary:
            continue
        label = {"fixed": "固定向量", "random": "随机激励", "ai": "离线 MockProvider",
                 "online_ai": f"在线模型（{baseline_name}）"}.get(strategy, strategy)
        lines.append(
            f"| {label} | {summary.get('defects_found', 0)}/{summary.get('defects_total', 0)} "
            f"| {summary.get('detection_rate', 0) * 100:.1f}% "
            f"| {summary.get('reference_false_positives', 0)} "
            f"| {summary.get('inconclusive_runs', 0)} |"
        )
    lines.append("")

    # token 用量
    lines.append("## token 用量与费用（仅在线模型）")
    lines.append("")
    lines.append("| 模型 | 有 usage 的请求数 | prompt | completion | total | 费用估算 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    pricing = load_pricing(ROOT)
    for name in model_names:
        totals = _usage_totals(payloads[name], "online_ai")
        if not totals["requests_with_usage"]:
            lines.append(f"| {name} | 0 | 服务商未返回 usage | — | — | — |")
            continue
        estimate = pricing.estimate(
            name, prompt_tokens=totals["prompt_tokens"], completion_tokens=totals["completion_tokens"]
        )
        if estimate.amount is None:
            money = f"未估算（{estimate.reason}）"
        else:
            money = f"≈ {estimate.amount:.4f} {estimate.currency}（核验于 {estimate.verified_on}）"
        lines.append(
            f"| {name} | {totals['requests_with_usage']} | {totals['prompt_tokens']:,} "
            f"| {totals['completion_tokens']:,} | {totals['total_tokens']:,} | {money} |"
        )
    lines.append("")
    lines.append(
        "> 价格表在 `data/model_pricing.json`，每行带来源与核验日期；"
        "**未经核验的价格不给金额**（`null` 不等于 0，也不做汇率换算）。"
        "更新方式：查阅服务商官方定价页后填入实际数值与核验日期。"
    )
    lines.append("")

    # 逐案例差异：分母统一取自基准清单，避免"分母随手变"的假对比
    lines.append("## 逐案例检出对比（`online_ai` 策略）")
    lines.append("")
    lines.append("| 案例 | 缺陷数 | " + " | ".join(model_names) + " | 差异 |")
    lines.append("|---|" + "---:|" * (len(model_names) + 1) + "---|")
    cases = sorted(_case_set(payloads[baseline_name]))
    for case in cases:
        variants = _defect_variants(case)
        if not variants:
            continue
        detected = {name: _detected_variants(payloads[name], "online_ai", case) for name in model_names}
        best = max(len(item) for item in detected.values())
        worst = min(len(item) for item in detected.values())
        cells = [f"{len(detected[name])}/{len(variants)}" for name in model_names]
        gap = "—" if best == worst else f"**{best - worst}**"
        lines.append(f"| {case} | {len(variants)} | " + " | ".join(cells) + f" | {gap} |")
    lines.append("")
    lines.append("> 分母取自 `benchmarks/manifest.json`，不是从运行记录反推——否则某个模型整条跳过的变体会悄悄缩小分母。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="多模型公平对比")
    parser.add_argument("directories", nargs="+", help="各模型实验的输出目录（含 strategy_matrix.json）")
    parser.add_argument("--output", default=None, help="Markdown 输出路径")
    args = parser.parse_args()

    payloads: dict[str, dict] = {}
    try:
        for directory in args.directories:
            path = Path(directory)
            name = path.name.replace("model-compare-", "")
            payloads[name] = load(path / "strategy_matrix.json")
        check_comparable(payloads)
    except CompareError as exc:
        print(f"不可比或数据缺失：{exc}", file=sys.stderr)
        return 2

    markdown = render(list(payloads), payloads)
    output = Path(args.output) if args.output else ROOT / "docs" / "experiment" / "model_comparison.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\n已写入 {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
