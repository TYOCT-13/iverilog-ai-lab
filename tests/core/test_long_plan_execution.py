"""Long waits must retain all executed cycles, comparisons and observations."""
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import PipelineValidationError, VerificationPipeline
from iverilog_ai.core.testbench import TestbenchGenerator as Generator
from iverilog_ai.core.toolchain import locate_tools
from iverilog_ai.core.vcd import analyze_failure_windows, analyze_vcd_file


TOOLS = locate_tools()


def _contract(clocked=True):
    data = {"module": "long_probe", "ports": [
        {"name": "clk", "direction": "input"},
        {"name": "rst_n", "direction": "input"},
        {"name": "en", "direction": "input"},
        {"name": "q", "direction": "output", "width": 16},
        {"name": "y", "direction": "output"}]}
    if clocked:
        data["clock"] = {"signal": "clk", "period_ns": 62.5, "edge": "posedge"}
        data["reset"] = {"signal": "rst_n", "active_level": 0, "assert_cycles": 2}
    return DutContract.from_dict(data)


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("clocked", [False, True])
def test_compact_wait_matches_expanded_execution_and_every_observation(tmp_path, phase, clocked):
    rtl = tmp_path / "long_probe.v"
    rtl.write_text(
        "module long_probe(input clk, rst_n, en, output reg [15:0] q, output y);"
        " assign y=en; initial q=0;"
        " always @(posedge clk or negedge rst_n) if (!rst_n) q<=0; else if(en) q<=q+1;"
        " endmodule", encoding="ascii")
    plan = Plan.model_validate({"design": "long_probe", "objective": "preserve long waits",
        "vectors": [
            {"name": "wait_without_check", "cycles": 64,
             "inputs": {"rst_n": 1, "en": 1}, "sample_phase": phase},
            {"name": "check_at_end", "cycles": 32, "sample_phase": phase,
             "expected": {"y": 1, "q": 65535}},
            {"name": "idle", "cycles": 2, "inputs": {"en": 0}, "expected": {"y": 0}}]})
    results = []
    snapshots = []
    phases = []
    for compact in (False, True):
        result = VerificationPipeline(generator=Generator(compact_repeated_vectors=compact),
            reference_policy="disabled").run(plan, _contract(clocked), rtl,
                tmp_path / str(compact), allowed_roots=(tmp_path,),
                iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp,
                capture_observations=True, on_progress=phases.append)
        results.append(result)
        packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
        assert packet["status"] == "complete" and packet["observed_cycles"] == 98
        snapshots.append(packet["samples"])
    assert snapshots[0] == snapshots[1]
    assert [r.to_dict() for r in results[0].records] == [r.to_dict() for r in results[1].records]
    assert results[0].simulation.summary == results[1].simulation.summary
    assert results[1].simulation.check_count == 3
    assert len(results[1].simulation.failures) == 1
    assert phases[0] == "校验接口与测试计划" and phases[-1] == "保存运行结果"
    assert "分析失败波形窗口" in phases


def test_long_source_is_bounded_by_vectors_instead_of_cycle_count(tmp_path):
    def source(cycles):
        plan = Plan.model_validate({"design": "long_probe", "objective": "long waits",
            "vectors": [{"name": "wait", "cycles": cycles, "inputs": {"en": 1},
                         "expected": {"y": 1}}]})
        return Generator().generate(plan, _contract(), tmp_path).read_text(encoding="utf-8")
    short, long = source(32), source(1000)
    assert "for (" in long
    assert len(long) < len(short) + 20
    assert long.count("@( posedge clk );") == short.count("@( posedge clk );")


def _vcd(tmp_path):
    path = tmp_path / "long.vcd"
    header = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! y $end\n$upscope $end\n$enddefinitions $end\n"
    path.write_text(header + "".join(f"#{i}\n{i % 2}!\n" for i in range(10001)), encoding="ascii")
    return path


def test_batch_failure_windows_match_individual_scans_including_late_events(tmp_path, monkeypatch):
    path = _vcd(tmp_path)
    read_bytes = Path.read_bytes
    reads = []
    def counted_read(source):
        reads.append(source)
        return read_bytes(source)
    monkeypatch.setattr(Path, "read_bytes", counted_read)
    batch = analyze_failure_windows(path, [0, 1, 2, 900, 900], radius=1, max_changes=3)
    assert len(reads) == 1
    assert batch["requested_windows"] == 4 and not batch["truncated"]
    for window in batch["windows"]:
        single = analyze_vcd_file(path, start_ns=window["start_ns"], end_ns=window["end_ns"], max_changes=3)
        assert window["analysis"] == single
    assert batch["windows"][-1]["analysis"]["changes"][0]["time_ns"] == 8990


def test_failure_window_preview_limit_is_explicit(tmp_path):
    batch = analyze_failure_windows(_vcd(tmp_path), list(range(80)))
    assert batch["requested_windows"] == 80 and batch["returned_windows"] == 64
    assert batch["truncated"] and batch["omitted_cycles"] == list(range(64, 80))
    for invalid in (0, -1, True, 2.5):
        with pytest.raises(ValueError, match="max_windows"):
            analyze_failure_windows(tmp_path / "missing.vcd", [1], max_windows=invalid)


def test_progress_callback_validation_precedes_artifact_creation(tmp_path):
    with pytest.raises(PipelineValidationError, match="on_progress"):
        VerificationPipeline().run({}, {}, tmp_path / "missing.v", tmp_path / "out", on_progress="invalid")
    assert not (tmp_path / "out").exists()
