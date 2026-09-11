"""Run the reproducible synthesis matrix (Yosys, generic gate level).

`docs/layered_evidence.md` claims that every reference design *and* every defect
variant is synthesizable.  That claim used to be backed by an ad-hoc command, so
a reader could not re-run it.  This script makes it reproducible: it walks the
same case table as the simulation matrix, synthesizes each RTL file with
`YosysSynthRunner`, and writes a JSON/Markdown summary.

Judgement rules (deliberately strict):

* a variant counts as synthesized only when Yosys actually produced `stat -json`
  output -- the WASM build can abort during ABC while still exiting 0;
* `unavailable` / `timeout` / `error` are **not** counted as passes and make the
  exit code non-zero, because "we could not check" is not evidence;
* defects are *functional*, so a synthesizable defect is the expected result.
  A defect that fails to synthesize is reported loudly, not hidden.

This layer never participates in PASS/FAIL: it only says whether the RTL can be
mapped to generic cells.  No timing, no bitstream, no hardware.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from iverilog_ai.core.benchmark_cases import case_table, load_manifest
from iverilog_ai.core.synthesis import (
    ERROR,
    FAILED,
    PASSED,
    TIMEOUT,
    UNAVAILABLE,
    SynthConfig,
    YosysSynthRunner,
    find_yosys,
)


def _variants(root: Path) -> list[dict[str, str]]:
    """参考设计与全部缺陷变体，顺序与基准矩阵一致（参考在前）。

    顶层模块名一律取**参考 RTL** 的模块名：缺陷变体是参考设计的改动副本，
    模块名保持不变（例如 `rtl/mod10_counter_bug_enable.v` 里仍是
    `module mod10_counter`）。若按文件名推顶层，80 个缺陷会全部报"找不到顶层"。
    """

    cases = case_table(root)
    manifest = load_manifest(root)
    variants: list[dict[str, str]] = []
    for case, info in cases.items():
        variants.append(
            {
                "case": case,
                "variant": "reference",
                "kind": "reference",
                "rtl": info["rtl"],
                # 综合的是 RTL 本身，顶层就是参考设计的模块名；testbench 不参与综合。
                "top": Path(info["rtl"]).stem,
            }
        )
    for defect in manifest.get("defects", []):
        case = str(defect["type"])
        info = cases[case]
        rtl = str(defect["file"])
        variants.append(
            {
                "case": case,
                "variant": str(defect["id"]),
                "kind": "defect",
                "rtl": rtl,
                "top": Path(info["rtl"]).stem,
            }
        )
    return variants


def _markdown(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    lines = [
        "# Synthesis matrix result",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Yosys: `{payload['yosys']}`",
        f"- Variants: **{s['total']}** = {s['references']} reference + {s['defects']} defect",
        f"- Synthesized (got statistics): **{s['passed']}**",
        f"- Failed to synthesize: **{s['failed']}**",
        f"- Not checkable (unavailable/timeout/error): **{s['not_checked']}**",
        "",
        "> Synthesis at generic gate level (Yosys `synth -run begin:fine`).",
        "> No timing model, no pin constraints, no bitstream, no hardware.",
        "> This layer never decides PASS/FAIL.",
        "",
        "| case | variant | kind | status | cells | cell kinds | ms |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in payload["runs"]:
        cells = "-" if row["cell_count"] is None else str(row["cell_count"])
        kinds = "-" if row["cell_kinds"] is None else str(row["cell_kinds"])
        lines.append(
            f"| `{row['case']}` | `{row['variant']}` | {row['kind']} | `{row['status']}` | "
            f"{cells} | {kinds} | {row['duration_ms']} |"
        )
    lines.extend(["", "Per-variant Yosys logs are retained under the output directory.", ""])
    return "\n".join(lines)


def run_synthesis_matrix(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    yosys_path: str | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    output_root = (
        Path(output_dir) if output_dir is not None else root / ".iverilog-ai" / "synthesis-matrix"
    ).expanduser().resolve()
    try:
        output_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must remain inside project_root") from exc
    output_root.mkdir(parents=True, exist_ok=True)
    variants = _variants(root)
    yosys = find_yosys(yosys_path)
    started = time.perf_counter()
    runs: list[dict[str, Any]] = []
    for item in variants:
        work_dir = output_root / item["variant"]
        config = SynthConfig(
            rtl_path=root / item["rtl"],
            top=item["top"],
            work_dir=work_dir,
            yosys_path=yosys_path,
            timeout_s=timeout,
        )
        result = YosysSynthRunner(config).run()
        runs.append(
            {
                **item,
                "status": result.status,
                "cell_count": result.cell_count,
                "wire_count": result.wire_count,
                "cell_kinds": result.cell_kinds if result.status in {PASSED, FAILED} else None,
                "memories": result.memory_count,
                "cells": [{"cell": name, "count": count} for name, count in result.cells],
                "duration_ms": result.duration_ms,
                "error": result.error,
                "skipped_reason": result.skipped_reason,
                "log_path": result.log_path,
                "artifact_path": str(work_dir),
            }
        )
    references = [row for row in runs if row["kind"] == "reference"]
    defects = [row for row in runs if row["kind"] == "defect"]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_root": str(root),
        "output_dir": str(output_root),
        "yosys": yosys or "",
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "runs": runs,
        "summary": {
            "total": len(runs),
            "references": len(references),
            "defects": len(defects),
            "passed": sum(1 for row in runs if row["status"] == PASSED),
            "failed": sum(1 for row in runs if row["status"] == FAILED),
            "not_checked": sum(1 for row in runs if row["status"] in {UNAVAILABLE, TIMEOUT, ERROR}),
            "disclaimer": (
                "综合通过只说明可映射到通用门级单元，不代表时序收敛、布局布线或上板可用；"
                "本项目不做时序签核。"
            ),
        },
    }
    (output_root / "synth-matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "synth-matrix.md").write_text(_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--yosys", default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    payload = run_synthesis_matrix(
        args.project_root, args.output_dir, yosys_path=args.yosys, timeout=args.timeout
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    summary = payload["summary"]
    ok = summary["failed"] == 0 and summary["not_checked"] == 0 and summary["passed"] == summary["total"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
