"""按核验过的官方价目表，把一次实验的 token 用量换算成费用区间。

为什么不能只报一个数：官方定价**分时段**（高峰/非高峰，相差一倍）且**输入分 cache
hit/miss**（相差最多 50 倍）。而我们的用量记录是逐请求的，`prompt_cache_hit_tokens` /
`prompt_cache_miss_tokens` 都在——所以能给的是**区间**而不是一个假装精确的数字。
刻意不去猜"当时是不是高峰"：那需要逐请求的时间戳与官方节假日规则，猜错就是把误差
藏起来。给区间，读者一眼就知道不确定度有多大。

用法：
    python scripts/estimate_model_cost.py .iverilog-ai/model-compare-r10-deepseek-flash
    python scripts/estimate_model_cost.py <目录> --pricing data/model_pricing.json --json

目录里需要有 `strategy_matrix.json`（带逐请求 `usage`）。按 `request_id` 去重：
一次请求的计划会被同案例的多个变体复用，按行累加会把 token 放大 6~13 倍。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from iverilog_ai.core.pricing import load_pricing  # noqa: E402


def collect_usage(matrix_path: Path) -> tuple[dict[str, int], int]:
    """按 `request_id` 去重后汇总用量。返回 (分项合计, 去重后的请求数)。"""

    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    seen: dict[str, dict[str, Any]] = {}
    for row in payload.get("runs", []):
        usage = row.get("usage")
        request_id = row.get("request_id")
        if isinstance(usage, dict) and request_id:
            seen.setdefault(str(request_id), usage)
    totals: dict[str, int] = {
        "prompt_cache_hit_tokens": sum(int(u.get("prompt_cache_hit_tokens") or 0) for u in seen.values()),
        "prompt_cache_miss_tokens": sum(int(u.get("prompt_cache_miss_tokens") or 0) for u in seen.values()),
        "completion_tokens": sum(int(u.get("completion_tokens") or 0) for u in seen.values()),
    }
    # 老记录可能没有 cache 分项，退回 prompt_tokens，避免把输入算成 0。
    if not totals["prompt_cache_hit_tokens"] and not totals["prompt_cache_miss_tokens"]:
        totals["prompt_cache_miss_tokens"] = sum(int(u.get("prompt_tokens") or 0) for u in seen.values())
    return totals, len(seen)


def _cost(detail: dict[str, Any], totals: dict[str, int], bucket: str) -> float:
    hit = detail.get("input_cache_hit", {}).get(bucket, 0.0)
    miss = detail.get("input_cache_miss", {}).get(bucket, 0.0)
    out = detail.get("output", {}).get(bucket, 0.0)
    return (
        totals["prompt_cache_hit_tokens"] / 1e6 * float(hit)
        + totals["prompt_cache_miss_tokens"] / 1e6 * float(miss)
        + totals["completion_tokens"] / 1e6 * float(out)
    )


def estimate(model: str, matrix_path: Path, pricing_path: Path) -> dict[str, Any]:
    table = load_pricing(path=pricing_path)
    row = table.lookup(model)
    totals, requests = collect_usage(matrix_path)
    result: dict[str, Any] = {
        "model": model,
        "matrix": str(matrix_path),
        "requests": requests,
        **totals,
    }
    detail = (row or {}).get("price_detail")
    if not row or not detail:
        result.update({
            "error": None if row else "价格表中没有该模型",
            "reason": "价格表里没有 price_detail，无法给出区间" if row else "价格表中没有该模型",
        })
        return result
    result.update({
        "currency": "USD",
        "off_peak": round(_cost(detail, totals, "off_peak"), 4),
        "peak": round(_cost(detail, totals, "peak"), 4),
        "basis": row.get("basis"),
        "verified_on": row.get("verified_on"),
        "source": row.get("source"),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="把实验 token 用量换算成费用区间")
    parser.add_argument("matrix", help="实验输出目录（含 strategy_matrix.json）")
    parser.add_argument("--model", default=None, help="模型名；默认从目录名里的 model-compare-r10-<model> 推断")
    parser.add_argument("--matrix-name", default="strategy_matrix.json")
    parser.add_argument("--pricing", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    directory = Path(args.matrix).expanduser().resolve()
    matrix_path = directory / args.matrix_name
    if not matrix_path.is_file():
        print(f"找不到 {matrix_path}", file=sys.stderr)
        return 2
    model = args.model
    if not model:
        name = directory.name
        model = name.split("model-compare-r10-", 1)[1] if "model-compare-r10-" in name else name
    pricing_path = Path(args.pricing).expanduser().resolve() if args.pricing else Path(__file__).resolve().parents[1] / "data" / "model_pricing.json"

    result = estimate(model, matrix_path, pricing_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif "off_peak" in result:
        print(f"{result['model']}：{result['requests']} 次请求（按 request_id 去重），"
              f"输入命中 {result['prompt_cache_hit_tokens']:,} / 未命中 {result['prompt_cache_miss_tokens']:,}，"
              f"输出 {result['completion_tokens']:,}")
        print(f"  费用区间 ${result['off_peak']:.3f}（非高峰）～ ${result['peak']:.3f}（高峰）"
              f"；口径：{result['basis']}")
        print(f"  价格核验于 {result['verified_on']}，来源 {result['source']}")
    else:
        print(f"{result['model']}：{result.get('reason') or result.get('error')}，只报用量不报金额", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
