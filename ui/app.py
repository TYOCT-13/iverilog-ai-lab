"""安全的单页演示：案例来自代码内白名单，仿真交给 IcarusExecutor。"""
from pathlib import Path
import json
import streamlit as st

import os
import hashlib
import shutil
import subprocess
from iverilog_ai.ai import MockProvider, OpenAICompatibleProvider, plan_tests, supplement_tests
from iverilog_ai.core.config import ExecutionConfig
from iverilog_ai.core.executor import IcarusExecutor
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.pipeline import explain_failure_record
from iverilog_ai.core.report import write_report
from iverilog_ai.core.rtl_import import import_rtl_bytes, extract_contract_draft, available_modules, RTLImportError
from iverilog_ai.core.repair_compare import safe_candidate_copy, compare_simulation_results
from iverilog_ai.core.rtl_compare import compare_rtl_sources
from iverilog_ai.core.rules import rules_context, rule_manifest, rules_fingerprint
from iverilog_ai.core.rule_assertions import assertion_suggestions
from scripts.create_evidence_pack import create_evidence_pack
from iverilog_ai.core.static_review import review_rtl_file, render_static_markdown
from iverilog_ai.core.vcd import analyze_vcd_file

ROOT = Path(__file__).resolve().parents[1]

def _open_vcd_with_gtkwave(vcd_path: Path) -> tuple[bool, str]:
    """Launch GTKWave directly with a fixed executable (never through a shell)."""
    candidates = []
    found = shutil.which("gtkwave")
    if found:
        candidates.append(Path(found))
    candidates.extend(Path(p) for p in (
        r"C:\Program Files\gtkwave\bin\gtkwave.exe",
        r"C:\Program Files (x86)\gtkwave\bin\gtkwave.exe",
        r"D:\gtkwave\bin\gtkwave.exe",
        r"D:\iverilog\gtkwave\bin\gtkwave.exe",
    ))
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None:
        return False, "未找到 GTKWave。请安装 GTKWave，或将 gtkwave.exe 加入 PATH。"
    try:
        # Keep the GUI process visible.  Some Windows GTKWave launchers exit
        # immediately when started with CREATE_NO_WINDOW.
        # Use the executable directory as cwd: GTKWave bundles DLLs and
        # launcher helpers next to the binary on Windows.
        subprocess.Popen(
            [str(executable), str(vcd_path)],
            shell=False,
            close_fds=True,
            cwd=str(executable.parent),
        )
    except OSError as exc:
        return False, f"GTKWave 启动失败：{exc}"
    return True, f"已使用 GTKWave 打开：{vcd_path.name}"


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


def _verification_rules(case_name: str, contract: DutContract, spec_text: str) -> str:
    """Load bounded repository rules for model guidance; never executes them."""
    return rules_context(ROOT, RULE_CASE_NAMES.get(case_name, case_name), contract.to_json(), spec_text=spec_text)[0]


def _show_vcd_analysis(vcd_path: Path, *, key_prefix: str, preset: dict | None = None) -> None:
    """Display VCD signal metadata and a bounded time-window analysis."""
    data = preset or {}
    if data.get("status") == "parsed":
        st.caption(f"VCD 时间范围：{data.get('start_ns')} ns ～ {data.get('end_ns')} ns；信号 {data.get('signal_count', 0)} 个；变化 {data.get('total_changes', 0)} 次")
        if data.get("signals"):
            with st.expander("查看 VCD 信号列表"):
                st.dataframe(data["signals"], use_container_width=True, hide_index=True)

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
        start = st.number_input("窗口起始时间 (ns)", min_value=0.0, value=float(window["start"]), key=f"{key_prefix}_start")
        end = st.number_input("窗口结束时间 (ns)", min_value=float(start), value=max(float(start), float(window["end"])), key=f"{key_prefix}_end")
        if st.button("读取窗口波形", key=f"{key_prefix}_read"):
            try:
                st.session_state[f"{key_prefix}_window_data"] = analyze_vcd_file(vcd_path, start_ns=start, end_ns=end, max_changes=2000)
            except Exception as exc:
                st.error(f"VCD 窗口分析失败：{exc}")
    window_data = st.session_state.get(f"{key_prefix}_window_data")
    if window_data:
        st.caption(f"窗口变化：{window_data.get('total_changes', 0)} 次")
        if window_data.get("changes"):
            st.dataframe(window_data["changes"], use_container_width=True, hide_index=True)
        st.download_button("下载 VCD 分析 JSON", json.dumps(window_data, ensure_ascii=False, indent=2).encode("utf-8"), file_name="vcd-analysis.json", mime="application/json", key=f"{key_prefix}_download")
CASES = {
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
}

RULE_CASE_NAMES = {
    "交通灯·紧急模式": "traffic_light_emergency", "模十计数器": "mod10_counter", "简单 ALU": "simple_alu", "101 序列检测（允许重叠）": "sequence_101_overlap", "同步上升沿检测器": "edge_detector", "脉冲展宽器": "pulse_stretcher", "单时钟 FIFO": "sync_fifo", "UART 发送器": "uart_tx", "SPI 主机": "spi_master", "Valid-Ready 握手级": "handshake_stage", "按键去抖": "debounce", "PWM": "pwm", "四选一多路选择器": "mux4", "同步复位模块": "sync_reset", "自定义 RTL": "custom_rtl",
}

st.set_page_config(page_title="Icarus智测", layout="wide")
st.title("Icarus智测 · 可复现验证演示")
st.caption("Icarus 是非官方扩展的真实编译/仿真后端；AI 仅生成受校验的测试计划。")
name = st.selectbox("选择案例", ["自定义 RTL"] + list(CASES))
is_custom = name == "自定义 RTL"
case = CASES.get(name, {"rtl": None, "tb": None, "top": None, "spec": "自定义 RTL", "contract": None})

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

def _contract_editor() -> None:
    """显示受控的 DUT contract 表格和时钟/复位字段，并支持生成 JSON。"""
    if not st.session_state.get("custom_contract_text"):
        return
    _set_contract_editor(st.session_state.custom_contract_text) if "custom_contract_editor_ports" not in st.session_state else None
    with st.expander("表格化编辑 DUT contract（可与 JSON 双向同步）", expanded=True):
        rows = st.data_editor(
            st.session_state.get("custom_contract_editor_ports", []),
            num_rows="dynamic", use_container_width=True, key="custom_ports_editor",
            column_config={
                "name": st.column_config.TextColumn("端口名称", required=True),
                "direction": st.column_config.SelectboxColumn("方向", options=["input", "output", "inout"], required=True),
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
        if st.button("从表格生成 JSON", key="contract_editor_to_json"):
            try:
                payload = {"module": st.session_state.get("custom_selected_module", "dut"), "ports": list(rows)}
                if st.session_state.get("custom_contract_editor_parameters"):
                    payload["parameters"] = dict(st.session_state.custom_contract_editor_parameters)
                if clock_signal.strip():
                    payload["clock"] = {"signal": clock_signal.strip(), "period_ns": float(clock_period), "edge": clock_edge}
                if reset_signal.strip():
                    payload["reset"] = {"signal": reset_signal.strip(), "active_level": int(reset_active), "synchronous": bool(reset_sync), "assert_cycles": int(reset_cycles)}
                contract = DutContract.from_dict(payload)
                st.session_state.custom_contract_text = contract.to_json()
                st.session_state.custom_contract_json_text = st.session_state.custom_contract_text
                st.session_state.custom_contract = None
                st.session_state.custom_contract_editor_ports = list(contract.to_dict()["ports"])
                st.success("已从表格生成 JSON，请继续点击“校验自定义 contract”。")
                st.rerun()
            except Exception as exc:
                st.error(f"表格内容无效：{exc}")
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
    contract_text = st.text_area("DUT contract JSON（确认方向、位宽、时钟、复位后再校验）", value=st.session_state.get("custom_contract_text", ""), height=220, key="custom_contract_json_text")
    # JSON 文本编辑也会回写到表格编辑器，下一次页面刷新时保持双向同步。
    if contract_text != st.session_state.get("custom_contract_text", ""):
        st.session_state.custom_contract_text = contract_text
        _set_contract_editor(contract_text)
    if st.button("校验自定义 contract"):
        try:
            st.session_state.custom_contract = DutContract.from_json(contract_text)
            st.session_state.custom_contract_text = st.session_state.custom_contract.to_json()
            st.success("contract 校验通过，可以生成 AI 计划")
        except Exception as exc:
            st.session_state.custom_contract = None
            st.error(f"contract 无效：{exc}")
    if st.session_state.get("custom_contract") is not None:
        st.download_button("下载 contract JSON", st.session_state.custom_contract.to_json(), file_name="dut_contract.json", mime="application/json")
    case = {"rtl": st.session_state.get("custom_rtl_path"), "tb": None, "top": None, "spec": "自定义 RTL", "contract": None}
    reference_options = [p for p in sorted((ROOT / "rtl").glob("*.v")) if "_bug_" not in p.name and "bug_" not in p.name]
    if st.session_state.get("custom_rtl_source") and reference_options:
        reference_choice = st.selectbox("标准 RTL 参考实现", reference_options, format_func=lambda p: p.name)
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
        st.download_button("下载 RTL 对比报告", json.dumps(comparison, ensure_ascii=False, indent=2), file_name="rtl-comparison.json", mime="application/json", key="download_rtl_comparison")
else:
    st.write(f"规格：`{case['spec']}`")

if case.get("rtl") and Path(case["rtl"]).is_file():
    if st.button("执行 RTL 静态质量审查", key="run_static_rtl_review", help="检查时序/组合赋值、复位、default、CDC 提示和其他规则；不替代仿真"):
        try:
            st.session_state.static_rtl_review = review_rtl_file(case["rtl"])
        except Exception as exc:
            st.error(f"RTL 静态审查失败：{exc}")
if st.session_state.get("static_rtl_review"):
    static_review = st.session_state.static_rtl_review
    st.subheader("RTL 静态质量审查")
    _score_col, _status_col = st.columns(2)
    _score_col.metric("质量评分", f"{static_review['quality_score']}/100")
    _status_col.metric("审查状态", static_review["status"])
    st.caption(static_review["disclaimer"])
    st.json({"counts": static_review["counts"], "finding_count": static_review["finding_count"], "source_sha256": static_review["source_sha256"]})
    if static_review["findings"]:
        st.dataframe(static_review["findings"], use_container_width=True, hide_index=True)
    st.download_button("下载 RTL 静态审查 Markdown", render_static_markdown(static_review).encode("utf-8"), file_name="rtl_quality_report.md", mime="text/markdown", key="download_static_review_md")
    st.download_button("下载 RTL 静态审查 JSON", json.dumps(static_review, ensure_ascii=False, indent=2).encode("utf-8"), file_name="rtl_quality_report.json", mime="application/json", key="download_static_review_json")
objective = st.text_area("验证目标（只用于离线规划展示）", "覆盖复位、状态转换与边界时序")
assertions_text = st.text_area(
    "结构化断言（可选，JSON 数组）",
    value=st.session_state.get("structured_assertions_text", "[]"),
    height=100,
    help='仅支持 signal_equals、signal_stable、never_high 模板；禁止填写 Verilog/SVA 代码。',
)
st.session_state.structured_assertions_text = assertions_text
st.session_state.run_synthesis = st.checkbox(
    "附加 Yosys 综合证据层（可选）",
    value=bool(st.session_state.get("run_synthesis", False)),
    help="多跑一次综合，报告里增加「仿真/综合/时序/比特流/上板」分层证据表。不参与 PASS/FAIL 裁决，也不做时序分析。",
)
if not is_custom:
    _suggested_assertions = assertion_suggestions(RULE_CASE_NAMES.get(name, name))
    if _suggested_assertions and st.button("载入本案例推荐结构化断言", key="load_case_assertions"):
        st.session_state.structured_assertions_text = json.dumps(_suggested_assertions, ensure_ascii=False, indent=2)
        st.rerun()
with st.expander("AI 接口设置（可选）"):
    provider_mode = st.radio(
        "规划器",
        ["离线 Mock（无需密钥）", "本地调试模型（无需密钥、不联网）", "在线 API（密钥只保存在本次页面会话）"],
        horizontal=True,
    )
    use_online = provider_mode.startswith("在线")
    use_debug_local = provider_mode.startswith("本地调试")
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
    api_base = st.text_input("Base URL", value=os.getenv("IVERILOG_AI_BASE_URL", "https://api.deepseek.com"), help="默认使用 DeepSeek 官方兼容接口")
    api_model = st.text_input("模型", value=os.getenv("IVERILOG_AI_MODEL", "deepseek-v4-flash"), help="默认使用 DeepSeek V4 Flash；如果服务商模型列表没有该 ID，请改为列表中的精确名称")
    api_key = st.text_input("API Key", value="", type="password", help="不会写入项目文件或报告")
    api_timeout = st.slider("单次 API 等待时间（秒）", min_value=30, max_value=300, value=120, step=10, help="模型较慢或网关排队时可提高；超时表示服务端在此时间内没有返回")
    api_output_tokens = st.slider("模型最大输出 token", min_value=2048, max_value=8192, value=4096, step=512, help="推理模型需要同时容纳思考和最终 JSON；过小可能导致最终 content 为空")
    wire_api_label = st.selectbox("接口格式", ["Chat Completions API", "Responses API"], help="DeepSeek 默认使用 Chat Completions；只有服务商明确支持 /v1/responses 时才选 Responses")
    reasoning_label = st.selectbox("推理强度", ["不发送（兼容性最高）", "minimal", "low", "medium", "high", "xhigh"], help="某些第三方 Responses 网关不接受 reasoning 字段；连接被关闭时先选“不发送”")
    st.caption("当前页面不会读取或修改电脑上的 Codex/PyCharm 配置；API Key 仅用于本次请求。")


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
    wire = "responses" if wire_api_label.startswith("Responses") else "chat_completions"
    if "deepseek" in (api_base + " " + api_model).lower() and wire == "responses":
        wire = "chat_completions"
    if not api_key.strip():
        raise ValueError(f"{target}需要先输入 API Key（或改用本地调试模型）")
    return OpenAICompatibleProvider(
        endpoint=api_base,
        model=api_model,
        api_key=api_key,
        wire_api=wire,
        reasoning_effort=None if reasoning_label.startswith("不发送") or wire != "responses" else reasoning_label,
        allow_network=True,
        store=False,
        timeout=api_timeout,
        max_output_tokens=api_output_tokens,
    )

    if st.button("检查配置（不调用模型）"):
        try:
            _diag_wire = "responses" if wire_api_label.startswith("Responses") else "chat_completions"
            _diag_reasoning = None if reasoning_label.startswith("不发送") or _diag_wire != "responses" else reasoning_label
            _diag_provider = OpenAICompatibleProvider(endpoint=api_base, model=api_model, api_key=api_key,
                wire_api=_diag_wire, reasoning_effort=_diag_reasoning, allow_network=True, store=False, timeout=api_timeout, max_output_tokens=api_output_tokens)
            st.json(_diag_provider.request_diagnostics())
        except Exception as exc:
            st.error(f"配置无效：{exc}")
    if st.button("读取模型列表", help="使用当前配置请求 /models；不会显示或保存 API Key"):
        try:
            _models_wire = "responses" if wire_api_label.startswith("Responses") else "chat_completions"
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
        st.caption("服务商返回的模型 ID：" + ", ".join(st.session_state.available_models))
    if "deepseek" in (api_base + " " + api_model).lower() and wire_api_label.startswith("Responses"):
        st.warning("检测到 DeepSeek 配置：官方接口使用 Chat Completions。生成时会自动改用 /chat/completions。")

def _contract() -> DutContract:
    if is_custom:
        if st.session_state.get("custom_contract") is None:
            raise ValueError("请先上传 RTL 并校验 DUT contract")
        return st.session_state.custom_contract
    return DutContract.from_json((ROOT / case["contract"]).read_text(encoding="utf-8"))

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

if st.button("生成测试计划", help="本地调试/离线模式不联网；在线模式按所选接口格式请求真实模型"):
    provider = None
    try:
        contract = _contract()
        spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
        if use_online or use_debug_local:
            provider = _build_provider("生成测试计划")
        else:
            provider = MockProvider()
        generated_plan = plan_tests(objective, name, provider=provider, max_retries=0, context=_verification_rules(name, contract, spec_text))
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
        _rule_files = rule_manifest(ROOT, RULE_CASE_NAMES.get(name, name))
        st.caption("本次模型使用规则集：" + rules_fingerprint(_rule_files))
        with st.expander("查看规则文件指纹"):
            st.json(_rule_files)
    except ValueError:
        pass
    st.json(st.session_state.ai_plan.model_dump(mode="json"))

if case["rtl"] is None:
    st.info("这是即将加入的案例，仅展示规格占位；当前没有可执行 RTL/testbench。")
elif not is_custom and st.button("执行真实 Icarus 仿真", type="primary"):
    output = ROOT / ".iverilog-ai" / "runs"
    config = ExecutionConfig(rtl_path=ROOT / case["rtl"], testbench_path=ROOT / case["tb"], top_module=case["top"], output_dir=output, allowed_roots=(ROOT,))
    try:
        result = IcarusExecutor(config).run()
        report = write_report(result, Path(result.artifacts["run_dir"]) / "report.md")
        st.subheader(f"结论：{result.status.value}")
        st.metric("结构化记录", f"{sum(r.ok for r in result.records)}/{len(result.records)} 通过")
        st.json(result.to_dict())
        st.write("报告路径：")
        st.code(str(report), language="text")
        if Path(report).is_file():
            st.download_button("下载 Markdown 报告", Path(report).read_bytes(), file_name="report.md", mime="text/markdown")
        if result.failures:
            st.subheader("失败反例")
            st.json([f.to_dict() for f in result.failures])
            _show_candidate_repair(result, case["rtl"], "icarus_candidate_repair")
    except Exception as exc:
        st.error(f"执行配置或仿真失败：{exc}")

if st.session_state.ai_plan is not None and st.button("执行 AI 计划并生成 testbench", type="primary"):
    try:
        contract = _contract()
        output = ROOT / ".iverilog-ai" / "pipeline-ui"
        result = VerificationPipeline(
            run_synthesis=st.session_state.get("run_synthesis", False),
            yosys_path=os.getenv("YOSYS_PATH") or None,
        ).run(
            st.session_state.ai_plan, contract, ROOT / case["rtl"], output,
            allowed_roots=(ROOT,), iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
            vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe",
            emit_vcd=True,
        )
        st.session_state.last_pipeline_result = result
        st.session_state.last_pipeline_case = name
        pipeline_report = Path(result.artifacts["output_dir"]) / "report.md"
        write_report(result.simulation, pipeline_report, title="Icarus 智测 AI 流水线报告")
        st.subheader(f"AI 计划流水线结论：{result.status.value}")
        st.metric("结构化记录", f"{sum(r.ok for r in result.records)}/{len(result.records)} 通过")
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
                col_download, col_open = st.columns(2)
                col_download.download_button("下载 VCD 波形", vcd_path.read_bytes(), file_name=vcd_path.name, mime="application/octet-stream", key="download_pipeline_vcd")
                if col_open.button("用 GTKWave 自动打开", key="open_pipeline_vcd"):
                    ok, message = _open_vcd_with_gtkwave(vcd_path)
                    st.session_state.gtkwave_message = message
                    st.session_state.gtkwave_message_ok = ok
                    # Streamlit already reruns once for the button event.
                    # Do not trigger a second rerun: it would reset/collapse
                    # the pipeline result section and make the page appear
                    # to lose the passed/failed conclusion.
                    renderer = st.success if ok else st.warning
                    renderer(message)
                st.caption(f"波形大小：{vcd_path.stat().st_size:,} bytes；可使用 GTKWave 打开。")
                _show_vcd_analysis(vcd_path, key_prefix="pipeline_vcd", preset=result.simulation.config.get("vcd_analysis", {}) if isinstance(result.simulation.config, dict) else None)
                if st.session_state.get("gtkwave_message"):
                    renderer = st.success if st.session_state.get("gtkwave_message_ok") else st.warning
                    renderer(st.session_state.gtkwave_message)
        if result.failure_summaries:
            st.json(list(result.failure_summaries))
            _show_failure_explanation(result, "pipeline_explain_failure")
            _show_candidate_repair(result, case["rtl"], "pipeline_candidate_repair")
            _show_candidate_verify(result.simulation, ROOT / case["rtl"], _contract(), st.session_state.ai_plan, "pipeline_candidate_verify")
            if st.button("根据失败补充测试向量", help="向当前 AI Provider 请求一组新的测试向量；不会自动执行"):
                try:
                    contract = _contract()
                    spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
                    if use_online or use_debug_local:
                        feedback_provider = _build_provider("补充测试向量")
                    else:
                        feedback_provider = MockProvider()
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
    _last_vcd = _last.artifacts.get("vcd", "")
    if _last_vcd and Path(_last_vcd).is_file():
        st.subheader("最近一次仿真波形（VCD）")
        st.code(str(_last_vcd), language="text")
        _dl, _open = st.columns(2)
        _dl.download_button("下载 VCD 波形", Path(_last_vcd).read_bytes(), file_name=Path(_last_vcd).name, mime="application/octet-stream", key="persisted_download_pipeline_vcd")
        if _open.button("用 GTKWave 自动打开", key="persisted_open_pipeline_vcd"):
            _ok, _message = _open_vcd_with_gtkwave(Path(_last_vcd))
            st.session_state.gtkwave_message = _message
            st.session_state.gtkwave_message_ok = _ok
            (st.success if _ok else st.warning)(_message)
        if st.session_state.get("gtkwave_message"):
            (st.success if st.session_state.get("gtkwave_message_ok") else st.warning)(st.session_state.gtkwave_message)
        _show_vcd_analysis(Path(_last_vcd), key_prefix="persisted_vcd", preset=_last.simulation.config.get("vcd_analysis", {}) if isinstance(_last.simulation.config, dict) else None)
    if getattr(_last, "failures", ()):
        st.subheader("最近一次流水线失败记录")
        st.json([f.to_dict() for f in _last.failures])
        _show_failure_explanation(_last, "persisted_pipeline_explain")
        _show_candidate_repair(_last, case.get("rtl") or st.session_state.get("custom_rtl_path", ""), "persisted_pipeline_repair")

# 运行目录是可审计证据；网页提供最近运行的只读索引，便于回看而不重新执行。
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

st.warning("安全边界：案例路径为白名单；不把 UI 文本拼入命令，不接受 shell 参数，不上传密钥，不自动提交 PR。")
