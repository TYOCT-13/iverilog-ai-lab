"""外部模块验证夹具（P0-D）的离线回归。

只测**不依赖网络、不依赖上游文件**的部分：合约与激励计划必须能被项目的严格校验接受。
端口级计时判据另外用独立的周期脚本发射器验证正负例，不冒充真实外部检出成绩。
真正的对比运行需要先抓取上游 RTL（`.iverilog-ai/external/`，不进版本库），
在 CI 里没有网络也能跑的就到这里为止——与其写一个"网络不通就 skip"的假回归，
不如把能离线钉住的部分钉死。

为什么值得钉：这份合约里的 `reset.active_level = 1`（高有效）与 `prescale` 的 16 位宽
正是本轮 A 修掉的两类静默猜测。如果哪天夹具被"顺手"改成低有效或把 prescale 写成 8 位，
这个测试会红——而线上跑的时候不会有任何报错，只会得出错误的结论。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_check_external_module", ROOT / "scripts" / "check_external_module.py"
)
assert _SPEC and _SPEC.loader
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)


def test_contract_is_accepted_and_states_reset_semantics_explicitly():
    contract = DutContract.from_dict(harness.CONTRACT)
    assert contract.module == "uart_rx"
    # 高有效 + 同步：这两条在源码里有依据（always @(posedge clk) if (rst)），必须显式写出
    assert contract.reset is not None
    assert contract.reset.active_level == 1
    assert contract.reset.synchronous is True
    assert contract.clock is not None and contract.clock.edge == "posedge"
    # 16 位输入：宽端口是"最高位必须被驱动"那条修复的现场
    assert contract.port_map["prescale"].width == 16
    assert contract.port_map["m_axis_tdata"].width == 8


def test_plan_is_schema_valid_and_covers_a_bad_stop_bit():
    plan = TestPlan.model_validate(harness.build_plan())
    names = [vector.name for vector in plan.vectors]
    assert any("bad_stop" in name for name in names), "停止位为 0 的那一帧是检出该变体的唯一依据"
    # 计划只含激励：外部模块的判据是"与基线行为一致"，不臆造期望值
    assert all(not vector.expected for vector in plan.vectors)
    # 同一份计划会同时跑基线与候选，因此必须驱动全部输入端口
    driven = {signal for vector in plan.vectors for signal in vector.inputs}
    assert {"rxd", "prescale", "m_axis_tready"} <= driven


def test_test_byte_is_not_a_bit_palindrome():
    """测试字节必须是位序非回文，否则"位序写反"的变体在行为上与基线一模一样。"""

    byte = harness.BYTE
    reversed_byte = int(f"{byte:08b}"[::-1], 2)
    assert byte != reversed_byte, f"0x{byte:02X} 是位序回文，检不出位序类缺陷"
    bits = harness.BITS
    assert len(bits) == 8 and bits == [(byte >> i) & 1 for i in range(8)]


@pytest.mark.parametrize("name", list(harness.VARIANTS))
def test_every_variant_has_a_real_source_anchor(name: str):
    """每个变体的锚点都必须能在上游源码里找到——否则"变异"会静默地什么都没改。"""

    description, old, new = harness.VARIANTS[name]
    assert description and old and new
    assert old != new


@pytest.mark.parametrize("name", list(harness.TX_VARIANTS))
def test_every_tx_variant_has_a_real_source_anchor(name: str):
    description, old, new = harness.TX_VARIANTS[name]
    assert description and old and new
    assert old != new, "变体的替换文本与原文相同 = 没有变异，却会被记成'未检出'"


@pytest.mark.parametrize("name", list(harness.PE_VARIANTS))
def test_every_priority_encoder_variant_has_a_real_source_anchor(name: str):
    description, old, new = harness.PE_VARIANTS[name]
    assert description and old and new
    assert old != new


def test_priority_encoder_contract_is_parameterised_and_clockless():
    """参数化 + 无时钟的合约必须被校验接受：不写 clock/reset 就是"没有"，不是"猜一个"。"""

    contract = DutContract.from_dict(harness.PE_CONTRACT)
    assert contract.parameters == {"WIDTH": 4, "LSB_HIGH_PRIORITY": 0}
    assert contract.clock is None and contract.reset is None
    # $clog2(4) = 2：编码输出只有 2 位，写错会让测试台接错线
    assert contract.port_map["output_encoded"].width == 2
    assert contract.port_map["input_unencoded"].width == 4


def test_priority_encoder_plan_sweeps_the_whole_input_space():
    plan = TestPlan.model_validate(harness.build_pe_plan())
    driven = [vector.inputs["input_unencoded"] for vector in plan.vectors]
    assert driven == list(range(16)), "组合逻辑的激励必须穷举输入空间，否则覆盖率没有依据"


def _manifest(tmp_path):
    import hashlib
    import json
    root = tmp_path / "source"
    root.mkdir()
    modules = {}
    for name in harness.MODULES:
        data = f"frozen source {name}".encode()
        (root / f"{name}.v").write_bytes(data)
        modules[name] = {"local": f"{name}.v", "sha256": hashlib.sha256(data).hexdigest()}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "external-inputs-v1", "modules": modules}))
    return manifest


def test_freeze_copies_verified_inputs_and_refuses_existing_run(tmp_path):
    manifest = _manifest(tmp_path)
    work = tmp_path / "run"
    records = harness.freeze_inputs(manifest, work)
    assert len(records) == 3
    assert (work / "inputs/uart_rx.v").read_bytes() == b"frozen source uart_rx"
    with pytest.raises(FileExistsError):
        harness.freeze_inputs(manifest, work)


def test_changed_input_fails_before_creating_output(tmp_path):
    manifest = _manifest(tmp_path)
    (manifest.parent / "uart_rx.v").write_bytes(b"modified")
    work = tmp_path / "run"
    with pytest.raises(ValueError, match="hash mismatch"):
        harness.freeze_inputs(manifest, work)
    assert not work.exists()


def test_manifest_cannot_escape_bundle_directory(tmp_path):
    import json
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["modules"]["uart_rx"]["local"] = "../outside.v"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="escapes"):
        harness.freeze_inputs(manifest, tmp_path / "run")


def test_check_requires_explicit_paths():
    with pytest.raises(SystemExit) as error:
        harness.main([])
    assert error.value.code == 2


def test_fetch_registry_matches_checked_modules_and_rejects_wrong_hash(tmp_path):
    spec = importlib.util.spec_from_file_location("external_fetch", ROOT / "scripts/fetch_external_modules.py")
    fetcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetcher)
    assert set(fetcher.SOURCES) == set(harness.MODULES)
    item = fetcher.SOURCES["uart_rx"]
    wrong = tmp_path / item["legacy_local"]
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(b"wrong source")
    with pytest.raises(ValueError, match="hash differs"):
        fetcher.freeze(tmp_path / "output", tmp_path)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("summary,exit_code,complete", [
    ("", 0, False), ("SPEC_SUMMARY checks=0 failures=0", 0, False),
    ("SPEC_SUMMARY checks=11 failures=0", 1, False),
    ("SPEC_SUMMARY checks=11 failures=2", 0, True),
])
def test_missing_or_crashed_spec_run_is_not_reported_as_pass(tmp_path, monkeypatch, summary, exit_code, complete):
    from subprocess import CompletedProcess
    calls = iter([CompletedProcess([], 0, "", ""), CompletedProcess([], exit_code, summary, "")])
    monkeypatch.setattr(harness, "WORK", tmp_path)
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: next(calls))
    monkeypatch.setattr(harness, "run_verify_diff", lambda *a: {"status": "identical", "exit": 0})
    result = harness.run_case_generic(tmp_path / "x.v", "baseline", "", "uart_rx",
                                      tmp_path / "contract.json", tmp_path / "plan.json")
    assert result["spec_complete"] is complete


def _task_source(name: str) -> str:
    """Use the production checker tasks with an independently scripted waveform."""
    import re
    found = re.search(rf"  task {name};.*?  endtask", harness.TX_SPEC_TB, re.S)
    assert found is not None
    return found.group()


# Fixture-only transmitter: schedule txd from the elapsed frame index. It does
# not copy the frozen upstream's prescale counter/shift-register implementation.
# The fixture probes the new port-level timing tasks, not the loopback receiver.
_TIMELINE_TRANSMITTER = r"""
`timescale 1ns/1ps
module uart_tx #(
  parameter DATA_WIDTH=8, PERIOD_SHORT=0, STUCK_BUSY=0, BAD_STOP=0
)(
  input wire clk, rst,
  input wire [DATA_WIDTH-1:0] s_axis_tdata,
  input wire s_axis_tvalid,
  output reg s_axis_tready, txd, busy,
  input wire [15:0] prescale
);
  reg [9:0] scripted_frame;
  integer elapsed=0, bit_window=8, bit_index;
  reg emitting=0;
  initial begin s_axis_tready=0; txd=1; busy=0; end
  always @(posedge clk) begin
    if (rst) begin
      busy<=0; txd<=1; s_axis_tready<=0; elapsed<=0; emitting<=0;
    end else if (!emitting) begin
      s_axis_tready<=1;
      if (s_axis_tready && s_axis_tvalid) begin
        scripted_frame <= {BAD_STOP ? 1'b0 : 1'b1, s_axis_tdata, 1'b0};
        bit_window <= 8*prescale-PERIOD_SHORT;
        elapsed<=0; emitting<=1; busy<=1; txd<=0; s_axis_tready<=0;
      end
    end else begin
      elapsed<=elapsed+1;
      bit_index=(elapsed+1)/bit_window;
      txd <= bit_index<10 ? scripted_frame[bit_index] : 1'b1;
      if (elapsed+1==10*bit_window+1) begin
        emitting<=0; busy<=STUCK_BUSY ? 1'b1 : 1'b0; s_axis_tready<=1;
      end
    end
  end
endmodule
"""


@pytest.mark.parametrize("fixture_parameters,expected_failure", [
    ("", None),
    (", .PERIOD_SHORT(1)", "serial_bit_value_or_duration"),
    (", .STUCK_BUSY(1)", "busy_released_on_deadline"),
    (", .BAD_STOP(1)", "serial_bit_value_or_duration"),
])
def test_tx_port_timing_oracle_accepts_good_trace_and_rejects_bad_controls(
    tmp_path, fixture_parameters, expected_failure,
):
    """An accurate decoder alone must not hide shortened bits or stuck busy."""
    import subprocess
    from iverilog_ai.core.toolchain import locate_tools

    tools = locate_tools()
    assert tools.iverilog and tools.vvp, "these offline oracle controls require Icarus"
    tasks = "\n".join(_task_source(name) for name in ("check", "offer", "check_frame_timing"))
    testbench = f"""
`timescale 1ns/1ps
module tb;
  reg clk=0, rst=1;
  reg [7:0] tdata=0;
  reg tvalid=0;
  reg [15:0] prescale=1;
  wire tready, txd, tx_busy;
  integer checks=0, failures=0, waited=0;
  uart_tx #(.DATA_WIDTH(8){fixture_parameters}) dut(
    .clk(clk), .rst(rst), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid),
    .s_axis_tready(tready), .txd(txd), .busy(tx_busy), .prescale(prescale));
  always #5 clk=~clk;
{tasks}
  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk); rst=0;
    repeat (2) begin @(posedge clk); #1; end
    check_frame_timing(1);
    check_frame_timing(2);
    $display("SPEC_SUMMARY checks=%0d failures=%0d", checks, failures);
    $finish;
  end
endmodule
"""
    source = tmp_path / "timing_controls.v"
    source.write_text(_TIMELINE_TRANSMITTER + testbench, encoding="utf-8")
    executable = tmp_path / "timing_controls.vvp"
    compiled = subprocess.run(
        [tools.iverilog, "-g2012", "-s", "tb", "-o", str(executable), str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr
    simulated = subprocess.run([tools.vvp, str(executable)], capture_output=True, text=True, timeout=30)
    assert simulated.returncode == 0, simulated.stderr
    failed = [line for line in simulated.stdout.splitlines() if line.endswith("FAIL")]
    if expected_failure is None:
        assert not failed, "correct trace must pass at both prescale=1 and prescale=2"
        assert "failures=0" in simulated.stdout
    else:
        assert any(f"CHECK {expected_failure} FAIL" == line for line in failed), simulated.stdout
