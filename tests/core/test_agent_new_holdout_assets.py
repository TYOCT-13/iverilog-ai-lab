"""新内部合成资产的来源、预算和正确规格纯基线，不需要私有旧实验。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "benchmarks/agent_new_holdout_20261005"
SPECS = ROOT / "spec/agent_new_holdout_20261005"
CASES = ("valid_data_pipeline", "event_accumulator")


def load_asset(name: str):
    spec = importlib.util.spec_from_file_location(f"new_holdout_asset_{name}", ASSETS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINES = load_asset("baselines")
REFERENCES = load_asset("reference_models")


def typed_contract(case: str) -> DutContract:
    return DutContract.from_json((ASSETS / "contracts" / f"{case}_contract.json").read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_member_and_resource_hashes_bind_all_formal_files():
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "agent-holdout-modules-v1" and set(manifest["cases"]) == set(CASES)
    assert not manifest["human_trial"] and not manifest["independent_human_review"]
    assert manifest["preparation_API_calls"] == 0 and not manifest["preparation_is_agent_score"]
    members = manifest["members"]
    actual = {path.relative_to(ROOT).as_posix(): digest(path) for directory in (ASSETS, SPECS) for path in directory.rglob("*")
              if path.is_file() and path != ASSETS / "manifest.json" and "__pycache__" not in path.parts}
    assert members == actual
    for case, item in manifest["cases"].items():
        assert item["default_parameters"] == {} and item["cycle_budget"] == 24
        assert item["max_vectors_per_proposal"] == 12 and item["max_accepted_vectors_total"] == 64
        for path_key, sha_key in (("reference_rtl", "reference_sha256"), ("contract_path", "contract_sha256"), ("spec_path", "spec_sha256")):
            assert digest(ROOT / item[path_key]) == item[sha_key]
        assert len(item["targets"]) == 3
        assert [row["variant"] for row in item["targets"]] == ["reference", "mutation_b", "mutation_c"]
        assert len({row["rtl"] for row in item["targets"]}) == 3
        for target in item["targets"]:
            assert digest(ROOT / target["rtl"]) == target["sha256"]
        assert item["targets"][0]["sha256"] == item["reference_sha256"]
        assert typed_contract(case).module == case
    for record in manifest["private_metadata"]:
        assert record["API_visible"] is False and digest(ROOT / record["path"]) == record["sha256"]


@pytest.mark.parametrize("case", CASES)
def test_two_variants_are_exact_single_source_replacements_with_same_interface(case):
    reference = (ASSETS / "targets" / case / "A" / f"{case}.v").read_text(encoding="utf-8")
    metadata = json.loads((ASSETS / "private_metadata" / f"{case}_mutations.json").read_text(encoding="utf-8"))
    assert len(metadata) == 2 and {row["variant"] for row in metadata} == {"B", "C"}
    for mutation in metadata:
        source = (ASSETS / "targets" / case / mutation["variant"] / f"{case}.v").read_text(encoding="utf-8")
        assert mutation["API_visible"] is False
        assert reference.count(mutation["before"]) == 1
        assert source == reference.replace(mutation["before"], mutation["after"], 1)
        assert f"module {case}" in source and "mutation" not in source.lower()


@pytest.mark.parametrize("case", CASES)
def test_correct_specs_include_full_fixed_timing_and_no_private_label_or_witness(case):
    text = (SPECS / f"{case}_spec.md").read_text(encoding="utf-8")
    typed = typed_contract(case)
    assert all(port.name in text for port in typed.ports)
    assert "24" in text and "12" in text and "after" in text and "2 个上升沿" in text
    assert "保持之前的值" in text and "异步低有效" in text
    assert "mutation_b" not in text and "mutation_c" not in text and "private-witness" not in text
    assert "benchmarks/" not in text and "targets/" not in text and "private_metadata" not in text


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("strategy", ("fixed", "random", "protocol_random"))
@pytest.mark.parametrize("seed", (0, 1, 2))
def test_baseline_factory_reads_only_correct_spec_and_meets_identical_caps(case, strategy, seed):
    typed = typed_contract(case)
    original_read = Path.read_text
    reads = []
    allowed = (SPECS / f"{case}_spec.md").resolve()

    def audited_read(path, *args, **kwargs):
        assert path.resolve() == allowed
        reads.append(path)
        return original_read(path, *args, **kwargs)

    with patch.object(Path, "read_text", audited_read):
        first = BASELINES.baseline_factory(case, strategy, seed, typed, 24)
        second = BASELINES.baseline_factory(case, strategy, seed, typed, 24)
    assert reads and first.model_dump() == second.model_dump()
    assert isinstance(first, Plan) and type(first.clock_period_ns) is int and first.clock_period_ns == 10
    assert sum(vector.cycles for vector in first.vectors) == 24 and len(first.vectors) <= 12
    assert all(not vector.expected and vector.sample_phase == "after" and vector.inputs["i_rstn"] == 1 for vector in first.vectors)
    if strategy == "random":
        assert len(first.vectors) == 12 and all(vector.cycles == 2 for vector in first.vectors)
    if strategy != "random":
        inputs = [vector.inputs for vector in first.vectors]
        if case == CASES[0]:
            assert any(row["i_flush"] for row in inputs) and any(row["i_valid"] for row in inputs)
        else:
            assert any(row["i_clear"] and not row["i_enable"] for row in inputs)
            assert any(vector.cycles >= 16 and vector.inputs["i_enable"] and vector.inputs["i_event"] for vector in first.vectors)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("bad", ("case", "strategy", "negative_seed", "boolean_seed", "short_cycles", "float_cycles", "raw_contract"))
def test_baseline_factory_rejects_wrong_arguments(case, bad):
    arguments = [case, "fixed", 0, typed_contract(case), 24]
    replacements = {"case": (0, "unknown"), "strategy": (1, "unknown"), "negative_seed": (2, -1), "boolean_seed": (2, True),
                    "short_cycles": (4, 23), "float_cycles": (4, 24.0), "raw_contract": (3, {})}
    index, value = replacements[bad]
    arguments[index] = value
    with pytest.raises(ValueError):
        BASELINES.baseline_factory(*arguments)


def test_private_reference_functions_validate_known_inputs_and_zero_word_is_valid_data():
    pipeline = REFERENCES.valid_data_pipeline
    assert pipeline([{"i_rstn": 1, "i_flush": 0, "i_valid": 1, "i_data": 0},
                     {"i_rstn": 1, "i_flush": 0, "i_valid": 0, "i_data": 0}]) == [{"o_valid": 0, "o_data": 0}, {"o_valid": 1, "o_data": 0}]
    with pytest.raises(ValueError):
        pipeline([{"i_rstn": 1, "i_flush": 0, "i_valid": 1, "i_data": 256}])
    with pytest.raises(ValueError):
        REFERENCES.event_accumulator([{"i_rstn": 1, "i_enable": True, "i_event": 1, "i_clear": 0}])
