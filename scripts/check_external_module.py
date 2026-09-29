"""外部模块验证（P0-D）第 1 个模块：`alexforencich/verilog-uart` 的 `uart_rx`。

这个脚本做四件事，全部离线、只用本机 Icarus：

1. 用**手写规格测试台**证明基线实现是对的（这是"可信基线"的正确性依据，
   不是"我觉得它对"）；
2. 生成一份**只含激励**的计划（不含期望值——外部模块的判据是"与基线行为一致"）；
3. 造 1 个等价改写 + 5 个人工变体 + 1 个编不过的输入；
4. 用项目自己的 `verify-diff` 路径逐个比对，检查四类输入是否落到正确的类别：
   等价改写→一致、功能变体→不同、编不过→未取得可比证据、基线自己→一致。

产物写在 `.iverilog-ai/external/uart_rx_check/`（上游源码与变体不进版本库）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()
UPSTREAM = ROOT / ".iverilog-ai/external/verilog-uart-master/uart_rx.v"
WORK = ROOT / ".iverilog-ai/external/uart_rx_check"
PYTHON = sys.executable

CONTRACT = {
    "module": "uart_rx",
    "parameters": {"DATA_WIDTH": 8},
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "m_axis_tdata", "direction": "output", "width": 8},
        {"name": "m_axis_tvalid", "direction": "output", "width": 1},
        {"name": "m_axis_tready", "direction": "input", "width": 1},
        {"name": "rxd", "direction": "input", "width": 1},
        {"name": "busy", "direction": "output", "width": 1},
        {"name": "overrun_error", "direction": "output", "width": 1},
        {"name": "frame_error", "direction": "output", "width": 1},
        {"name": "prescale", "direction": "input", "width": 16},
    ],
    # 显式确认：上升沿时钟；复位**高有效且同步**（源码是 always @(posedge clk) if (rst)）。
    # 这两条以前会被"按名字猜"成低有效/异步——正是本轮 A 修掉的那类问题。
    "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
    "reset": {"signal": "rst", "active_level": 1, "synchronous": True, "assert_cycles": 3},
}

# 只含激励：两帧。prescale=1 → 起始位之后每位 8 个时钟（8 倍过采样）。
#
# 测试字节刻意**不是**位序回文：0xA5 = 1010_0101 正反读一样，第一版就用它，
# 结果"位序写反"的变体在波形上完全看不出来（verify-diff 也说一致）。
# 0x96 = 1001_0110 反过来是 0110_1001，位序一改就露馅。
BYTE = 0x96
BITS = [(BYTE >> index) & 1 for index in range(8)]


def _frame_vectors(prefix: str, byte: int, stop_bit: int, start_cycle: int) -> list[dict]:
    """一帧：起始位 + 8 数据位（LSB 优先）+ 停止位。"""

    bits = [(byte >> index) & 1 for index in range(8)]
    vectors = [
        {"name": f"{prefix}_start", "inputs": {"rxd": 0}, "cycles": 10, "sample_phase": "after",
         "expected": {}, "rationale": "start bit low"},
    ]
    for index, bit in enumerate(bits):
        vectors.append({
            "name": f"{prefix}_bit{index}", "inputs": {"rxd": bit}, "cycles": 8,
            "sample_phase": "after", "expected": {}, "rationale": f"data bit {index} (LSB first)",
        })
    vectors.append({
        "name": f"{prefix}_stop", "inputs": {"rxd": stop_bit}, "cycles": 8,
        "sample_phase": "after", "expected": {},
        "rationale": "stop bit" + ("（正常高电平）" if stop_bit else "（**故意为 0**：必须报 frame_error）"),
    })
    return vectors


def build_plan() -> dict:
    vectors = [
        {"name": "idle_before", "inputs": {"prescale": 1, "rxd": 1, "m_axis_tready": 1},
         "cycles": 4, "sample_phase": "after", "expected": {}, "rationale": "idle line high"},
    ]
    vectors += _frame_vectors("frame1", BYTE, 1, 0)
    vectors += [
        {"name": "idle_between", "inputs": {"rxd": 1}, "cycles": 6, "sample_phase": "after",
         "expected": {}, "rationale": "gap between frames"},
    ]
    # 第二帧：停止位为 0。没有这一帧，"不检查停止位"的变体在行为上与基线完全一样
    # （第一版就是这样漏掉它的）——激励覆盖哪里，才可能检出哪里。
    vectors += _frame_vectors("frame2_bad_stop", BYTE, 0, 0)
    vectors += [
        {"name": "idle_after", "inputs": {"rxd": 1}, "cycles": 8, "sample_phase": "after",
         "expected": {}, "rationale": "let frame_error be observed"},
    ]
    return {
        "schema_version": "1.0",
        "design": "uart_rx",
        "objective": "external module: one good frame and one frame with a bad stop bit, so baseline and candidate see identical stimulus",
        "clock_period_ns": 10,
        "reset": {"active_low": False},
        "vectors": vectors,
    }


SPEC_TB = """\
// 手写规格测试台：证明基线 uart_rx 真的能按 UART 规范收下一帧。
// 它只依据**规格**（起始位/8 数据位 LSB 优先/停止位/握手/复位语义），不看 DUT 内部实现。
//
// 观测方式刻意用**粘滞标志**而不是"第几拍采样"：tvalid 与 frame_error 都是单周期脉冲，
// 按固定拍数去采样会因为差一拍而误判（第一版就是这么错的：基线自己挂了 3 项）。
// 规格说的是"这一帧里出现过 valid / 出现过 frame_error"，粘滞标志正是这个意思。
`timescale 1ns/1ps
module tb_uart_rx;
  reg clk = 0, rst = 0, rxd = 1, m_axis_tready = 1;
  reg [15:0] prescale = 1;
  wire [7:0] m_axis_tdata;
  wire m_axis_tvalid, busy, overrun_error, frame_error;
  integer failures = 0, checks = 0;

  uart_rx #(.DATA_WIDTH(8)) dut (
    .clk(clk), .rst(rst), .m_axis_tdata(m_axis_tdata), .m_axis_tvalid(m_axis_tvalid),
    .m_axis_tready(m_axis_tready), .rxd(rxd), .busy(busy),
    .overrun_error(overrun_error), .frame_error(frame_error), .prescale(prescale));

  always #5 clk = ~clk;

  // 粘滞观测
  reg saw_tvalid = 0, saw_frame_error = 0;
  reg [7:0] latched = 8'h00;
  always @(posedge clk) begin
    if (m_axis_tvalid) begin saw_tvalid <= 1'b1; latched <= m_axis_tdata; end
    if (frame_error) saw_frame_error <= 1'b1;
  end

  task clear_flags; begin saw_tvalid = 0; saw_frame_error = 0; end endtask

  task check;
    input [255:0] name;
    input condition;
    begin
      checks = checks + 1;
      if (!condition) begin
        failures = failures + 1;
        $display("CHECK %0s FAIL", name);
      end else begin
        $display("CHECK %0s ok", name);
      end
    end
  endtask

  task send_bit;
    input value;
    integer i;
    begin
      rxd = value;
      for (i = 0; i < 8; i = i + 1) @(posedge clk);
    end
  endtask

  task send_frame;
    input [7:0] value;
    input good_stop;
    integer i;
    begin
      send_bit(1'b0);
      for (i = 0; i < 8; i = i + 1) send_bit(value[i]);
      send_bit(good_stop);
    end
  endtask

  integer i;
  initial begin
    // 复位（高有效）后应当空闲
    rst = 1; repeat (3) @(posedge clk); #1;
    check("reset_clears_busy", busy === 1'b0);
    rst = 0; repeat (2) @(posedge clk);

    // 第一帧：tready 保持 0，验证 tvalid 会保持住（AXI 握手语义）
    clear_flags(); m_axis_tready = 0;
    send_frame(8'h96, 1'b1);
    repeat (4) @(posedge clk); #1;
    check("frame_decoded", latched === 8'h96);
    check("tvalid_pulsed", saw_tvalid === 1'b1);
    check("no_frame_error", saw_frame_error === 1'b0);
    check("not_busy_after", busy === 1'b0);
    check("tvalid_holds_without_tready", m_axis_tvalid === 1'b1);
    m_axis_tready = 1; repeat (2) @(posedge clk); #1;
    check("tvalid_clears_after_ready", m_axis_tvalid === 1'b0);

    // 帧中途复位：busy 必须被清掉（这条会抓住"复位极性反了"的实现）
    send_bit(1'b0); repeat (4) @(posedge clk); #1;
    check("busy_during_frame", busy === 1'b1);
    rst = 1; repeat (2) @(posedge clk); #1;
    check("reset_mid_frame_clears_busy", busy === 1'b0);
    rst = 0; repeat (2) @(posedge clk);

    // 停止位为 0：必须报 frame_error，且不产出数据
    rxd = 1; repeat (6) @(posedge clk);
    clear_flags();
    send_frame(8'h96, 1'b0);
    repeat (4) @(posedge clk); #1;
    check("bad_stop_sets_frame_error", saw_frame_error === 1'b1);
    check("bad_stop_no_data", saw_tvalid === 1'b0);

    $display("SPEC_SUMMARY checks=%0d failures=%0d", checks, failures);
    $finish(0);
  end
endmodule
"""

# 人工变体：每一条都是**语义**改动（不是改注释），对应一类真实缺陷。
VARIANTS: dict[str, tuple[str, str, str]] = {
    "mut_reset_polarity": ("复位极性反过来（if (rst) → if (!rst)）", "if (rst) begin", "if (~rst) begin"),
    "mut_bit_order": ("数据位序写反（LSB 优先 → MSB 优先）",
                      "data_reg <= {rxd_reg, data_reg[DATA_WIDTH-1:1]};",
                      "data_reg <= {data_reg[DATA_WIDTH-2:0], rxd_reg};"),
    "mut_frame_length": ("帧长多一位（bit_cnt = DATA_WIDTH+2 → +3）", "bit_cnt <= DATA_WIDTH+2;", "bit_cnt <= DATA_WIDTH+3;"),
    "mut_stop_bit_check": ("不检查停止位（无条件接受数据）", "if (rxd_reg) begin", "if (1'b1) begin"),
    "mut_valid_never_clears": ("tvalid 不会被 tready 清掉", "if (m_axis_tvalid && m_axis_tready) begin",
                               "if (1'b0) begin"),
}

# 等价改写：把"decrement + 比较"改成 case 选择，语义不变。
EQUIVALENT = [
    (
        "        if (prescale_reg > 0) begin\n"
        "            prescale_reg <= prescale_reg - 1;\n"
        "        end else if (bit_cnt > 0) begin\n",
        "        if (prescale_reg > 0) begin\n"
        "            prescale_reg <= prescale_reg - 16'd1;\n"
        "        end else if (bit_cnt != 4'd0) begin\n",
    ),
    (
        "            if (bit_cnt > DATA_WIDTH+1) begin",
        "            if (bit_cnt >= DATA_WIDTH+2) begin",
    ),
]

BROKEN = "module uart_rx(input wire clk); this is not verilog; endmodule\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_spec_tb(rtl: Path, tag: str) -> dict:
    """用手写规格测试台跑一份实现，返回检查结果。"""

    tb = WORK / f"tb_spec_{tag}.v"
    vvp = WORK / f"spec_{tag}.vvp"
    compile_result = subprocess.run(
        [r"D:\iverilog\bin\iverilog.exe", "-g2005", "-o", str(vvp), str(rtl), str(tb)],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
    )
    if compile_result.returncode != 0:
        return {"compiled": False, "error": (compile_result.stdout + compile_result.stderr).strip()[:200]}
    done = subprocess.run(
        [r"D:\iverilog\bin\vvp.exe", str(vvp)],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
    )
    output = done.stdout + done.stderr
    failed = [line.split()[1] for line in output.splitlines() if line.startswith("CHECK") and line.endswith("FAIL")]
    summary = next((line for line in output.splitlines() if line.startswith("SPEC_SUMMARY")), "")
    return {"compiled": True, "failed_checks": failed, "summary": summary}


def run_verify_diff(candidate: Path, module: str, contract: Path, plan: Path, tag: str) -> dict:
    """走项目自己的 verify-diff 路径（基线与候选用同一份合约与同一份计划）。"""

    out = WORK / f"diff_{tag}"
    done = subprocess.run(
        [PYTHON, "-m", "iverilog_ai", "verify-diff",
         "--baseline", str(BASELINES[module]), "--candidate", str(candidate),
         "--contract", str(contract), "--plan", str(plan),
         "--module", module, "--output-dir", str(out),
         "--iverilog", r"D:\iverilog\bin\iverilog.exe", "--vvp", r"D:\iverilog\bin\vvp.exe"],
        capture_output=True, text=True, timeout=600, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"},
    )
    status = ""
    for candidate_json in sorted(out.glob("*.json")):
        try:
            payload = json.loads(candidate_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "status" in payload:
            status = str(payload["status"])
            break
    return {"exit": done.returncode, "status": status, "stdout": done.stdout.strip()[-160:]}


# =====================================================================================
# 第 2 个模块：同一个上游仓库的 uart_tx（发送侧）
#
# 规格测试台刻意做成**环回**：uart_tx → uart_rx，收到的字节必须等于发出的字节。
# 好处是它同时检验两侧、而且**不需要人工数拍**去采样串行位——位序、停止位、
# 位周期（prescale）任何一处错了，环回都会失败。这正是第一版 rx 测试台用手工采样
# 时踩坑（单周期脉冲差一拍）的反面教材。
# =====================================================================================

TX_UPSTREAM = UPSTREAM.parent / "uart_tx.v"

TX_CONTRACT = {
    "module": "uart_tx",
    "parameters": {"DATA_WIDTH": 8},
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "s_axis_tdata", "direction": "input", "width": 8},
        {"name": "s_axis_tvalid", "direction": "input", "width": 1},
        {"name": "s_axis_tready", "direction": "output", "width": 1},
        {"name": "txd", "direction": "output", "width": 1},
        {"name": "busy", "direction": "output", "width": 1},
        {"name": "prescale", "direction": "input", "width": 16},
    ],
    # 与 rx 同源：高有效、同步复位（源码 `always @(posedge clk) if (rst)`）。
    "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
    "reset": {"signal": "rst", "active_level": 1, "synchronous": True, "assert_cycles": 3},
}

TX_BYTE = 0x96
TX_BITS = [(TX_BYTE >> index) & 1 for index in range(8)]


def build_tx_plan() -> dict:
    """只含激励：给一帧数据，观察 txd 与握手（判据是"与基线行为一致"）。"""

    vectors = [
        {"name": "idle", "inputs": {"prescale": 1, "s_axis_tvalid": 0, "s_axis_tdata": 0},
         "cycles": 4, "sample_phase": "after", "expected": {}, "rationale": "idle, waiting for data"},
        {"name": "handshake", "inputs": {"s_axis_tvalid": 1, "s_axis_tdata": TX_BYTE},
         "cycles": 2, "sample_phase": "after", "expected": {}, "rationale": "offer one byte"},
        {"name": "sending", "inputs": {"s_axis_tvalid": 0, "s_axis_tdata": 0},
         "cycles": 90, "sample_phase": "after", "expected": {},
         "rationale": "let the whole frame shift out (start + 8 data bits + stop at prescale=1)"},
        {"name": "settle", "inputs": {"s_axis_tvalid": 0}, "cycles": 8, "sample_phase": "after",
         "expected": {}, "rationale": "return to idle"},
    ]
    return {
        "schema_version": "1.0",
        "design": "uart_tx",
        "objective": "external module: shift out one UART frame so baseline and candidate see identical stimulus",
        "clock_period_ns": 10,
        "reset": {"active_low": False},
        "vectors": vectors,
    }


TX_SPEC_TB = """\
// 环回规格测试台：uart_tx 发出去的字节，必须被 uart_rx 原样收回来。
// 只依据 UART 规范（起始位/8 数据位 LSB 优先/停止位）与 AXI-Stream 握手语义。
`timescale 1ns/1ps
module tb_uart_tx;
  reg clk = 0, rst = 0;
  reg [7:0] tdata = 0;
  reg tvalid = 0;
  reg [15:0] prescale = 1;
  wire tready, txd, tx_busy;
  wire [7:0] rdata;
  wire rvalid, rbusy, ferr, oerr;
  integer failures = 0, checks = 0;

  uart_tx #(.DATA_WIDTH(8)) tx (
    .clk(clk), .rst(rst), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid),
    .s_axis_tready(tready), .txd(txd), .busy(tx_busy), .prescale(prescale));

  uart_rx #(.DATA_WIDTH(8)) rx (
    .clk(clk), .rst(rst), .m_axis_tdata(rdata), .m_axis_tvalid(rvalid),
    .m_axis_tready(1'b1), .rxd(txd), .busy(rbusy),
    .overrun_error(oerr), .frame_error(ferr), .prescale(prescale));

  always #5 clk = ~clk;

  task check;
    input [255:0] name;
    input condition;
    begin
      checks = checks + 1;
      if (!condition) begin
        failures = failures + 1;
        $display("CHECK %0s FAIL", name);
      end else begin
        $display("CHECK %0s ok", name);
      end
    end
  endtask

  // 发一个字节并等它被环回收回；返回收到的字节
  reg [7:0] received;
  integer waited;
  task send_and_receive;
    input [7:0] value;
    begin
      received = 8'h00;
      @(posedge clk);
      tdata = value; tvalid = 1'b1;
      @(posedge clk);
      // 等握手（tready 在空闲时为 1；被接受后随发送拉低）
      waited = 0;
      while (!tready && waited < 20) begin @(posedge clk); waited = waited + 1; end
      tvalid = 1'b0;
      // 等环回收回
      waited = 0;
      while (waited < 400) begin
        @(posedge clk);
        if (rvalid) begin received = rdata; waited = 400; end
        waited = waited + 1;
      end
      // 等**发送侧**也回到空闲再返回：接收侧收到字节比发送侧收尾早一拍，
      // 不等的话下一次激励会撞在还忙着的 DUT 上（第一版就是因此误报 busy 检查失败）。
      waited = 0;
      while (tx_busy && waited < 100) begin @(posedge clk); waited = waited + 1; end
      repeat (2) @(posedge clk);
    end
  endtask

  initial begin
    rst = 1; repeat (3) @(posedge clk); #1;
    check("reset_clears_busy", tx_busy === 1'b0);
    check("reset_idle_txd_high", txd === 1'b1);
    rst = 0; repeat (2) @(posedge clk);

    send_and_receive(8'h96);
    check("loopback_96", received === 8'h96);
    check("no_frame_error", ferr === 1'b0);

    send_and_receive(8'h3C);
    check("loopback_3C", received === 8'h3C);

    // 连续两帧：握手必须允许背靠背发送
    send_and_receive(8'hE1);
    check("loopback_E1", received === 8'hE1);

    // 发送中途复位：busy 必须被清掉（抓"复位极性反了"的实现）
    // tvalid 要**跨过至少一个时钟边沿**再撤：在 `@(posedge clk)` 之后立刻清掉，
    // 会与 DUT 的时钟块抢同一个时间步（谁先执行不确定），第一版就是这么"发了但没被接受"的。
    tdata = 8'h55; tvalid = 1'b1;
    repeat (2) @(posedge clk);
    tvalid = 1'b0;
    repeat (6) @(posedge clk); #1;
    check("busy_during_send", tx_busy === 1'b1);
    rst = 1; repeat (2) @(posedge clk); #1;
    check("reset_mid_send_clears_busy", tx_busy === 1'b0);
    check("reset_drives_txd_high", txd === 1'b1);
    rst = 0; repeat (2) @(posedge clk);

    // 复位之后仍能正常发送
    send_and_receive(8'h0F);
    check("loopback_after_reset", received === 8'h0F);

    $display("SPEC_SUMMARY checks=%0d failures=%0d", checks, failures);
    $finish(0);
  end
endmodule
"""

TX_VARIANTS: dict[str, tuple[str, str, str]] = {
    "mut_reset_polarity": ("复位极性反过来（if (rst) → if (~rst)）", "    if (rst) begin", "    if (~rst) begin"),
    "mut_prescale_off_by_one": ("位周期少一拍（prescale<<3)-1 → -2）",
                                "prescale_reg <= (prescale << 3)-1;", "prescale_reg <= (prescale << 3)-2;"),
    "mut_stop_bit_low": ("停止位发成 0（txd_reg <= 1 → 0）",
                         "                prescale_reg <= (prescale << 3);\n                txd_reg <= 1;",
                         "                prescale_reg <= (prescale << 3);\n                txd_reg <= 0;"),
    "mut_busy_never_clears": ("busy 不会被清掉", "            s_axis_tready_reg <= 1;\n            busy_reg <= 0;",
                              "            s_axis_tready_reg <= 1;\n            busy_reg <= busy_reg;"),
    # 说明：曾经这里放的是"接受数据后 tready 不再拉高"，但查源码后发现那个改动与
    # 原实现**语义等价**（发送期间 ready 本来就是 0，帧尾又会置 1），
    # 于是 verify-diff 判"一致"是**正确**的，不是漏检。换成真正的数据通路改动。
    "mut_data_off_by_one": ("发出的字节差一（data_reg 载入 +1）",
                            "data_reg <= {1'b1, s_axis_tdata};", "data_reg <= {1'b1, s_axis_tdata} + 1'b1;"),
}

TX_EQUIVALENT = [
    ("            if (bit_cnt > 1) begin", "            if (bit_cnt >= 2) begin"),
    ("                bit_cnt <= bit_cnt - 1;\n                prescale_reg <= (prescale << 3);",
     "                bit_cnt <= bit_cnt - 4'd1;\n                prescale_reg <= (prescale << 3);"),
]


def run_case_generic(
    rtl: Path,
    tag: str,
    tb_source: str,
    module: str,
    contract: Path,
    plan: Path,
    spec_deps: tuple[Path, ...] = (),
) -> dict:
    """编译并运行规格测试台，然后走项目自己的 verify-diff。

    两步是**独立**的：规格测试台编不过时（例如环回需要另一个模块）仍然要跑 verify-diff，
    因为"编不过的候选"本身就是要验证的一类输入——它必须落到 `inconclusive`，
    而不是没有结论。
    """

    tb = write(WORK / f"tb_{module}_{tag}.v", tb_source)
    vvp = WORK / f"{module}_{tag}.vvp"
    command = [r"D:\iverilog\bin\iverilog.exe", "-g2012", "-o", str(vvp), str(rtl)]
    command += [str(path) for path in spec_deps]
    command.append(str(tb))
    compile_result = subprocess.run(
        command, capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
    )
    if compile_result.returncode != 0:
        spec: dict = {
            "compiled": False,
            "error": (compile_result.stdout + compile_result.stderr).strip()[:200],
            "failed_checks": [],
            "summary": "",
        }
    else:
        done = subprocess.run(
            [r"D:\iverilog\bin\vvp.exe", str(vvp)],
            capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace",
        )
        output = done.stdout + done.stderr
        spec = {
            "compiled": True,
            "error": "",
            "failed_checks": [
                line.split()[1] for line in output.splitlines() if line.startswith("CHECK") and line.endswith("FAIL")
            ],
            "summary": next((l for l in output.splitlines() if l.startswith("SPEC_SUMMARY")), ""),
        }
    diff = run_verify_diff(rtl, module, contract, plan, f"{module}_{tag}")
    return {**spec, "diff_status": diff["status"], "diff_exit": diff["exit"]}


# =====================================================================================
# 第 3 个模块：verilog-axi 的 priority_encoder（**参数化输入**这一类）
#
# 为什么是它：前两个模块都是"8 位数据 + 时钟 + 复位 + 握手"，缺"参数化"这一类。
# 它是纯组合逻辑（没有时钟/复位），行为由 WIDTH 与 LSB_HIGH_PRIORITY 两个参数决定，
# 于是这一格同时覆盖了：参数化位宽、两种参数取值的对照、以及**无时钟设计**的合约路径。
#
# 来源说明（重要）：它属于 **开发集**——静态约定规则是从 verilog-axi 抽取的，
# 所以它是"别人写的 RTL"，但**不是**未见过的保留集。引用时必须写明这一点。
# =====================================================================================

PE_UPSTREAM = ROOT / ".iverilog-ai/upstream-cache/verilog-axi-516bd5dadc33/rtl/priority_encoder.v"

PE_CONTRACT = {
    "module": "priority_encoder",
    "parameters": {"WIDTH": 4, "LSB_HIGH_PRIORITY": 0},
    "ports": [
        {"name": "input_unencoded", "direction": "input", "width": 4},
        {"name": "output_valid", "direction": "output", "width": 1},
        {"name": "output_encoded", "direction": "output", "width": 2},
        {"name": "output_unencoded", "direction": "output", "width": 4},
    ],
    # 纯组合逻辑：没有时钟也没有复位。合约里就不写这两项——
    # 不写等于"没有"，而不是"猜一个时钟/复位出来"。
}


def build_pe_plan() -> dict:
    """只含激励：把 4 位输入的 16 种取值全部走一遍（组合逻辑不需要时钟）。"""

    vectors = []
    for value in range(16):
        vectors.append({
            "name": f"in_{value:04b}",
            "inputs": {"input_unencoded": value},
            "cycles": 1,
            "sample_phase": "after",
            "expected": {},
            "rationale": "exhaustive sweep of a 4-bit combinational input",
        })
    return {
        "schema_version": "1.0",
        "design": "priority_encoder",
        "objective": "external module: exhaustive 4-bit sweep so baseline and candidate see identical stimulus",
        "clock_period_ns": 10,
        "reset": {"active_low": True},
        "vectors": vectors,
    }


PE_SPEC_TB = """\
// 手写规格测试台：优先编码器的行为只依据规格——
//   * 任何一位为 1 → output_valid 必须为 1；全 0 → output_valid 必须为 0；
//   * 胜者是"优先级最高的那一位"：LSB_HIGH_PRIORITY=0 时最高位优先，=1 时最低位优先；
//   * output_encoded 是胜者下标，output_unencoded 是该下标的独热。
// 同一份测试台里实例化**两个参数取值**，直接检验"参数化"这件事本身。
// 注意：全 0 时 output_encoded/output_unencoded 模块文档没有规定，因此**不做断言**
// （把实现细节当规格是测试台最常见的自欺）。
`timescale 1ns/1ps
module tb_priority_encoder;
  reg [3:0] value = 0;
  wire msb_valid, lsb_valid;
  wire [1:0] msb_enc, lsb_enc;
  wire [3:0] msb_unenc, lsb_unenc;
  integer failures = 0, checks = 0;

  priority_encoder #(.WIDTH(4), .LSB_HIGH_PRIORITY(0)) dut_msb (
    .input_unencoded(value), .output_valid(msb_valid),
    .output_encoded(msb_enc), .output_unencoded(msb_unenc));

  priority_encoder #(.WIDTH(4), .LSB_HIGH_PRIORITY(1)) dut_lsb (
    .input_unencoded(value), .output_valid(lsb_valid),
    .output_encoded(lsb_enc), .output_unencoded(lsb_unenc));

  task check;
    input [255:0] name;
    input condition;
    begin
      checks = checks + 1;
      if (!condition) begin
        failures = failures + 1;
        $display("CHECK %0s FAIL", name);
      end else begin
        $display("CHECK %0s ok", name);
      end
    end
  endtask

  task expect_pair;
    input [3:0] pattern;
    input [1:0] expected_msb;      // 最高位优先时的胜者下标
    input [1:0] expected_lsb;      // 最低位优先时的胜者下标
    input [255:0] name;
    begin
      value = pattern; #1;
      check({name, "_valid"}, msb_valid === 1'b1 && lsb_valid === 1'b1);
      check({name, "_msb"}, msb_enc === expected_msb && msb_unenc === (4'b0001 << expected_msb));
      check({name, "_lsb"}, lsb_enc === expected_lsb && lsb_unenc === (4'b0001 << expected_lsb));
    end
  endtask

  initial begin
    // 全 0：valid 必须为 0（编码值不做断言）
    value = 4'b0000; #1;
    check("empty_valid_low", msb_valid === 1'b0 && lsb_valid === 1'b0);

    // 单个位：两种优先级下胜者相同
    expect_pair(4'b0001, 0, 0, "bit0");
    expect_pair(4'b0010, 1, 1, "bit1");
    expect_pair(4'b0100, 2, 2, "bit2");
    expect_pair(4'b1000, 3, 3, "bit3");

    // 多位：两种优先级必须给出**不同**的胜者，这是参数语义的核心
    expect_pair(4'b1010, 3, 1, "bits31");
    expect_pair(4'b0101, 2, 0, "bits20");
    expect_pair(4'b0110, 2, 1, "bits21");
    expect_pair(4'b1111, 3, 0, "all");

    $display("SPEC_SUMMARY checks=%0d failures=%0d", checks, failures);
    $finish(0);
  end
endmodule
"""

PE_VARIANTS: dict[str, tuple[str, str, str]] = {
    "mut_pair_priority_flip": ("每一对内的优先级取反",
                               "assign stage_enc[0][n] = input_padded[n*2+1];",
                               "assign stage_enc[0][n] = input_padded[n*2+0];"),
    "mut_valid_ignores_low_bit": ("valid 只看奇数位（漏掉只设了偶数位的情况）",
                                  "assign stage_valid[0][n] = |input_padded[n*2+1:n*2];",
                                  "assign stage_valid[0][n] = input_padded[n*2+1];"),
    "mut_encoded_off_by_one": ("编码结果差一",
                               "assign output_encoded = stage_enc[LEVELS-1];",
                               "assign output_encoded = stage_enc[LEVELS-1] + 1'b1;"),
    "mut_unencoded_not_onehot": ("output_unencoded 变成全 1",
                                 "assign output_unencoded = 1 << output_encoded;",
                                 "assign output_unencoded = {WIDTH{output_valid}};"),
    "mut_valid_stuck_high": ("output_valid 恒为 1（空输入也说有效）",
                             "assign output_valid = stage_valid[LEVELS-1];",
                             "assign output_valid = 1'b1;"),
}

PE_EQUIVALENT = [
    # 等价改写：把"取某一级的 valid"换成"直接看输入是否非零"，语义相同（填充位恒为 0）。
    ("assign output_valid = stage_valid[LEVELS-1];",
     "assign output_valid = (input_padded != {W{1'b0}});"),
    # 等价改写：把独热写成显式拼接移位，值不变。
    ("assign output_unencoded = 1 << output_encoded;",
     "assign output_unencoded = {{(WIDTH-1){1'b0}}, 1'b1} << output_encoded;"),
]


#: 每个模块的基线路径。
BASELINES = {"uart_rx": UPSTREAM, "uart_tx": TX_UPSTREAM, "priority_encoder": PE_UPSTREAM}

#: 模块注册表：加一个外部模块就加一条。
MODULES: dict[str, dict] = {
    "uart_rx": {
        "baseline": UPSTREAM,
        "contract": CONTRACT,
        "plan": build_plan,
        "spec_tb": SPEC_TB,
        "variants": VARIANTS,
        "equivalent": EQUIVALENT,
        "description": "接收侧：一帧好帧 + 一帧停止位为 0",
    },
    "uart_tx": {
        "baseline": TX_UPSTREAM,
        "contract": TX_CONTRACT,
        "plan": build_tx_plan,
        "spec_tb": TX_SPEC_TB,
        "variants": TX_VARIANTS,
        "equivalent": TX_EQUIVALENT,
        "description": "发送侧：环回（tx → rx）验证整帧",
        # 环回测试台同时实例化 rx，所以编译规格测试台时要把它一起传进去。
        "spec_deps": (UPSTREAM,),
    },
    "priority_encoder": {
        "baseline": PE_UPSTREAM,
        "contract": PE_CONTRACT,
        "plan": build_pe_plan,
        "spec_tb": PE_SPEC_TB,
        "variants": PE_VARIANTS,
        "equivalent": PE_EQUIVALENT,
        "description": "参数化输入（纯组合、两个参数取值对照）；来源属**开发集**",
    },
}


def run_module(name: str, spec: dict, work: Path) -> list[dict]:
    """跑一个模块的全部输入：基线 / 等价改写 / 各变体 / 编不过的。"""

    contract = write(work / f"{name}_contract.json", json.dumps(spec["contract"], ensure_ascii=False, indent=2) + "\n")
    plan = write(work / f"{name}_plan.json", json.dumps(spec["plan"](), ensure_ascii=False, indent=2) + "\n")
    baseline = work / f"{name}_baseline.v"
    baseline.write_bytes(spec["baseline"].read_bytes())
    source = spec["baseline"].read_text(encoding="utf-8")

    cases: list[tuple[str, str, Path]] = [("baseline", "基线（上游原样）", baseline)]
    for variant, (description, old, new) in spec["variants"].items():
        assert old in source, f"{name} 变体 {variant} 的锚点没找到：{old[:60]}"
        write(work / f"{name}_{variant}.v", source.replace(old, new, 1))
        cases.append((variant, description, work / f"{name}_{variant}.v"))

    equivalent = source
    for old, new in spec["equivalent"]:
        assert old in equivalent, f"{name} 等价改写的锚点没找到：{old[:60]}"
        equivalent = equivalent.replace(old, new, 1)
    write(work / f"{name}_equivalent_rewrite.v", equivalent)
    cases.append(("equivalent_rewrite", "等价改写（语义不变，写法不同）", work / f"{name}_equivalent_rewrite.v"))

    write(work / f"{name}_broken_compile.v", BROKEN)
    cases.append(("broken_compile", "编不过的实现", work / f"{name}_broken_compile.v"))

    print(f"\n=== {name}（{spec['description']}）===")
    print(f"{'输入':26s} {'规格测试台':14s} {'verify-diff':12s} 说明")
    rows: list[dict] = []
    for tag, description, asset in cases:
        outcome = run_case_generic(asset, tag, spec["spec_tb"], name, contract, plan, spec.get("spec_deps", ()))
        if not outcome["compiled"]:
            spec_text = "编译失败"
        elif outcome["failed_checks"]:
            spec_text = f"{len(outcome['failed_checks'])} 项失败"
        else:
            spec_text = "全过"
        print(f"{tag:26s} {spec_text:14s} {outcome['diff_status'] or '（无状态）':12s} {description}")
        if outcome["compiled"] and outcome["failed_checks"]:
            print(f"{'':26s}   失败的检查：{', '.join(outcome['failed_checks'])}")
        rows.append({"module": name, "variant": tag, "description": description, "result": outcome})
    return rows


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for name, spec in MODULES.items():
        rows.extend(run_module(name, spec, WORK))
    write(
        WORK / "evidence.json",
        json.dumps({"byte_rx": BYTE, "byte_tx": TX_BYTE, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
    )
    print(f"\n证据：{WORK / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
