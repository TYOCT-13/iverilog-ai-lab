"""Run the offline AI-path matrix: every case through plan → testbench → Icarus.

Why this exists (and why the benchmark matrix is not enough): the benchmark matrix
drives **hand-written** testbenches.  Nothing there proves the *generated* path
works — that the offline planner can produce a schema-valid plan for every case,
that the constrained generator emits a compilable testbench, that the reference
model supplies authoritative expectations, and that the optional evidence layers
(coverage / oracle / layered evidence) really appear in the report.

This script closes that gap.  It is fully offline (no API key, no network), so it
belongs in CI next to the benchmark matrix.

Judgement rules:

* a case passes only when the pipeline result is `passed` **and** the expectation
  source is `reference_model` — falling back to AI-supplied numbers would mean the
  authoritative oracle silently stopped covering that case;
* a `failed_checks` verdict is a failure here (the offline planner's stimulus is
  the project's own deterministic stimulus table, so a mismatch means either the
  stimulus table or the reference model drifted);
* the coverage block must be present, otherwise the report lost its stimulus
  quality evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from iverilog_ai.ai.debug_provider import DeterministicLocalProvider
from iverilog_ai.ai.planner import plan_tests
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.benchmark_cases import case_table
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rules import rules_context
from iverilog_ai.core.toolchain import locate_tools

#: 规划目标按案例的语义给一句白话，避免所有案例用同一句"通用"目标。
OBJECTIVES: dict[str, str] = {
    "mod10_counter": "覆盖复位、使能保持与 9→0 回绕",
    "traffic_light_emergency": "覆盖正常轮转与紧急抢占后恢复",
    "simple_alu": "覆盖加减、位运算、移位与零标志边界",
    "sequence_101_overlap": "覆盖 101 序列的重叠检测与复位",
    "sync_fifo": "覆盖写满、读空与同时读写",
    "uart_tx": "覆盖整帧发送、起始位与结束后的空闲电平",
    "spi_master": "覆盖一次完整传输、sclk 相位与 done 脉冲",
    "handshake_stage": "覆盖 valid/ready 握手与反压保持",
    "debounce": "覆盖抖动与稳定后的状态切换",
    "pwm": "覆盖 0%/100% 占空比边界",
    "mux4": "覆盖四个通道的选择与切换",
    "sync_reset": "覆盖异步断言与两级同步释放",
    "johnson_counter": "覆盖完整循环与使能暂停",
    "edge_detector": "覆盖单拍上升沿、连续高电平与复位",
    "pulse_stretcher": "覆盖展宽长度、展宽期内重触发与异步复位",
}


def _plan_for(provider: DeterministicLocalProvider, case: str, contract: DutContract, root: Path) -> TestPlan:
    """走真实的规划入口（`plan_tests`），而不是自己拼 prompt。

    这样这条路径与网页/实验用的是同一段代码：注入同一份规则与实测约定、
    同样的严格校验与重试。
    """

    context, _manifest = rules_context(root, case, contract.to_dict())
    objective = OBJECTIVES.get(case, "覆盖复位、边界时序与状态转换")
    return plan_tests(objective, case, provider=provider, context=context)


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Offline AI-path matrix result",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Provider: `{payload['provider']}` (offline, deterministic, no API key)",
        f"- Cases: **{summary['total']}**",
        f"- Passed (authoritative expectations + clean run): **{summary['passed']}**",
        f"- Failed: **{summary['failed']}**",
        f"- Not run (missing contract/tool): **{summary['skipped']}**",
        "",
        "> This path uses the bundled deterministic planner, not a real model.",
        "> It proves the *pipeline* works for every case; it is not AI-quality evidence.",
        "",
        "| case | status | verdict | expectation source | records | failures | generated TB | coverage |",
        "|---|---|---|---|---:|---:|:---:|:---:|",
    ]
    for row in payload["runs"]:
        lines.append(
            f"| `{row['case']}` | `{row['status']}` | `{row['verdict']}` | `{row['expectation_source']}` | "
            f"{row['records']} | {row['failures']} | {'yes' if row['testbench_generated'] else 'no'} | "
            f"{'yes' if row['coverage_present'] else 'no'} |"
        )
    lines.extend(["", "Generated testbenches and reports are retained under the output directory.", ""])
    return "\n".join(lines)


def run_pipeline_matrix(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    iverilog_path: str | None = None,
    vvp_path: str | None = None,
    timeout: float = 30.0,
    cases: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    output_root = (
        Path(output_dir) if output_dir is not None else root / ".iverilog-ai" / "pipeline-matrix"
    ).expanduser().resolve()
    try:
        output_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must remain inside project_root") from exc
    output_root.mkdir(parents=True, exist_ok=True)

    table = case_table(root)
    selected = {name: table[name] for name in (cases or list(table))}
    tools = locate_tools()
    iverilog_path = iverilog_path or tools.iverilog
    vvp_path = vvp_path or tools.vvp
    provider = DeterministicLocalProvider(seed=0)

    runs: list[dict[str, Any]] = []
    for case, info in selected.items():
        contract_path = root / "examples" / f"{case}_contract.json"
        rtl_path = root / info["rtl"]
        run_dir = output_root / case
        row: dict[str, Any] = {
            "case": case,
            "rtl": info["rtl"],
            "contract": contract_path.relative_to(root).as_posix(),
            "run_dir": str(run_dir),
        }
        if not contract_path.is_file():
            row.update({"status": "skipped", "verdict": "skipped", "expectation_source": "",
                        "records": 0, "failures": 0, "testbench_generated": False,
                        "coverage_present": False, "reason": "contract 不存在"})
            runs.append(row)
            continue
        contract = DutContract.from_dict(json.loads(contract_path.read_text(encoding="utf-8")))
        started = time.perf_counter()
        try:
            plan = _plan_for(provider, case, contract, root)
            result = VerificationPipeline().run(
                plan,
                contract,
                rtl_path,
                run_dir,
                allowed_roots=(root,),
                iverilog_path=iverilog_path,
                vvp_path=vvp_path,
                timeout_seconds=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 失败要如实记进矩阵，不能中断整轮
            row.update({"status": "error", "verdict": "failed", "expectation_source": "",
                        "records": 0, "failures": 0, "testbench_generated": False,
                        "coverage_present": False, "reason": f"{type(exc).__name__}: {exc}"})
            runs.append(row)
            continue
        simulation = result.simulation
        oracle: dict[str, Any] = {}
        if isinstance(simulation.config, dict):
            oracle = simulation.config.get("oracle") or {}
        vcd_analysis = simulation.config.get("vcd_analysis") if isinstance(simulation.config, dict) else None
        report_path = Path(result.artifacts.get("report", "")) if result.artifacts.get("report") else None
        row.update(
            {
                "status": result.status.value,
                "verdict": simulation.verdict,
                "expectation_source": str(oracle.get("expectation_source", "")),
                "expectation_evidence_level": str(oracle.get("expectation_evidence_level", "")),
                "coverage_level": str(oracle.get("coverage_level", "")),
                "records": len(result.records),
                "failures": len(result.failures),
                "testbench_generated": Path(result.testbench_path).is_file(),
                "coverage_present": bool(isinstance(vcd_analysis, dict) and vcd_analysis.get("coverage")),
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "report": "" if report_path is None else str(report_path),
                "plan_vectors": len(plan.vectors),
            }
        )
        # 判据：跑通、无失败记录、期望值来自参考模型、报告里有覆盖率证据
        row["ok"] = (
            result.status.value == "passed"
            and not result.failures
            and row["expectation_source"] == "reference_model"
            and row["testbench_generated"]
            and row["coverage_present"]
        )
        runs.append(row)

    passed = sum(1 for row in runs if row.get("ok"))
    skipped = sum(1 for row in runs if row["status"] == "skipped")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_root": str(root),
        "output_dir": str(output_root),
        "provider": "DeterministicLocalProvider(seed=0)",
        "iverilog": iverilog_path or "",
        "runs": runs,
        "summary": {
            "total": len(runs),
            "passed": passed,
            "failed": len(runs) - passed - skipped,
            "skipped": skipped,
            "disclaimer": (
                "本矩阵证明的是**流水线**在每个案例上都能跑通（计划合法 → 生成 testbench → "
                "Icarus 裁决 → 权威期望值 → 覆盖率证据）。计划由仓库自带的确定性规则生成，"
                "不代表任何真实模型的能力。"
            ),
        },
    }
    (output_root / "pipeline-matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "pipeline-matrix.md").write_text(_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--iverilog", default=None)
    parser.add_argument("--vvp", default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--case", action="append", default=None, help="只跑指定案例，可重复")
    args = parser.parse_args()
    payload = run_pipeline_matrix(
        args.project_root,
        args.output_dir,
        iverilog_path=args.iverilog,
        vvp_path=args.vvp,
        timeout=args.timeout,
        cases=args.case,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    for row in payload["runs"]:
        if not row.get("ok"):
            print(f"FAIL {row['case']}: status={row['status']} verdict={row['verdict']} "
                  f"source={row['expectation_source']} failures={row['failures']} "
                  f"reason={row.get('reason', '')}")
    summary = payload["summary"]
    return 0 if summary["failed"] == 0 and summary["skipped"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
