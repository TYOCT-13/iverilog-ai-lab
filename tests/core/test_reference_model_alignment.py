"""参考模型与 RTL 的逐拍对齐测试。

为什么需要这个测试：``reference_expectations`` 会把参考模型的复算值当作**权威
期望值**。如果模型时序与 RTL 有一拍之差，预言机就会把"参考设计通过"改写成
"参考设计失败"——比没有预言机更糟。

因此规则是：**对齐一个、加入一个**。本测试把同一组向量同时喂给参考模型和 RTL，
逐拍比较可观测输出，要求零差异。只有通过这里的设计才允许进入
``reference_model.AUTHORITATIVE``。

测试完全离线（Icarus + 本地调试激励生成器），不需要网络或密钥。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from iverilog_ai.ai.debug_server import build_plan_response
from iverilog_ai.core.reference_model import AUTHORITATIVE, _DesignState

ROOT = Path(__file__).parents[2]
IVERILOG = r"D:\iverilog\bin\iverilog.exe"
VVP = r"D:\iverilog\bin\vvp.exe"

# 用例字段说明：
#   rtl/top/instance  参考 RTL、顶层模块名、实例化语句（端口按模块声明顺序连接）
#   inputs            激励信号声明（含位宽），键名必须与向量里的输入名一致
#   outputs           输出端口 → $display 格式码；解析按 16 进制统一处理
#   declarations      额外声明（wire 等）
#   observed          参与逐拍比较的输出（必须是 outputs 的子集）
#   combinational     True 表示无时钟的组合逻辑，用 assign 驱动、不写 always
ALIGNED_CASES: dict[str, dict[str, object]] = {
    "mod10_counter": {
        "rtl": "rtl/mod10_counter.v",
        "top": "mod10_counter",
        "instance": "mod10_counter dut(.clk(clk),.rst_n(rst_n),.enable(enable),.count(count));",
        "inputs": {"rst_n": "reg", "enable": "reg"},
        "outputs": {"count": "h"},
        "declarations": ["wire [3:0] count;"],
        "observed": ("count",),
    },
    "simple_alu": {
        "rtl": "rtl/simple_alu.v",
        "top": "simple_alu",
        "instance": "simple_alu dut(.a(a),.b(b),.op(op),.result(result),.carry(carry),.zero(zero));",
        "inputs": {"a": "reg [7:0]", "b": "reg [7:0]", "op": "reg [2:0]"},
        "outputs": {"result": "h", "carry": "b", "zero": "b"},
        "declarations": ["wire [7:0] result; wire carry; wire zero;"],
        "observed": ("result", "carry", "zero"),
        "combinational": True,
    },
    "sequence_101_overlap": {
        "rtl": "rtl/sequence_101_overlap.v",
        "top": "sequence_101_overlap",
        "instance": "sequence_101_overlap dut(.clk(clk),.rst_n(rst_n),.bit_in(bit_in),.detected(detected));",
        "inputs": {"rst_n": "reg", "bit_in": "reg"},
        "outputs": {"detected": "b"},
        "declarations": ["wire detected;"],
        "observed": ("detected",),
    },
    "traffic_light_emergency": {
        "rtl": "rtl/traffic_light_emergency.v",
        "top": "traffic_light_emergency",
        "instance": "traffic_light_emergency dut(.clk(clk),.rst_n(rst_n),.emergency(emergency),"
                    ".main_light(main_light),.side_light(side_light));",
        "inputs": {"rst_n": "reg", "emergency": "reg"},
        "outputs": {"main_light": "h", "side_light": "h"},
        "declarations": ["wire [1:0] main_light; wire [1:0] side_light;"],
        "observed": ("main_light", "side_light"),
    },
    "sync_fifo": {
        "rtl": "rtl/sync_fifo.v",
        "top": "sync_fifo",
        "instance": "sync_fifo #(.DATA_WIDTH(8), .DEPTH(4)) dut(.clk(clk),.rst_n(rst_n),"
                    ".wr_en(wr_en),.wr_data(wr_data),.rd_en(rd_en),.rd_data(rd_data),"
                    ".full(full),.empty(empty));",
        "inputs": {"rst_n": "reg", "wr_en": "reg", "rd_en": "reg", "wr_data": "reg [7:0]"},
        "outputs": {"rd_data": "h", "full": "b", "empty": "b"},
        "declarations": ["wire [7:0] rd_data; wire full, empty;"],
        "observed": ("rd_data", "empty", "full"),
    },
    "uart_tx": {
        "rtl": "rtl/uart_tx.v",
        "top": "uart_tx",
        "instance": "uart_tx #(.CLKS_PER_BIT(4)) dut(.clk(clk),.rst_n(rst_n),.start(start),"
                    ".data_in(data_in),.tx(tx),.busy(busy));",
        "inputs": {"rst_n": "reg", "start": "reg", "data_in": "reg [7:0]"},
        "outputs": {"tx": "b", "busy": "b"},
        "declarations": ["wire tx; wire busy;"],
        "observed": ("tx", "busy"),
    },
    "spi_master": {
        "rtl": "rtl/spi_master.v",
        "top": "spi_master",
        "instance": "spi_master #(.WIDTH(8)) dut(.clk(clk),.rst_n(rst_n),.start(start),"
                    ".data_in(data_in),.sclk(sclk),.mosi(mosi),.busy(busy),.done(done));",
        "inputs": {"rst_n": "reg", "start": "reg", "data_in": "reg [7:0]"},
        "outputs": {"sclk": "b", "mosi": "b", "busy": "b", "done": "b"},
        "declarations": ["wire sclk; wire mosi; wire busy; wire done;"],
        "observed": ("sclk", "mosi", "busy", "done"),
    },
    "handshake_stage": {
        "rtl": "rtl/handshake_stage.v",
        "top": "handshake_stage",
        "instance": "handshake_stage #(.WIDTH(8)) dut(.clk(clk),.rst_n(rst_n),.in_valid(in_valid),"
                    ".in_ready(in_ready),.in_data(in_data),.out_valid(out_valid),"
                    ".out_ready(out_ready),.out_data(out_data));",
        "inputs": {"rst_n": "reg", "in_valid": "reg", "in_data": "reg [7:0]", "out_ready": "reg"},
        "outputs": {"in_ready": "b", "out_valid": "b", "out_data": "h"},
        "declarations": ["wire in_ready; wire out_valid; wire [7:0] out_data;"],
        "observed": ("in_ready", "out_valid", "out_data"),
    },
    "debounce": {
        "rtl": "rtl/debounce.v",
        "top": "debounce",
        "instance": "debounce #(.COUNT_MAX(3)) dut(.clk(clk),.rst_n(rst_n),.key_in(key_in),"
                    ".key_state(key_state));",
        "inputs": {"rst_n": "reg", "key_in": "reg"},
        "outputs": {"key_state": "b"},
        "declarations": ["wire key_state;"],
        "observed": ("key_state",),
    },
    "pwm": {
        "rtl": "rtl/pwm.v",
        "top": "pwm",
        "instance": "pwm #(.WIDTH(8)) dut(.clk(clk),.rst_n(rst_n),.duty(duty),.pwm_out(pwm_out));",
        "inputs": {"rst_n": "reg", "duty": "reg [7:0]"},
        "outputs": {"pwm_out": "b"},
        "declarations": ["wire pwm_out;"],
        "observed": ("pwm_out",),
    },
    "sync_reset": {
        "rtl": "rtl/sync_reset.v",
        "top": "sync_reset",
        "instance": "sync_reset dut(.clk(clk),.ext_rst_n(ext_rst_n),.rst_n(rst_n));",
        "inputs": {"ext_rst_n": "reg"},
        "outputs": {"rst_n": "b"},
        "declarations": ["wire rst_n;"],
        "observed": ("rst_n",),
    },
    "mux4": {
        "rtl": "rtl/mux4.v",
        "top": "mux4",
        "instance": "mux4 #(.WIDTH(8)) dut(.d0(d0),.d1(d1),.d2(d2),.d3(d3),.sel(sel),.y(y));",
        "inputs": {"d0": "reg [7:0]", "d1": "reg [7:0]", "d2": "reg [7:0]", "d3": "reg [7:0]", "sel": "reg [1:0]"},
        "outputs": {"y": "h"},
        "declarations": ["wire [7:0] y;"],
        "observed": ("y",),
        "combinational": True,
    },
}


def _iverilog_available() -> bool:
    return Path(IVERILOG).is_file() and Path(VVP).is_file()


def _warmup_vectors(case: str, contract: dict) -> list[dict]:
    """复位向量：把复位端口拉到有效电平并保持 contract 声明的周期数。

    复位也由激励驱动（而不是测试台隐式序列），这样模型与 RTL 看到的复位历史
    完全一致，对齐比较才有意义。
    """

    reset = contract.get("reset")
    if not reset:
        return []
    signal = str(reset.get("signal", ""))
    active = int(reset.get("active_level", 0))
    cycles = max(1, int(reset.get("assert_cycles", 1)))
    if signal not in ALIGNED_CASES[case]["inputs"]:  # type: ignore[operator]
        return []
    return [{"name": "align_reset", "inputs": {signal: active}, "cycles": cycles}]


def _build_testbench(case: str, vectors: list[dict], warmup: list[dict]) -> str:
    spec = ALIGNED_CASES[case]
    outputs: dict[str, str] = spec["outputs"]  # type: ignore[assignment]
    inputs: dict[str, str] = spec["inputs"]  # type: ignore[assignment]
    # 统一用 16 进制打印再解析：位宽不同也能安全比较（8 位以上不会溢出）
    fmt = " ".join(f"{name}=%{code}" for name, code in outputs.items())
    combinational = bool(spec.get("combinational"))
    # 复位端口也由激励驱动，初值为复位有效电平：这样模型与 RTL 看到的复位
    # 历史完全一致（对照 contract 隐式复位序列更容易对齐，也不会出现
    # `negedge rst_n` 与 `posedge clk` 同刻的竞争）。
    initial_values = {name: 0 for name in inputs}

    lines = [
        "`timescale 1ns/1ps",
        f"module tb_align_{case};",
    ]
    if not combinational:
        lines.append("  reg clk=0;")
    lines.extend(
        f"  {kind} {name}={int(initial_values.get(name, 0))};" for name, kind in inputs.items()
    )
    lines.extend(f"  {decl}" for decl in spec["declarations"])  # type: ignore[union-attr]
    lines.append(f"  {spec['instance']}")
    if not combinational:
        lines.append("  always #5 clk = ~clk;")
    lines.append("  initial begin")

    for vector in warmup + vectors:
        for _ in range(int(vector.get("cycles", 1))):
            if combinational:
                for signal, value in vector["inputs"].items():
                    if signal in inputs:
                        lines.append(f"    {signal} = {int(value)};")
                lines.append("    #1;")
            else:
                # 与生成式 testbench（core/testbench.py）完全一致的顺序：
                # 先在时钟低电平期间施加激励，再等时钟沿，最后在沿之后采样。
                # 这一顺序决定了"第 N 拍采样值由第 N 拍激励决定"，模型的
                # 采样语义必须与之对齐。
                for signal, value in vector["inputs"].items():
                    if signal in inputs:
                        lines.append(f"    {signal} = {int(value)};")
                lines.append("    @(posedge clk); #1;")
            lines.append(f'    $display("ROW {fmt}", {", ".join(outputs.keys())});')
    lines += ["    $finish(0);", "  end", "endmodule", ""]
    return "\n".join(lines)


def _rtl_trace(case: str, vectors: list[dict], warmup: list[dict], rtl: Path, tmp_path: Path) -> list[dict]:
    spec = ALIGNED_CASES[case]
    outputs: dict[str, str] = spec["outputs"]  # type: ignore[assignment]
    tb = tmp_path / f"tb_align_{case}.v"
    tb.write_text(_build_testbench(case, vectors, warmup), encoding="utf-8")
    vvp = tmp_path / f"align_{case}.vvp"
    built = subprocess.run(
        [IVERILOG, "-g2012", "-o", str(vvp), str(tb), str(rtl)],
        capture_output=True, text=True, timeout=120,
    )
    assert built.returncode == 0, built.stderr[:400]
    run = subprocess.run([VVP, str(vvp)], capture_output=True, text=True, timeout=180)

    rows = []
    for line in run.stdout.splitlines():
        if not line.startswith("ROW "):
            continue
        row = {}
        for name in outputs:
            token = line.split(f"{name}=")[1].split()[0]
            row[name] = int(token, 16)
        rows.append(row)
    return rows


def _model_trace(case: str, vectors: list[dict], warmup: list[dict], contract: dict) -> list[dict]:
    """按生成式 testbench 的采样语义推进模型。

    生成式 testbench 的顺序是"施加本拍激励 → 等时钟沿 → 沿后采样"，因此第 N 拍
    的采样值里**已经包含**第 N 拍激励的寄存器效果。``_DesignState.step(inputs)``
    返回的正是"施加 inputs 之后"的寄存器值，逐拍调用即可对齐。

    末尾 `$finish` 会让生成式 testbench 少采最后一拍，因此丢弃模型多出的一拍。
    """

    state = _DesignState(case, contract)
    rows: list[dict] = []
    for vector in warmup + vectors:
        for _ in range(int(vector.get("cycles", 1))):
            rows.append(dict(state.step(vector["inputs"], 1)))
    rows.pop()
    return rows


@pytest.mark.skipif(not _iverilog_available(), reason="Icarus Verilog 未安装在预期路径")
def test_aligned_models_match_rtl_cycle_by_cycle(tmp_path):
    """每个已对齐的设计必须在多个随机 seed 上与 RTL 逐拍零差异。"""

    for case, spec in ALIGNED_CASES.items():
        assert case in AUTHORITATIVE, f"{case} 已对齐但未加入 AUTHORITATIVE"
        contract = json.loads((ROOT / f"examples/{case}_contract.json").read_text(encoding="utf-8"))
        prompt = "Design: %s DUT context: %s Schema: {}" % (case, json.dumps(contract, ensure_ascii=False))
        rtl = ROOT / str(spec["rtl"])
        observed = list(spec["observed"])  # type: ignore[arg-type]

        for seed in (0, 1, 2, 3):
            vectors = build_plan_response(prompt, vector_count=12, seed=seed)["vectors"]
            warmup = _warmup_vectors(case, contract)
            rtl_rows = _rtl_trace(case, vectors, warmup, rtl, tmp_path)
            model_rows = _model_trace(case, vectors, warmup, contract)
            # 生成式 testbench 在最后一个向量之后 `$finish`，末尾那个时钟沿只在
            # 对齐测试台里留下采样；因此 RTL 序列可能比模型多一拍尾部，比较范围
            # 取两者较短的长度。
            assert abs(len(rtl_rows) - len(model_rows)) <= 1, (
                f"{case} 行数差异超过边界一拍：rtl={len(rtl_rows)} model={len(model_rows)}"
            )
            compare = min(len(rtl_rows), len(model_rows))

            for index in range(compare):
                model, actual = model_rows[index], rtl_rows[index]
                if case == "uart_tx" and seed == 0:
                    import sys as _sys
                    print(f"DBG {index:>3} model={model} rtl={actual}", file=_sys.stderr)
                for signal in observed:
                    assert signal in model, (
                        f"{case} seed={seed} 第 {index} 拍参考模型没有产出可观测输出 {signal}；"
                        "模型只覆盖部分输出时不得加入 AUTHORITATIVE"
                    )
                    assert model[signal] == actual[signal], (
                        f"{case} seed={seed} 第 {index} 拍 {signal} 不一致："
                        f"model={model[signal]} rtl={actual[signal]}；"
                        "参考模型与 RTL 未对齐时不得加入 AUTHORITATIVE"
                    )


def test_authoritative_designs_are_supported():
    """权威集合必须是已建模设计的子集，避免出现拼写错误的设计名。"""

    from iverilog_ai.core.reference_model import SUPPORTED

    assert AUTHORITATIVE <= SUPPORTED


def test_alignment_cases_cover_authoritative_set():
    """对齐用例表与权威集合必须一致，防止"加入 AUTHORITATIVE 却忘了对齐"。"""

    assert set(ALIGNED_CASES) == set(AUTHORITATIVE)
