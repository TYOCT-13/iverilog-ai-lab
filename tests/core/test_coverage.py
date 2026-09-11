"""信号活动覆盖率的回归测试。

口径是这套东西的全部价值所在，因此测试重点在三处：

1. **必须排除编译期常量与存储体**：`localparam RED=2'b00, YELLOW=2'b01` 里的名字
   按定义永不变化，计入会形成整片假缺口（实测 traffic_light_emergency 曾把 7 个
   状态常量列为"未变化"）；
2. **取值覆盖要有区分力**：只看"信号是否变化"是不够的——复位把计数器清零也算
   "变化过"，弱激励因此仍能报 100%。测试用充分/弱两种激励对比，
   要求弱激励的取值覆盖显著更低；
3. **不可观测时必须说"不知道"**，不能报 0% 或 100%。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.coverage import (
    DISCLAIMER,
    analyze_signal_activity,
    module_signals,
    strip_comments,
)
from iverilog_ai.core.toolchain import locate_tools
from iverilog_ai.core.vcd import analyze_vcd_file

ROOT = Path(__file__).parents[2]
_TOOLS = locate_tools()
WORK = ROOT / ".iverilog-ai" / "test-coverage"


def test_strip_comments_keeps_line_numbers():
    source = "line1\n/* two\nlines */\nline4 // tail\n"
    cleaned = strip_comments(source)
    assert cleaned.count("\n") == source.count("\n")
    assert "// tail" not in cleaned


def test_module_signals_extracts_ports_and_internal():
    source = """`timescale 1ns/1ps
module m(input wire clk, input wire [3:0] d, output reg [3:0] q);
  reg [3:0] tmp;
  always @(posedge clk) begin tmp <= d; q <= tmp; end
endmodule
"""
    modules = module_signals(source)
    assert [item.name for item in modules] == ["m"]
    names = set(modules[0].signals)
    assert {"clk", "d", "q", "tmp"} <= names


def test_localparam_names_are_excluded_not_reported_as_unchanged():
    """`localparam A=0, B=1;` 的 A/B 是常量，不能算作"未变化的信号"。"""

    source = """`timescale 1ns/1ps
module m(input wire clk, output reg [1:0] state);
  localparam RED=2'b00, YELLOW=2'b01, GREEN=2'b10;
  always @(posedge clk) state <= GREEN;
endmodule
"""
    modules = module_signals(source)
    assert set(modules[0].parameters) == {"RED", "YELLOW", "GREEN"}, modules[0].parameters
    for name in ("RED", "YELLOW", "GREEN"):
        assert name not in modules[0].signals, f"{name} 是常量，不应进入信号集合"


def test_memory_declarations_are_excluded():
    source = """`timescale 1ns/1ps
module m(input wire clk, input wire [7:0] d);
  reg [7:0] mem [0:3];
  always @(posedge clk) mem[0] <= d;
endmodule
"""
    modules = module_signals(source)
    assert "mem" in modules[0].memories
    assert "mem" not in modules[0].signals


def test_unobservable_instance_reports_unknown_not_zero():
    """没有该实例的信号时必须说"不知道"，不能报 0% 或 100%。"""

    source = (ROOT / "rtl" / "mod10_counter.v").read_text(encoding="utf-8")
    report = analyze_signal_activity(source, {"signals": []}, top="tb_mod10_counter", instance="dut_i")
    assert report["status"] == "unknown"
    assert "无法判定" in report["note"]
    assert DISCLAIMER in report["disclaimer"]


def test_signals_outside_the_instance_are_ignored():
    """测试台自己的信号不属于 DUT，不能计入 DUT 的覆盖率。"""

    source = (ROOT / "rtl" / "mod10_counter.v").read_text(encoding="utf-8")
    analysis = {
        "signals": [
            {"name": "tb_mod10_counter.cycle", "changes": 40, "distinct_values": 40},
            {"name": "tb_mod10_counter.dut_i.count", "changes": 12, "distinct_values": 6},
        ]
    }
    report = analyze_signal_activity(source, analysis, top="tb_mod10_counter", instance="dut_i")
    assert report["status"] == "measured"
    assert report["changed_signals"] == 1
    assert "count" in report["changed_by_instance"]["dut_i"]
    # 测试台信号名不得出现在任何实例分组里
    for leaves in report["changed_by_instance"].values():
        assert "cycle" not in leaves


def test_report_carries_the_disclaimer_that_it_is_not_code_coverage():
    source = (ROOT / "rtl" / "pwm.v").read_text(encoding="utf-8")
    report = analyze_signal_activity(source, {"signals": []}, top="tb_pwm", instance="dut_i")
    assert "不是语句、分支、条件或翻转覆盖率" in report["disclaimer"]


# --------------------------------------------------------------------------
# 端到端：取值覆盖必须能区分激励强弱
# --------------------------------------------------------------------------
def _run_mod10(vectors: list[dict], tag: str) -> dict:
    from iverilog_ai.ai.schema import TestPlan
    from iverilog_ai.core.contracts import DutContract
    from iverilog_ai.core.pipeline import VerificationPipeline

    WORK.mkdir(parents=True, exist_ok=True)
    contract = DutContract.from_dict(
        json.loads((ROOT / "examples" / "mod10_counter_contract.json").read_text(encoding="utf-8"))
    )
    source = (ROOT / "rtl" / "mod10_counter.v").read_text(encoding="utf-8")
    plan = TestPlan.model_validate({"design": "mod10_counter", "objective": tag, "vectors": vectors})
    result = VerificationPipeline().run(
        plan, contract, ROOT / "rtl" / "mod10_counter.v", WORK / tag,
        allowed_roots=(ROOT,), iverilog_path=_TOOLS.iverilog, vvp_path=_TOOLS.vvp,
    )
    analysis = analyze_vcd_file(result.simulation.artifacts["vcd"], max_changes=5000)
    return analyze_signal_activity(source, analysis, top="tb_mod10_counter", instance="dut_i")


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog")
def test_value_coverage_distinguishes_weak_from_rich_stimulus():
    """弱激励（只保持使能为 0）的取值覆盖必须明显低于充分激励。

    这条用例是本模块存在意义的证明：如果弱激励也报满，这个指标就没有诊断价值。
    同时它也说明"是否变化"不够用——两种激励下所有信号都"变化过"。
    """

    rich = _run_mod10(
        [
            {"name": "reset", "inputs": {"rst_n": 0, "enable": 0}, "cycles": 2, "expected": {}},
            {"name": "count", "inputs": {"rst_n": 1, "enable": 1}, "cycles": 5, "expected": {}},
            {"name": "hold", "inputs": {"rst_n": 1, "enable": 0}, "cycles": 2, "expected": {}},
        ],
        "rich",
    )
    weak = _run_mod10(
        [
            {"name": "reset", "inputs": {"rst_n": 0, "enable": 0}, "cycles": 2, "expected": {}},
            {"name": "hold", "inputs": {"rst_n": 1, "enable": 0}, "cycles": 6, "expected": {}},
        ],
        "weak",
    )
    # 两种激励下信号都"变化过"——所以活动比例本身没有区分力
    assert rich["ratio"] == 1.0 and weak["ratio"] == 1.0
    # 取值覆盖必须拉开差距
    assert rich["value_coverage"] is not None and weak["value_coverage"] is not None
    assert weak["value_coverage"] < rich["value_coverage"], (weak["value_coverage"], rich["value_coverage"])
    # 弱激励下 count 只到过 1 个取值（复位清零那次）
    count_entry = next(item for item in weak["value_detail"] if item["signal"] == "count")
    assert count_entry["distinct_values"] == 1
    assert count_entry["possible_values"] == 16
