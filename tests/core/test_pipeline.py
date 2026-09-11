from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.models import FailureRecord, ResultStatus
from iverilog_ai.core.pipeline import (
    PipelineValidationError,
    VerificationPipeline,
    explain_failure,
)
from iverilog_ai.core.testbench import TestbenchGenerator as Generator
from iverilog_ai.core.toolchain import locate_tools

# 工具位置统一由 core.toolchain 解析，保证同一套测试在本机与 Linux CI 上都能跑。
_TOOLS = locate_tools()
IVERILOG = _TOOLS.iverilog
VVP = _TOOLS.vvp


def _plan(expected=1):
    return Plan.model_validate(
        {
            "design": "and_gate",
            "objective": "verify output",
            "vectors": [{"name": "one", "inputs": {"a": 1, "b": 1}, "expected": {"y": expected}}],
        }
    )


def _contract():
    return DutContract.from_dict(
        {
            "module": "and_gate",
            "ports": [
                {"name": "a", "direction": "input"},
                {"name": "b", "direction": "input"},
                {"name": "y", "direction": "output"},
            ],
        }
    )


def _rtl(root: Path) -> Path:
    path = root / "and_gate.v"
    path.write_text(
        "module and_gate(input wire a, input wire b, output wire y); assign y = a & b; endmodule\n",
        encoding="ascii",
    )
    return path


def test_clocked_vectors_generate_wait_edge_sequence(tmp_path):
    rtl = tmp_path / "counter.v"
    rtl.write_text(
        "module counter(input wire clk, input wire rst_n, input wire en, output reg [3:0] q);"
        " always @(posedge clk) begin if (!rst_n) q <= 4'b0; else if (en) q <= q + 1'b1; end"
        " endmodule\n",
        encoding="ascii",
    )
    plan = Plan.model_validate(
        {
            "design": "counter",
            "objective": "verify sequential increments",
            "vectors": [
                {"name": "step1", "inputs": {"rst_n": 1, "en": 1}, "expected": {"q": 1}},
                {"name": "step2", "inputs": {"en": 1}, "expected": {"q": 2}},
                {"name": "step3", "inputs": {"en": 1}, "expected": {"q": 3}},
            ],
        }
    )
    contract = DutContract.from_dict(
        {
            "module": "counter",
            "ports": [
                {"name": "clk", "direction": "input"},
                {"name": "rst_n", "direction": "input"},
                {"name": "en", "direction": "input"},
                {"name": "q", "direction": "output", "width": 4},
            ],
            "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
            "reset": {"signal": "rst_n", "active_level": 0, "assert_cycles": 2},
        }
    )
    generated = Generator().generate(plan, contract, tmp_path / "generated")
    source = generated.read_text(encoding="utf-8")
    assert "@( posedge clk );" in source
    assert "always #5" in source


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog（iverilog/vvp）")
def test_pipeline_runs_real_iverilog_and_persists_explicit_artifacts(tmp_path):
    result = VerificationPipeline().run(
        _plan(),
        _contract(),
        _rtl(tmp_path),
        tmp_path / "artifacts",
        allowed_roots=(tmp_path,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    assert result.status is ResultStatus.PASSED
    assert result.testbench_path.is_file()
    assert Path(result.artifacts["result_json"]).is_file()
    assert Path(result.artifacts["pipeline_result"]).is_file()
    assert result.simulation.records[0].ok is True


@pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog（iverilog/vvp）")
def test_pipeline_runs_real_clocked_vectors(tmp_path):
    rtl = tmp_path / "counter.v"
    rtl.write_text(
        "module counter(input wire clk, input wire rst_n, input wire en, output reg [3:0] q);"
        " always @(posedge clk) begin if (!rst_n) q <= 4'b0; else if (en) q <= q + 1'b1; end"
        " endmodule\n",
        encoding="ascii",
    )
    plan = Plan.model_validate(
        {
            "design": "counter",
            "objective": "verify sequential increments",
            "vectors": [
                {"name": "step1", "inputs": {"rst_n": 1, "en": 1}, "expected": {"q": 1}},
                {"name": "step2", "inputs": {"en": 1}, "expected": {"q": 2}},
                {"name": "step3", "inputs": {"en": 1}, "expected": {"q": 3}},
            ],
        }
    )
    contract = DutContract.from_dict(
        {
            "module": "counter",
            "ports": [
                {"name": "clk", "direction": "input"},
                {"name": "rst_n", "direction": "input"},
                {"name": "en", "direction": "input"},
                {"name": "q", "direction": "output", "width": 4},
            ],
            "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
            "reset": {"signal": "rst_n", "active_level": 0, "assert_cycles": 2},
        }
    )
    result = VerificationPipeline().run(
        plan,
        contract,
        rtl,
        tmp_path / "artifacts",
        allowed_roots=(tmp_path,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    assert result.status is ResultStatus.PASSED
    assert [record.actual for record in result.records] == ["0001", "0010", "0011"]


def test_pipeline_rejects_out_of_scope_output_before_creation(tmp_path):
    rtl = _rtl(tmp_path)
    outside = tmp_path.parent / "iverilog_ai_pipeline_outside_should_not_exist"
    if outside.exists():
        pytest.skip("stale manual path exists")
    with pytest.raises(PipelineValidationError):
        VerificationPipeline().run(
            _plan(),
            _contract(),
            rtl,
            outside,
            allowed_roots=(tmp_path,),
            iverilog_path=IVERILOG,
            vvp_path=VVP,
        )
    assert not outside.exists()


def test_failure_explanation_is_chinese_and_reproducible():
    failure = FailureRecord(
        test_id="wrap",
        cycle=11,
        signal="count",
        expected=0,
        actual=10,
        message="counter did not wrap",
    )
    first = explain_failure(failure)
    second = explain_failure(failure)
    assert first == second
    assert all(word in first for word in ("wrap", "count", "期望", "实际", "复现"))
