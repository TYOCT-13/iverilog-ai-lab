from pathlib import Path

import pytest

from iverilog_ai.core.config import ExecutionConfig, SafePathError
from iverilog_ai.core.executor import IcarusExecutor, parse_result_records
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.toolchain import locate_tools

# 工具位置统一由 core.toolchain 解析（显式 → 环境变量 → PATH → 常见目录），
# 因此同一套测试在本机与 Linux CI 上都能跑，而不是在 CI 里全部 skip。
_TOOLS = locate_tools()
IVERILOG = _TOOLS.iverilog
VVP = _TOOLS.vvp


def test_parse_result_records_is_strict():
    records, diagnostics = parse_result_records(
        'ordinary text\nIVERILOG_AI_RESULT {"ok":true,"test_id":"reset"}\n'
        'IVERILOG_AI_RESULT {"ok":false,"test_id":"wrap","cycle":11}\n'
        'IVERILOG_AI_RESULT {broken}\n'
    )
    assert [record.ok for record in records] == [True, False]
    assert len(diagnostics) == 1


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog（iverilog/vvp）")
def test_executor_runs_real_iverilog_and_vvp(tmp_path):
    rtl = tmp_path / "dut.v"
    tb = tmp_path / "tb_dut.v"
    rtl.write_text(
        "module dut(input wire clk, output reg q); "
        "always @(posedge clk) q <= ~q; endmodule\n",
        encoding="utf-8",
    )
    tb.write_text(
        "module tb_dut; reg clk=0; wire q; dut u(.clk(clk),.q(q)); "
        "always #1 clk=~clk; initial begin #0; "
        '$display("IVERILOG_AI_RESULT {\\\"ok\\\":true,\\\"test_id\\\":\\\"toggle\\\",\\\"cycle\\\":1}"); '
        "#4 $finish; end endmodule\n",
        encoding="utf-8",
    )
    config = ExecutionConfig(
        rtl_path=rtl,
        testbench_path=tb,
        top_module="tb_dut",
        output_dir=tmp_path / "runs",
        allowed_roots=(tmp_path,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
        timeout_seconds=5,
    )
    result = IcarusExecutor(config).run()
    assert result.status is ResultStatus.PASSED
    assert result.compile.returncode == 0
    assert result.run is not None and result.run.returncode == 0
    assert result.artifacts["result_json"]


def test_defines_and_include_dirs_reach_the_compiler(tmp_path):
    """宏定义与 include 目录必须真的出现在 iverilog 命令行上。

    网页新增了这两个输入框，CLI 也一直有 `--define/--include-dir`；它们很容易"看起来
    接上了、实际没传下去"。这里直接断言编译命令，而不是只看仿真是否通过——因为即使
    不传宏，只要 RTL 用了默认值，仿真照样会通过。
    """

    rtl = tmp_path / "dut.v"
    tb = tmp_path / "tb_dut.v"
    include_dir = tmp_path / "inc"
    include_dir.mkdir()
    rtl.write_text(
        "`ifdef USE_WIDE\n"
        "module dut(input wire clk, output reg [7:0] q); always @(posedge clk) q <= 8'h5a; endmodule\n"
        "`else\n"
        "module dut(input wire clk, output reg q); always @(posedge clk) q <= ~q; endmodule\n"
        "`endif\n",
        encoding="utf-8",
    )
    tb.write_text(
        "module tb_dut; reg clk=0; wire q; dut u(.clk(clk),.q(q)); "
        "always #1 clk=~clk; initial begin #0; "
        '$display("IVERILOG_AI_RESULT {\\\"ok\\\":true,\\\"test_id\\\":\\\"compile_flags\\\",\\\"cycle\\\":1}"); '
        "#4 $finish; end endmodule\n",
        encoding="utf-8",
    )
    config = ExecutionConfig(
        rtl_path=rtl,
        testbench_path=tb,
        top_module="tb_dut",
        output_dir=tmp_path / "runs",
        allowed_roots=(tmp_path,),
        defines=("USE_WIDE", "WIDTH=8"),
        include_dirs=(str(include_dir),),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
        timeout_seconds=5,
    )
    result = IcarusExecutor(config).run()
    command = list(result.compile.command)
    assert "-DUSE_WIDE" in command, command
    assert "-DWIDTH=8" in command, command
    assert "-I" in command and str(include_dir) in command, command
    assert result.status is ResultStatus.PASSED


def test_executor_rejects_source_outside_allowed_root(tmp_path):
    outside = tmp_path.parent / "outside_dut.v"
    outside.write_text("module dut; endmodule\n", encoding="utf-8")
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; initial $finish; endmodule\n", encoding="utf-8")
    config = ExecutionConfig(
        rtl_path=outside,
        testbench_path=tb,
        top_module="tb",
        output_dir=tmp_path / "runs",
        allowed_roots=(tmp_path,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    with pytest.raises(SafePathError):
        config.resolve()


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog（iverilog/vvp）")
def test_executor_persists_compile_failure_evidence(tmp_path):
    rtl = tmp_path / "broken.v"
    tb = tmp_path / "tb_broken.v"
    rtl.write_text("module broken(input wire clk; endmodule\n", encoding="utf-8")
    tb.write_text("module tb_broken; initial $finish; endmodule\n", encoding="utf-8")
    config = ExecutionConfig(
        rtl_path=rtl,
        testbench_path=tb,
        top_module="tb_broken",
        output_dir=tmp_path / "runs",
        allowed_roots=(tmp_path,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
        timeout_seconds=5,
    )
    result = IcarusExecutor(config).run()
    assert result.status is ResultStatus.COMPILE_FAILED
    assert result.run is None
    result_json = Path(result.artifacts["result_json"])
    assert result_json.is_file()
    assert "compile.stderr" in result.artifacts["compile_stderr"]
