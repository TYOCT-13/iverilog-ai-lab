from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.testbench import TestbenchGenerationError as GenerationError, TestbenchGenerator as Generator


def _comb_contract() -> DutContract:
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


def test_generator_emits_only_controlled_verilog_and_marker(tmp_path):
    plan = Plan.model_validate(
        {
            "design": "and_gate",
            "objective": "boundary vectors",
            "vectors": [
                {"name": "zero", "inputs": {"a": 0, "b": 1}, "expected": {"y": 0}},
                {"name": "one", "inputs": {"a": 1}, "expected": {"y": 1}},
            ],
        }
    )
    target = Generator().generate(plan, _comb_contract(), tmp_path)
    source = target.read_text(encoding="utf-8")
    assert target.name == "tb_and_gate.v"
    assert "IVERILOG_AI_RESULT" in source
    assert "dut_i (.a(a), .b(b), .y(y));" in source
    assert "$system" not in source and "$readmemh" not in source
    assert "boundary vectors" not in source


def test_generator_rejects_unknown_ports_and_verilog_like_values(tmp_path):
    contract = _comb_contract()
    unknown = Plan.model_validate(
        {
            "design": "and_gate",
            "objective": "x",
            "vectors": [{"name": "bad", "inputs": {"missing": 1}}],
        }
    )
    with pytest.raises(GenerationError, match="unknown port"):
        Generator().generate(unknown, contract, tmp_path)

    injected = Plan.model_validate(
        {
            "design": "and_gate",
            "objective": "x",
            "vectors": [{"name": "bad", "inputs": {"a": "1'b0; $finish"}}],
        }
    )
    with pytest.raises(GenerationError, match="unsupported value"):
        Generator().generate(injected, contract, tmp_path)


def test_generator_has_deterministic_source(tmp_path):
    plan = Plan.model_validate(
        {
            "design": "and_gate",
            "objective": "x",
            "vectors": [{"name": "x", "inputs": {"a": 1, "b": 1}, "expected": {"y": 1}}],
        }
    )
    first = Generator().generate(plan, _comb_contract(), tmp_path, filename="tb_first.v")
    source = first.read_text(encoding="utf-8")
    second = Generator().generate(plan, _comb_contract(), tmp_path, filename="tb_second.v")
    assert source == second.read_text(encoding="utf-8")
