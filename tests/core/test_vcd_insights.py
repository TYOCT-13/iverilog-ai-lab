"""VCD 波形语义分析的回归测试：边沿、稳定性、相位与双波形差异。

用例都用**脚本构造的最小 VCD**，不依赖 Icarus，因此稳定且快；
真实缺陷上的端到端验证见 `docs/vcd_analysis.md` 记录的实测结果。

VCD 标识符统一使用字母数字（``a1``/``a2``…），避免标点类标识符触发
header 解析的边界情况——这里要测的是分析逻辑，不是 VCD 词法本身。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iverilog_ai.core.vcd import (
    analyze_failure_windows,
    analyze_vcd_file,
    compare_waveforms,
    detect_phase_violations,
    signal_edges,
    signal_stability,
    waveform_insights,
)

_HEADER = """$timescale 1ns $end
$scope module tb $end
$var wire 1 a1 clk $end
$var wire 1 a2 start $end
$var wire 1 a3 done $end
$var wire 1 a4 a $end
$var wire 1 a5 b $end
$upscope $end
$enddefinitions $end
"""


def _write(tmp_path: Path, body: str, name: str = "wave.vcd", declarations: str = "") -> Path:
    """写一份 VCD；``declarations`` 用于补充 header 内的嵌套作用域与信号声明。

    插入点在 ``$upscope`` **之前**，因此补充的声明位于 ``tb`` 作用域内部，
    与真实 $dumpvars 输出的层次结构一致。
    """

    path = tmp_path / name
    header = _HEADER.replace("$upscope $end\n", f"{declarations}$upscope $end\n", 1)
    path.write_text(header + body, encoding="utf-8")
    return path


def _values(pairs: list[tuple[int, str, str]]) -> str:
    """把 (时间, 标识符, 值) 列表渲染成 VCD 主体。"""

    lines: list[str] = []
    current = None
    for time_ns, ident, value in pairs:
        if time_ns != current:
            lines.append(f"#{time_ns}")
            current = time_ns
        lines.append(f"{value}{ident}")
    return "\n".join(lines) + "\n"


def test_signal_edges_detects_rise_fall_and_initial(tmp_path):
    body = _values([
        (0, "a1", "0"), (0, "a2", "1"), (0, "a3", "0"),
        (5, "a1", "1"),
        (10, "a1", "0"), (10, "a2", "0"), (10, "a3", "1"),
        (15, "a1", "1"),
        (20, "a1", "0"), (20, "a3", "0"),
        (25, "a1", "1"),
    ])
    analysis = analyze_vcd_file(_write(tmp_path, body))
    assert [edge["edge"] for edge in signal_edges(analysis, "tb.clk")] == [
        "initial", "rise", "fall", "rise", "fall", "rise",
    ]
    assert [edge["edge"] for edge in signal_edges(analysis, "tb.start")] == ["initial", "fall"]
    assert [edge["edge"] for edge in signal_edges(analysis, "tb.done")] == ["initial", "rise", "fall"]


def test_signal_edges_ignores_x_and_z(tmp_path):
    body = _values([(0, "a4", "0"), (5, "a4", "x"), (10, "a4", "1"), (15, "a4", "0")])
    analysis = analyze_vcd_file(_write(tmp_path, body))
    edges = signal_edges(analysis, "tb.a")
    # 遇到 x 会清空"上一个已知值"，因此之后的 1 记为 initial、0 记为 fall
    assert [edge["edge"] for edge in edges] == ["initial", "initial", "fall"]


def test_signal_stability_flags_irregular_glitch_but_not_regular_toggling(tmp_path):
    """判据是相对的：常规节奏的翻转不算毛刺，明显更短的间隔才算。"""

    # 规律翻转（每 10ns 一次）：不是毛刺，即使窗口内翻转多次
    regular = _values([(index * 10, "a4", "1" if index % 2 else "0") for index in range(8)])
    regular_analysis = analyze_vcd_file(_write(tmp_path, regular, name="regular.vcd"))
    assert signal_stability(regular_analysis, "tb.a", window_ns=30.0)["status"] == "stable"

    # 常规 20ns 节奏中插入一段连续 1ns 快翻：应报不稳定
    glitchy = _values([
        (0, "a4", "0"), (20, "a4", "1"), (40, "a4", "0"), (60, "a4", "1"), (80, "a4", "0"),
        (100, "a4", "1"),
        (110, "a4", "0"), (111, "a4", "1"), (112, "a4", "0"), (113, "a4", "1"),
        (133, "a4", "0"), (153, "a4", "1"), (173, "a4", "0"), (193, "a4", "1"), (213, "a4", "0"),
    ])
    glitchy_analysis = analyze_vcd_file(_write(tmp_path, glitchy, name="glitchy.vcd"))
    report = signal_stability(glitchy_analysis, "tb.a", window_ns=30.0)
    assert report["status"] == "unstable"
    assert report["unstable_windows"][0]["shortest_interval_ns"] <= 1.0
    assert report["typical_interval_ns"] == pytest.approx(20.0, abs=1e-6)

    # 单个短间隔是正常的窄脉冲（busy 信号就是这样），不构成毛刺结论
    pulse = _values([
        (0, "a4", "0"), (100, "a4", "1"), (110, "a4", "0"), (200, "a4", "1"),
    ])
    pulse_analysis = analyze_vcd_file(_write(tmp_path, pulse, name="pulse.vcd"))
    assert signal_stability(pulse_analysis, "tb.a", window_ns=30.0)["status"] == "stable"


def test_waveform_insights_separates_dut_signals_from_testbench_bookkeeping(tmp_path):
    """检查任务的检查寄存器由激励脚本驱动，不应被报成 DUT 毛刺。"""

    body = "\n".join(
        [
            _values([(0, "a1", "0")]),
            # DUT 内部信号：窗口内多次翻转但节奏均匀，不应报毛刺
            _values([
                (0, "a7", "0"), (10, "a7", "1"), (20, "a7", "0"), (30, "a7", "1"), (40, "a7", "0"),
            ]),
            # testbench 记账信号：20→21→22→23 ns 连续快翻，是脚本行为不是电路毛刺
            _values([
                (0, "a4", "0"), (10, "a4", "1"), (20, "a4", "0"), (21, "a4", "1"), (22, "a4", "0"),
                (23, "a4", "1"), (33, "a4", "0"), (43, "a4", "1"),
            ]),
        ]
    )
    declarations = "$scope module dut $end\n$var wire 1 a7 internal $end\n$upscope $end\n"
    path = _write(tmp_path, body, name="scoped.vcd", declarations=declarations)
    analysis = analyze_vcd_file(path)
    assert {item["name"]: item["scope"] for item in analysis["signals"]}["tb.dut.internal"] == "tb.dut"

    insights = waveform_insights(
        analysis,
        clock_period_ns=10.0,
        stability_signals=["tb.a", "tb.dut.internal"],
        dut_scopes=["tb.dut"],
    )
    assert insights["unstable_signals"] == []
    # 记账信号 20→22→23 ns 连续快翻判为不稳定，但归入辅助列表，不冒充电路结论
    assert insights["unstable_auxiliary"] == ["tb.a"]
    assert all("不作为电路结论" in note for note in insights["notes"] if "tb.a" in note)
    assert insights["dut_scopes"] == ["tb.dut"]


def test_detect_phase_violations_reports_on_time_late_and_early(tmp_path):
    on_time = _values([(0, "a2", "0"), (0, "a3", "0"), (10, "a2", "1"), (20, "a3", "1")])
    analysis = analyze_vcd_file(_write(tmp_path, on_time, name="on_time.vcd"))
    ok = detect_phase_violations(analysis, [{"trigger": "tb.start", "response": "tb.done", "expected_delay_cycles": 1}], clock_period_ns=10.0)
    assert ok[0]["status"] == "ok"
    assert ok[0]["observed_delay_cycles"] == pytest.approx(1.0, abs=1e-6)

    late = _values([(0, "a2", "0"), (0, "a3", "0"), (10, "a2", "1"), (40, "a3", "1")])
    late_analysis = analyze_vcd_file(_write(tmp_path, late, name="late.vcd"))
    result = detect_phase_violations(late_analysis, [("tb.start", "tb.done", 1)], clock_period_ns=10.0)
    assert result[0]["status"] == "late"
    assert result[0]["worst_delta_cycles"] == pytest.approx(2.0, abs=1e-6)
    assert "晚" in result[0]["message"]

    early = _values([(0, "a2", "0"), (0, "a3", "0"), (10, "a2", "1"), (12, "a3", "1")])
    early_analysis = analyze_vcd_file(_write(tmp_path, early, name="early.vcd"))
    result = detect_phase_violations(early_analysis, [("tb.start", "tb.done", 3)], clock_period_ns=10.0)
    assert result[0]["status"] == "early"


def test_detect_phase_violations_marks_unobservable(tmp_path):
    body = _values([(0, "a2", "0"), (0, "a3", "0"), (10, "a2", "1")])
    analysis = analyze_vcd_file(_write(tmp_path, body, name="no_resp.vcd"))
    result = detect_phase_violations(analysis, [("tb.start", "tb.done", 1)], clock_period_ns=10.0)
    assert result[0]["status"] == "unobservable"


def test_compare_waveforms_reports_timing_and_edge_count_differences(tmp_path):
    reference = _values([(0, "a5", "0"), (10, "a5", "1"), (20, "a5", "0"), (30, "a5", "1")])
    reference_analysis = analyze_vcd_file(_write(tmp_path, reference, name="ref.vcd"))

    shifted = _values([(0, "a5", "0"), (15, "a5", "1"), (25, "a5", "0"), (35, "a5", "1")])
    shifted_analysis = analyze_vcd_file(_write(tmp_path, shifted, name="shift.vcd"))
    timing = compare_waveforms(reference_analysis, shifted_analysis, clock_period_ns=10.0)
    assert timing["status"] == "different"
    shift = next(item for item in timing["differences"] if item["kind"] == "timing")
    assert shift["shift_cycles"] == pytest.approx(0.5, abs=1e-6)

    # 同名信号但跳变次数不同，且候选波形多出一个信号
    extra = _values([(0, "a5", "0"), (10, "a5", "1"), (20, "a5", "0"), (25, "a5", "1"), (30, "a5", "0")])
    candidate_header = _HEADER.replace("$var wire 1 a4 a $end\n", "$var wire 1 a4 a $end\n$var wire 1 a6 extra $end\n")
    path = tmp_path / "extra.vcd"
    path.write_text(candidate_header + extra, encoding="utf-8")
    extra_analysis = analyze_vcd_file(path)
    counts = compare_waveforms(reference_analysis, extra_analysis, clock_period_ns=10.0)
    assert any(item["kind"] == "edge_count" for item in counts["differences"])
    assert counts["only_in_candidate"] == ["tb.extra"]


def test_compare_waveforms_identical_input_is_identical(tmp_path):
    body = _values([(0, "a5", "0"), (10, "a5", "1")])
    analysis = analyze_vcd_file(_write(tmp_path, body))
    other = analyze_vcd_file(_write(tmp_path, body, name="same.vcd"))
    report = compare_waveforms(analysis, other)
    assert report["status"] == "identical"
    assert report["difference_count"] == 0


def test_waveform_insights_summarizes_without_clock(tmp_path):
    body = _values([
        (0, "a1", "0"), (0, "a2", "1"), (0, "a3", "0"), (0, "a4", "0"),
        (5, "a1", "1"),
        (10, "a1", "0"), (10, "a2", "0"), (10, "a3", "1"), (10, "a4", "1"),
        (15, "a1", "1"),
        (20, "a1", "0"), (20, "a3", "0"), (20, "a4", "1"),
    ])
    analysis = analyze_vcd_file(_write(tmp_path, body))
    insights = waveform_insights(
        analysis,
        clock_period_ns=10.0,
        stability_signals=["tb.start", "tb.done", "tb.a"],
        phase_pairs=[{"trigger": "tb.start", "response": "tb.done", "expected_delay_cycles": 1}],
    )
    signals = {item["signal"] for item in insights["signal_edges"]}
    assert signals == {"tb.start", "tb.done", "tb.a"}
    assert insights["phase_checks"]
    assert insights["disclaimer"]


def test_analyze_failure_windows_maps_cycles_to_time(tmp_path):
    body = _values([(index * 10, "a4", "1" if index % 2 else "0") for index in range(6)])
    path = _write(tmp_path, body, name="windows.vcd")
    report = analyze_failure_windows(path, [1, 3], clock_period_ns=10.0, radius=1)
    assert report["status"] == "parsed"
    assert [item["cycle"] for item in report["windows"]] == [1, 3]
    assert report["windows"][0]["start_ns"] == 0.0
    assert report["windows"][0]["end_ns"] == 30.0


def test_invalid_arguments_are_rejected(tmp_path):
    body = _values([(0, "a4", "0")])
    path = _write(tmp_path, body, name="arg.vcd")
    analysis = analyze_vcd_file(path)
    with pytest.raises(ValueError):
        detect_phase_violations(analysis, [("tb.a", "tb.b", 1)], clock_period_ns=0)
    with pytest.raises(ValueError):
        detect_phase_violations(analysis, [("tb.a", "tb.b", 1)], clock_period_ns=10, tolerance_cycles=-1)
    with pytest.raises(ValueError):
        analyze_failure_windows(path, [1], clock_period_ns=-1)
    with pytest.raises(ValueError):
        analyze_vcd_file(path, max_changes=0)
