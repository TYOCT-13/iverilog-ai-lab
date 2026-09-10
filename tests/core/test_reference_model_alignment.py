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

# 设计 → (RTL, 观测端口表达式)
ALIGNED_CASES: dict[str, dict[str, object]] = {
    "sync_fifo": {
        "rtl": "rtl/sync_fifo.v",
        "top": "sync_fifo",
        "instance": "sync_fifo #(.DATA_WIDTH(8), .DEPTH(4)) dut(.clk(clk),.rst_n(rst_n),"
                    ".wr_en(wr_en),.wr_data(wr_data),.rd_en(rd_en),.rd_data(rd_data),"
                    ".full(full),.empty(empty));",
        "inputs": {"wr_en": "reg", "rd_en": "reg", "wr_data": "reg [7:0]"},
        "outputs": {"rd_data": "%h", "full": "%b", "empty": "%b"},
        "declarations": ["wire [7:0] rd_data; wire full, empty;"],
        "observed": ("rd_data", "empty", "full"),
    },
}


def _iverilog_available() -> bool:
    return Path(IVERILOG).is_file() and Path(VVP).is_file()


def _rtl_trace(case: str, vectors: list[dict], rtl: Path, tmp_path: Path) -> list[dict]:
    spec = ALIGNED_CASES[case]
    fmt = " ".join(f"{name}={code}" for name, code in spec["outputs"].items())  # type: ignore[union-attr]
    args = " ".join(f"{name}=" for name in spec["outputs"])  # type: ignore[union-attr]
    lines = [
        "`timescale 1ns/1ps",
        f"module tb_align_{case};",
        "  reg clk=0, rst_n=0;",
        *[f"  {kind} {name}=0;" for name, kind in spec["inputs"].items()],  # type: ignore[union-attr]
        *[f"  {decl}" for decl in spec["declarations"]],  # type: ignore[union-attr]
        f"  {spec['instance']}",
        "  always #5 clk = ~clk;",
        "  initial begin",
        "    rst_n = 1; #2; rst_n = 0; @(posedge clk); #1; rst_n = 1;",
    ]
    for vector in vectors:
        for _ in range(int(vector.get("cycles", 1))):
            for signal, value in vector["inputs"].items():
                lines.append(f"    {signal} = {int(value)};")
            lines.append("    @(posedge clk); #1;")
            lines.append(f'    $display("ROW {fmt}", {", ".join(spec["outputs"].keys())});')  # type: ignore[union-attr]
    lines += ["    $finish(0);", "  end", "endmodule", ""]

    tb = tmp_path / f"tb_align_{case}.v"
    tb.write_text("\n".join(lines), encoding="utf-8")
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
        for name in spec["outputs"]:  # type: ignore[union-attr]
            token = line.split(f"{name}=")[1].split()[0]
            row[name] = int(token, 16) if name == "rd_data" else int(token)
        rows.append(row)
    return rows


def _model_trace(case: str, vectors: list[dict], contract: dict) -> list[dict]:
    state = _DesignState(case, contract)
    rows = []
    for vector in vectors:
        for _ in range(int(vector.get("cycles", 1))):
            rows.append(state.step(vector["inputs"], 1))
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
            rtl_rows = _rtl_trace(case, vectors, rtl, tmp_path)
            model_rows = _model_trace(case, vectors, contract)
            assert len(rtl_rows) == len(model_rows), f"{case} 行数不一致"

            for index, (model, actual) in enumerate(zip(model_rows, rtl_rows)):
                for signal in observed:
                    assert model[signal] == actual[signal], (
                        f"{case} seed={seed} 第 {index} 拍 {signal} 不一致："
                        f"model={model[signal]} rtl={actual[signal]}；"
                        "参考模型与 RTL 未对齐时不得加入 AUTHORITATIVE"
                    )


def test_authoritative_designs_are_supported():
    """权威集合必须是已建模设计的子集，避免出现拼写错误的设计名。"""

    from iverilog_ai.core.reference_model import SUPPORTED

    assert AUTHORITATIVE <= SUPPORTED
