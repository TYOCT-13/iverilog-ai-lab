"""Run the reproducible fixed-vector benchmark matrix.

The benchmark runner deliberately delegates every compile and simulation to
``IcarusExecutor``.  It records the raw result artifact for each reference and
defect variant, then writes a compact JSON/Markdown summary suitable for the
experiment log.  A defect is counted only when a successful simulation emits
at least one structured ``ok=false`` record; compile errors and inconclusive
runs stay visible but are never treated as detections.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from iverilog_ai.core.config import ExecutionConfig
from iverilog_ai.core.executor import IcarusExecutor
from iverilog_ai.core.models import ResultStatus


CASES: dict[str, dict[str, str]] = {
    "mod10_counter": {"rtl": "rtl/mod10_counter.v", "testbench": "tb/tb_mod10_counter.v", "top": "tb_mod10_counter"},
    "traffic_light_emergency": {
        "rtl": "rtl/traffic_light_emergency.v",
        "testbench": "tb/tb_traffic_light_emergency.v",
        "top": "tb_traffic_light_emergency",
    },
    "simple_alu": {"rtl": "rtl/simple_alu.v", "testbench": "tb/tb_simple_alu.v", "top": "tb_simple_alu"},
    "sequence_101_overlap": {
        "rtl": "rtl/sequence_101_overlap.v",
        "testbench": "tb/tb_sequence_101_overlap.v",
        "top": "tb_sequence_101_overlap",
    },
}


def _relative(path: str | Path, root: Path) -> str:
    try:
        return Path(path).resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _run_one(
    *, root: Path, output_root: Path, case: str, variant: str, rtl: Path, testbench: Path, top: str,
    iverilog_path: str | None, vvp_path: str | None, timeout: float,
) -> dict[str, Any]:
    run_output = output_root / case / variant
    config = ExecutionConfig(
        rtl_path=rtl,
        testbench_path=testbench,
        top_module=top,
        output_dir=run_output,
        allowed_roots=(root,),
        iverilog_path=iverilog_path,
        vvp_path=vvp_path,
        timeout_seconds=timeout,
        keep_artifacts=True,
    )
    result = IcarusExecutor(config).run()
    run_ms = None if result.run is None else result.run.duration_ms
    is_defect = variant != "reference"
    # Functional mismatches are WARN by policy, so a defect can be detected
    # while the aggregate status is passed_with_warnings.
    detected = bool(is_defect and result.failures)
    return {
        "strategy": "fixed",
        "case": case,
        "variant": variant,
        "rtl": _relative(rtl, root),
        "status": result.status.value,
        "records_pass": sum(1 for record in result.records if record.ok),
        "records": len(result.records),
        "failures": len(result.failures),
        "defect_found": detected,
        "compile_ms": result.compile.duration_ms,
        "sim_ms": run_ms,
        "artifact_path": result.artifacts.get("run_dir", ""),
        "result_json": result.artifacts.get("result_json", ""),
        "diagnostics": list(result.diagnostics),
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Benchmark matrix result",
        "",
        f"- Strategy: `{payload['strategy']}`",
        f"- Generated: `{payload['generated_at']}`",
        f"- Defect detection: **{summary['defects_found']}/{summary['defects_total']}** ({summary['detection_rate']:.1%})",
        f"- Reference false positives: **{summary['reference_false_positives']}/{summary['references_total']}**",
        f"- Inconclusive runs: **{summary['inconclusive_runs']}**",
        "",
        "| case | variant | status | records | failures | found | compile ms | sim ms |",
        "|---|---|---:|---:|---:|:---:|---:|---:|",
    ]
    for row in payload["runs"]:
        lines.append(
            f"| `{row['case']}` | `{row['variant']}` | `{row['status']}` | {row['records']} | "
            f"{row['failures']} | {'yes' if row['defect_found'] else 'no'} | {row['compile_ms']} | {row['sim_ms'] if row['sim_ms'] is not None else '-'} |"
        )
    lines.extend(["", "Raw `result.json` artifacts are retained under the matrix output directory.", ""])
    return "\n".join(lines)


def run_matrix(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    iverilog_path: str | None = None,
    vvp_path: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    output_root = (Path(output_dir) if output_dir is not None else root / ".iverilog-ai" / "benchmark-matrix").expanduser().resolve()
    try:
        output_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must remain inside project_root") from exc
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "benchmarks" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = []
    for case, info in CASES.items():
        runs.append(
            _run_one(
                root=root,
                output_root=output_root,
                case=case,
                variant="reference",
                rtl=root / info["rtl"],
                testbench=root / info["testbench"],
                top=info["top"],
                iverilog_path=iverilog_path,
                vvp_path=vvp_path,
                timeout=timeout,
            )
        )
    for defect in manifest.get("defects", []):
        case = str(defect["type"])
        if case not in CASES:
            raise ValueError(f"manifest defect refers to unknown case: {case}")
        info = CASES[case]
        runs.append(
            _run_one(
                root=root,
                output_root=output_root,
                case=case,
                variant=str(defect["id"]),
                rtl=root / str(defect["file"]),
                testbench=root / info["testbench"],
                top=info["top"],
                iverilog_path=iverilog_path,
                vvp_path=vvp_path,
                timeout=timeout,
            )
        )
    references = [row for row in runs if row["variant"] == "reference"]
    defects = [row for row in runs if row["variant"] != "reference"]
    found = sum(1 for row in defects if row["defect_found"])
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "strategy": "fixed",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_root": str(root),
        "output_dir": str(output_root),
        "runs": runs,
        "summary": {
            "references_total": len(references),
            "reference_false_positives": sum(1 for row in references if row["status"] != "passed"),
            "defects_total": len(defects),
            "defects_found": found,
            "detection_rate": found / len(defects) if defects else 0.0,
            "inconclusive_runs": sum(1 for row in runs if row["status"] == "inconclusive"),
        },
    }
    (output_root / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_root / "matrix.md").write_text(_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--iverilog", default=None)
    parser.add_argument("--vvp", default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    payload = run_matrix(args.project_root, args.output_dir, iverilog_path=args.iverilog, vvp_path=args.vvp, timeout=args.timeout)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["summary"]["reference_false_positives"] == 0 and payload["summary"]["defects_found"] == payload["summary"]["defects_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
