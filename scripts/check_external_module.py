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


def run_verify_diff(candidate: Path, contract: Path, plan: Path, tag: str) -> dict:
    """走项目自己的 verify-diff 路径（基线与候选用同一份合约与同一份计划）。"""

    out = WORK / f"diff_{tag}"
    done = subprocess.run(
        [PYTHON, "-m", "iverilog_ai", "verify-diff",
         "--baseline", str(UPSTREAM), "--candidate", str(candidate),
         "--contract", str(contract), "--plan", str(plan),
         "--module", "uart_rx", "--output-dir", str(out),
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


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    contract = write(WORK / "uart_rx_contract.json", json.dumps(CONTRACT, ensure_ascii=False, indent=2) + "\n")
    plan = write(WORK / "uart_rx_plan.json", json.dumps(build_plan(), ensure_ascii=False, indent=2) + "\n")
    baseline = WORK / "uart_rx_baseline.v"
    baseline.write_bytes(UPSTREAM.read_bytes())

    source = UPSTREAM.read_text(encoding="utf-8")
    cases: list[tuple[str, str, Path]] = [("baseline", "基线（上游原样）", baseline)]

    for name, (description, old, new) in VARIANTS.items():
        assert old in source, f"变体 {name} 的锚点没找到：{old}"
        write(WORK / f"{name}.v", source.replace(old, new, 1))
        cases.append((name, description, WORK / f"{name}.v"))

    equivalent = source
    for old, new in EQUIVALENT:
        assert old in equivalent, f"等价改写的锚点没找到：{old[:40]}"
        equivalent = equivalent.replace(old, new, 1)
    write(WORK / "equivalent_rewrite.v", equivalent)
    cases.append(("equivalent_rewrite", "等价改写（语义不变，写法不同）", WORK / "equivalent_rewrite.v"))

    write(WORK / "broken_compile.v", BROKEN)
    cases.append(("broken_compile", "编不过的实现", WORK / "broken_compile.v"))

    # 每个变体都要有各自的规格测试台文件（同一个 TB 文本，模块名不同会冲突，故一次性写多份）
    spec_source = SPEC_TB
    for tag, _description, _path in cases:
        write(WORK / f"tb_spec_{tag}.v", spec_source)

    print(f"{'输入':26s} {'规格测试台':12s} {'verify-diff':10s} 说明")
    rows = []
    for tag, description, path in cases:
        spec = run_spec_tb(path, tag)
        diff = run_verify_diff(path, contract, plan, tag)
        if not spec["compiled"]:
            spec_text = "编译失败"
        elif spec["failed_checks"]:
            spec_text = f"{len(spec['failed_checks'])} 项失败"
        else:
            spec_text = "全过"
        print(f"{tag:26s} {spec_text:12s} {diff['status'] or '（无状态）':10s} {description}")
        if spec["compiled"] and spec["failed_checks"]:
            print(f"{'':26s}   失败的检查：{', '.join(spec['failed_checks'])}")
        rows.append({"variant": tag, "description": description, "spec": spec, "diff": diff})

    write(WORK / "evidence.json", json.dumps({"contract": CONTRACT, "byte": BYTE, "rows": rows}, ensure_ascii=False, indent=2) + "\n")
    print(f"\n证据：{WORK / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
