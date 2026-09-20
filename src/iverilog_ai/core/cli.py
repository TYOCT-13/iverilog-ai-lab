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
from .failure_guide import build_failure_guide, reproduce_command, rtl_source_for
from .grading import grade_submissions, summarise
from .labels import layered_conclusion
from .models import ModelValidationError, ResultStatus, SimulationResult, TestPlan
from .pipeline import PipelineValidationError, VerificationPipeline
from .behavior_compare import compare_rtl_behavior
from .report import write_report
from .verify_diff import verify_diff
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

    compare_parser = subparsers.add_parser(
        "compare-rtl",
        help="行为级对比：同一份 TestPlan 分别仿真用户 RTL 与参考 RTL，比对结果与波形",
    )
    compare_parser.add_argument("--plan", required=True, help="AI 测试计划 JSON 文件")
    compare_parser.add_argument("--contract", required=True, help="显式 DUT 合约 JSON 文件")
    compare_parser.add_argument("--user-rtl", required=True, help="待评估的 RTL .v/.sv 文件")
    compare_parser.add_argument("--reference-rtl", required=True, help="参考 RTL .v/.sv 文件")
    compare_parser.add_argument("--output-dir", "--output", dest="output_dir", default=None, help="工件目录")
    compare_parser.add_argument("--iverilog", dest="iverilog_path", default=None, help="iverilog 可执行文件路径")
    compare_parser.add_argument("--vvp", dest="vvp_path", default=None, help="vvp 可执行文件路径")
    compare_parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=30.0, help="单个进程超时秒数")
    compare_parser.add_argument("--language", default="2012", help="Icarus generation，默认 2012")
    compare_parser.add_argument("--print-json", action="store_true", help="将完整对比结果 JSON 打印到标准输出")
    compare_parser.add_argument("--quiet", action="store_true", help="不输出摘要，只输出退出码")
    _add_path_options(compare_parser)

    verify_parser = subparsers.add_parser(
        "verify-diff",
        help="一条命令判断两份 RTL 行为是否一致（合约与测试计划都可自动准备）",
    )
    verify_parser.add_argument("--baseline", required=True, help="基线 RTL .v/.sv（合约草稿也从它提取）")
    verify_parser.add_argument("--candidate", required=True, help="候选 RTL .v/.sv（例如 AI 重写后的版本）")
    verify_parser.add_argument("--contract", default=None, help="DUT 合约 JSON；省略则从基线 RTL 提取草稿")
    verify_parser.add_argument("--plan", default=None, help="测试计划 JSON；省略则用离线确定性规划器生成")
    verify_parser.add_argument("--module", default=None, help="模块名；省略则用合约里的 module")
    verify_parser.add_argument("--output-dir", "--output", dest="output_dir", default=None, help="工件目录")
    verify_parser.add_argument("--iverilog", dest="iverilog_path", default=None, help="iverilog 可执行文件路径")
    verify_parser.add_argument("--vvp", dest="vvp_path", default=None, help="vvp 可执行文件路径")
    verify_parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=30.0, help="单个进程超时秒数")
    verify_parser.add_argument("--language", default="2012", help="Icarus generation，默认 2012")
    verify_parser.add_argument("--print-json", action="store_true", help="将完整结果 JSON 打印到标准输出")
    verify_parser.add_argument("--print-markdown", action="store_true", help="打印可贴进 PR 的 Markdown 报告")
    verify_parser.add_argument("--no-vcd", action="store_true", help="不生成 VCD（更快，但失去逐拍比对）")
    verify_parser.add_argument("--quiet", action="store_true", help="不输出摘要，只输出退出码")
    _add_path_options(verify_parser)

    grade_parser = subparsers.add_parser(
        "grade",
        help="批量批改：把一整个目录的提交与标准实现做行为对比，并挑出需要人看的相似对",
    )
    grade_parser.add_argument("--dir", required=True, help="提交所在目录（含 .v/.sv）")
    grade_parser.add_argument("--golden", required=True, help="标准实现 RTL")
    grade_parser.add_argument("--contract", default=None, help="DUT 合约 JSON；省略则从标准实现提取草稿")
    grade_parser.add_argument("--plan", default=None, help="测试计划 JSON；省略则用离线确定性规划器生成")
    grade_parser.add_argument("--module", default=None, help="模块名；省略则用合约里的 module")
    grade_parser.add_argument("--output-dir", "--output", dest="output_dir", default=None, help="输出目录")
    grade_parser.add_argument("--recursive", action="store_true", help="递归子目录")
    grade_parser.add_argument(
        "--similarity-threshold", type=float, default=0.75,
        help="归一化相似度阈值，超过就列进待看清单；默认 0.75，调低会显著增加条目",
    )
    grade_parser.add_argument("--iverilog", dest="iverilog_path", default=None, help="iverilog 可执行文件路径")
    grade_parser.add_argument("--vvp", dest="vvp_path", default=None, help="vvp 可执行文件路径")
    grade_parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=30.0, help="单个进程超时秒数")
    grade_parser.add_argument("--print-markdown", action="store_true", help="打印可存档的 Markdown 批改报告")
    grade_parser.add_argument("--print-json", action="store_true", help="打印完整 JSON")
    _add_path_options(grade_parser)

    report_parser = subparsers.add_parser("report", help="从 result.json 生成 Markdown 或 HTML")
    report_parser.add_argument("--result", required=True, help="SimulationResult JSON 文件")
    report_parser.add_argument("--output", dest="output_path", default=None, help="报告目标路径")
    report_parser.add_argument("--format", choices=["markdown", "html"], default=None)
    report_parser.add_argument("--title", default="Icarus 智测仿真报告")
    _add_path_options(report_parser)

    explain_parser = subparsers.add_parser(
        "explain",
        help="把 result.json 里的失败翻成「下一步看哪里」的白话（面向刚学 Verilog 的人）",
    )
    explain_parser.add_argument("--result", required=True, help="SimulationResult JSON 文件")
    explain_parser.add_argument("--rtl", default=None, help="被测 RTL 源码；省略则用 result.json 里记录的路径")
    explain_parser.add_argument("--limit", type=int, default=5, help="最多解释几条失败，默认 5")
    explain_parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    _add_path_options(explain_parser)

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
            # verdict 是给脚本/人看的单一结论词：passed / failed_checks / failed / inconclusive。
            # 缺陷变体的 status 是 passed_with_warnings 且 passed=True，只看这两个字段会读错。
            "verdict": result.verdict,
            "passed": result.passed,
            "records": len(result.records),
            "failures": len(result.failures),
            # 上面四个键是为了脚本兼容保留的**机器字段**；同一份 JSON 里 status 与 verdict
            # 取值同名、且检出缺陷时 passed 仍为 true，人读容易读错。因此额外给一句
            # 分层的白话，三层不共用任何词（措辞表见 core/labels.py）。
            "conclusion_zh": layered_conclusion(
                result.status, result.verdict, len(result.failures)
            ),
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
                        "verdict": result.simulation.verdict,
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


def _compare_rtl_command(args: argparse.Namespace) -> int:
    """行为级对比：同一份 TestPlan 跑两份 RTL，再比对记录与波形。"""

    roots = args.allowed_root or [str(_infer_project_root(args.user_rtl))]
    policy = SafePathPolicy.from_roots(roots)
    try:
        plan_path = policy.input_file(args.plan, extensions=(".json",))
        contract_path = policy.input_file(args.contract, extensions=(".json",))
        user_rtl = policy.input_file(args.user_rtl)
        reference_rtl = policy.input_file(args.reference_rtl)
        ai_plan = AITestPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        contract = DutContract.from_json(contract_path.read_text(encoding="utf-8"))
        output_dir = args.output_dir or str(policy.allowed_roots[0] / ".iverilog-ai" / "behavior-compare")
        outcome = compare_rtl_behavior(
            ai_plan,
            contract,
            user_rtl,
            reference_rtl,
            output_dir,
            allowed_roots=tuple(roots),
            iverilog_path=args.iverilog_path,
            vvp_path=args.vvp_path,
            timeout_seconds=args.timeout_seconds,
            language=args.language,
        )
    except (OSError, SafePathError, PipelineValidationError, ValueError) as exc:
        print(f"行为对比失败：{exc}", file=sys.stderr)
        return 2
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "behavior_compare.json"
    result_path.write_text(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        if args.print_json:
            print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
        else:
            summary = outcome.record_summary
            print(
                json.dumps(
                    {
                        "status": outcome.status,
                        "identical": outcome.identical,
                        "module": outcome.module,
                        "user_status": summary.get("user_status"),
                        "reference_status": summary.get("reference_status"),
                        "checks": f"{summary.get('user_checks')} vs {summary.get('reference_checks')}",
                        "failed": f"{summary.get('user_failed')} vs {summary.get('reference_failed')}",
                        "mismatched_checks": summary.get("mismatched_checks"),
                        "waveform": outcome.waveform.get("status"),
                        "dut_waveform_differences": len(outcome.waveform.get("dut_differences", [])),
                        "result": str(result_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    # identical → 0；different → 1（便于脚本判断）；其余 → 2
    return 0 if outcome.status == "identical" else (1 if outcome.status == "different" else 2)


def _verify_diff_command(args: argparse.Namespace) -> int:
    """一条命令判断两份 RTL 行为是否一致。

    退出码沿用 `compare-rtl` 的约定，并额外把"没比出结论"与"不同"分开：
    **0 = 两侧一致，1 = 两侧不同，2 = 未取得可比证据**。CI 里把 2 当成失败处理，
    否则"没测出东西"会被静默当成"没问题"——这正是本项目最想避免的误读。
    """

    roots = args.allowed_root or [str(_infer_project_root(args.baseline))]
    policy = SafePathPolicy.from_roots(roots)
    try:
        baseline = policy.input_file(args.baseline)
        candidate = policy.input_file(args.candidate)
        contract = None
        if args.contract:
            contract = DutContract.from_json(
                policy.input_file(args.contract, extensions=(".json",)).read_text(encoding="utf-8")
            )
        plan = None
        if args.plan:
            plan = AITestPlan.model_validate_json(
                policy.input_file(args.plan, extensions=(".json",)).read_text(encoding="utf-8")
            )
        output_dir = args.output_dir or str(policy.allowed_roots[0] / ".iverilog-ai" / "verify-diff")
        result = verify_diff(
            baseline,
            candidate,
            output_dir,
            contract=contract,
            plan=plan,
            module=args.module,
            allowed_roots=tuple(roots),
            iverilog_path=args.iverilog_path,
            vvp_path=args.vvp_path,
            timeout_seconds=args.timeout_seconds,
            language=args.language,
            emit_vcd=not args.no_vcd,
        )
    except (OSError, SafePathError, PipelineValidationError, ModelValidationError, ValueError) as exc:
        print(f"行为对比失败：{exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        if args.print_markdown:
            print(result.to_markdown())
        elif args.print_json:
            print(result.to_json())
        else:
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "status_label": result.label,
                        "module": result.module,
                        "contract_source": result.contract_source,
                        "plan_source": result.plan_source,
                        "plan_evidence_level": result.plan_evidence_level,
                        "comparable_checks": result.comparable_checks,
                        "waveform_compared": result.waveform_compared,
                        "differences": len(result.differences),
                        "caveats": list(result.caveats),
                        "result": result.artifacts["json"],
                        "report": result.artifacts["markdown"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    return result.exit_code


def _explain_command(args: argparse.Namespace) -> int:
    """把失败的"事实"翻成"下一步看哪里"。

    与 `report` 的分工：那个生成正式报告（给人存档、给评委看），这个只回答
    "我接下来该打开哪个文件、看哪一行、改完怎么验"——所以它默认只讲前几条，
    并且**从不声称某一行就是错的那一行**。
    """

    roots = args.allowed_root or [str(_infer_project_root(args.result))]
    policy = SafePathPolicy.from_roots(roots)
    try:
        result = SimulationResult.from_json(
            policy.input_file(args.result, extensions=(".json",)).read_text(encoding="utf-8")
        )
        source = None
        if args.rtl:
            source = policy.input_file(args.rtl).read_text(encoding="utf-8")
        else:
            # 不给 --rtl 就沿用 result.json 里记录的路径——用户刚跑完就敲 explain，
            # 不该被迫再写一遍同一个文件名。
            source = rtl_source_for(result)
    except (OSError, SafePathError, ModelValidationError) as exc:
        print(f"无法读取输入：{exc}", file=sys.stderr)
        return 2

    failures = tuple(result.failures)
    if not failures:
        print("这次运行没有失败记录；设计结果是「符合预期」。")
        return 0

    guides = [
        build_failure_guide(item, source=source, reproduce=reproduce_command(result))
        for item in failures[: max(0, args.limit)]
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "failures": len(failures),
                    "explained": len(guides),
                    "guides": [item.to_dict() for item in guides],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"这次运行有 {len(failures)} 条失败记录，下面解释前 {len(guides)} 条：")
        print()
        for item in guides:
            print(item.to_markdown())
    return 0


def _grade_command(args: argparse.Namespace) -> int:
    """批量批改：一次比对一整个目录，并挑出需要人看的相似对。

    退出码与单份对比不同：**只在整批都跑不起来时返回 2**，否则返回 0——
    "有学生行为不同"是正常的批改结果，不是脚本错误。
    """

    roots = args.allowed_root or [str(_infer_project_root(args.golden)), str(Path(args.dir).expanduser().resolve())]
    try:
        contract = None
        if args.contract:
            contract = DutContract.from_json(
                SafePathPolicy.from_roots(roots).input_file(args.contract, extensions=(".json",)).read_text(encoding="utf-8")
            )
        plan = None
        if args.plan:
            plan = AITestPlan.model_validate_json(
                SafePathPolicy.from_roots(roots).input_file(args.plan, extensions=(".json",)).read_text(encoding="utf-8")
            )
        output_dir = args.output_dir or str(Path(roots[0]) / ".iverilog-ai" / "grading")
        report = grade_submissions(
            args.dir,
            args.golden,
            output_dir,
            contract=contract,
            plan=plan,
            module=args.module,
            threshold=args.similarity_threshold,
            recursive=args.recursive,
            iverilog_path=args.iverilog_path,
            vvp_path=args.vvp_path,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, SafePathError, PipelineValidationError, ModelValidationError, ValueError) as exc:
        print(f"批量批改失败：{exc}", file=sys.stderr)
        return 2

    if args.print_markdown:
        print(report.to_markdown())
    elif args.print_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(summarise(report))
        print(f"报告：{report.artifacts['markdown']}")
        print(f"JSON：{report.artifacts['json']}")
        for row in report.rows:
            if row.needs_attention:
                print(f"  需人工看：{row.name} —— {row.error or row.label}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"run", "simulate"}:
            return _run_command(args)
        if args.command in {"plan-run", "pipeline"}:
            return _pipeline_command(args)
        if args.command == "compare-rtl":
            return _compare_rtl_command(args)
        if args.command == "verify-diff":
            return _verify_diff_command(args)
        if args.command == "grade":
            return _grade_command(args)
        if args.command == "report":
            return _report_command(args)
        if args.command == "explain":
            return _explain_command(args)
        if args.command in {"validate-plan", "plan"}:
            return _plan_command(args)
    except (ConfigurationError, SafePathError, OSError, ModelValidationError) as exc:
        print(f"配置或执行失败：{exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


__all__ = ["main"]
