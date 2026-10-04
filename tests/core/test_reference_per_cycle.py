"""逐拍权威检查保留原计划，捕获输入段内部的真实协议差异。"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.debug_server import build_plan_response
from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.pipeline import PipelineValidationError, VerificationPipeline, coverage_summary
from iverilog_ai.core.reference_model import (
    AUTHORITATIVE, ReferenceSamplingError, reference_cycle_expectations,
    reference_expectations, reference_sampling_profile,
)
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()


def _contract(design: str) -> DutContract:
    return DutContract.from_dict(json.loads((ROOT / f"examples/{design}_contract.json").read_text(encoding="utf-8")))


def _plan(design: str, vectors: list[dict]) -> Plan:
    return Plan.model_validate({"design": design, "objective": "per-cycle reference regression", "vectors": vectors})


def _uart_plan() -> Plan:
    # sample-031 第一轮的四段输入/86拍；用固定激励重现，不依赖私有历史工件。
    return _plan("uart_tx", [
        {"name": "idle", "inputs": {"rst_n": 1, "start": 0, "data_in": 0}, "cycles": 2},
        {"name": "frame_96", "inputs": {"start": 1, "data_in": 150}, "cycles": 41},
        {"name": "release", "inputs": {"start": 0, "data_in": 0}, "cycles": 2},
        {"name": "frame_ff", "inputs": {"start": 1, "data_in": 255}, "cycles": 41},
    ])


def _run(plan: Plan, rtl: str, output: Path, *, sampling: str = "per_cycle", pipeline=None):
    return (pipeline or VerificationPipeline()).run(plan, _contract(plan.design), ROOT / rtl, output,
        reference_sampling=sampling, capture_observations=True, emit_vcd=False,
        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp, max_output_chars=2_000_000)


def test_cycle_states_are_not_repeated_vector_end_and_inputs_hold():
    plan = _plan("mod10_counter", [
        {"name": "advance", "inputs": {"enable": 1}, "cycles": 7, "expected": {"count": 9}},
        {"name": "held", "inputs": {}, "cycles": 2},
        {"name": "clear", "inputs": {"rst_n": 0}, "cycles": 2},
        {"name": "resume", "inputs": {"rst_n": 1}, "cycles": 1},
    ])
    original = plan.model_dump(mode="json")
    samples = reference_cycle_expectations(plan, _contract("mod10_counter"))
    assert [row["count"] for row in samples["advance"]] == list(range(1, 8))
    assert [row["count"] for row in samples["held"]] == [8, 9]
    assert [row["count"] for row in samples["clear"]] == [0, 0]
    assert samples["resume"] == ({"count": 1},)
    ends = reference_expectations(plan, contract=_contract("mod10_counter"))
    assert {name: rows[-1] for name, rows in samples.items()} == ends
    assert plan.model_dump(mode="json") == original


def test_uart_cycle_reference_matches_independent_8n1_bit_sequence():
    rows = reference_cycle_expectations(_uart_plan(), _contract("uart_tx"))["frame_96"]
    bits = [0] + [(150 >> bit) & 1 for bit in range(8)] + [1]
    assert [row["tx"] for row in rows] == [bit for bit in bits for _ in range(4)] + [1]
    assert [row["busy"] for row in rows] == [1] * 40 + [0]


@pytest.mark.parametrize("fault", ["before", "unknown_input", "clock_input", "parameter", "module", "width", "reset", "edge", "short_clock"])
def test_unsupported_or_unknown_reference_is_refused(fault):
    plan = _uart_plan()
    data = _contract("uart_tx").to_dict()
    if fault == "before": plan.vectors[0].sample_phase = "before"
    if fault == "unknown_input": plan.vectors[1].inputs["data_in"] = "8'bxxxxxxxx"
    if fault == "clock_input": plan.vectors[0].inputs["clk"] = 1
    if fault == "parameter": data["parameters"]["CLKS_PER_BIT"] = 5
    if fault == "module": data["module"] = "external_uart"
    if fault == "width": next(p for p in data["ports"] if p["name"] == "data_in")["width"] = 7
    if fault == "reset": data["reset"]["active_level"] = 1
    if fault == "edge": data["clock"]["edge"] = "negedge"
    if fault == "short_clock": data["clock"]["period_ns"] = 2
    with pytest.raises(ReferenceSamplingError):
        reference_cycle_expectations(plan, DutContract.from_dict(data))


def test_per_cycle_rejection_precedes_artifact_creation(tmp_path):
    plan = _uart_plan()
    plan.vectors[0].sample_phase = "before"
    target = tmp_path / "not-created"
    with pytest.raises(PipelineValidationError, match="after"):
        VerificationPipeline().run(plan, _contract("uart_tx"), ROOT / "rtl/uart_tx.v", target,
                                   reference_sampling="per_cycle")
    assert not target.exists()
    with pytest.raises(PipelineValidationError, match="builtin"):
        VerificationPipeline(reference_policy="disabled").run(_uart_plan(), _contract("uart_tx"),
            ROOT / "rtl/uart_tx.v", target, reference_sampling="per_cycle")
    assert not target.exists()


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_uart_internal_bit_order_failures_enter_standard_records_without_expanding_plan(tmp_path):
    plan = _uart_plan()
    original = plan.model_dump(mode="json")
    endpoint = _run(plan, "rtl/uart_tx_bug_msb_first.v", tmp_path / "end", sampling="vector_end")
    checked = _run(plan, "rtl/uart_tx_bug_msb_first.v", tmp_path / "cycles")
    good = _run(plan, "rtl/uart_tx.v", tmp_path / "good")
    assert endpoint.status is ResultStatus.PASSED and endpoint.simulation.check_count == 8
    assert checked.verdict == "failed_checks" and checked.simulation.check_count == 172
    assert good.status is ResultStatus.PASSED and good.simulation.check_count == 172
    assert len(checked.failures) == 16 and {failure.signal for failure in checked.failures} == {"tx"}
    assert all(failure.test_id == "frame_96" for failure in checked.failures)
    assert plan.model_dump(mode="json") == original
    assert checked.plan is plan and len(checked.plan.vectors) == 4
    observed_end = json.loads(Path(endpoint.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    observed_cycle = json.loads(Path(checked.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert observed_end["samples"] == observed_cycle["samples"]  # No extra delays/drives.
    assert checked.coverage["checks"] == {"covered": 172, "total": 172, "percent": 100.0}
    assert checked.coverage["per_signal"]["tx"]["total"] == 86
    assert checked.simulation.config["coverage"] == checked.coverage


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("rtl,expected", [("rtl/spi_master.v", "passed"),
                                       ("rtl/spi_master_bug_sclk_polarity.v", "failed_checks")])
def test_spi_clock_polarity_is_checked_at_every_original_cycle(tmp_path, rtl, expected):
    plan = _plan("spi_master", [
        {"name": "idle", "inputs": {"start": 0}, "cycles": 2},
        {"name": "accept", "inputs": {"start": 1, "data_in": 0x96}, "cycles": 1},
        {"name": "transfer", "inputs": {"start": 0}, "cycles": 17},
    ])
    result = _run(plan, rtl, tmp_path / "spi")
    assert result.verdict == expected and result.simulation.check_count == 80
    if expected == "failed_checks":
        assert any(f.signal == "sclk" for f in result.failures)
    assert len(result.plan.vectors) == 3


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_long_vector_remains_one_vector_with_real_reference_samples_and_bound_artifacts(tmp_path):
    plan = _plan("uart_tx", [{"name": "long_idle", "inputs": {"start": 0}, "cycles": 512}])
    original = plan.model_dump(mode="json")
    result = _run(plan, "rtl/uart_tx.v", tmp_path / "long")
    assert result.status is ResultStatus.PASSED and result.simulation.check_count == 1024
    assert len(result.plan.vectors) == 1 and plan.model_dump(mode="json") == original
    assert json.loads(Path(result.artifacts["testplan"]).read_text(encoding="utf-8")) == original
    assert len(json.loads(Path(result.artifacts["authoritative_plan"]).read_text(encoding="utf-8"))["vectors"]) == 1
    path = Path(result.artifacts["reference_samples"])
    packet = json.loads(path.read_text(encoding="utf-8"))
    metadata = result.simulation.config["oracle"]["reference_samples"]
    assert packet["status"] == "generated" and packet["source"] == "independent_reference_model"
    assert packet["expected_cycles"] == 512 and packet["expected_checks"] == 1024
    assert metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    for key, artifact in [("plan_sha256", "testplan"), ("contract_sha256", "dut_contract"),
                          ("testbench_sha256", "testbench")]:
        assert packet["provenance"][key] == hashlib.sha256(Path(result.artifacts[artifact]).read_bytes()).hexdigest()
    assert packet["provenance"]["rtl_sha256"] == hashlib.sha256((ROOT / "rtl/uart_tx.v").read_bytes()).hexdigest()
    assert packet["provenance"]["reference_model_sha256"] == hashlib.sha256(
        (ROOT / "src/iverilog_ai/core/reference_model.py").read_bytes()).hexdigest()
    for record in result.records:
        expected = packet["samples"][record.cycle]["expected"][record.signal]
        assert expected == record.expected == record.actual
    # 同一 test_id 的重复/错误周期记录不能填补其它未执行的周期。
    sparse = replace(result.simulation, records=tuple(result.records[:2]) * 512)
    assert coverage_summary(plan, sparse)["checks"]["covered"] == 2


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("design", sorted(AUTHORITATIVE))
def test_all_default_builtin_profiles_match_actual_rtl_cycle_by_cycle(tmp_path, design):
    contract = _contract(design)
    assert reference_sampling_profile(contract) is not None
    payload = build_plan_response(f"Design: {design} DUT context: {contract.to_json()} Schema: {{}}",
                                  vector_count=12, seed=3)
    payload["sample_before_reset"] = False
    plan = Plan.model_validate(payload)
    original = plan.model_dump(mode="json")
    result = _run(plan, f"rtl/{design}.v", tmp_path / design)
    expected_cycles = sum(vector.cycles for vector in plan.vectors)
    assert result.status is ResultStatus.PASSED, [failure.to_dict() for failure in result.failures[:3]]
    assert result.simulation.check_count == expected_cycles * len(contract.outputs)
    assert plan.model_dump(mode="json") == original and result.plan is plan
    packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert packet["status"] == "complete" and packet["observed_cycles"] == expected_cycles


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("expected_tx,diagnosis", [("1'b1", "passed"), ("1'bx", "inconclusive")])
def test_encoded_literals_use_actual_drive_semantics_and_unknown_ai_expectations_are_not_compared(tmp_path, expected_tx, diagnosis):
    plan = _plan("uart_tx", [
        {"name": "frame", "inputs": {"start": 1, "data_in": "8'h96"}, "cycles": 41,
         "expected": {"tx": expected_tx}},
        {"name": "held", "inputs": {"start": 0}, "cycles": 2},
    ])
    result = _run(plan, "rtl/uart_tx.v", tmp_path / "encoded")
    assert result.status is ResultStatus.PASSED and result.simulation.check_count == 86
    assert result.simulation.config["oracle"]["status"] == diagnosis
    if diagnosis == "inconclusive":
        assert result.simulation.config["oracle"]["checked_expected"] == 0
        assert result.simulation.config["oracle"]["uncheckable_expected"][0]["reason"] == "unknown_expected_bits"
