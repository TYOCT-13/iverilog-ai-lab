"""逐拍表的完整性校验和可用于 Agent 的纯内存生成预检。"""
import copy
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import reference_cycle_expectations
from iverilog_ai.core.testbench import TestbenchGenerationError as GenerationError, TestbenchGenerator as Generator


def _contract():
    return DutContract.from_dict({"module": "mod10_counter", "ports": [
        {"name": "clk", "direction": "input"}, {"name": "rst_n", "direction": "input"},
        {"name": "enable", "direction": "input"}, {"name": "count", "direction": "output", "width": 4}],
        "clock": {"signal": "clk", "period_ns": 10},
        "reset": {"signal": "rst_n", "active_level": 0, "assert_cycles": 2}})


def _plan():
    return Plan.model_validate({"design": "mod10_counter", "objective": "generator preflight", "vectors": [
        {"name": "three", "inputs": {"enable": 1}, "cycles": 3, "expected": {"count": 3}}]})


@pytest.mark.parametrize("fault", ["missing_vector", "extra_vector", "missing_cycle", "extra_cycle", "missing_output",
                                   "extra_output", "bad_width", "unknown_value", "before", "wrong_mode"])
def test_bad_cycle_table_is_rejected_before_output_is_created(tmp_path, fault):
    plan, contract = _plan(), _contract()
    table = {name: list(rows) for name, rows in reference_cycle_expectations(plan, contract).items()}
    table = copy.deepcopy(table)
    if fault == "missing_vector": table.clear()
    if fault == "extra_vector": table["extra"] = table["three"]
    if fault == "missing_cycle": table["three"].pop()
    if fault == "extra_cycle": table["three"].append({"count": 4})
    if fault == "missing_output": table["three"][1] = {}
    if fault == "extra_output": table["three"][1]["enable"] = 1
    if fault == "bad_width": table["three"][1]["count"] = 16
    if fault == "unknown_value": table["three"][1]["count"] = "4'bxxxx"
    if fault == "before": plan.vectors[0].sample_phase = "before"
    target = tmp_path / "not-created"
    with pytest.raises(GenerationError):
        Generator().generate(plan, contract, target,
            reference_sampling="vector_end" if fault == "wrong_mode" else "per_cycle", cycle_expectations=table)
    assert not target.exists()


def test_validate_is_pure_memory_and_catches_actual_clock_and_port_restrictions(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight cannot create or write files")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    generator = Generator()
    assert generator.validate(_plan(), _contract()) is None
    bad = _plan()
    bad.vectors[0].inputs["clk"] = 1
    with pytest.raises(GenerationError, match="clock"):
        generator.validate(bad, _contract())
    bad = _plan()
    bad.vectors[0].inputs["count"] = 1
    with pytest.raises(GenerationError, match="output"):
        generator.validate(bad, _contract())
    with pytest.raises(GenerationError, match="max_total_cycles"):
        Generator(max_total_cycles=2).validate(_plan(), _contract())


def test_valid_cycle_table_checks_changing_reference_without_modifying_plan(tmp_path):
    plan, contract = _plan(), _contract()
    original = plan.model_dump(mode="json")
    table = reference_cycle_expectations(plan, contract)
    path = Generator().generate(plan, contract, tmp_path, reference_sampling="per_cycle", cycle_expectations=table)
    source = path.read_text(encoding="utf-8")
    assert source.count("checks = checks + 1;") == 3
    for value in ("0001", "0010", "0011"):
        assert source.count(f"if (count !== 4'b{value})") == 1
    assert plan.model_dump(mode="json") == original and len(plan.vectors) == 1
