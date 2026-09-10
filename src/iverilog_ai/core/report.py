"""从机器可读结果生成可复现的 Markdown/HTML 报告。"""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from .models import ProcessResult, SimulationResult


def _coverage_for_result(result: SimulationResult) -> dict:
    """Best-effort coverage data embedded by pipeline; standalone runs have none."""
    return result.config.get("coverage", {}) if isinstance(result.config, dict) else {}


def _oracle_for_result(result: SimulationResult) -> dict:
    return result.config.get("oracle", {}) if isinstance(result.config, dict) else {}


def _assertions_for_result(result: SimulationResult) -> dict:
    return result.config.get("structured_assertions", {}) if isinstance(result.config, dict) else {}


def _cross_validation_for_result(result: SimulationResult) -> dict:
    return result.config.get("cross_validation", {}) if isinstance(result.config, dict) else {}


def _vcd_analysis_for_result(result: SimulationResult) -> dict:
    return result.config.get("vcd_analysis", {}) if isinstance(result.config, dict) else {}


def _synthesis_for_result(result: SimulationResult, explicit: Mapping[str, Any] | None) -> dict[str, Any]:
    """综合证据可以显式传入，也可以由流水线写在 config 里。"""

    if explicit:
        return dict(explicit)
    config = result.config if isinstance(result.config, dict) else {}
    value = config.get("synthesis")
    return dict(value) if isinstance(value, Mapping) else {}


_STAGE_LABELS = {
    "provided_by_pipeline": "本次流水线提供",
    "passed": "通过",
    "failed": "失败",
    "unavailable": "工具不可用",
    "timeout": "超时",
    "error": "执行错误",
    "not_run": "未运行",
}


def _synthesis_section(synthesis: Mapping[str, Any]) -> list[str]:
    """渲染"仿真→综合→时序→比特流→上板"的分层证据。

    这张表的作用是**把没做的事也写清楚**：只有仿真与综合两行是实际跑过的，
    其余三行显式标 not_run，避免读者把"综合通过"误读成"能上板"。
    """

    stages = synthesis.get("stages") or []
    if not stages:
        return []
    lines = ["## 分层证据（仿真 / 综合 / 时序 / 比特流 / 上板）", ""]
    lines.extend(["| 层级 | 状态 | 说明 |", "|---|---|---|"])
    for stage in stages:
        status = str(stage.get("status", "not_run"))
        lines.append(
            f"| {_md_cell(stage.get('title', stage.get('stage', '')))} | "
            f"{_STAGE_LABELS.get(status, status)} | {_md_cell(stage.get('detail', ''))} |"
        )
    lines.append("")
    status = str(synthesis.get("status", "not_run"))
    if status == "passed":
        lines.extend(
            [
                "### 综合结果",
                "",
                f"- 顶层模块：`{_md_cell(synthesis.get('top', ''))}`",
                f"- 通用门级单元数：{synthesis.get('cell_count')}（{synthesis.get('cell_kinds', 0)} 种类型）",
                f"- 连线数：{synthesis.get('wire_count')}；端口数：{synthesis.get('port_count')}",
                f"- 存储块：{synthesis.get('memory_count')}；进程：{synthesis.get('process_count')}",
                f"- 综合耗时：{synthesis.get('duration_ms', 0)} ms",
                "",
            ]
        )
        cells = synthesis.get("cells") or []
        if cells:
            lines.extend(["| 单元类型 | 数量 |", "|---|---:|"])
            for item in cells[:20]:
                lines.append(f"| `{_md_cell(item.get('cell', ''))}` | {item.get('count', 0)} |")
            lines.append("")
    elif status == "failed":
        lines.extend(
            [
                "### 综合结果",
                "",
                f"- **综合失败**：{_md_cell(synthesis.get('error') or '未知原因')}",
                "- 这是强证据：仿真通过也不能说明这份 RTL 可综合。",
                "",
            ]
        )
    else:
        reason = synthesis.get("skipped_reason") or synthesis.get("error") or "本次运行未启用综合证据层"
        lines.extend(["### 综合结果", "", f"- 未执行：{_md_cell(reason)}", ""])
    if synthesis.get("warnings"):
        lines.extend(
            [
                f"- 综合告警：{len(synthesis['warnings'])} 条"
                f"（首条：{_md_cell(str(synthesis['warnings'][0]))}）",
                "",
            ]
        )
    if synthesis.get("disclaimer"):
        lines.extend([f"> {_md_cell(synthesis['disclaimer'])}", ""])
    return lines


ReportFormat = Literal["markdown", "md", "html"]


def _status(value: object) -> str:
    return getattr(value, "value", str(value))


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _process_markdown(name: str, process: ProcessResult | None) -> list[str]:
    if process is None:
        return [f"### {name}", "", "未执行。", ""]
    lines = [
        f"### {name}",
        "",
        f"- 状态：{_status(process.status)}",
        f"- 返回码：{process.returncode}",
        f"- 用时：{process.duration_ms} ms",
    ]
    if process.timed_out:
        lines.append("- 超时：true")
    if process.error:
        lines.extend(["- 错误：", "", f"  {process.error}"])
    if process.stderr:
        lines.extend(["", "标准错误：", "", "~~~text", process.stderr.rstrip(), "~~~"])
    if process.stdout:
        lines.extend(["", "标准输出：", "", "~~~text", process.stdout.rstrip(), "~~~"])
    lines.append("")
    return lines


def render_markdown(
    result: SimulationResult,
    *,
    title: str = "Icarus 智测仿真报告",
    synthesis: Mapping[str, Any] | None = None,
) -> str:
    """渲染不依赖外部网络资源的 Markdown 报告。

    ``synthesis`` 是可选的分层证据（见 ``core/synthesis.py``）：它**不参与**
    PASS/FAIL 结论，只在报告里单独成节，并显式列出未做的层级。
    """

    total = len(result.records)
    passed = sum(1 for record in result.records if record.ok)
    lines = [
        f"# {title}",
        "",
        "> 结论来自本地 iverilog/vvp 进程；AI 解释或自评不是正确性证据。",
        "",
        f"- 运行 ID：{result.run_id}",
        f"- 总体状态：{_status(result.status)}",
        f"- 证据结论：{result.config.get('verification_status', 'unknown') if isinstance(result.config, dict) else 'unknown'}",
        f"- 结构化记录：{passed}/{total} 通过",
        f"- 开始：{result.started_at}",
        f"- 结束：{result.finished_at}",
        "",
    ]
    coverage = _coverage_for_result(result)
    if coverage:
        lines.extend(["## 测试覆盖摘要", "", "> 以下是测试计划执行覆盖率，不代表 RTL 代码覆盖率。", ""])
        for key, label in (("vectors", "测试向量"), ("checks", "检查项")):
            item = coverage.get(key, {})
            lines.append(f"- {label}：{item.get('covered', 0)}/{item.get('total', 0)} ({item.get('percent', 0)}%)")
        lines.append("")
        if coverage.get("per_signal"):
            lines.extend(["| 信号 | 覆盖 | 总数 | 百分比 |", "|---|---:|---:|---:|"])
            for signal, item in coverage["per_signal"].items():
                lines.append(f"| {_md_cell(signal)} | {item.get('covered', 0)} | {item.get('total', 0)} | {item.get('percent', 0)}% |")
            lines.append("")
    oracle = _oracle_for_result(result)
    if oracle:
        lines.extend(["## 期望值可信度", "", f"- 证据等级：`{oracle.get('evidence_level', 'unknown')}`", f"- 参考模型检查：{oracle.get('checked_expected', 0)} 项", f"- 一致：{oracle.get('matched_expected', 0)} 项", f"- 一致率：{('N/A' if oracle.get('consistency_rate') is None else str(oracle.get('consistency_rate') * 100) + '%')}"])
        if oracle.get("warnings"):
            lines.append("- 结论：`plan_inconsistent`（AI expected 与参考模型存在差异，不能作为高可信预言机）")
        lines.append("")
    assertions = _assertions_for_result(result)
    if assertions and assertions.get("status") != "skipped":
        lines.extend(["## 结构化断言", "", f"- 检查：{assertions.get('checked', 0)} 项", f"- 通过：{assertions.get('passed', 0)} 项", f"- 失败：{assertions.get('failed', 0)} 项", ""])
        for item in assertions.get("results", []):
            lines.append(f"- `{item.get('kind', 'invalid')}` / `{item.get('signal', '')}`：{'PASS' if item.get('passed') else 'WARN'}；{item.get('message', '')}")
        lines.append("")
    cross = _cross_validation_for_result(result)
    if cross:
        lines.extend(["## 多来源交叉验证", "", f"- 来源：{', '.join(cross.get('sources', []))}", f"- 独立来源数：{cross.get('independent_sources', 0)}", f"- 交叉结论：`{cross.get('status', 'unknown')}`", ""])
    lines.extend(_synthesis_section(_synthesis_for_result(result, synthesis)))
    vcd = _vcd_analysis_for_result(result)
    if vcd and vcd.get("status") == "parsed":
        lines.extend(["## VCD 波形分析", "", f"- 时间精度：`{vcd.get('timescale_ns')} ns`", f"- 时间范围：`{vcd.get('start_ns')} ns` ～ `{vcd.get('end_ns')} ns`", f"- 信号数量：{vcd.get('signal_count', 0)}", f"- 变化总数：{vcd.get('total_changes', 0)}", f"- 变化记录是否截断：`{vcd.get('truncated', False)}`", ""])
        if vcd.get("signals"):
            lines.extend(["| 信号 | 位宽 | 变化次数 |", "|---|---:|---:|"])
            for item in vcd["signals"]:
                lines.append(f"| `{_md_cell(item.get('name', ''))}` | {item.get('width', 1)} | {item.get('changes', 0)} |")
            lines.append("")

        insights = vcd.get("insights") or {}
        if insights.get("notes") or insights.get("signal_edges"):
            lines.extend(["### 波形语义结论", ""])
            notes = insights.get("notes") or []
            if notes:
                lines.extend(f"- {_md_cell(note)}" for note in notes)
            else:
                lines.append("- 未发现不稳定信号或相位偏差。")
            dut_unstable = insights.get("unstable_signals") or []
            auxiliary_unstable = insights.get("unstable_auxiliary") or []
            if dut_unstable or auxiliary_unstable:
                lines.append(
                    f"- 不稳定信号统计：DUT 内部 {len(dut_unstable)} 个"
                    f"{('（' + '、'.join(f'`{_md_cell(name)}`' for name in dut_unstable) + '）') if dut_unstable else ''}，"
                    f"testbench 记账 {len(auxiliary_unstable)} 个"
                    f"{('（' + '、'.join(f'`{_md_cell(name)}`' for name in auxiliary_unstable) + '）') if auxiliary_unstable else ''}"
                )
                lines.append("- 说明：testbench 记账信号（如检查任务的 `expected`/`actual` 寄存器）的跳变节奏由激励脚本决定，不计入电路结论。")
            lines.append("")
            lines.extend(["| 信号 | 归属 | 上升沿 | 下降沿 | 首次跳变(ns) | 稳定性 |", "|---|---|---:|---:|---:|---|"])
            stability = {item.get("signal"): item for item in insights.get("stability", [])}
            for item in insights["signal_edges"]:
                entry = stability.get(item.get("signal"), {})
                status = entry.get("status", "-")
                if entry.get("status") == "unstable":
                    status = "不稳定(DUT)" if entry.get("is_dut") else "不稳定(tb记账)"
                owner = "DUT" if entry.get("is_dut") else ("testbench" if entry else "-")
                lines.append(
                    f"| `{_md_cell(item.get('signal', ''))}` | {owner} | {item.get('rises', 0)} | {item.get('falls', 0)} | "
                    f"{item.get('first_edge_ns', '-')} | {status} |"
                )
            lines.append("")
        if insights.get("phase_checks"):
            lines.extend(["### 相位检查（输出晚/早一拍）", "", "| 激励 | 响应 | 期望周期 | 实测周期 | 结论 |", "|---|---|---:|---:|---|"])
            for item in insights["phase_checks"]:
                observed = item.get("observed_delay_cycles")
                lines.append(
                    f"| `{_md_cell(item.get('trigger', ''))}` | `{_md_cell(item.get('response', ''))}` | "
                    f"{item.get('expected_delay_cycles', '-')} | {observed if observed is not None else '-'} | {item.get('status', '')} |"
                )
            lines.append("")

        windows = vcd.get("failure_windows") or {}
        if windows.get("status") == "parsed" and windows.get("windows"):
            lines.extend([
                "### 失败周期对应的波形时间窗",
                "",
                f"- 时钟周期：`{windows.get('clock_period_ns')} ns`；窗口半径：`{windows.get('radius')}` 个周期",
                "",
                "| 失败周期 | 时间窗(ns) | 窗口内信号数 | 窗口内变化数 |",
                "|---:|---|---:|---:|",
            ])
            for item in windows["windows"]:
                analysis = item.get("analysis") or {}
                lines.append(
                    f"| {item.get('cycle')} | {item.get('start_ns')} ～ {item.get('end_ns')} | "
                    f"{analysis.get('signal_count', 0)} | {analysis.get('total_changes', 0)} |"
                )
            lines.extend(["", f"> {windows.get('disclaimer', '')}", ""])
    if result.error:
        lines.extend(["## 总体错误", "", result.error, ""])
    lines.extend(["## 进程证据", ""])
    lines.extend(_process_markdown("iverilog 编译", result.compile))
    lines.extend(_process_markdown("vvp 仿真", result.run))
    lines.extend(["## 失败反例", ""])
    if result.failures:
        lines.extend(
            [
                "| 级别 | 测试 | 周期 | 信号 | 期望 | 实际 | 消息 |",
                "|---|---|---:|---|---|---|---|",
            ]
        )
        for failure in result.failures:
            values = [
                _md_cell(failure.severity.upper()),
                _md_cell(failure.test_id or ""),
                _md_cell("" if failure.cycle is None else str(failure.cycle)),
                _md_cell(failure.signal or ""),
                _md_cell(json.dumps(failure.expected, ensure_ascii=False)),
                _md_cell(json.dumps(failure.actual, ensure_ascii=False)),
                _md_cell(failure.message),
            ]
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    else:
        lines.extend(["没有结构化失败反例。", ""])
    if result.diagnostics:
        lines.extend(["## 诊断", ""])
        lines.extend(f"- {item}" for item in result.diagnostics)
        lines.append("")
    lines.extend(["## 工件", ""])
    if result.artifacts:
        for name, path in result.artifacts.items():
            if path:
                lines.append(f"- {name}：{path}")
    else:
        lines.append("无")
    lines.append("")
    lines.extend(["## 执行配置", "", "~~~json", json.dumps(result.config, ensure_ascii=False, indent=2), "~~~", ""])
    return "\n".join(lines)


def _process_html(process: ProcessResult | None) -> str:
    if process is None:
        return "<p>未执行。</p>"
    bits = [
        f"<p>状态：<code>{escape(_status(process.status))}</code>；"
        f"返回码：<code>{escape(str(process.returncode))}</code>；"
        f"用时：<code>{process.duration_ms} ms</code></p>"
    ]
    if process.error:
        bits.append(f"<p class='error'>{escape(process.error)}</p>")
    if process.stderr:
        bits.append(f"<details><summary>标准错误</summary><pre>{escape(process.stderr)}</pre></details>")
    if process.stdout:
        bits.append(f"<details><summary>标准输出</summary><pre>{escape(process.stdout)}</pre></details>")
    return "".join(bits)


def render_html(
    result: SimulationResult,
    *,
    title: str = "Icarus 智测仿真报告",
    synthesis: Mapping[str, Any] | None = None,
) -> str:
    """渲染可离线打开的 HTML 报告，并对进程输出做 HTML 转义。"""

    rows = []
    for failure in result.failures:
        rows.append(
            "<tr>"
            f"<td>{escape(failure.severity.upper())}</td>"
            f"<td>{escape(failure.test_id or '')}</td>"
            f"<td>{escape('' if failure.cycle is None else str(failure.cycle))}</td>"
            f"<td>{escape(failure.signal or '')}</td>"
            f"<td><code>{escape(json.dumps(failure.expected, ensure_ascii=False))}</code></td>"
            f"<td><code>{escape(json.dumps(failure.actual, ensure_ascii=False))}</code></td>"
            f"<td>{escape(failure.message)}</td>"
            "</tr>"
        )
    failure_table = (
            "<table><thead><tr><th>级别</th><th>测试</th><th>周期</th><th>信号</th><th>期望</th><th>实际</th><th>消息</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
        if rows
        else "<p>没有结构化失败反例。</p>"
    )
    diagnostics = "".join(f"<li>{escape(item)}</li>" for item in result.diagnostics) or "<li>无</li>"
    artifacts = "".join(
        f"<li><code>{escape(name)}</code>：<code>{escape(path)}</code></li>"
        for name, path in result.artifacts.items()
        if path
    ) or "<li>无</li>"
    total = len(result.records)
    passed = sum(1 for record in result.records if record.ok)
    status = _status(result.status)
    coverage = _coverage_for_result(result)
    coverage_html = ""
    if coverage:
        coverage_html = "<h2>测试覆盖摘要</h2><p>以下是测试计划执行覆盖率，不代表 RTL 代码覆盖率。</p>"
        for key, label in (("vectors", "测试向量"), ("checks", "检查项")):
            item = coverage.get(key, {})
            coverage_html += f"<p>{escape(label)}：{item.get('covered', 0)}/{item.get('total', 0)} ({item.get('percent', 0)}%)</p>"
    error_html = f"<p class='error'>{escape(result.error)}</p>" if result.error else ""
    synth_data = _synthesis_for_result(result, synthesis)
    synth_md = _synthesis_section(synth_data)
    if synth_md:
        body_rows = []
        for stage in synth_data.get("stages", []):
            st = str(stage.get("status", "not_run"))
            body_rows.append(
                "<tr>"
                f"<td>{escape(str(stage.get('title', '')))}</td>"
                f"<td>{escape(_STAGE_LABELS.get(st, st))}</td>"
                f"<td>{escape(str(stage.get('detail', '')))}</td>"
                "</tr>"
            )
        extra = ""
        if str(synth_data.get("status")) == "passed":
            extra = (
                f"<p>通用门级单元数：{synth_data.get('cell_count')}"
                f"（{synth_data.get('cell_kinds', 0)} 种类型）；"
                f"连线 {synth_data.get('wire_count')}；端口 {synth_data.get('port_count')}；"
                f"耗时 {synth_data.get('duration_ms', 0)} ms</p>"
            )
        elif str(synth_data.get("status")) == "failed":
            extra = f"<p class='error'>综合失败：{escape(str(synth_data.get('error') or ''))}</p>"
        else:
            extra = f"<p>未执行：{escape(str(synth_data.get('skipped_reason') or synth_data.get('error') or ''))}</p>"
        synthesis_html = (
            "<h2>分层证据（仿真 / 综合 / 时序 / 比特流 / 上板）</h2>"
            "<table><thead><tr><th>层级</th><th>状态</th><th>说明</th></tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table>"
            + extra
            + f"<p><small>{escape(str(synth_data.get('disclaimer', '')))}</small></p>"
        )
    else:
        synthesis_html = ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #17202a; }}
code, pre {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
pre {{ white-space: pre-wrap; background: #f3f5f7; padding: .75rem; border-radius: .35rem; }}
.status {{ padding: .5rem .75rem; border-radius: .35rem; background: #e9f2ff; display: inline-block; }}
.error {{ color: #a00000; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #ccd2d8; padding: .4rem; text-align: left; vertical-align: top; }}
th {{ background: #f3f5f7; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<p>结论来自本地 iverilog/vvp 进程；AI 解释或自评不是正确性证据。</p>
<p class="status">总体状态：<strong>{escape(status)}</strong>；
结构化记录：{passed}/{total} 通过；运行 ID：<code>{escape(result.run_id)}</code></p>
{error_html}
{coverage_html}
{synthesis_html}
<h2>进程证据</h2>
<h3>iverilog 编译</h3>
{_process_html(result.compile)}
<h3>vvp 仿真</h3>
{_process_html(result.run)}
<h2>失败反例</h2>
{failure_table}
<h2>诊断</h2><ul>{diagnostics}</ul>
<h2>工件</h2><ul>{artifacts}</ul>
<h2>执行配置</h2><pre>{escape(json.dumps(result.config, ensure_ascii=False, indent=2))}</pre>
</body>
</html>
"""


def write_report(
    result: SimulationResult,
    path: str | Path,
    *,
    format: ReportFormat | None = None,
    title: str = "Icarus 智测仿真报告",
    synthesis: Mapping[str, Any] | None = None,
) -> Path:
    """写入 Markdown 或 HTML；父目录必须由调用方的路径策略校验。"""

    target = Path(path)
    selected = format
    if selected is None:
        selected = "html" if target.suffix.lower() in {".html", ".htm"} else "markdown"
    if selected not in {"markdown", "md", "html"}:
        raise ValueError("report format must be markdown, md, or html")
    content = (
        render_html(result, title=title, synthesis=synthesis)
        if selected == "html"
        else render_markdown(result, title=title, synthesis=synthesis)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


generate_report = render_markdown


__all__ = [
    "ReportFormat",
    "generate_report",
    "render_html",
    "render_markdown",
    "write_report",
]
