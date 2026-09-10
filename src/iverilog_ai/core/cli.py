"""命令行入口：run、plan-run、report 和 validate-plan。"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import os
import sys
from typing import Sequence

from .config import ConfigurationError, ExecutionConfig, SafePathError, SafePathPolicy
from .executor import IcarusExecutor
from .models import ModelValidationError, ResultStatus, SimulationResult, TestPlan
from .pipeline import PipelineValidationError, VerificationPipeline
from .report import write_report
from ..ai.schema import TestPlan as AITestPlan
from .contracts import DutContract


def _infer_project_root(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    for parent in (candidate.parent, *candidate.parents):
        if (parent / "PROJECT_SCOPE.md").is_file():
            return parent
    return candidate.parent


def _add_path_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allowed-root",
        action="append",
        default=None,
        help="允许 RTL、testbench 和报告路径所在的根目录，可重复指定",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iverilog-ai",
        description="围绕 Icarus Verilog 的受控 AI 辅助仿真工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        aliases=["simulate"],
        help="编译 RTL/testbench，执行 vvp 并生成结构化结果",
    )
    run_parser.add_argument("--rtl", required=True, help="受控目录内的 RTL .v/.sv 文件")
    run_parser.add_argument(
        "--testbench",
        "--tb",
        dest="testbench",
        required=True,
        help="受控目录内的自检 testbench .v/.sv 文件",
    )
    run_parser.add_argument("--top", "--top-module", dest="top_module", required=True, help="顶层 testbench 模块名")
    run_parser.add_argument("--output-dir", "--output", dest="output_dir", default=None, help="报告和仿真工件目录")
    run_parser.add_argument("--iverilog", dest="iverilog_path", default=None, help="iverilog 可执行文件路径")
    run_parser.add_argument("--vvp", dest="vvp_path", default=None, help="vvp 可执行文件路径")
    run_parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=30.0, help="单个进程超时秒数")
    run_parser.add_argument("--include-dir", action="append", default=[], help="Verilog include 目录，可重复指定")
    run_parser.add_argument("--define", action="append", default=[], help="预处理宏 NAME 或 NAME=VALUE，可重复指定")
    run_parser.add_argument("--language", default="2012", help="Icarus generation，默认 2012")
    run_parser.add_argument("--report-format", choices=["markdown", "html", "none"], default="markdown")
    run_parser.add_argument("--report-path", default=None, help="报告目标路径；默认写入 run 目录")
    run_parser.add_argument("--result-path", "--json", dest="result_path", default=None, help="额外复制一份 result.json 到该路径")
    run_parser.add_argument("--print-json", action="store_true", help="将完整结果 JSON 打印到标准输出")
    run_parser.add_argument("--no-keep-artifacts", action="store_true", help="保留日志但不承诺编译中间产物")
    run_parser.add_argument("--quiet", action="store_true", help="不输出进程摘要，只输出退出码")
    _add_path_options(run_parser)

    pipeline_parser = subparsers.add_parser(
        "plan-run",
        aliases=["pipeline"],
        help="校验 AI 测试计划和 DUT 合约，生成 testbench 后执行 Icarus/vvp",
    )
    pipeline_parser.add_argument("--plan", required=True, help="AI 测试计划 JSON 文件")
    pipeline_parser.add_argument("--contract", required=True, help="显式 DUT 合约 JSON 文件")
    pipeline_parser.add_argument("--rtl", required=True, help="受控目录内的 RTL .v/.sv 文件")
    pipeline_parser.add_argument("--output-dir", "--output", dest="output_dir", default=None, help="流水线工件目录")
    pipeline_parser.add_argument("--iverilog", dest="iverilog_path", default=None, help="iverilog 可执行文件路径")
    pipeline_parser.add_argument("--vvp", dest="vvp_path", default=None, help="vvp 可执行文件路径")
    pipeline_parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=30.0, help="单个进程超时秒数")
    pipeline_parser.add_argument("--include-dir", action="append", default=[], help="Verilog include 目录，可重复指定")
    pipeline_parser.add_argument("--define", action="append", default=[], help="预处理宏 NAME 或 NAME=VALUE，可重复指定")
    pipeline_parser.add_argument("--language", default="2012", help="Icarus generation，默认 2012")
    pipeline_parser.add_argument("--report-format", choices=["markdown", "html", "none"], default="markdown")
    pipeline_parser.add_argument("--report-path", default=None, help="报告目标路径；默认写入流水线工件目录")
    pipeline_parser.add_argument("--print-json", action="store_true", help="将完整流水线结果 JSON 打印到标准输出")
    pipeline_parser.add_argument("--quiet", action="store_true", help="不输出摘要，只输出退出码")
    # 综合证据层是可选的：开启后额外跑一次 Yosys，报告里多一节分层证据。
    # 它不参与 PASS/FAIL 结论，也不做时序分析。
    pipeline_parser.add_argument("--synth", action="store_true", help="附加 Yosys 综合证据层（不参与 PASS/FAIL 裁决）")
    pipeline_parser.add_argument("--yosys", dest="yosys", default=None, help="Yosys 可执行文件路径；默认从 PATH 查找")
    pipeline_parser.add_argument("--synth-timeout", dest="synth_timeout", type=float, default=180.0, help="综合超时秒数")
    _add_path_options(pipeline_parser)

    report_parser = subparsers.add_parser("report", help="从 result.json 生成 Markdown 或 HTML")
    report_parser.add_argument("--result", required=True, help="SimulationResult JSON 文件")
    report_parser.add_argument("--output", dest="output_path", default=None, help="报告目标路径")
    report_parser.add_argument("--format", choices=["markdown", "html"], default=None)
    report_parser.add_argument("--title", default="Icarus 智测仿真报告")
    _add_path_options(report_parser)

    plan_parser = subparsers.add_parser("validate-plan", aliases=["plan"], help="校验 AI 测试计划 JSON")
    plan_parser.add_argument("--plan", required=True, help="测试计划 JSON 文件")
    plan_parser.add_argument("--output", dest="output_path", default=None, help="输出规范化 JSON 文件")
    _add_path_options(plan_parser)
    return parser


def _policy_for_input(input_path: str, roots: list[str] | None) -> SafePathPolicy:
    if roots:
        return SafePathPolicy.from_roots(roots)
    return SafePathPolicy.from_roots([_infer_project_root(input_path)])


def _safe_output(policy: SafePathPolicy, path: str | os.PathLike[str]) -> Path:
    target = Path(path).expanduser().resolve(strict=False)
    parent = policy.output_dir(target.parent)
    return parent / target.name


def _run_command(args: argparse.Namespace) -> int:
    roots = args.allowed_root
    root = _infer_project_root(args.rtl)
    if roots is None:
        roots = [str(root)]
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = str(root / ".iverilog-ai" / "runs")
    config = ExecutionConfig(
        rtl_path=args.rtl,
        testbench_path=args.testbench,
        top_module=args.top_module,
        output_dir=output_dir,
        iverilog_path=args.iverilog_path,
        vvp_path=args.vvp_path,
        timeout_seconds=args.timeout_seconds,
        allowed_roots=tuple(roots),
        include_dirs=tuple(args.include_dir),
        defines=tuple(args.define),
        language=args.language,
        keep_artifacts=not args.no_keep_artifacts,
    )
    result = IcarusExecutor(config).run()
    resolved = config.resolve()
    report_path: Path | None = None
    if args.report_format != "none":
        if args.report_path:
            report_path = _safe_output(resolved.policy, args.report_path)
        else:
            suffix = ".html" if args.report_format == "html" else ".md"
            report_path = resolved.policy.output_dir(result.artifacts["run_dir"]) / f"report{suffix}"
        write_report(result, report_path, format=args.report_format)
    if args.result_path:
        result_copy = _safe_output(resolved.policy, args.result_path)
        result_copy.write_text(result.to_json() + "\n", encoding="utf-8")
    if not args.quiet:
        summary = {
            "run_id": result.run_id,
            "status": result.status.value,
            "passed": result.passed,
            "records": len(result.records),
            "failures": len(result.failures),
            "result_json": result.artifacts.get("result_json", ""),
            "report": "" if report_path is None else str(report_path),
        }
        print(json.dumps(result.to_dict() if args.print_json else summary, ensure_ascii=False, indent=2))
    return 0 if result.status is ResultStatus.PASSED else 1


def _report_command(args: argparse.Namespace) -> int:
    roots = args.allowed_root or [str(_infer_project_root(args.result))]
    policy = SafePathPolicy.from_roots(roots)
    result_path = policy.input_file(args.result, extensions=(".json",))
    try:
        result = SimulationResult.from_json(result_path.read_text(encoding="utf-8"))
    except (OSError, ModelValidationError) as exc:
        print(f"无法读取 result.json：{exc}", file=sys.stderr)
        return 2
    if args.output_path:
        output = _safe_output(policy, args.output_path)
    else:
        output = result_path.with_suffix(".html" if args.format == "html" else ".md")
        output = _safe_output(policy, output)
    try:
        written = write_report(result, output, format=args.format, title=args.title)
    except (OSError, ValueError, SafePathError) as exc:
        print(f"无法写入报告：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result.status.value, "report": str(written)}, ensure_ascii=False, indent=2))
    return 0


def _pipeline_command(args: argparse.Namespace) -> int:
    """Run the constrained AI-plan -> generated testbench -> Icarus pipeline."""

    roots = args.allowed_root
    if roots is None:
        roots = [str(_infer_project_root(args.rtl))]
    policy = SafePathPolicy.from_roots(roots)
    try:
        plan_path = policy.input_file(args.plan, extensions=(".json",))
        contract_path = policy.input_file(args.contract, extensions=(".json",))
        rtl_path = policy.input_file(args.rtl)
        ai_plan = AITestPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        contract = DutContract.from_json(contract_path.read_text(encoding="utf-8"))
        output_dir = args.output_dir or str(policy.allowed_roots[0] / ".iverilog-ai" / "pipeline")
        result = VerificationPipeline(
            run_synthesis=args.synth,
            yosys_path=args.yosys,
            synthesis_timeout_s=args.synth_timeout,
        ).run(
            ai_plan,
            contract,
            rtl_path,
            output_dir,
            allowed_roots=tuple(roots),
            iverilog_path=args.iverilog_path,
            vvp_path=args.vvp_path,
            include_dirs=tuple(args.include_dir),
            defines=tuple(args.define),
            timeout_seconds=args.timeout_seconds,
            language=args.language,
        )
    except (OSError, SafePathError, PipelineValidationError, ValueError) as exc:
        print(f"流水线输入或执行失败：{exc}", file=sys.stderr)
        return 2
    report_path: Path | None = None
    if args.report_format != "none":
        report_path = Path(args.report_path) if args.report_path else Path(result.artifacts["output_dir"]) / (
            "report.html" if args.report_format == "html" else "report.md"
        )
        try:
            report_path = _safe_output(policy, report_path)
            write_report(result.simulation, report_path, format=args.report_format, title="Icarus 智测流水线报告")
        except (OSError, SafePathError, ValueError) as exc:
            print(f"无法写入流水线报告：{exc}", file=sys.stderr)
            return 2
    if not args.quiet:
        if args.print_json:
            print(result.to_json())
        else:
            print(
                json.dumps(
                    {
                        "status": result.status.value,
                        "passed": result.passed,
                        "records": len(result.records),
                        "failures": len(result.failures),
                        "synthesis": {
                            "status": result.synthesis.get("status", "not_run"),
                            "cell_count": result.synthesis.get("cell_count"),
                        },
                        "pipeline_result": result.artifacts.get("pipeline_result", ""),
                        "report": "" if report_path is None else str(report_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    return 0 if result.passed else 1


def _plan_command(args: argparse.Namespace) -> int:
    roots = args.allowed_root or [str(_infer_project_root(args.plan))]
    policy = SafePathPolicy.from_roots(roots)
    try:
        plan_path = policy.input_file(args.plan, extensions=(".json",))
        raw = plan_path.read_text(encoding="utf-8")
        # The public plan format is the strict Pydantic AI schema. Keep a
        # fallback for the original core.models format so older local plans
        # remain readable during migration.
        try:
            plan = AITestPlan.model_validate_json(raw)
            normalized = plan.model_dump_json(indent=2)
        except Exception as ai_error:
            try:
                legacy_plan = TestPlan.from_json(raw)
            except ModelValidationError as legacy_error:
                raise ModelValidationError(
                    f"AI test plan invalid: {ai_error}; legacy plan invalid: {legacy_error}"
                ) from ai_error
            normalized = legacy_plan.to_json()
    except (OSError, SafePathError, ModelValidationError) as exc:
        print(f"测试计划无效：{exc}", file=sys.stderr)
        return 2
    if args.output_path:
        output = _safe_output(policy, args.output_path)
        output.write_text(normalized + "\n", encoding="utf-8")
        print(json.dumps({"valid": True, "output": str(output)}, ensure_ascii=False, indent=2))
    else:
        print(normalized)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"run", "simulate"}:
            return _run_command(args)
        if args.command in {"plan-run", "pipeline"}:
            return _pipeline_command(args)
        if args.command == "report":
            return _report_command(args)
        if args.command in {"validate-plan", "plan"}:
            return _plan_command(args)
    except (ConfigurationError, SafePathError, OSError, ModelValidationError) as exc:
        print(f"配置或执行失败：{exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


__all__ = ["main"]
