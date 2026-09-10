"""Deterministic failure-window summaries for simulation records.

The summary deliberately does not require GTKWave or a VCD parser.  It uses the
structured records emitted by the controlled testbench, making it portable and
safe to embed in reports/UI.  When records contain ``time_ns``/``timestamp_ns``
in ``data`` those values are preserved, but cycle remains the primary key.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _get(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _row(record: object) -> dict[str, Any]:
    data = _get(record, "data", {})
    data = dict(data) if isinstance(data, Mapping) else {}
    result = {
        "cycle": _get(record, "cycle"),
        "test_id": _get(record, "test_id"),
        "signal": _get(record, "signal"),
        "ok": bool(_get(record, "ok", False)),
        "expected": _get(record, "expected"),
        "actual": _get(record, "actual"),
        "severity": _get(record, "severity", "warn"),
    }
    for key in ("time_ns", "timestamp_ns", "time"):
        if key in data:
            result[key] = data[key]
    return result


def summarize_failure_window(
    records: Sequence[object],
    failures: Sequence[object] = (),
    *,
    radius: int = 2,
    max_rows: int = 200,
) -> dict[str, Any]:
    """Return rows around each failed cycle.

    ``radius`` is the number of cycles on either side of a failure.  Failures
    without a cycle are represented in ``uncorrelated_failures``.  Ordering and
    de-duplication are deterministic, and input objects are never modified.
    """
    if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
        raise ValueError("radius must be a non-negative integer")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    rows = [_row(item) for item in records]
    rows.sort(key=lambda r: (r["cycle"] is None, r["cycle"] if r["cycle"] is not None else 0,
                             str(r["test_id"] or ""), str(r["signal"] or "")))
    failure_rows = [_row(item) for item in failures]
    cycles = sorted({r["cycle"] for r in failure_rows if isinstance(r["cycle"], int)})
    selected = [r for r in rows if isinstance(r["cycle"], int) and any(abs(r["cycle"] - c) <= radius for c in cycles)]
    if not cycles and failure_rows:
        selected = []
    truncated = len(selected) > max_rows
    selected = selected[:max_rows]
    return {
        "radius": radius,
        "failure_cycles": cycles,
        "rows": selected,
        "uncorrelated_failures": [r for r in failure_rows if r["cycle"] is None],
        "truncated": truncated,
        "total_rows": len(selected),
    }


def render_failure_window(summary: Mapping[str, Any]) -> str:
    """Render a compact, offline Markdown waveform-style table."""
    cycles = summary.get("failure_cycles", [])
    lines = [
        "### 失败周期附近波形摘要",
        "",
        f"失败周期：{', '.join(str(c) for c in cycles) if cycles else '未提供周期'}",
        f"窗口半径：{summary.get('radius', 0)} 周期",
        "",
        "| 周期 | 测试 | 信号 | 期望 | 实际 | 结果 |",
        "|---:|---|---|---|---|---|",
    ]
    for row in summary.get("rows", []):
        cycle = "" if row.get("cycle") is None else str(row["cycle"])
        status = "PASS" if row.get("ok") else str(row.get("severity", "WARN")).upper()
        vals = [cycle, row.get("test_id") or "", row.get("signal") or "", row.get("expected"), row.get("actual"), status]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in vals) + " |")
    if summary.get("truncated"):
        lines.extend(["", "> 摘要行数已截断；请结合完整结构化记录或 VCD 文件继续分析。"])
    if summary.get("uncorrelated_failures"):
        lines.extend(["", f"> {len(summary['uncorrelated_failures'])} 条失败没有周期信息，无法关联窗口。"])
    return "\n".join(lines)


__all__ = ["summarize_failure_window", "render_failure_window"]
