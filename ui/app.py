"""安全的单页演示：案例来自代码内白名单，仿真交给 IcarusExecutor。"""
from pathlib import Path
from typing import Any, Literal
import json
import sys
import streamlit as st

import os
import hashlib
import shutil
import subprocess
import time
from iverilog_ai.ai import DeterministicLocalProvider, MockProvider, OpenAICompatibleProvider, offline_provider, plan_tests, supplement_tests
from iverilog_ai.core.config import ExecutionConfig
from iverilog_ai.core.executor import IcarusExecutor
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.pipeline import explain_failure_record
from iverilog_ai.core.report import write_report
from iverilog_ai.core.toolchain import locate_tools
from iverilog_ai.core.rtl_import import import_rtl_bytes, extract_contract_draft, available_modules, RTLImportError
from iverilog_ai.core.repair_compare import safe_candidate_copy, compare_simulation_results
from iverilog_ai.core.rtl_compare import compare_rtl_sources
from iverilog_ai.core.behavior_compare import compare_rtl_behavior
from iverilog_ai.core.rules import rules_context, rule_manifest, rules_fingerprint
from iverilog_ai.core.rule_assertions import assertion_suggestions
# `scripts/` 不是安装包的一部分：从仓库外启动页面（`streamlit run E:\...\ui\app.py`）时
# `import scripts.create_evidence_pack` 会失败。把仓库根加进 sys.path 再导入，
# 页面因此不依赖"当前工作目录必须是仓库根"。
_ROOT_HINT = Path(__file__).resolve().parents[1]
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))
from scripts.create_evidence_pack import create_evidence_pack
# 注意：core.rules 与 core.static_review 各有一个 rule_manifest，签名不同
# （前者按案例返回规则文本，后者返回静态规则注册表）。必须用别名区分，否则
# 后导入的会覆盖先导入的：实证面板会静默退化成一排 "—"，而案例规则文本会报错。
from iverilog_ai.core.static_review import review_rtl_file, render_static_markdown
from iverilog_ai.core.static_review import rule_manifest as static_rule_manifest
from iverilog_ai.core.vcd import analyze_vcd_file

ROOT = Path(__file__).resolve().parents[1]


def _count_test_cases(root: Path | None = None) -> int | None:
    """统计 `tests/` 下真实的测试用例数（函数级），而不是文件数。

    用 AST 数 `def test_*`：这是"测试函数数"，比文件数更接近读者理解的规模。
    注意它**小于** pytest 实际收集的用例数（`@pytest.mark.parametrize` 会在运行时
    展开成多条），因此 `tests/core/test_ui_assets.py` 会断言这里的口径与
    pytest 的收集结果一致，避免页面数字与实际跑的数量脱节。
    """

    import ast

    base = Path(root) if root is not None else ROOT
    total = 0
    try:
        for path in base.rglob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            total += sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
    except (OSError, SyntaxError):
        return None
    return total or None


def _project_evidence() -> dict:
    """读取仓库里的真实规模数据，用于页面顶部的"实证状态"面板。

    全部从磁盘现算（基准清单、规则注册表、测试函数数），不写死数字——写死的
    数字会随时间失真，而这个页面最重要的承诺就是"给的都是可核验的事实"。
    """

    evidence: dict = {}
    try:
        manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
        evidence["cases"] = len(manifest.get("categories", []))
        evidence["defects"] = len(manifest.get("defects", []))
    except (OSError, json.JSONDecodeError):
        evidence["cases"] = evidence["defects"] = None
    try:
        rules = static_rule_manifest()
        evidence["rules"] = len(rules)
        evidence["rule_errors"] = sum(1 for item in rules if item.get("severity") == "error")
    except Exception:
        evidence["rules"] = evidence["rule_errors"] = None
    evidence["tests"] = _count_test_cases()
    try:
        tools = locate_tools()
        evidence["iverilog"] = tools.iverilog
        evidence["vvp"] = tools.vvp
        evidence["yosys"] = tools.yosys
        # GTKWave 只用于"打开波形看"，缺失不影响仿真判决，因此单独一栏、单独显示。
        evidence["gtkwave"] = tools.gtkwave
    except Exception:  # pragma: no cover - 探测失败不影响页面其它部分
        evidence["iverilog"] = evidence["vvp"] = evidence["yosys"] = evidence["gtkwave"] = None
    try:
        from iverilog_ai.core.reference_model import AUTHORITATIVE, SUPPORTED

        evidence["models_aligned"] = len(AUTHORITATIVE)
        evidence["models_total"] = len(SUPPORTED)
    except Exception:
        evidence["models_aligned"] = evidence["models_total"] = None
    return evidence


def _render_evidence_header() -> None:
    """先讲清"证据从哪来"，再讲功能——这是本项目与其他 AI 工具最主要的差别。"""

    evidence = _project_evidence()
    st.caption(
        "**判决权威**：本页所有 PASS/FAIL 只由本机 Icarus Verilog 编译与仿真结果、"
        "以及结构化断言决定；AI 只提出测试计划，AI 自评不作为正确性证据。"
    )
    columns = st.columns(5)
    pairs = (
        ("基准案例", evidence.get("cases")),
        ("可复现缺陷", evidence.get("defects")),
        ("静态规则", evidence.get("rules")),
        ("自动化测试", evidence.get("tests")),
        ("已对齐参考模型", f"{evidence.get('models_aligned')}/{evidence.get('models_total')}"
         if evidence.get("models_total") else None),
    )
    for column, (label, value) in zip(columns, pairs):
        column.metric(label, "—" if value is None else value)
    st.caption(
        "以上数字由页面实时读取 `benchmarks/manifest.json`、规则注册表与 `tests/` 现算，"
        "不写死。基准矩阵的实跑结论见 `docs/verification_report.md`。"
    )


def _render_expectation_source(config: dict) -> None:
    """把"这一轮期望值是谁给的"讲清楚——这是可信度的关键，也是最容易被忽略的信息。"""

    oracle = (config or {}).get("oracle") or {}
    if not oracle:
        return
    source = oracle.get("expectation_source", "unknown")
    if source == "reference_model":
        st.success(
            "期望值来源：**确定性参考模型复算**（已与 RTL 逐拍对齐）。"
            "AI 给出的数字不参与裁决，偏差只作为诊断指标记录。"
        )
    elif source == "ai_generated":
        st.warning(
            "期望值来源：**AI 生成**（该设计暂无逐拍对齐的参考模型）。"
            "这种情况下期望值本身可能有误，结论的可信度低于参考模型复算的情形。"
        )
    elif source == "none_given":
        st.error(
            "期望值来源：**没有期望值** —— 本轮既没有参考模型，AI 也没有给出期望值，"
            "只有激励与结构化断言在起作用。**不要据此认为功能行为已被验证。**"
        )
    if oracle.get("advice"):
        st.caption(oracle["advice"])
    if oracle.get("ai_expected_mismatch"):
        st.caption(
            f"本轮检测到 AI 期望值与参考模型不一致 {oracle.get('mismatched_expected', '若干')} 项——"
            "这是 AI 的误差，已单独记为诊断指标，不影响 PASS/FAIL。"
        )


def _configured_gtkwave() -> str | None:
    """按"页面里填的路径 → 环境变量 → 自动探测"的顺序取 GTKWave 可执行文件。"""

    from iverilog_ai.core.toolchain import locate_tools

    manual = str(st.session_state.get("gtkwave_path", "") or "").strip()
    if manual:
        path = Path(manual)
        if path.is_file():
            return str(path)
    env_value = str(os.getenv("GTKWAVE_PATH", "") or "").strip()
    if env_value and Path(env_value).is_file():
        return env_value
    try:
        return locate_tools().gtkwave
    except Exception:
        return None


def _open_vcd_with_gtkwave(vcd_path: Path, *, executable: str | None = None) -> tuple[bool, str]:
    """用 GTKWave 打开 VCD（固定可执行文件 + 参数列表，绝不经过 shell）。

    路径来源见 :func:`_configured_gtkwave`：页面里手填的路径优先，其次是
    `GTKWAVE_PATH` 环境变量，最后是从 PATH / 常见目录 / iverilog 安装位置推断。
    真实反馈是"点了没反应、也不知道是不是没找到路径"，因此失败时把**找过哪些位置**
    一并带出来，而不是只说一句"未找到"。
    """

    resolved = executable or _configured_gtkwave()
    if not resolved:
        tried = _gtkwave_search_summary()
        return False, (
            "未找到 GTKWave。请在「设置 → 波形查看器（GTKWave）」里填写 gtkwave.exe 的完整路径，"
            "或设置环境变量 GTKWAVE_PATH。已查找：" + tried
        )
    target = Path(resolved)
    if not target.is_file():
        return False, f"GTKWave 路径不存在：{target}。请在「设置 → 波形查看器（GTKWave）」里更正。"
    if not Path(vcd_path).is_file():
        return False, f"波形文件不存在：{vcd_path}"
    try:
        # Keep the GUI process visible.  Some Windows GTKWave launchers exit
        # immediately when started with CREATE_NO_WINDOW.
        # Use the executable directory as cwd: GTKWave bundles DLLs and
        # launcher helpers next to the binary on Windows.
        process = subprocess.Popen(
            [str(target), str(vcd_path)],
            shell=False,
            close_fds=True,
            cwd=str(target.parent),
        )
    except OSError as exc:
        return False, f"GTKWave 启动失败：{exc}（路径：{target}）"
    # 启动后立刻退出通常意味着缺 DLL 或参数不被接受；这里等一下再确认，避免"看起来成功了"。
    time.sleep(0.4)
    if process.poll() is not None:
        return False, f"GTKWave 启动后立即退出（退出码 {process.returncode}）：{target}"
    return True, f"已用 GTKWave 打开：{vcd_path.name}（{target}，PID {process.pid}）"


def _gtkwave_search_summary() -> str:
    """列出 GTKWave 的查找位置，供失败提示使用（不猜测、只说实际找过的地方）。"""

    from iverilog_ai.core.toolchain import gtkwave_candidates, locate_tools

    parts: list[str] = []
    manual = str(st.session_state.get("gtkwave_path", "") or "").strip()
    if manual:
        parts.append(f"页面填写的路径（不存在）：{manual}")
    if os.getenv("GTKWAVE_PATH"):
        parts.append(f"环境变量 GTKWAVE_PATH={os.getenv('GTKWAVE_PATH')}")
    if shutil.which("gtkwave"):
        parts.append(f"PATH：{shutil.which('gtkwave')}")
    else:
        parts.append("PATH 中没有 gtkwave")
    for candidate in gtkwave_candidates(locate_tools().iverilog):
        parts.append(candidate)
    return "；".join(parts)


def _show_behavior_comparison(data: dict) -> None:
    """展示行为级对比结论：逐检查项结果 + 波形差异 + 口径说明。"""

    st.subheader("行为级对比（同一份 TestPlan，两份 RTL）")
    status = str(data.get("status", ""))
    summary = data.get("record_summary", {})
    if status == "identical":
        st.success("在本次测试计划覆盖的激励范围内，两份 RTL 的行为没有可观测差异。")
    elif status == "different":
        st.warning("两份 RTL 存在行为差异。")
    else:
        st.info(f"对比结论：{status}")
    columns = st.columns(4)
    columns[0].metric("用户 RTL 状态", str(summary.get("user_status", "-")))
    columns[1].metric("参考 RTL 状态", str(summary.get("reference_status", "-")))
    columns[2].metric("检查项差异", summary.get("mismatched_checks", 0))
    columns[3].metric(
        "失败项（用户/参考）",
        f"{summary.get('user_failed', 0)}/{summary.get('reference_failed', 0)}",
    )
    mismatches = data.get("mismatches", [])
    if mismatches:
        with st.expander(f"逐检查项差异（{len(mismatches)} 处）", expanded=True):
            st.dataframe(
                [
                    {
                        "测试": item.get("test_id"),
                        "信号": item.get("signal"),
                        "类型": item.get("kind"),
                        "用户 RTL": (item.get("user") or {}).get("actual"),
                        "参考 RTL": (item.get("reference") or {}).get("actual"),
                    }
                    for item in mismatches
                ],
                use_container_width=True,
                hide_index=True,
            )
    waveform = data.get("waveform", {})
    st.markdown("**波形比对**")
    st.write(
        f"- 状态：`{waveform.get('status')}`；共有信号差异 {waveform.get('difference_count', 0)} 处"
        f"（其中 DUT 内部信号 {len(waveform.get('dut_differences', []))} 处）"
    )
    dut_differences = waveform.get("dut_differences", [])
    if dut_differences:
        for item in dut_differences[:10]:
            st.write(f"- {item.get('message', '')}")
    if waveform.get("reference_only_signals") or waveform.get("user_only_signals"):
        st.caption(
            "信号集合差异：参考独有 "
            + (", ".join(waveform.get("reference_only_signals", [])) or "无")
            + "；用户独有 "
            + (", ".join(waveform.get("user_only_signals", [])) or "无")
        )
    for note in data.get("notes", []):
        st.caption(note)
    st.caption(data.get("disclaimer", ""))
    st.download_button(
        "下载行为对比 JSON",
        json.dumps(data, ensure_ascii=False, indent=2),
        file_name="behavior-comparison.json",
        mime="application/json",
        key="download_behavior_comparison",
    )


def _show_synthesis(synthesis: dict | None) -> None:
    """展示分层证据：仿真/综合跑过，时序/比特流/上板显式标未运行。

    这张表刻意把"没做的事"写出来，避免把"综合通过"误读成"能上板"。
    """

    data = synthesis or {}
    stages = data.get("stages") or []
    if not stages:
        return
    st.subheader("分层证据（仿真 / 综合 / 时序 / 比特流 / 上板）")
    labels = {
        "provided_by_pipeline": "本次流水线提供",
        "passed": "通过",
        "failed": "失败",
        "unavailable": "工具不可用",
        "timeout": "超时",
        "error": "执行错误",
        "not_run": "未运行",
    }
    st.dataframe(
        [
            {
                "层级": item.get("title", item.get("stage", "")),
                "状态": labels.get(str(item.get("status")), item.get("status")),
                "说明": item.get("detail", ""),
            }
            for item in stages
        ],
        use_container_width=True,
        hide_index=True,
    )
    status = str(data.get("status", "not_run"))
    if status == "passed":
        columns = st.columns(4)
        columns[0].metric("门级单元", data.get("cell_count") or 0)
        columns[1].metric("单元类型", data.get("cell_kinds") or 0)
        columns[2].metric("连线", data.get("wire_count") or 0)
        columns[3].metric("综合耗时", f"{data.get('duration_ms', 0)} ms")
        if data.get("cells"):
            with st.expander("门级单元明细"):
                st.dataframe(data["cells"], use_container_width=True, hide_index=True)
    elif status == "failed":
        st.error("综合失败：" + str(data.get("error") or "未知原因"))
        st.caption("这是强证据——仿真通过也不能说明这份 RTL 可综合。")
    else:
        st.info("综合未执行：" + str(data.get("skipped_reason") or data.get("error") or "本次运行未启用综合证据层"))
    if data.get("warnings"):
        st.caption(f"综合告警 {len(data['warnings'])} 条；首条：{data['warnings'][0]}")
    st.caption(data.get("disclaimer", ""))


# 注意：这个函数必须定义在**第一次调用之前**。ui/app.py 是线性脚本，模块级语句
# 按顺序执行——把它放在文件后半部分时，自定义 RTL 的行为级对比会在调用点抛
# NameError（被 except Exception 捕获成一句"行为级对比失败：name '_contract' is not defined"）。
def _compile_options() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """读取界面上填写的宏定义与 include 目录（逗号分隔）。

    这两项以前只有命令行支持（`--define` / `--include-dir`），网页上无法使用，
    于是"自定义 RTL 依赖宏或 include"的场景在演示时只能绕开。路径合法性不在这里
    判断：`SafePathPolicy` 会在执行前统一校验，越界会以明确错误返回。
    """

    raw_defines = str(st.session_state.get("compile_defines", "") or "")
    raw_includes = str(st.session_state.get("compile_includes", "") or "")
    defines = tuple(item.strip() for item in raw_defines.replace(";", ",").split(",") if item.strip())
    includes = tuple(item.strip() for item in raw_includes.replace(";", ",").split(",") if item.strip())
    return defines, includes


def _wire_api_for(label: str) -> Literal["responses", "chat_completions"]:
    """把界面上的接口格式标签映射成 provider 接受的**字面量**取值。

    原先三处各写一遍内联三元表达式，类型上退化成 `str`，静态检查无法确认
    传进去的一定是合法取值。集中成一个函数后，类型与实现都只有一份。
    """

    return "responses" if label.startswith("Responses") else "chat_completions"


def _contract() -> DutContract:
    if is_custom:
        if st.session_state.get("custom_contract") is None:
            raise ValueError("请先上传 RTL 并校验 DUT contract")
        return st.session_state.custom_contract
    return DutContract.from_json((ROOT / case["contract"]).read_text(encoding="utf-8"))

def _verification_rules(case_name: str, contract: DutContract, spec_text: str) -> str:
    """Load bounded repository rules for model guidance; never executes them."""
    return rules_context(ROOT, RULE_CASE_NAMES.get(case_name, case_name), contract.to_json(), spec_text=spec_text)[0]


@st.fragment
def _show_vcd_analysis(vcd_path: Path, *, key_prefix: str, preset: dict | None = None) -> None:
    """显示 VCD 信号元数据、语义结论与时间窗分析。

    **整段是 fragment**：用户反馈"点『读取窗口波形』『分析 VCD 时间窗口』像是没反应"——
    功能其实跑通了，但每次点击都重跑**整个脚本**，页面回到顶部、结果落在视口之外，
    看起来就像没生效（"用 GTKWave 自动打开"同理）。放进 fragment 后，这几个按钮只重跑
    这一段，结果就地出现。
    """

    data = preset or {}
    if data.get("status") == "parsed":
        st.caption(f"VCD 时间范围：{data.get('start_ns')} ns ～ {data.get('end_ns')} ns；信号 {data.get('signal_count', 0)} 个；变化 {data.get('total_changes', 0)} 次")
        if data.get("signals"):
            with st.expander("查看 VCD 信号列表"):
                st.dataframe(data["signals"], use_container_width=True, hide_index=True)

        # 信号活动覆盖率：激励质量的指标，**不是**代码覆盖率（口径见 docs/coverage.md）
        activity = data.get("coverage") or {}
        if activity.get("status") == "measured":
            st.markdown("**信号活动覆盖率（激励质量）**")
            columns = st.columns(3)
            columns[0].metric(
                "活动信号",
                f"{activity.get('changed_signals', 0)}/{activity.get('declared_signals', 0)}",
                f"{activity.get('ratio', 0) * 100:.0f}%",
            )
            value_coverage = activity.get("value_coverage")
            columns[1].metric("取值覆盖", "—" if value_coverage is None else f"{value_coverage * 100:.0f}%")
            columns[2].metric("未变化信号", activity.get("unchanged_signals", 0))
            if activity.get("unchanged"):
                st.info("本次仿真中未发生变化的信号：" + "、".join(activity["unchanged"]))
            if activity.get("value_detail"):
                with st.expander("各信号的取值覆盖明细"):
                    st.dataframe(activity["value_detail"], use_container_width=True, hide_index=True)
            st.caption(activity.get("disclaimer", ""))
            if activity.get("note"):
                st.caption(activity["note"])

        # 波形语义结论：边沿统计、稳定性与相位检查（来自流水线的 insights）
        insights = data.get("insights") or {}
        if insights.get("notes"):
            st.markdown("**波形语义结论**")
            for note in insights["notes"]:
                st.write(f"- {note}")
        if insights.get("unstable_signals"):
            st.warning("DUT 信号稳定性存疑：" + "、".join(insights["unstable_signals"]))
        if insights.get("unstable_auxiliary"):
            st.info(
                "testbench 记账信号在窗口内多次翻转（由激励脚本决定，不作为电路结论）："
                + "、".join(insights["unstable_auxiliary"])
            )
        if insights.get("signal_edges"):
            with st.expander("波形边沿统计（上升沿 / 下降沿 / 稳定性）"):
                rows = []
                stability = {item.get("signal"): item for item in insights.get("stability", [])}
                for item in insights["signal_edges"]:
                    entry = stability.get(item.get("signal"), {})
                    status = entry.get("status", "-")
                    if entry.get("status") == "unstable":
                        status = "不稳定(DUT)" if entry.get("is_dut") else "不稳定(tb记账)"
                    rows.append({**item, "归属": "DUT" if entry.get("is_dut") else "testbench", "稳定性": status})
                st.dataframe(rows, use_container_width=True, hide_index=True)
        if insights.get("phase_checks"):
            st.markdown("**相位检查（输出晚/早一拍）**")
            st.dataframe(insights["phase_checks"], use_container_width=True, hide_index=True)

        # 失败周期对应的波形时间窗（流水线已算好，此前没有展示入口）
        windows = data.get("failure_windows") or {}
        if windows.get("status") == "parsed" and windows.get("windows"):
            with st.expander(f"失败周期对应的波形时间窗（{len(windows['windows'])} 个）"):
                st.caption(windows.get("disclaimer", ""))
                rows = [
                    {
                        "失败周期": item.get("cycle"),
                        "时间窗(ns)": f"{item.get('start_ns')} ～ {item.get('end_ns')}",
                        "窗口内信号数": (item.get("analysis") or {}).get("signal_count", 0),
                        "窗口内变化数": (item.get("analysis") or {}).get("total_changes", 0),
                    }
                    for item in windows["windows"]
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)
                st.download_button(
                    "下载失败周期时间窗 JSON",
                    json.dumps(windows, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="failure-windows.json",
                    mime="application/json",
                    key=f"{key_prefix}_failure_windows",
                )
    if st.button("分析 VCD 时间窗口", key=f"{key_prefix}_analyze", help="按时间范围重新解析波形变化；不依赖 GTKWave"):
        if data.get("start_ns") is None or data.get("end_ns") is None:
            st.warning("VCD 没有可用时间范围")
        else:
            st.session_state[f"{key_prefix}_window"] = {"start": float(data["start_ns"]), "end": float(data["end_ns"])}
    window = st.session_state.get(f"{key_prefix}_window")
    if window is not None:
        st.caption("按时间范围重新解析波形变化（纯 Python 解析 VCD，不依赖 GTKWave）。")
        _win_cols = st.columns(2)
        start = _win_cols[0].number_input("窗口起始时间 (ns)", min_value=0.0, value=float(window["start"]), key=f"{key_prefix}_start")
        end = _win_cols[1].number_input("窗口结束时间 (ns)", min_value=float(start), value=max(float(start), float(window["end"])), key=f"{key_prefix}_end")
        if st.button("读取窗口波形", key=f"{key_prefix}_read", type="primary"):
            try:
                st.session_state[f"{key_prefix}_window_data"] = analyze_vcd_file(vcd_path, start_ns=start, end_ns=end, max_changes=2000)
            except Exception as exc:
                st.error(f"VCD 窗口分析失败：{exc}")
    window_data = st.session_state.get(f"{key_prefix}_window_data")
    if window_data:
        _win_total = window_data.get("total_changes", 0)
        _win_signals = window_data.get("signal_count", 0)
        st.success(
            f"已读取窗口 {window_data.get('start_ns')} ～ {window_data.get('end_ns')} ns："
            f"{_win_total} 次变化，覆盖 {_win_signals} 个信号"
            + ("（列表已按 2000 条截断，完整数据请下载 JSON）" if window_data.get("truncated") else "")
        )
        if window_data.get("changes"):
            st.dataframe(window_data["changes"], use_container_width=True, hide_index=True)
        else:
            st.info("该时间窗内没有任何信号变化；把起始/结束时间放宽一些再试。")
        st.download_button("下载 VCD 分析 JSON", json.dumps(window_data, ensure_ascii=False, indent=2).encode("utf-8"), file_name="vcd-analysis.json", mime="application/json", key=f"{key_prefix}_download")
    else:
        st.caption("提示：先点『分析 VCD 时间窗口』展开时间范围，再点『读取窗口波形』。")

    # 波形查看器：按钮放在 fragment 内，点击只重跑这一段（此前会整页重跑，看起来像没反应）。
    st.divider()
    _gv_col, _gv_info = st.columns([1, 3])
    with _gv_col:
        if st.button("用 GTKWave 打开", key=f"{key_prefix}_gtkwave_open"):
            ok, message = _open_vcd_with_gtkwave(vcd_path)
            st.session_state.gtkwave_message = message
            st.session_state.gtkwave_message_ok = ok
    with _gv_info:
        _gv_path = _configured_gtkwave()
        if _gv_path:
            st.caption(f"GTKWave：{_gv_path}")
        else:
            st.caption("GTKWave：未找到。可在「设置 → 波形查看器（GTKWave）」里手动填写路径。")
    if st.session_state.get("gtkwave_message"):
        renderer = st.success if st.session_state.get("gtkwave_message_ok") else st.warning
        renderer(st.session_state.gtkwave_message)


CASES: dict[str, dict[str, Any]] = {
    "交通灯·紧急模式": {"rtl": "rtl/traffic_light_emergency.v", "tb": "tb/tb_traffic_light_emergency.v", "top": "tb_traffic_light_emergency", "spec": "spec/traffic_light_emergency_spec.md", "contract": "examples/traffic_light_emergency_contract.json"},
    "模十计数器": {"rtl": "rtl/mod10_counter.v", "tb": "tb/tb_mod10_counter.v", "top": "tb_mod10_counter", "spec": "spec/mod10_counter_spec.md", "contract": "examples/mod10_counter_contract.json"},
    "简单 ALU": {"rtl": "rtl/simple_alu.v", "tb": "tb/tb_simple_alu.v", "top": "tb_simple_alu", "spec": "spec/simple_alu_spec.md", "contract": "examples/simple_alu_contract.json"},
    "101 序列检测（允许重叠）": {"rtl": "rtl/sequence_101_overlap.v", "tb": "tb/tb_sequence_101_overlap.v", "top": "tb_sequence_101_overlap", "spec": "spec/sequence_101_overlap_spec.md", "contract": "examples/sequence_101_overlap_contract.json"},
    "同步上升沿检测器": {"rtl": "rtl/edge_detector.v", "tb": "tb/tb_edge_detector.v", "top": "tb_edge_detector", "spec": "spec/edge_detector_spec.md", "contract": "examples/edge_detector_contract.json"},
    "脉冲展宽器": {"rtl": "rtl/pulse_stretcher.v", "tb": "tb/tb_pulse_stretcher.v", "top": "tb_pulse_stretcher", "spec": "spec/pulse_stretcher_spec.md", "contract": "examples/pulse_stretcher_contract.json"},
    "单时钟 FIFO": {"rtl": "rtl/sync_fifo.v", "tb": "tb/tb_sync_fifo.v", "top": "tb_sync_fifo", "spec": "spec/common_cases.md", "contract": "examples/sync_fifo_contract.json"},
    "UART 发送器": {"rtl": "rtl/uart_tx.v", "tb": "tb/tb_uart_tx.v", "top": "tb_uart_tx", "spec": "spec/common_cases.md", "contract": "examples/uart_tx_contract.json"},
    "SPI 主机": {"rtl": "rtl/spi_master.v", "tb": "tb/tb_spi_master.v", "top": "tb_spi_master", "spec": "spec/common_cases.md", "contract": "examples/spi_master_contract.json"},
    "Valid-Ready 握手级": {"rtl": "rtl/handshake_stage.v", "tb": "tb/tb_handshake_stage.v", "top": "tb_handshake_stage", "spec": "spec/common_cases.md", "contract": "examples/handshake_stage_contract.json"},
    "按键去抖": {"rtl": "rtl/debounce.v", "tb": "tb/tb_debounce.v", "top": "tb_debounce", "spec": "spec/common_cases.md", "contract": "examples/debounce_contract.json"},
    "PWM": {"rtl": "rtl/pwm.v", "tb": "tb/tb_pwm.v", "top": "tb_pwm", "spec": "spec/common_cases.md", "contract": "examples/pwm_contract.json"},
    "四选一多路选择器": {"rtl": "rtl/mux4.v", "tb": "tb/tb_mux4.v", "top": "tb_mux4", "spec": "spec/common_cases.md", "contract": "examples/mux4_contract.json"},
    "同步复位模块": {"rtl": "rtl/sync_reset.v", "tb": "tb/tb_sync_reset.v", "top": "tb_sync_reset", "spec": "spec/common_cases.md", "contract": "examples/sync_reset_contract.json"},
    "约翰逊计数器": {"rtl": "rtl/johnson_counter.v", "tb": "tb/tb_johnson_counter.v", "top": "tb_johnson_counter", "spec": "spec/johnson_counter_spec.md", "contract": "examples/johnson_counter_contract.json"},
}

RULE_CASE_NAMES = {
    "交通灯·紧急模式": "traffic_light_emergency", "模十计数器": "mod10_counter", "简单 ALU": "simple_alu", "101 序列检测（允许重叠）": "sequence_101_overlap", "同步上升沿检测器": "edge_detector", "脉冲展宽器": "pulse_stretcher", "单时钟 FIFO": "sync_fifo", "UART 发送器": "uart_tx", "SPI 主机": "spi_master", "Valid-Ready 握手级": "handshake_stage", "按键去抖": "debounce", "PWM": "pwm", "四选一多路选择器": "mux4", "同步复位模块": "sync_reset", "约翰逊计数器": "johnson_counter", "自定义 RTL": "custom_rtl",
}


def _show_failure_explanation(result, key):
    failures = getattr(result, "failures", ())
    if failures and st.button("解释失败原因", key=key):
        for failure in failures:
            item = explain_failure_record(failure)
            if getattr(failure, "severity", "warn") == "error":
                st.error(item.summary)
            else:
                st.warning(item.summary)
            st.caption(f"失败指纹：{item.fingerprint}")


def _candidate_repair_text(result, rtl_path):
    """Create a review-only repair proposal; never mutates RTL or invokes a shell."""
    failures = tuple(getattr(result, "failures", ()) or ())
    source = Path(rtl_path)
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        digest = "unavailable"
    lines = [
        "# 候选 RTL 修复建议（待人工确认）", "",
        "> 这不是已应用的补丁。系统不会自动覆盖原始 RTL。请人工审查后在临时副本中验证。", "",
        f"- RTL 文件：`{source.name}`", f"- RTL SHA-256：`{digest}`",
        f"- 失败条数：{len(failures)}", "", "## 失败证据",
    ]
    for index, failure in enumerate(failures, 1):
        item = explain_failure_record(failure)
        lines.extend([f"{index}. {item.summary}", f"   - 指纹：`{item.fingerprint}`"])
    lines += ["", "## 建议检查方向"]
    for failure in failures:
        message = (failure.message or "").lower()
        if "timeout" in message or "超时" in message:
            suggestion = "检查 testbench 是否缺少 $finish、时钟/复位是否持续，以及 RTL 是否存在无法退出的状态循环。"
        elif failure.signal:
            suggestion = f"检查信号 `{failure.signal}` 的时序、复位极性和边界条件；以失败周期附近波形为证据。"
        else:
            suggestion = "根据失败周期和 VCD 波形定位状态转换或输出时序问题。"
        lines.append(f"- {suggestion}")
    lines += ["", "## 人工确认清单", "- [ ] 已阅读失败证据和 VCD 波形", "- [ ] 已在临时副本应用修改", "- [ ] 已使用相同回归集重新仿真", "- [ ] 回归通过后再决定是否手动合并"]
    return "\n".join(lines) + "\n"


def _show_candidate_repair(result, rtl_path, key):
    """Show/download a candidate proposal only after an explicit user action."""
    failures = tuple(getattr(result, "failures", ()) or ())
    if not failures:
        return
    st.subheader("候选修复（仅建议，不自动写回）")
    st.caption("候选修复基于脱敏失败证据生成。下载内容是审查清单，不是已执行的 RTL 补丁。")
    if st.button("生成候选修复建议", key=key):
        st.session_state["candidate_repair_text"] = _candidate_repair_text(result, rtl_path)
    proposal = st.session_state.get("candidate_repair_text")
    if proposal:
        st.code(proposal, language="markdown")
        st.download_button("下载候选修复建议", proposal.encode("utf-8"), file_name="candidate-repair.md", mime="text/markdown", key=f"{key}_download")
        st.warning("请在临时副本中人工修改并重新运行完整回归；此页面不会自动修改原始 RTL。")


def _show_candidate_verify(before_result, rtl_path, contract, plan, key):
    """验证用户上传的候选 RTL 副本，并比较同一计划的前后结果。"""
    uploaded = st.file_uploader("上传候选修复 RTL（仅 .v/.sv；不会覆盖原文件）", type=["v", "sv"], key=f"{key}_upload")
    if uploaded is None:
        return
    if st.button("在临时副本中验证候选修复", key=f"{key}_run"):
        try:
            candidate = import_rtl_bytes(uploaded.name, uploaded.getvalue(), ROOT).path
            output = ROOT / ".iverilog-ai" / "repair-candidates" / candidate.stem
            after = VerificationPipeline().run(plan, contract, candidate, output, allowed_roots=(ROOT,),
                iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe", emit_vcd=True)
            comparison = compare_simulation_results(before_result, after.simulation)
            st.subheader("候选修复验证对比")
            st.json(comparison.__dict__)
            st.session_state[f"{key}_candidate_result"] = comparison.__dict__
            if comparison.verdict == "candidate_verified": st.success("候选修复通过相同测试计划验证")
            elif comparison.verdict == "improved": st.warning("候选版本有所改善，但仍需人工审查")
            else: st.error("候选修复未验证通过")
        except Exception as exc:
            st.error(f"候选修复验证失败：{exc}")


def _set_contract_editor(raw: str) -> None:
    """将 JSON contract 拆分到表格编辑器的 session 状态。"""
    try:
        value = json.loads(raw)
        st.session_state.custom_contract_editor_ports = list(value.get("ports", []))
        clock = value.get("clock") or {}
        reset = value.get("reset") or {}
        st.session_state.custom_contract_editor_parameters = dict(value.get("parameters") or {})
        st.session_state.custom_contract_editor_clock = {
            "signal": clock.get("signal", ""), "period_ns": float(clock.get("period_ns", 10.0)),
            "edge": clock.get("edge", "posedge"),
        }
        st.session_state.custom_contract_editor_reset = {
            "signal": reset.get("signal", ""), "active_level": int(reset.get("active_level", 0)),
            "synchronous": bool(reset.get("synchronous", False)), "assert_cycles": int(reset.get("assert_cycles", 2)),
        }
    except Exception:
        pass


def _contract_payload(
    *,
    module: str,
    ports: list,
    parameters: dict | None,
    clock_signal: str,
    clock_period: float,
    clock_edge: str,
    reset_signal: str,
    reset_active: Any,
    reset_sync: bool,
    reset_cycles: Any,
) -> dict:
    """把编辑区里的表格与时钟/复位字段拼成 contract 字典（纯函数，便于单测）。

    抽出来的理由：这段转换是"表格 → 合约"的唯一逻辑，出错的后果是**合约静默错位**
    （比如复位电平写反），而它原本埋在 Streamlit 控件代码里，无法在测试里直接调用。
    """

    payload: dict = {"module": module or "dut", "ports": list(ports)}
    if parameters:
        payload["parameters"] = dict(parameters)
    if str(clock_signal).strip():
        payload["clock"] = {"signal": str(clock_signal).strip(), "period_ns": float(clock_period), "edge": clock_edge}
    if str(reset_signal).strip():
        payload["reset"] = {
            "signal": str(reset_signal).strip(),
            "active_level": int(reset_active or 0),
            "synchronous": bool(reset_sync),
            "assert_cycles": int(reset_cycles or 1),
        }
    return payload


def _contract_editor_notice(level: str, message: str) -> None:
    """把一条提示留给 `_contract_editor` 在**下一次运行**开头渲染。

    为什么不直接 `st.success(...)`：校验逻辑放在控件回调里（见下），而回调在 fragment
    主体之前执行，此时渲染的提示会跑到编辑区最上方、与按钮离得很远；存下来在主体里渲染，
    位置稳定、也不会因为随后的重跑丢掉。
    """

    st.session_state["contract_editor_notice"] = (str(level), str(message))


def _validate_contract_on_click() -> None:
    """「校验 contract」按钮的回调：校验 + 规范化 + 回写文本框。

    **回调是关键**：Streamlit 在每次运行开始时先跑控件回调，再执行 fragment 主体，
    因此这里回写 `st.session_state.custom_contract_json_text` 完全合法——即使那个文本框
    带 `key` 也一样（它还没被创建）。

    真实事故：这段逻辑原先写在按钮的 `if st.button(...)` 分支里，位置在文本框**创建之后**，
    于是每次点「校验 contract」都抛
    `StreamlitAPIException: st.session_state.custom_contract_json_text cannot be modified
    after the widget with key ... is instantiated`，按钮等于完全不可用。
    """

    try:
        contract = DutContract.from_json(st.session_state.get("custom_contract_json_text", ""))
    except Exception as exc:
        st.session_state.custom_contract = None
        _contract_editor_notice("error", f"contract 无效：{exc}")
        return
    st.session_state.custom_contract = contract
    canonical = contract.to_json()
    st.session_state.custom_contract_text = canonical
    # 回调阶段回写控件 key 合法：文本框本次运行还没创建，下一次渲染就会显示规范格式。
    st.session_state.custom_contract_json_text = canonical
    _contract_editor_notice("success", "contract 校验通过，可以生成 AI 计划")


def _apply_json_to_table_on_click() -> None:
    """「用 JSON 刷新表格」的回调：把 JSON 里的端口、时钟、复位同步到编辑控件。

    同样靠"回调先于主体执行"这条性质：换掉 data_editor 的 key（让它用新数据重新初始化）、
    直接写时钟/复位控件的 key，都不需要任何重跑。以前这一步用
    `st.rerun(scope="fragment")`，而整页运行时 Streamlit 会**拒绝**该 scope
    （"can only be specified from @st.fragment-decorated functions during fragment reruns"），
    同一个按钮在两种运行上下文里表现不一致；现在整条交互链里不再有 `st.rerun`。
    """

    try:
        parsed = DutContract.from_json(st.session_state.get("custom_contract_json_text", ""))
    except Exception as exc:
        _contract_editor_notice("error", f"JSON 无效：{exc}")
        return
    payload = parsed.to_dict()
    st.session_state.custom_contract_editor_ports = list(payload.get("ports", []))
    # 换一代 key：data_editor 用新端口列表重新初始化（数据始终只从影子列表来）。
    st.session_state["contract_editor_gen"] = int(st.session_state.get("contract_editor_gen", 0)) + 1
    st.session_state.custom_contract_text = parsed.to_json()
    _set_contract_editor(parsed.to_json())
    clock = payload.get("clock") or {}
    reset = payload.get("reset") or {}
    st.session_state["contract_clock_signal"] = str(clock.get("signal", ""))
    st.session_state["contract_clock_period"] = float(clock.get("period_ns", 10.0))
    st.session_state["contract_clock_edge"] = str(clock.get("edge", "posedge"))
    st.session_state["contract_reset_signal"] = str(reset.get("signal", ""))
    st.session_state["contract_reset_active"] = int(reset.get("active_level", 0))
    st.session_state["contract_reset_sync"] = bool(reset.get("synchronous", False))
    st.session_state["contract_reset_cycles"] = int(reset.get("assert_cycles", 2))
    # JSON 改过就必须重新校验，避免用旧合约继续跑
    st.session_state.custom_contract = None
    _contract_editor_notice("success", "已用 JSON 刷新表格；下一步点「校验 contract」。")


def _load_suggested_assertions_on_click() -> None:
    """「载入本案例推荐结构化断言」的回调：把已验证的建议写进断言文本框。

    放在回调里（而不是 `if st.button(...)` 分支里）有两个原因：回调在主体之前执行，
    写进去的值本次运行就会显示；而且不需要整页重跑——用户在「从表格生成 JSON」那里
    明确反馈过整页刷新很烦。

    当前 `rule_assertions` 的建议表是空的（原先 5 条全部不成立，见该模块说明），
    因此这个按钮暂时不会渲染；表里一旦重新加入经门禁验证的条目，按钮即可用。
    """

    case_key = str(st.session_state.get("case_name", ""))
    suggestions = assertion_suggestions(RULE_CASE_NAMES.get(case_key, case_key))
    if suggestions:
        st.session_state.structured_assertions_text = json.dumps(suggestions, ensure_ascii=False, indent=2)


def _contract_module_hint() -> str:
    """从当前 JSON 文本框里取 `module`，作为「从表格生成 JSON」的模块名兜底。

    只读、只认字符串且非空；解析失败就返回空串（调用方再兜底 "dut"）。
    """

    try:
        payload = json.loads(st.session_state.get("custom_contract_json_text") or "{}")
    except Exception:
        return ""
    if isinstance(payload, dict):
        module = payload.get("module")
        if isinstance(module, str) and module.strip():
            return module.strip()
    return ""


@st.fragment
def _contract_editor() -> None:
    """DUT contract 编辑区（**整段跑在 fragment 里**）。

    为什么要 fragment：Streamlit 默认"控件一变就重跑整个脚本"，编辑表格或点按钮都会让
    整页重新渲染——滚动位置丢失、其它区域闪烁，体验上就像刷新了整个页面。
    `@st.fragment` 让这一段的交互只重跑这一段。

    另外两处修正：
    - 表格 ↔ JSON 的同步原来是**自动双向**的（JSON 一变回写表格、表格一变又靠
      `st.rerun()` 回写），既容易互相覆盖，也必须多跑一遍脚本才生效。现在改成两个显式
      动作：表格 → JSON（表单提交）、JSON → 表格（按钮），不再有隐式重跑。
    - 原来"从表格生成 JSON"先 `st.success(...)` 再 `st.rerun()`，那条成功提示会被立刻
      丢掉（用户只看到页面一闪）。现在不重跑，提示留在原地。

    还有一条 Streamlit 硬规则必须绕开：**本**次运行里已经创建过 `key=X` 的控件之后，
    再写 `st.session_state.X` 会直接抛
    `StreamlitAPIException: ... cannot be modified after the widget with key ... is instantiated`。
    这里的对策是**按动作选位置**，而不是到处搬代码：
    - 「表格 → JSON」需要 data_editor 的返回值，只能在主体里做——它写的是文本框 key，
      但位置在文本框**之前**，合法；
    - 「校验 contract」不需要任何控件返回值（JSON 文本就在 session state 里），因此整个
      搬到 `on_click` 回调里，在主体之前执行，回写文本框 key 合法且当次立即生效；
    - 「JSON → 表格」要在渲染前换成新数据（换 data_editor 的 key、并回写时钟/复位控件），
      同样放在回调里，因此**整条交互链里没有 `st.rerun`**：不需要整页重跑，也不需要
      `scope="fragment"` 重跑（后者在整页运行时会被 Streamlit 直接拒绝）。
    """

    _notice = st.session_state.pop("contract_editor_notice", None)
    if isinstance(_notice, tuple) and len(_notice) == 2:
        _level, _message = str(_notice[0]), str(_notice[1])
        (st.error if _level == "error" else st.success)(_message)

    if not st.session_state.get("custom_contract_text"):
        return
    # 影子列表（端口数据）永远是 list：解析失败也要留一个空列表，否则后续读取会 KeyError。
    if not isinstance(st.session_state.get("custom_contract_editor_ports"), list):
        _set_contract_editor(st.session_state.custom_contract_text)
        if not isinstance(st.session_state.get("custom_contract_editor_ports"), list):
            st.session_state.custom_contract_editor_ports = []
    _ports_shadow = st.session_state["custom_contract_editor_ports"]
    # data_editor 的数据**始终**来自影子列表（`custom_contract_editor_ports`），
    # `key` 只用来标识控件。踩过的坑：`session_state[key]` 里存的是 Streamlit 自己的
    # **编辑状态**（`{edited_rows, added_rows, deleted_rows}`），不是端口数据；把它当数据
    # 喂回 data_editor，pandas 会抛 "Mixing dicts with non-Series…" 直接把整页打成 500
    # （真实事故，见 job 日志）。所以：数据只从一个地方来，编辑结果只看返回值。
    #
    # 需要"换一批数据"时（JSON → 表格），靠换 key 让编辑器重新初始化：
    _editor_generation = int(st.session_state.get("contract_editor_gen", 0))
    _editor_key = f"custom_ports_editor_{_editor_generation}"

    with st.expander("① 表格化编辑 DUT contract", expanded=True):
        with st.form("contract_form", clear_on_submit=False):
            rows = st.data_editor(
                _ports_shadow,
                num_rows="dynamic",
                use_container_width=True,
                key=_editor_key,
                column_config={
                    "name": st.column_config.TextColumn("端口名称", required=True),
                    "direction": st.column_config.SelectboxColumn(
                        "方向", options=["input", "output", "inout"], required=True
                    ),
                    "width": st.column_config.NumberColumn("位宽", min_value=1, max_value=4096, step=1, required=True),
                    "signed": st.column_config.CheckboxColumn("有符号", default=False),
                },
            )
            c1, c2, c3 = st.columns(3)
            clock = st.session_state.get("custom_contract_editor_clock", {"signal": "", "period_ns": 10.0, "edge": "posedge"})
            reset = st.session_state.get("custom_contract_editor_reset", {"signal": "", "active_level": 0, "synchronous": False, "assert_cycles": 2})
            with c1:
                clock_signal = st.text_input("时钟信号", value=clock.get("signal", ""), key="contract_clock_signal")
                clock_period = st.number_input("时钟周期 (ns)", min_value=0.001, value=float(clock.get("period_ns", 10.0)), key="contract_clock_period")
                clock_edge = st.selectbox("时钟边沿", ["posedge", "negedge"], index=0 if clock.get("edge", "posedge") == "posedge" else 1, key="contract_clock_edge")
            with c2:
                reset_signal = st.text_input("复位信号（可留空）", value=reset.get("signal", ""), key="contract_reset_signal")
                reset_active = st.selectbox("复位有效电平", [0, 1], index=int(reset.get("active_level", 0)), key="contract_reset_active")
                reset_sync = st.checkbox("同步复位", value=bool(reset.get("synchronous", False)), key="contract_reset_sync")
            with c3:
                reset_cycles = st.number_input("复位持续周期", min_value=1, max_value=10000, value=int(reset.get("assert_cycles", 2)), step=1, key="contract_reset_cycles")
                st.caption("留空复位信号表示 contract 不包含 reset。")
            _submitted = st.form_submit_button("从表格生成 JSON", type="primary")
        if _submitted:
            try:
                payload = _contract_payload(
                    # 模块名的优先级：用户显式选的顶层 module → 当前 JSON 里写的 module →
                    # 兜底 "dut"。早先只写 `get("custom_selected_module", "dut")`：从没上传过
                    # RTL（例如直接手写 JSON 进编辑区）时会静默生成一份 `module="dut"` 的
                    # 合约——它自己校验得过，但和真实 RTL 的模块名对不上。
                    module=str(
                        st.session_state.get("custom_selected_module") or _contract_module_hint() or "dut"
                    ),
                    ports=list(rows),
                    parameters=st.session_state.get("custom_contract_editor_parameters"),
                    clock_signal=clock_signal,
                    clock_period=clock_period,
                    clock_edge=str(clock_edge or "posedge"),
                    reset_signal=reset_signal,
                    reset_active=reset_active,
                    reset_sync=reset_sync,
                    reset_cycles=reset_cycles,
                )
                _contract = DutContract.from_dict(payload)
                st.session_state.custom_contract_text = _contract.to_json()
                st.session_state.custom_contract_editor_ports = list(_contract.to_dict()["ports"])
                # 文本框在下方创建，本行在它之前执行，因此回写它的 key 合法。
                st.session_state.custom_contract_json_text = _contract.to_json()
                # 表格改过就必须重新校验，避免用旧合约继续跑
                st.session_state.custom_contract = None
                st.success("已生成 JSON，下一步点「校验 contract」。")
            except Exception as exc:
                st.error(f"表格内容无效：{exc}")

    # 文本框带 `key`，值由 Streamlit 自己管；首帧用一个种子，避免出现空框。
    if "custom_contract_json_text" not in st.session_state:
        st.session_state.custom_contract_json_text = st.session_state.get("custom_contract_text", "")
    st.text_area(
        "② DUT contract JSON（可直接编辑）",
        height=190,
        key="custom_contract_json_text",
        help="表格与 JSON 不再自动互相同步：表格改完点上面的「从表格生成 JSON」，JSON 改完点下面的「用 JSON 刷新表格」。",
    )
    _sync_col, _validate_col, _export_col = st.columns([1, 1, 3])
    with _sync_col:
        # 两个按钮的逻辑都放在 `on_click` 回调里：回调在本次运行**创建任何控件之前**执行，
        # 因此可以合法地回写控件 key、也可以在渲染前换掉 data_editor 的数据，
        # 既不需要整页重跑，也不需要 fragment 级重跑（见两个回调函数的说明）。
        st.button(
            "用 JSON 刷新表格",
            key="contract_json_to_editor",
            on_click=_apply_json_to_table_on_click,
        )
    with _validate_col:
        st.button(
            "校验 contract",
            type="primary",
            key="validate_custom_contract",
            on_click=_validate_contract_on_click,
        )
    with _export_col:
        if st.session_state.get("custom_contract") is not None:
            with st.popover("导出"):
                st.download_button(
                    "contract JSON",
                    st.session_state.custom_contract.to_json(),
                    file_name="dut_contract.json",
                    mime="application/json",
                    key="download_custom_contract",
                )


def _offline_provider(contract: DutContract, *, vector_count: int | None = None) -> DeterministicLocalProvider:
    """构造页面「离线」模式用的规划器：按**当前 DUT contract** 生成激励。

    真实事故：这里原先直接 `MockProvider()`，而它的默认返回值是一份写死的演示计划
    （design=demo，向量固定驱动 `rst_n`）。选中组合逻辑案例（`simple_alu`、`mux4`
    的合约中没有时钟也没有复位）后点「生成测试计划」，下游生成 testbench 时必然
    报 `vectors[0].inputs contains unknown port 'rst_n'`——而同一个案例点「执行真实
    Icarus 仿真」却是通过的，看起来像"离线模式坏了"。

    现在离线模式走仓库自带的确定性离线规划器（与本地调试模型服务同一个引擎），
    它按合约里真实存在的端口生成激励，因此对组合逻辑与时序案例都有效。
    """

    # seed 固定为 0：同一次输入永远得到同一份计划，报告与复现实验才能对齐。
    if vector_count is None:
        return offline_provider(contract, seed=0)
    return offline_provider(contract, seed=0, vector_count=vector_count)


def _build_provider(target: str):
    """按当前界面选择构造 provider；本地调试模型不需要密钥，也不允许出站网络。"""

    if use_debug_local:
        return OpenAICompatibleProvider(
            endpoint=debug_endpoint,
            model="debug-local",
            wire_api="chat_completions",
            reasoning_effort=None,
            allow_network=False,
            store=False,
            timeout=30,
        )
    wire = _wire_api_for(str(wire_api_label))
    if "deepseek" in (api_base + " " + api_model).lower() and wire == "responses":
        wire = "chat_completions"
    if not api_key.strip():
        raise ValueError(f"{target}需要先输入 API Key（或改用本地调试模型）")
    return OpenAICompatibleProvider(
        endpoint=api_base,
        model=api_model,
        api_key=api_key,
        wire_api=wire,
        reasoning_effort=None if str(reasoning_label).startswith("不发送") or wire != "responses" else reasoning_label,
        allow_network=True,
        store=False,
        timeout=api_timeout,
        max_output_tokens=api_output_tokens,
    )


# ---------------------------------------------------------------------------
# 视觉主题（莱茵生命风格：临床白 + 青色强调 + 细线 + 等宽数值）
# ---------------------------------------------------------------------------
_RL_CSS = """
<style>
:root{
  --rl-bg:#eef2f4; --rl-panel:#ffffff; --rl-ink:#0d1b24; --rl-ink-soft:#33474f;
  --rl-muted:#6f8189; --rl-line:#d7e0e4; --rl-line-strong:#b9c7cd;
  --rl-cyan:#00a3b4; --rl-cyan-dark:#00707b; --rl-cyan-soft:#e3f4f6;
  --rl-amber:#b8802b; --rl-red:#b8453d; --rl-green:#2f8f6b;
  --rl-mono:ui-monospace,"Cascadia Mono","JetBrains Mono",Consolas,"SFMono-Regular",monospace;
}
/* 临床白底 + 淡青色网格（实验室感，不喧宾夺主） */
.stApp{
  background:
    linear-gradient(0deg, rgba(0,163,180,.045) 1px, transparent 1px) 0 0/100% 30px,
    linear-gradient(90deg, rgba(0,163,180,.045) 1px, transparent 1px) 0 0/30px 100%,
    var(--rl-bg);
}
.block-container{padding-top:1.1rem; padding-bottom:2.5rem; max-width:1400px;}
#MainMenu, footer{visibility:hidden;}
h1,h2,h3{letter-spacing:.01em; color:var(--rl-ink);}
h2{font-size:1.12rem !important; padding-left:.55rem; border-left:3px solid var(--rl-cyan);}
h3{font-size:.98rem !important; color:var(--rl-ink-soft);}
/* 导航栏 */
.stTabs [data-baseweb="tab-list"]{gap:0; border-bottom:1px solid var(--rl-line-strong); background:transparent;}
.stTabs [data-baseweb="tab"]{
  height:38px; padding:0 16px; background:transparent;
  font-size:.8rem; font-weight:600; letter-spacing:.16em; color:var(--rl-muted);
}
.stTabs [data-baseweb="tab"]:hover{color:var(--rl-cyan-dark);}
.stTabs [aria-selected="true"]{color:var(--rl-cyan-dark) !important;}
.stTabs [data-baseweb="tab-highlight"]{background-color:var(--rl-cyan) !important; height:2px;}
.stTabs [data-baseweb="tab-border"]{background-color:var(--rl-line);}
/* 按钮：主操作只有一个（青色实心），次操作描边，三级操作去掉边框 */
.stButton>button, .stDownloadButton>button{font-size:.82rem; border-radius:3px; font-weight:600;}
.stButton>button[kind="primary"], .stButton>button[data-testid="baseButton-primary"]{
  background:var(--rl-cyan); border:1px solid var(--rl-cyan); color:#fff;
}
.stButton>button[kind="primary"]:hover{background:var(--rl-cyan-dark); border-color:var(--rl-cyan-dark);}
.stButton>button[kind="secondary"], .stButton>button[data-testid="baseButton-secondary"]{
  background:var(--rl-panel); border:1px solid var(--rl-line-strong); color:var(--rl-ink-soft);
}
.stButton>button[kind="secondary"]:hover{border-color:var(--rl-cyan); color:var(--rl-cyan-dark);}
/* 三级动作（下载/次要导出）：更小、更轻 */
.stDownloadButton>button{
  background:transparent; border:1px dashed var(--rl-line-strong); color:var(--rl-muted);
  font-size:.74rem; font-weight:500; padding:.15rem .5rem; min-height:1.6rem;
}
.stDownloadButton>button:hover{border-color:var(--rl-cyan); color:var(--rl-cyan-dark); background:var(--rl-cyan-soft);}
/* 指标卡：白底细边，数值等宽 */
[data-testid="stMetric"]{
  background:var(--rl-panel); border:1px solid var(--rl-line); border-radius:4px;
  padding:.5rem .7rem;
}
[data-testid="stMetricLabel"] p{font-size:.72rem; letter-spacing:.08em; color:var(--rl-muted);}
[data-testid="stMetricValue"]{font-family:var(--rl-mono); font-size:1.35rem; color:var(--rl-ink);}
/* 折叠面板：标题更小，边框更细 */
[data-testid="stExpander"] details{border:1px solid var(--rl-line); border-radius:4px; background:var(--rl-panel);}
[data-testid="stExpander"] summary{font-size:.84rem; color:var(--rl-ink-soft);}
/* 数据表与代码块 */
[data-testid="stDataFrame"], [data-testid="stTable"]{border:1px solid var(--rl-line);}
.stCode, pre{font-family:var(--rl-mono) !important; font-size:.8rem;}
/* 状态点 */
.rl-chip{display:inline-flex; align-items:center; gap:.35rem; margin:0 .35rem .25rem 0;
  padding:.12rem .45rem; border:1px solid var(--rl-line-strong); border-radius:3px;
  background:var(--rl-panel); font-size:.72rem; color:var(--rl-ink-soft); font-family:var(--rl-mono);}
.rl-chip b{font-weight:600; color:var(--rl-ink);}
.rl-dot{width:7px; height:7px; background:var(--rl-cyan); display:inline-block;
  clip-path:polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%);}
.rl-dot.ok{background:var(--rl-green);} .rl-dot.warn{background:var(--rl-amber);}
.rl-dot.err{background:var(--rl-red);} .rl-dot.idle{background:var(--rl-line-strong);}
/* 品牌栏 */
.rl-brand{display:flex; align-items:baseline; gap:.7rem; border-bottom:2px solid var(--rl-ink);
  padding:.15rem 0 .4rem 0; margin-bottom:.35rem;}
.rl-brand .mark{font-family:var(--rl-mono); font-weight:700; letter-spacing:.18em; font-size:1.02rem; color:var(--rl-ink);}
.rl-brand .mark span{color:var(--rl-cyan);}
.rl-brand .tag{font-size:.72rem; letter-spacing:.14em; color:var(--rl-muted); text-transform:uppercase;}
.rl-note{border-left:2px solid var(--rl-cyan); background:var(--rl-cyan-soft);
  padding:.45rem .7rem; font-size:.78rem; color:var(--rl-ink-soft); border-radius:0 3px 3px 0;}
.rl-manual h4{margin:.6rem 0 .2rem 0;}
</style>
"""


def _inject_theme() -> None:
    st.markdown(_RL_CSS, unsafe_allow_html=True)


def _chips(items: list[tuple[str, str, str]]) -> None:
    """渲染状态小标签：`(标签, 值, 状态)`，状态取 ok/warn/err/idle。"""

    html = "".join(
        f'<span class="rl-chip"><i class="rl-dot {state}"></i>{label} <b>{value}</b></span>'
        for label, value, state in items
    )
    st.markdown(html, unsafe_allow_html=True)


def _brandbar() -> None:
    st.markdown(
        '<div class="rl-brand">'
        '<div class="mark">ICARUS<span>·</span>智测</div>'
        '<div class="tag">AI proposes · open-source simulator decides</div>'
        "</div>",
        unsafe_allow_html=True,
    )


_MANUAL_DIR = ROOT / "docs" / "manual"
_MANUAL_PAGES = (
    ("入门 · 15 分钟跑通", "01_beginner.md"),
    ("进阶 · 接进你的流程", "02_advanced.md"),
    ("深度 · 判据与可复现", "03_deep.md"),
    ("按目的 · 四条最短路径", "04_by_goal.md"),
)


def _render_manual() -> None:
    """在网页内渲染多版使用手册（内容源是仓库里的 Markdown，CLI 与网页共用一份）。"""

    tabs = st.tabs([title for title, _ in _MANUAL_PAGES])
    for tab, (title, filename) in zip(tabs, _MANUAL_PAGES):
        with tab:
            path = _MANUAL_DIR / filename
            if not path.is_file():
                st.warning(f"手册文件缺失：{path.relative_to(ROOT)}")
                continue
            st.markdown(path.read_text(encoding="utf-8"), unsafe_allow_html=False)
    st.caption("手册源文件在 `docs/manual/`，与命令行/报告用的是同一份，欢迎直接改。")


st.set_page_config(page_title="Icarus 智测", page_icon="⬢", layout="wide")
_inject_theme()
_brandbar()

# ── 全局控制行（紧凑：案例选择不占整行） ───────────────────────────────────
_col_case, _col_meta = st.columns([1.1, 3.4])
with _col_case:
    name = st.selectbox("案例", ["自定义 RTL"] + list(CASES), label_visibility="collapsed", key="case_name")
is_custom = name == "自定义 RTL"
case: dict[str, Any] = CASES.get(
    str(name),
    {"rtl": None, "tb": None, "top": None, "spec": "自定义 RTL", "contract": None},
)
with _col_meta:
    _ev = _project_evidence()
    _aligned = int(_ev.get("models_aligned") or 0)
    _models_total = int(_ev.get("models_total") or 0)
    _tools_ok = bool(_ev.get("iverilog"))
    _chips(
        [
            ("案例", str(name), "warn" if is_custom else "ok"),
            ("参考模型", f"{_aligned}/{_models_total}", "ok" if _aligned == _models_total and _aligned else "idle"),
            ("Icarus", "可用" if _tools_ok else "缺失", "ok" if _tools_ok else "err"),
            ("GTKWave", "可用" if _ev.get("gtkwave") else "缺失", "ok" if _ev.get("gtkwave") else "idle"),
            ("基准", f"{_ev.get('cases', 0)} 案例 / {_ev.get('defects', 0)} 缺陷", "idle"),
            ("静态规则", f"{_ev.get('rules', 0)} 条", "idle"),
            ("测试", f"{_ev.get('tests', 0)} 项", "idle"),
        ]
    )

_TAB_OVERVIEW, _TAB_VERIFY, _TAB_QUALITY, _TAB_MANUAL, _TAB_SETTINGS, _TAB_HISTORY = st.tabs(
    ["概览", "验证", "质量与对比", "手册", "设置", "历史"]
)

with _TAB_OVERVIEW:
    st.markdown("### 本轮验证的现场状态")
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("基准规模", f"{_ev.get('cases', 0)} 案例", f"{_ev.get('defects', 0)} 个缺陷变体")
    _m2.metric("参考模型对齐", f"{len(_ev.get('aligned', []))} / {_ev.get('cases', 0)}", "权威期望值来源")
    _m3.metric("自动化测试", f"{_ev.get('tests', 0)}", "pytest")
    _m4.metric("静态规则", f"{_ev.get('rules', 0)}", "每条配正反例")
    _render_evidence_header()
    st.markdown("### 三步走完这轮验证")
    _s1, _s2, _s3 = st.columns(3)
    _s1.markdown("**① 选案例** —— 顶部下拉框选内置案例，或选「自定义 RTL」上传自己的设计。")
    _s2.markdown("**② 生成计划** —— 到「验证」页填验证目标 → 生成测试计划（AI 只负责这一件事）。")
    _s3.markdown("**③ 执行裁决** —— 同页点执行：编译 → 仿真 → 结构化断言 → 报告。判决权在 Icarus。")
    st.markdown(
        '<div class="rl-note">不确定从哪开始？<b>手册</b>页有四版说明：入门 / 进阶 / 深度 / 按目的。'
        "只想对比两份 RTL 的人，直接看「按目的」的第一节。</div>",
        unsafe_allow_html=True,
    )

with _TAB_MANUAL:
    _render_manual()


with _TAB_VERIFY:
    if is_custom:
        if "custom_rtl_path" not in st.session_state:
            st.session_state.custom_rtl_path = ""
            st.session_state.custom_contract = None
            st.session_state.custom_contract_text = ""
        uploaded = st.file_uploader(
            "上传 Verilog/SystemVerilog RTL 工程（可多选，支持 .v/.sv/.vh；单文件 2 MB 内）",
            type=["v", "sv", "vh"], accept_multiple_files=True,
            help="多文件会被安全复制到项目 .iverilog-ai/custom_rtl，并合并为仿真输入；不会执行上传文件中的命令。",
        )
        upload_key = tuple((item.name, len(item.getvalue())) for item in uploaded) if uploaded else ()
        if uploaded and st.session_state.get("custom_uploaded_key") != upload_key:
            try:
                imported_files = []
                sources = []
                for item in uploaded:
                    imported = import_rtl_bytes(item.name, item.getvalue(), ROOT)
                    imported_files.append(imported)
                    sources.append(f"// ---- {item.name} ----\n" + item.getvalue().decode("utf-8"))
                source = "\n\n".join(sources)
                digest = __import__("hashlib").sha256(source.encode("utf-8")).hexdigest()[:12]
                aggregate = ROOT / ".iverilog-ai" / "custom_rtl" / f"project-{digest}.sv"
                aggregate.write_text(source, encoding="utf-8")
                imported = imported_files[0]
                st.session_state.custom_uploaded_key = upload_key
                st.session_state.custom_uploaded_files = tuple(i.name for i in uploaded)
                st.session_state.custom_rtl_path = str(aggregate)
                st.session_state.custom_contract_text = json.dumps(imported.contract, ensure_ascii=False, indent=2)
                st.session_state.custom_rtl_source = source
                st.session_state.custom_modules = available_modules(st.session_state.custom_rtl_source)
                st.session_state.custom_selected_module = imported.module
                st.session_state.custom_warnings = tuple(w for i in imported_files for w in i.warnings)
                st.success(f"已导入 {len(uploaded)} 个文件；检测到 module：{', '.join(st.session_state.custom_modules) or '未识别'}")
            except RTLImportError as exc:
                st.error(str(exc))
        if st.session_state.get("custom_uploaded_files"):
            st.caption("已上传文件：" + "、".join(st.session_state.custom_uploaded_files))
        modules = st.session_state.get("custom_modules", ())
        if len(modules) > 1:
            selected = st.selectbox("顶层 module（多模块 RTL 请明确选择）", modules,
                                    index=max(0, modules.index(st.session_state.get("custom_selected_module", modules[0])))
                                    if st.session_state.get("custom_selected_module", modules[0]) in modules else 0)
            if selected != st.session_state.get("custom_selected_module"):
                try:
                    _, selected_contract, selected_warnings = extract_contract_draft(
                        st.session_state["custom_rtl_source"], module_name=selected
                    )
                    st.session_state.custom_selected_module = selected
                    st.session_state.custom_contract_text = json.dumps(selected_contract, ensure_ascii=False, indent=2)
                    st.session_state.custom_warnings = selected_warnings
                    st.rerun()
                except RTLImportError as exc:
                    st.error(f"顶层 module 解析失败：{exc}")
        for warning in st.session_state.get("custom_warnings", ()):
            st.warning(warning)
        _contract_editor()
        case = {"rtl": st.session_state.get("custom_rtl_path"), "tb": None, "top": None, "spec": "自定义 RTL", "contract": None}
        reference_options = [p for p in sorted((ROOT / "rtl").glob("*.v")) if "_bug_" not in p.name and "bug_" not in p.name]
        if st.session_state.get("custom_rtl_source") and reference_options:
            reference_choice = Path(str(st.selectbox("标准 RTL 参考实现", reference_options, format_func=lambda p: p.name)))
            if st.button("对比自定义 RTL 与标准实现", key="compare_custom_reference"):
                comparison = compare_rtl_sources(st.session_state.custom_rtl_source, reference_choice.read_text(encoding="utf-8"), user_name="上传 RTL", reference_name=reference_choice.name)
                st.session_state.rtl_comparison = comparison
        if st.session_state.get("rtl_comparison"):
            comparison = st.session_state.rtl_comparison
            st.subheader("RTL 结构对比与学习建议")
            st.metric("端口匹配", "通过" if comparison["port_match"] else "需检查")
            if comparison["strengths"]:
                st.success("做得好的地方：" + "；".join(comparison["strengths"]))
            if comparison["gaps"]:
                st.warning("可以改进：" + "；".join(comparison["gaps"]))
            st.write("下一步学习计划：")
            for index, item in enumerate(comparison["learning_plan"], 1):
                st.write(f"{index}. {item}")
            with st.popover("导出对比报告"):
                st.download_button(
                    "RTL 对比 JSON",
                    json.dumps(comparison, ensure_ascii=False, indent=2),
                    file_name="rtl-comparison.json",
                    mime="application/json",
                    key="download_rtl_comparison",
                )
            st.caption("以上是**结构级**对比（端口、复位、赋值风格等文本特征）。行为是否一致要看下面的行为级对比。")
            if st.session_state.get("custom_rtl_path") and Path(st.session_state.custom_rtl_path).is_file():
                if st.button("运行行为级对比（同一份 TestPlan 跑两份 RTL）", key="behavior_compare_button",
                             help="需要先生成 AI 测试计划；两侧用完全相同的激励与 contract，比对逐检查项结果与波形。"):
                    current_plan = st.session_state.get("ai_plan")
                    if current_plan is None:
                        st.warning("请先生成 AI 测试计划，再做行为级对比。")
                    else:
                        try:
                            outcome = compare_rtl_behavior(
                                current_plan,
                                _contract(),
                                st.session_state.custom_rtl_path,
                                reference_choice,
                                ROOT / ".iverilog-ai" / "behavior-compare-ui" / reference_choice.stem,
                                allowed_roots=(ROOT,),
                                iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                                vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe",
                            )
                            st.session_state.behavior_comparison = outcome.to_dict()
                        except Exception as exc:
                            st.error(f"行为级对比失败：{exc}")
        if st.session_state.get("behavior_comparison"):
            _show_behavior_comparison(st.session_state.behavior_comparison)
    else:
        st.write(f"规格：`{case['spec']}`")


with _TAB_QUALITY:
    if case.get("rtl") and Path(case["rtl"]).is_file():
        if st.button("执行 RTL 静态质量审查", key="run_static_rtl_review", help="检查时序/组合赋值、复位、default、CDC 提示和其他规则；不替代仿真"):
            try:
                st.session_state.static_rtl_review = review_rtl_file(case["rtl"])
            except Exception as exc:
                st.error(f"RTL 静态审查失败：{exc}")
    if st.session_state.get("static_rtl_review"):
        static_review = st.session_state.static_rtl_review
        st.subheader("RTL 静态质量审查")
        st.caption(
            "这一节只**读 RTL 文本**，不跑仿真、不做综合与时序分析——它回答的是"
            "「代码里有没有已知的坑与坏习惯」，**不是**「功能对不对」（功能对不对由 Icarus 判决）。"
            "每条命中给出六列：规则 ID（英文稳定标识，可用于查规则表/写反馈）、严重度、行号、"
            "问题描述、修改建议、命中的那一行代码。"
        )
        _score_col, _status_col, _count_col = st.columns(3)
        _score_col.metric("质量评分", f"{static_review['quality_score']}/100", help="按严重度加权扣分后的参考分（error 20 分、warn 5 分、info 1 分），不是功能正确性结论。")
        _status_col.metric("审查状态", {"pass": "通过", "warn": "有告警", "fail": "有错误"}.get(static_review["status"], static_review["status"]))
        _count_col.metric(
            "命中条数",
            static_review["finding_count"],
            f"错误 {static_review['counts'].get('error', 0)} / 警告 {static_review['counts'].get('warn', 0)} / 提示 {static_review['counts'].get('info', 0)}",
        )
        st.caption(static_review["disclaimer"])
        if static_review["findings"]:
            _severity_cn = {"error": "错误", "warn": "警告", "info": "提示"}
            st.dataframe(
                [
                    {
                        "规则ID": item["rule_id"],
                        "严重度": _severity_cn.get(item["severity"], item["severity"]),
                        "行号": item["line"],
                        "问题": item["message"],
                        "建议": item["suggestion"],
                        "代码片段": item.get("snippet", ""),
                    }
                    for item in static_review["findings"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success(f"当前规则集（{static_review.get('rule_count', 0)} 条）没有命中任何问题。")
        with st.expander(f"查看规则集（{static_review.get('rule_count', 0)} 条规则与出处）"):
            st.caption("规则按「能否可靠判定」分组登记；每条都在 tests/core/test_static_review_rules.py 里配了正例与反例。")
            st.dataframe(
                [
                    {
                        "规则ID": item["rule_id"],
                        "严重度": _severity_cn.get(item["severity"], item["severity"]),
                        "规则": item["title"],
                        "出处": item["source"],
                    }
                    for item in static_review.get("rule_set", [])
                ],
                use_container_width=True,
                hide_index=True,
            )
        st.json({"counts": static_review["counts"], "finding_count": static_review["finding_count"], "source_sha256": static_review["source_sha256"]})
        with st.popover("导出审查报告"):
            st.download_button(
                "Markdown",
                render_static_markdown(static_review).encode("utf-8"),
                file_name="rtl_quality_report.md",
                mime="text/markdown",
                key="download_static_review_md",
            )
            st.download_button(
                "JSON",
                json.dumps(static_review, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name="rtl_quality_report.json",
                mime="application/json",
                key="download_static_review_json",
            )


with _TAB_VERIFY:
    _obj_col, _asm_col = st.columns([1, 1])
    with _obj_col:
        objective = st.text_area(
            "验证目标",
            st.session_state.get("objective_text", "覆盖复位、状态转换与边界时序"),
            height=88,
            help="用一句话说清要覆盖哪些行为；离线/在线规划器都按它生成测试计划。",
            key="objective_text",
        )
    with _asm_col:
        assertions_text = st.text_area(
            "结构化断言（可选，JSON 数组）",
            value=st.session_state.get("structured_assertions_text", "[]"),
            height=88,
            help="仅支持 signal_equals、signal_stable、never_high、signal_sequence、signal_implies 模板；禁止填写 Verilog/SVA 代码。断言按该信号的整个采样序列判定。",
        )
        st.session_state.structured_assertions_text = assertions_text
    st.session_state.run_synthesis = st.checkbox(
        "附加 Yosys 综合证据层（可选，不参与判决）",
        value=bool(st.session_state.get("run_synthesis", False)),
        help="多跑一次综合，报告里增加「仿真/综合/时序/比特流/上板」分层证据表。不做时序分析。",
    )
    if not is_custom:
        _case_key = str(name)
        _suggested_assertions = assertion_suggestions(RULE_CASE_NAMES.get(_case_key, _case_key))
        if _suggested_assertions:
            # 回调在主体之前执行，写进去的值本次运行就会显示；不需要整页重跑。
            st.button(
                "载入本案例推荐结构化断言",
                key="load_case_assertions",
                on_click=_load_suggested_assertions_on_click,
            )
        else:
            # 断言按"整个采样序列"判定，只有真正的全局不变量才适合写成断言；本案例没有
            # 经过验证的推荐断言（2026-09 复核：原先 4 个案例的 5 条建议全部不成立/空检查/
            # 字段非法，已全部撤掉）。这里给出可直接改用的模板形状，而不是一份会误报的清单。
            st.caption(
                "结构化断言按该信号的**整个采样序列**判定，只有真正的全局不变量才适合写成断言；"
                "本案例没有经过验证的推荐断言。可改用的模板形状（信号名换成你的设计）："
                '`[{"kind":"signal_implies","when_signal":"req","when_value":1,'
                '"then_signal":"ack","then_value":1,"within_cycles":2}]`。'
                "模板与字段表见手册「进阶用法」第 3 节。"
            )


with _TAB_SETTINGS:
    with st.expander("AI 接口设置（可选）"):
        provider_mode = st.radio(
            "规划器",
            ["离线确定性规划器（无需密钥、进程内）", "本地调试模型（HTTP 回环、无需密钥）", "在线 API（密钥只保存在本次页面会话）"],
            horizontal=True,
        )
        use_online = str(provider_mode).startswith("在线")
        use_debug_local = str(provider_mode).startswith("本地调试")
        use_offline = str(provider_mode).startswith("离线")
        debug_endpoint = st.text_input(
            "本地调试模型地址",
            value=os.getenv("IVERILOG_AI_DEBUG_ENDPOINT", "http://127.0.0.1:11434/v1"),
            help="离线调试服务，仅监听回环地址；启动命令：python -m iverilog_ai.ai.debug_server",
        )
        if use_debug_local:
            st.caption(
                "本地调试模型由仓库自带的确定性规则生成计划，不调用任何真实模型、不联网、不需要密钥；"
                "用于在无凭据环境下验证整条流水线。它不代表任何模型能力，不能作为 AI 效果数据。"
            )
        elif use_offline:
            st.caption(
                "离线模式在**本进程内**按当前 DUT contract 生成确定性激励（不需要密钥、不联网、不启动任何服务），"
                "与本地调试模型是同一个规则引擎，区别只是不经 HTTP。它不代表任何模型能力，"
                "也不能作为 AI 效果数据；真实模型能力请在「在线 API」下测量。"
            )
        api_base = st.text_input("Base URL", value=os.getenv("IVERILOG_AI_BASE_URL", "https://api.deepseek.com"), help="默认使用 DeepSeek 官方兼容接口")
        api_model = st.text_input("模型", value=os.getenv("IVERILOG_AI_MODEL", "deepseek-v4-flash"), help="默认使用 DeepSeek V4 Flash；如果服务商模型列表没有该 ID，请改为列表中的精确名称")
        api_key = st.text_input("API Key", value="", type="password", help="不会写入项目文件或报告")
        api_timeout = st.slider("单次 API 等待时间（秒）", min_value=30, max_value=300, value=120, step=10, help="模型较慢或网关排队时可提高；超时表示服务端在此时间内没有返回")
        api_output_tokens = st.slider("模型最大输出 token", min_value=2048, max_value=8192, value=4096, step=512, help="推理模型需要同时容纳思考和最终 JSON；过小可能导致最终 content 为空")
        wire_api_label = st.selectbox("接口格式", ["Chat Completions API", "Responses API"], help="DeepSeek 默认使用 Chat Completions；只有服务商明确支持 /v1/responses 时才选 Responses")
        reasoning_label = st.selectbox("推理强度", ["不发送（兼容性最高）", "minimal", "low", "medium", "high", "xhigh"], help="某些第三方 Responses 网关不接受 reasoning 字段；连接被关闭时先选“不发送”")
        st.caption("当前页面不会读取或修改电脑上的 Codex/PyCharm 配置；API Key 仅用于本次请求。")
        if st.button("检查配置（不调用模型）"):
            try:
                _diag_wire = _wire_api_for(str(wire_api_label))
                _diag_reasoning = None if str(reasoning_label).startswith("不发送") or _diag_wire != "responses" else reasoning_label
                _diag_provider = OpenAICompatibleProvider(endpoint=api_base, model=api_model, api_key=api_key,
                    wire_api=_diag_wire, reasoning_effort=_diag_reasoning, allow_network=True, store=False, timeout=api_timeout, max_output_tokens=api_output_tokens)
                st.json(_diag_provider.request_diagnostics())
            except Exception as exc:
                st.error(f"配置无效：{exc}")
        if st.button("读取模型列表", help="使用当前配置请求 /models；不会显示或保存 API Key"):
            try:
                _models_wire = _wire_api_for(str(wire_api_label))
                if "deepseek" in (api_base + " " + api_model).lower():
                    _models_wire = "chat_completions"
                _models_provider = OpenAICompatibleProvider(
                    endpoint=api_base, model=api_model, api_key=api_key,
                    wire_api=_models_wire, reasoning_effort=None, allow_network=True, store=False, timeout=api_timeout, max_output_tokens=api_output_tokens,
                )
                if not api_key.strip():
                    raise ValueError("读取模型列表需要先输入 API Key")
                st.session_state.available_models = _models_provider.list_models()
                st.success(f"已读取 {len(st.session_state.available_models)} 个模型")
            except Exception as exc:
                st.error(f"读取模型列表失败：{exc}")
        if st.session_state.get("available_models"):
            _listed_models = list(st.session_state.available_models)
            st.caption("服务商返回的模型 ID：" + ", ".join(_listed_models))
            # 读到列表就要能用：选中即覆盖上面的「模型」输入，避免用户手抄 ID。
            _picked_model = st.selectbox(
                "从服务商列表中选择模型（覆盖上面的「模型」输入）",
                ["（不覆盖，使用上面的输入）"] + _listed_models,
                key="picked_model_from_list",
            )
            if _picked_model != "（不覆盖，使用上面的输入）":
                # st.selectbox 的返回值在类型标注上是宽泛的，显式转成 str：
                # 下游用它拼提示词与构造 provider，必须是字符串。
                api_model = str(_picked_model)
        if "deepseek" in (api_base + " " + api_model).lower() and str(wire_api_label).startswith("Responses"):
            st.warning("检测到 DeepSeek 配置：官方接口使用 Chat Completions。生成时会自动改用 /chat/completions。")

    with st.expander("波形查看器（GTKWave）"):
        # 真实反馈："用 GTKWave 自动打开没反应，不知道是不是找不到路径"。
        # 因此这里既做自动探测（PATH → 常见目录 → 从 iverilog 安装位置推断），
        # 也允许手填路径并当场校验——两条路都必须存在。
        _detected_gtkwave = _configured_gtkwave()
        _gtkwave_cols = st.columns([3, 1])
        with _gtkwave_cols[0]:
            gtkwave_input = st.text_input(
                "GTKWave 可执行文件路径",
                value=str(st.session_state.get("gtkwave_path", "") or os.getenv("GTKWAVE_PATH", "")),
                help="留空表示自动探测：先看 PATH，再看常见安装目录，最后从 iverilog 的安装位置推断"
                     r"（Icarus 官方 Windows 包把 GTKWave 放在同级 gtkwave\bin\ 下）。",
            )
            st.session_state.gtkwave_path = gtkwave_input
        with _gtkwave_cols[1]:
            st.write("")
            st.write("")
            if st.button("自动检测", key="detect_gtkwave"):
                st.session_state.gtkwave_path = ""
                st.session_state.gtkwave_detected = _configured_gtkwave()
        _shown_gtkwave = _configured_gtkwave()
        if _shown_gtkwave:
            st.success(f"当前使用的 GTKWave：{_shown_gtkwave}")
        else:
            st.warning(
                "未找到 GTKWave，波形只能用页面内的分析功能查看（下载 VCD 后用 GTKWave 手工打开也可以）。"
                "可以在上面填写 gtkwave.exe 的完整路径，或设置环境变量 GTKWAVE_PATH 后重启页面。"
            )
        from iverilog_ai.core.toolchain import describe_tools
        st.caption("工具探测结果：" + describe_tools())
        if st.session_state.get("gtkwave_detected"):
            st.caption(f"上次自动检测结果：{st.session_state.gtkwave_detected}")


with _TAB_VERIFY:
    if is_custom and st.session_state.get("rtl_comparison") and st.button("让 AI 解读 RTL 对比并生成学习计划", key="ai_rtl_review"):
        try:
            if use_online or use_debug_local:
                review_provider = _build_provider("AI RTL 解读")
            else:
                review_provider = MockProvider(response={"review": "请依据结构对比结果，说明优点、不足和学习计划。"})
            review_prompt = ("请作为 FPGA RTL 教学审查员。仅依据以下已脱敏的结构化对比结果，输出 JSON："
                             '{"strengths":[...],"gaps":[...],"learning_plan":[...],"confidence":"low|medium|high"}。'
                             "不要输出代码、命令或路径。\n" + json.dumps(st.session_state.rtl_comparison, ensure_ascii=False))
            raw_review = review_provider.generate(review_prompt)
            st.session_state.rtl_ai_review = raw_review
        except Exception as exc:
            st.error(f"AI RTL 解读失败：{exc}")
    if st.session_state.get("rtl_ai_review"):
        st.subheader("AI RTL 学习解读")
        st.code(st.session_state.rtl_ai_review, language="json")

    if "ai_plan" not in st.session_state:
        st.session_state.ai_plan = None
    if "ai_error" not in st.session_state:
        st.session_state.ai_error = None
    if "ai_plan_case" not in st.session_state:
        st.session_state.ai_plan_case = None
    if st.session_state.ai_plan_case not in {None, name}:
        st.session_state.ai_plan = None
        st.session_state.ai_error = None
        st.session_state.ai_plan_case = None

    _plan_missing = st.session_state.get("ai_plan") is None
    if st.button(
        "生成测试计划",
        type="primary" if _plan_missing else "secondary",
        help="本地调试/离线模式不联网；在线模式按所选接口格式请求真实模型。若模型返回的计划未通过严格校验，会把拒绝原因发回并重试一次（仅失败时多花一次请求）。",
        key="generate_plan",
    ):
        provider = None
        try:
            contract = _contract()
            spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
            if use_online or use_debug_local:
                provider = _build_provider("生成测试计划")
            else:
                provider = _offline_provider(contract)
            # 提示词里的 Design 用**合约里的模块名**，而不是案例列表上的中文标签：
            # 标签只是界面用语（"简单 ALU"），模型会把它当设计名回填，报告里的
            # 设计一栏也就跟着失去意义。模块名对内置案例与自定义 RTL 都成立，
            # 且与规则文件名、testbench 实例化的模块名三处一致。
            case_name = contract.module
            generated_plan = plan_tests(
                objective,
                case_name,
                provider=provider,
                # 允许一次"带着拒绝原因"的重试：模型偶尔会写错一个字段名（例如给
                # signal_implies 多写 signal），一次修正就能救回整轮；只在第一次被严格
                # 校验拒绝时才会多发一次请求（认证/限流错误不会重试）。
                max_retries=1,
                context=_verification_rules(case_name, contract, spec_text),
            )
            try:
                requested_assertions = json.loads(assertions_text or "[]")
                if not isinstance(requested_assertions, list):
                    raise ValueError("结构化断言必须是 JSON 数组")
                st.session_state.ai_plan = generated_plan.model_copy(update={"assertions": requested_assertions})
                # Re-validate the copied plan so UI-authored assertions use the
                # same strict boundary as model-authored data.
                from iverilog_ai.ai.schema import TestPlan
                st.session_state.ai_plan = TestPlan.model_validate(st.session_state.ai_plan.model_dump(mode="json"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"结构化断言 JSON 无效：{exc}") from exc
            st.session_state.ai_plan_case = name
            st.session_state.ai_error = None
        except Exception as exc:
            st.session_state.ai_plan = None
            detail = str(exc)
            if provider is not None and hasattr(provider, "request_diagnostics"):
                diag = provider.request_diagnostics()
                detail += "\n请求诊断（已脱敏）：" + str(diag)
            st.session_state.ai_error = detail
            if "timed out" in detail.lower() or "超时" in detail:
                st.warning("请求已发出但服务端在等待时间内没有返回。请确认模型 ID 可用；DeepSeek 官方常用模型为 deepseek-chat 或 deepseek-reasoner。也可以提高上方等待时间。")
    if st.session_state.ai_error:
        st.error(st.session_state.ai_error)
    if st.session_state.ai_plan is not None:
        st.subheader("已校验的 TestPlan")
        try:
            # 注意函数名：core.rules 里叫 `rule_manifest(root, case)`，
            # core.static_review 里的同名函数是 `static_rule_manifest()`（不同签名）。
            # 这里曾经写成不存在的 `rules_manifest`，抛出的 NameError 又不被
            # `except ValueError` 接住，于是**生成计划后整页渲染中断**。
            _case_key = str(name)
            _rule_files = rule_manifest(ROOT, RULE_CASE_NAMES.get(_case_key, _case_key))
            st.caption("本次模型使用规则集：" + rules_fingerprint(_rule_files))
            with st.expander("查看规则文件指纹"):
                st.json(_rule_files)
        except ValueError:
            pass
        st.json(st.session_state.ai_plan.model_dump(mode="json"))


with _TAB_SETTINGS:
    with st.expander("编译选项（可选：宏定义与 include 目录）"):
        st.text_input(
            "宏定义（逗号分隔，`NAME` 或 `NAME=VALUE`）",
            value=st.session_state.get("compile_defines", ""),
            key="compile_defines",
            help="例如 WIDTH=16,SYNTHESIS。只在本地 Icarus 编译时生效，不参与任何判决。",
        )
        st.text_input(
            "include 目录（逗号分隔）",
            value=st.session_state.get("compile_includes", ""),
            key="compile_includes",
            help="目录必须位于项目目录内；越界会被安全路径策略拒绝，并给出明确错误。",
        )
        st.caption("这两项同时作用于「执行真实 Icarus 仿真」与「执行 AI 计划」两条路径。")


with _TAB_VERIFY:
    if case["rtl"] is None:
        st.info("这是即将加入的案例，仅展示规格占位；当前没有可执行 RTL/testbench。")
    elif not is_custom and st.button("执行真实 Icarus 仿真", key="run_handwritten_tb"):
        output = ROOT / ".iverilog-ai" / "runs"
        _defines, _includes = _compile_options()
        config = ExecutionConfig(
            rtl_path=ROOT / str(case["rtl"]),
            testbench_path=ROOT / str(case["tb"]),
            top_module=str(case["top"]),
            output_dir=output,
            allowed_roots=(ROOT,),
            defines=_defines,
            include_dirs=_includes,
        )
        try:
            simulation_result = IcarusExecutor(config).run()
            report = write_report(simulation_result, Path(simulation_result.artifacts["run_dir"]) / "report.md")
            st.subheader(f"结论：{simulation_result.status.value}")
            st.metric("结构化记录", f"{sum(r.ok for r in simulation_result.records)}/{len(simulation_result.records)} 通过")
            st.json(simulation_result.to_dict())
            st.write("报告路径：")
            st.code(str(report), language="text")
            if Path(report).is_file():
                st.download_button("下载 Markdown 报告", Path(report).read_bytes(), file_name="report.md", mime="text/markdown")
            if simulation_result.failures:
                st.subheader("失败反例")
                st.json([f.to_dict() for f in simulation_result.failures])
                _show_candidate_repair(simulation_result, case["rtl"], "icarus_candidate_repair")
        except Exception as exc:
            st.error(f"执行配置或仿真失败：{exc}")

    if st.session_state.ai_plan is not None and st.button("执行 AI 计划并生成 testbench", type="primary"):
        try:
            contract = _contract()
            output = ROOT / ".iverilog-ai" / "pipeline-ui"
            rtl_relative = str(case["rtl"])
            _defines, _includes = _compile_options()
            result = VerificationPipeline(
                run_synthesis=st.session_state.get("run_synthesis", False),
                yosys_path=os.getenv("YOSYS_PATH") or None,
            ).run(
                st.session_state.ai_plan, contract, ROOT / rtl_relative, output,
                allowed_roots=(ROOT,), iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe",
                defines=_defines,
                include_dirs=_includes,
                emit_vcd=True,
            )
            st.session_state.last_pipeline_result = result
            st.session_state.last_pipeline_case = name
            pipeline_report = Path(result.artifacts["output_dir"]) / "report.md"
            write_report(result.simulation, pipeline_report, title="Icarus 智测 AI 流水线报告")
            st.subheader(f"AI 计划流水线结论：{result.status.value}")
            st.metric("结构化记录", f"{sum(r.ok for r in result.records)}/{len(result.records)} 通过")
            _render_expectation_source(result.simulation.config if isinstance(result.simulation.config, dict) else {})
            _show_synthesis(result.synthesis)
            coverage = result.coverage
            st.subheader("测试覆盖摘要")
            st.caption("这是测试计划执行覆盖率，不是 RTL 代码覆盖率。")
            col_vector, col_check = st.columns(2)
            vectors = coverage["vectors"]
            checks = coverage["checks"]
            col_vector.metric("测试向量覆盖", f"{vectors['covered']}/{vectors['total']}", f"{vectors['percent']}%")
            col_check.metric("检查项覆盖", f"{checks['covered']}/{checks['total']}", f"{checks['percent']}%")
            if coverage["per_signal"]:
                st.dataframe([
                    {"信号": signal, "已覆盖": item["covered"], "总检查": item["total"], "覆盖率": f"{item['percent']}%"}
                    for signal, item in coverage["per_signal"].items()
                ], use_container_width=True, hide_index=True)
            st.write("流水线工件：")
            st.code(str(result.artifacts.get("pipeline_result", "")), language="text")
            st.code(str(pipeline_report), language="text")
            if pipeline_report.is_file():
                st.download_button(
                    "下载 AI 流水线 Markdown 报告",
                    pipeline_report.read_bytes(),
                    file_name="pipeline-report.md",
                    mime="text/markdown",
                    key="download_pipeline_report",
                )
            if st.button("生成本次运行证据包", key="create_pipeline_evidence_pack", help="复制报告、TestPlan、testbench、result.json 和 VCD，并生成哈希清单"):
                try:
                    pack_dir = Path(result.artifacts.get("output_dir", pipeline_report.parent)) / "evidence-pack"
                    manifest = create_evidence_pack(result.artifacts.get("pipeline_result", ""), pack_dir)
                    st.success(f"证据包已生成：{pack_dir}（{len(manifest['files'])} 个文件）")
                    st.code(str(pack_dir / "README.md"), language="text")
                    zip_path = Path(manifest.get("zip_file", ""))
                    if zip_path.is_file():
                        st.download_button("下载证据包 ZIP", zip_path.read_bytes(), file_name=zip_path.name, mime="application/zip", key="download_pipeline_evidence_zip")
                except Exception as exc:
                    st.error(f"证据包生成失败：{exc}")
            with st.expander("查看生成的测试计划和 testbench"):
                st.json(result.plan.model_dump(mode="json"))
                st.code(Path(result.artifacts["testbench"]).read_text(encoding="utf-8"), language="verilog")
            vcd_value = result.artifacts.get("vcd", "")
            if vcd_value:
                vcd_path = Path(vcd_value)
                if vcd_path.is_file():
                    st.subheader("仿真波形（VCD）")
                    st.code(str(vcd_path), language="text")
                    st.download_button("下载 VCD 波形", vcd_path.read_bytes(), file_name=vcd_path.name, mime="application/octet-stream", key="download_pipeline_vcd")
                    st.caption(f"波形大小：{vcd_path.stat().st_size:,} bytes；可用下面的按钮直接在 GTKWave 里打开。")
                    # 「用 GTKWave 打开」与时间窗分析都在这个 fragment 里：点击只重跑这一段。
                    _show_vcd_analysis(vcd_path, key_prefix="pipeline_vcd", preset=result.simulation.config.get("vcd_analysis", {}) if isinstance(result.simulation.config, dict) else None)
            if result.failure_summaries:
                st.json(list(result.failure_summaries))
                _show_failure_explanation(result, "pipeline_explain_failure")
                _show_candidate_repair(result, case["rtl"], "pipeline_candidate_repair")
                _show_candidate_verify(
                    result.simulation,
                    ROOT / str(case["rtl"]),
                    _contract(),
                    st.session_state.ai_plan,
                    "pipeline_candidate_verify",
                )
                if st.button("根据失败补充测试向量", help="向当前 AI Provider 请求一组新的测试向量；不会自动执行"):
                    try:
                        contract = _contract()
                        spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
                        if use_online or use_debug_local:
                            feedback_provider = _build_provider("补充测试向量")
                        else:
                            # 离线模式不做任何推理，因此不会"针对失败"设计向量；
                            # 它按合约再补少量边界激励，条数必须留在 max_new_vectors 之内
                            # （确定性规划器一次会给出整份计划，条数超限会被严格校验拒绝）。
                            feedback_provider = _offline_provider(contract, vector_count=2)
                            st.caption("离线模式不分析失败原因，只按 DUT contract 追加少量边界激励。")
                        st.session_state.ai_plan = supplement_tests(
                            st.session_state.ai_plan, result.failures, feedback_provider,
                            context=spec_text + "\nDUT contract:\n" + contract.to_json(),
                            max_new_vectors=10, max_retries=0,
                        )
                        st.success("已生成补充测试向量；请再次点击上方按钮运行更新后的计划。")
                    except Exception as exc:
                        st.error(f"补充测试失败：{exc}")
        except Exception as exc:
            st.error(f"AI 计划流水线失败：{exc}")

    # Streamlit reruns the script after every button click. Restore the last
    # result so explanation/repair buttons do not collapse the evidence view.
    if st.session_state.get("last_pipeline_result") is not None and st.session_state.get("last_pipeline_case") == name:
        st.info("已保留最近一次 AI 流水线结果；可继续查看失败解释或候选修复。")
        _last = st.session_state.last_pipeline_result
        # Re-render the complete evidence summary after Streamlit's normal
        # button rerun.  Previously only failures were restored, so a click on
        # the GTKWave button appeared to make the passed/failed conclusion and
        # waveform section disappear.
        st.subheader(f"最近一次 AI 计划流水线结论：{_last.status.value}")
        st.metric("结构化记录", f"{sum(r.ok for r in _last.records)}/{len(_last.records)} 通过")
        _render_expectation_source(_last.simulation.config if isinstance(_last.simulation.config, dict) else {})
        _show_synthesis(_last.synthesis)
        _last_vcd = _last.artifacts.get("vcd", "")
        if _last_vcd and Path(_last_vcd).is_file():
            st.subheader("最近一次仿真波形（VCD）")
            st.code(str(_last_vcd), language="text")
            st.download_button("下载 VCD 波形", Path(_last_vcd).read_bytes(), file_name=Path(_last_vcd).name, mime="application/octet-stream", key="persisted_download_pipeline_vcd")
            _show_vcd_analysis(Path(_last_vcd), key_prefix="persisted_vcd", preset=_last.simulation.config.get("vcd_analysis", {}) if isinstance(_last.simulation.config, dict) else None)
        if getattr(_last, "failures", ()):
            st.subheader("最近一次流水线失败记录")
            st.json([f.to_dict() for f in _last.failures])
            _show_failure_explanation(_last, "persisted_pipeline_explain")
            _show_candidate_repair(_last, case.get("rtl") or st.session_state.get("custom_rtl_path", ""), "persisted_pipeline_repair")

    # 运行目录是可审计证据；网页提供最近运行的只读索引，便于回看而不重新执行。


with _TAB_HISTORY:
    history_root = ROOT / ".iverilog-ai" / "pipeline-ui"
    history_files = sorted(history_root.glob("runs/*/result.json"), key=lambda item: item.stat().st_mtime, reverse=True) if history_root.is_dir() else []
    if history_files:
        with st.expander(f"最近流水线运行（{min(len(history_files), 10)} 条）"):
            for result_file in history_files[:10]:
                try:
                    summary = json.loads(result_file.read_text(encoding="utf-8"))
                    st.write(f"{summary.get('run_id', result_file.parent.name)} · {summary.get('status', 'unknown')} · {result_file}")
                except (OSError, json.JSONDecodeError):
                    st.write(str(result_file))


st.divider()
st.caption(
    "安全边界：案例路径为白名单；不把 UI 文本拼入命令，不接受 shell 参数，不上传密钥，不自动提交 PR。"
)
