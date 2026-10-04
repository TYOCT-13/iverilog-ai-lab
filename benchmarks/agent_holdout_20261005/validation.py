"""本地 Icarus 逐拍检验工具；仅审查资产，不向 Agent 发送任何输入。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, TypedDict


class CasePorts(TypedDict):
    """固定接口信息，防止检查器把位宽和端口表混为任意对象。"""
    inputs: dict[str, int]
    output: str
    width: int
    reset: int


CASE_PORTS: dict[str, CasePorts] = {
    "credit_guard": {"inputs": {"acquire": 1, "release_req": 1}, "output": "credits", "width": 3, "reset": 3},
    "rotating_arbiter": {"inputs": {"request": 4, "advance": 1}, "output": "grant", "width": 4, "reset": 0},
}


def find_tool(name: str) -> str | None:
    """先使用项目指定工具，再尝试 PATH；不下载或安装。"""
    prescribed = Path("D:/iverilog/bin") / f"{name}.exe"
    return str(prescribed) if prescribed.is_file() else shutil.which(name)


def testbench_text(case: str, steps: Sequence[Mapping[str, int]]) -> str:
    """构建只输出观测值的测试台，不把独立预期值嵌入 DUT 检验过程。"""
    ports = CASE_PORTS[case]
    declarations = ["reg clk = 1'b0;", "reg rst_n = 1'b1;"]
    for name, width in ports["inputs"].items():
        declarations.append(f"reg [{width - 1}:0] {name} = 0;")
    declarations.append(f"wire [{ports['width'] - 1}:0] {ports['output']};")
    names = ["clk", "rst_n", *ports["inputs"], ports["output"]]
    connections = ", ".join(f".{name}({name})" for name in names)
    lines = [
        "`timescale 1ns / 1ps", f"module tb_{case};", *declarations,
        f"{case} dut({connections});", "always #5 clk = ~clk;", "initial begin",
        "  #1 rst_n = 1'b0;", f'  #1 $display("HOLDOUT RESET %0d", {ports["output"]});',
        "  repeat (2) @(posedge clk);", "  @(negedge clk);", "  rst_n = 1'b1;",
    ]
    for index, step in enumerate(steps):
        if index:
            lines.append("  @(negedge clk);")
        for name, width in {"rst_n": 1, **ports["inputs"]}.items():
            value = step.get(name, 1 if name == "rst_n" else 0)
            if type(value) is not int or not 0 <= value < (1 << width):
                raise ValueError("invalid_known_width_input")
            lines.append(f"  {name} = {width}'d{value};")
        if step.get("rst_n", 1) == 0:
            lines.append(f'  #1 $display("HOLDOUT ASYNC {index} %0d", {ports["output"]});')
        lines.extend(["  @(posedge clk);", f'  #1 $display("HOLDOUT OBS {index} %0d", {ports["output"]});'])
    lines.extend(["  $finish;", "end", "endmodule", ""])
    return "\n".join(lines)


def observe(case: str, rtl: Path, steps: Sequence[Mapping[str, int]], directory: Path) -> dict[str, Any]:
    """编译并执行真实 RTL，保存命令和原始输出，失败也先保存再报错。"""
    iverilog, vvp = find_tool("iverilog"), find_tool("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("icarus_unavailable")
    directory.mkdir(parents=True, exist_ok=False)
    testbench = directory / f"tb_{case}.v"
    binary = directory / "simulation.vvp"
    testbench.write_text(testbench_text(case, steps), encoding="utf-8")
    compile_command = [iverilog, "-g2001", "-Wall", "-s", f"tb_{case}", "-o", str(binary), str(rtl), str(testbench)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True, timeout=30, check=False)
    record: dict[str, Any] = {
        "case": case, "rtl": str(rtl), "inputs": [dict(step) for step in steps],
        "api_calls": 0, "network_used": False,
        "compile": {"command": compile_command, "returncode": compiled.returncode, "stdout": compiled.stdout, "stderr": compiled.stderr},
    }
    if compiled.returncode == 0:
        run_command = [vvp, str(binary)]
        executed = subprocess.run(run_command, capture_output=True, text=True, timeout=30, check=False)
        record["execution"] = {"command": run_command, "returncode": executed.returncode, "stdout": executed.stdout, "stderr": executed.stderr}
        observations, asynchronous = [], []
        for line in executed.stdout.splitlines():
            tokens = line.split()
            if tokens[:2] == ["HOLDOUT", "OBS"]:
                observations.append({"index": int(tokens[2]), "value": int(tokens[3])})
            elif tokens[:2] == ["HOLDOUT", "RESET"]:
                record["reset_value"] = int(tokens[2])
            elif tokens[:2] == ["HOLDOUT", "ASYNC"]:
                asynchronous.append({"index": int(tokens[2]), "value": int(tokens[3])})
        record["observations"], record["asynchronous_resets"] = observations, asynchronous
    (directory / "observation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if compiled.returncode != 0:
        raise AssertionError("icarus_compile_failed")
    if record["execution"]["returncode"] != 0:
        raise AssertionError("icarus_execution_failed")
    if len(record["observations"]) != len(steps):
        raise AssertionError("incomplete_cycle_observation")
    return record
