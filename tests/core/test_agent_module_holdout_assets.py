"""既有模块集合留出资产：公开来源、纯基线与真实逐拍语义校验。"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import socket
import subprocess

import pytest

from iverilog_ai.core.toolchain import locate_tools as _locate_test_tools
TEST_TOOLS = _locate_test_tools()

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import reference_cycle_expectations, reference_sampling_profile
from iverilog_ai.core.testbench import TestbenchGenerator as Generator

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "benchmarks/agent_module_holdout_20261005_v7"
MANIFEST = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
CASES = tuple(MANIFEST["cases"])


def helper(name):
    """辅助实现来自新公开资产，测试无需旧实验私有目录。"""
    spec = importlib.util.spec_from_file_location(f"module_holdout_{name}", ASSETS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINES, SEMANTICS, VALIDATION = helper("baselines"), helper("semantics"), helper("validation")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("module_holdout_asset_tests_are_offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def icarus():
    if not TEST_TOOLS.can_simulate:
        pytest.skip("required local Icarus unavailable; no actual toolchain pass may be claimed")


def contract(case):
    return DutContract.from_dict(json.loads((ROOT / MANIFEST["cases"][case]["contract_path"]).read_text(encoding="utf-8")))


def plan(case, vectors):
    return Plan.model_validate({"design": case, "objective": "Independent public-contract semantic audit", "vectors": vectors})


def core_after(case, stimulus):
    output = "rising" if case == "edge_detector" else "pulse_out"
    table = reference_cycle_expectations(stimulus, contract(case))
    return [row[output] for rows in table.values() for row in rows]


@pytest.mark.parametrize("case", CASES)
def test_original_sources_contracts_and_first_two_selection_are_exact(case):
    old_path = ROOT / MANIFEST["original_manifest_path"]
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == MANIFEST["original_manifest_sha256"]
    old = json.loads(old_path.read_text(encoding="utf-8"))
    selected = [item for item in old["defects"] if item["type"] == case][:2]
    entry = MANIFEST["cases"][case]
    assert len(entry["targets"]) == 3
    assert [target["metadata"]["private_original_id"] for target in entry["targets"][1:]] == [item["id"] for item in selected]
    for target in entry["targets"]:
        assert (ROOT / target["rtl"]).read_bytes() == (ROOT / target["original_path"]).read_bytes()
        assert hashlib.sha256((ROOT / target["rtl"]).read_bytes()).hexdigest() == target["sha256"] == target["original_sha256"]
        assert Path(target["rtl"]).name in {"A.v", "B.v", "C.v"}
    assert (ROOT / entry["contract_path"]).read_bytes() == (ROOT / entry["original_contract_path"]).read_bytes()
    assert hashlib.sha256((ROOT / entry["contract_path"]).read_bytes()).hexdigest() == entry["contract_sha256"] == entry["original_contract_sha256"]
    assert hashlib.sha256((ROOT / entry["reference_rtl"]).read_bytes()).hexdigest() == entry["reference_sha256"]
    assert hashlib.sha256((ROOT / entry["original_spec_path"]).read_bytes()).hexdigest() == entry["original_spec_sha256"]


def test_prior_agent_member_scope_uses_saved_public_metadata_only():
    path = ROOT / MANIFEST["membership_audit_path"]
    audit = json.loads(path.read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST["membership_audit_sha256"]
    assert audit["inspected_reports"] == len(audit["records"]) == 26
    assert all(not set(CASES) & set(record["cases"]) for record in audit["records"])
    for field in ("new_never_tested_designs", "external_blind_test", "new_independent_defect_authors", "pretraining_unseen_claim", "created_after_v7_freeze_claim"):
        assert MANIFEST[field] is False
    assert all(MANIFEST["cases"][case]["prior_offline_benchmark_known"] for case in CASES)


@pytest.mark.parametrize("case", CASES)
def test_complete_specs_match_default_contract_and_do_not_expose_private_answers(case):
    entry, dut = MANIFEST["cases"][case], contract(case)
    text = (ROOT / entry["spec_path"]).read_text(encoding="utf-8")
    assert hashlib.sha256((ROOT / entry["spec_path"]).read_bytes()).hexdigest() == entry["spec_sha256"]
    assert dut.module == case and dut.parameters == entry["default_parameters"]
    assert reference_sampling_profile(dut) == f"builtin-reference-per-cycle-v1:{case}"
    assert "异步低有效" in text and "sample_phase=after" in text and "English" in text
    for value in ("16", "12", "64", "三个", "独立自动复位"):
        assert value in text
    assert "200" not in text
    if case == "pulse_stretcher":
        assert "本任务不验证其他参数配置" in text
    else:
        assert "无参数" in text
    for forbidden in ("rtl/", "benchmarks/", "witness", "mutation_b", "mutation_c", "A.v", "B.v", "C.v", "缺陷"):
        assert forbidden not in text
    for target in entry["targets"][1:]:
        assert target["metadata"]["private_original_id"] not in text
    if case == "pulse_stretcher":
        assert "E0, E1, E2, E3" in text and "E4" in text and "WIDTH-1=3" in text


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("strategy", ("fixed", "random", "protocol_random"))
@pytest.mark.parametrize("seed", (0, 1, 2))
def test_baseline_is_deterministic_bounded_and_oracle_independent(case, strategy, seed):
    dut = contract(case)
    original = dut.to_dict()
    stimulus = BASELINES.baseline_factory(case, strategy, seed, dut, 16)
    assert stimulus.model_dump(mode="json") == BASELINES.baseline_factory(case, strategy, seed, dut, 16).model_dump(mode="json")
    assert dut.to_dict() == original
    assert sum(vector.cycles for vector in stimulus.vectors) == 16 and len(stimulus.vectors) <= 12
    assert all(vector.expected == {} and vector.sample_phase == "after" for vector in stimulus.vectors)
    assert all(vector.inputs.get("rst_n") == 1 and "clk" not in vector.inputs for vector in stimulus.vectors)
    assert all(value in (0, 1) and type(value) is int for vector in stimulus.vectors for value in vector.inputs.values())
    assert SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus)
    Generator().validate(stimulus, dut, reference_sampling="per_cycle", cycle_expectations=reference_cycle_expectations(stimulus, dut))
    if strategy == "random":
        assert [vector.cycles for vector in stimulus.vectors] == [2] * 4 + [1] * 8


@pytest.mark.parametrize("case", CASES)
def test_baseline_reads_only_the_correct_public_spec(monkeypatch, case):
    dut = contract(case)
    read_text = Path.read_text
    permitted = (ROOT / MANIFEST["cases"][case]["spec_path"]).resolve()
    reads = []

    def restricted(path, *args, **kwargs):
        assert path.resolve() == permitted
        reads.append(path.resolve())
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", restricted)
    for strategy in ("fixed", "random", "protocol_random"):
        BASELINES.baseline_factory(case, strategy, 1, dut, 16)
    assert reads == [permitted] * 3


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("bad", ("parameters", "missing_parameters", "clock", "reset", "port_width", "signed", "module"))
def test_baseline_rejects_wrong_contract_before_spec_io(case, bad, monkeypatch):
    dut = contract(case)
    if bad == "parameters":
        changed = replace(dut, parameters={"WIDTH": 5})
    elif bad == "missing_parameters":
        changed = replace(dut, parameters={} if case == "pulse_stretcher" else {"UNUSED": 1})
    elif bad == "clock":
        changed = replace(dut, clock=replace(dut.clock, period_ns=20))
    elif bad == "reset":
        changed = replace(dut, reset=replace(dut.reset, synchronous=True))
    elif bad == "port_width":
        changed = replace(dut, ports=(*dut.ports[:-1], replace(dut.ports[-1], width=2)))
    elif bad == "signed":
        changed = replace(dut, ports=(*dut.ports[:-1], replace(dut.ports[-1], signed=True)))
    else:
        changed = replace(dut, module="other_module")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("invalid contract must fail before spec read"))
    with pytest.raises(ValueError, match="baseline_"):
        BASELINES.baseline_factory(case, "fixed", 0, changed, 16)


@pytest.mark.parametrize("field,value", (("case", "unknown"), ("case", True), ("strategy", "feedback"), ("strategy", False), ("seed", -1), ("seed", True), ("seed", "0"), ("cycles", 15), ("cycles", 17), ("cycles", True), ("cycles", "16")))
def test_baseline_rejects_wrong_factory_scope(field, value):
    values = {"case": "edge_detector", "strategy": "fixed", "seed": 0, "contract": contract("edge_detector"), "cycles": 16}
    values[field] = value
    with pytest.raises(ValueError, match="baseline_"):
        BASELINES.baseline_factory(**values)


@pytest.mark.parametrize("case", CASES)
def test_manual_timing_goldens_and_episode_reset(case):
    signal = "signal_in" if case == "edge_detector" else "pulse_in"
    if case == "edge_detector":
        stimulus = plan(case, [{"name": "low", "inputs": {signal: 0}}, {"name": "high", "inputs": {signal: 1}, "cycles": 3}, {"name": "low_again", "inputs": {signal: 0}}, {"name": "rise_again", "inputs": {signal: 1}}])
        expected = [0, 1, 0, 0, 0, 1]
    else:
        stimulus = plan(case, [{"name": "held_high", "inputs": {signal: 1}, "cycles": 3}, {"name": "tail", "inputs": {signal: 0}, "cycles": 4}])
        expected = [1, 1, 1, 1, 1, 1, 0]
    assert SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus) == expected
    first = plan(case, [{"name": "first", "inputs": {signal: 1}}])
    assert SEMANTICS.expected_outputs(case, first) == SEMANTICS.expected_outputs(case, first) == [1]


@pytest.mark.parametrize("case", CASES)
def test_all_eight_cycle_binary_sequences_match_independent_time_semantics(case):
    signal = "signal_in" if case == "edge_detector" else "pulse_in"
    for word in itertools.product((0, 1), repeat=8):
        stimulus = plan(case, [{"name": f"sample_{index}", "inputs": {signal: value}} for index, value in enumerate(word)])
        assert SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("strategy", ("fixed", "random", "protocol_random"))
@pytest.mark.parametrize("seed", (0, 1, 2))
def test_actual_default_baselines_compare_all_cycles_with_both_oracles(case, strategy, seed, tmp_path, icarus):
    dut = contract(case)
    stimulus = BASELINES.baseline_factory(case, strategy, seed, dut, 16)
    original = stimulus.model_dump(mode="json")
    result = VALIDATION.simulate(stimulus, dut, ROOT / MANIFEST["cases"][case]["targets"][0]["rtl"], tmp_path / "actual")
    assert result["status"] == result["verdict"] == "passed" and result["failure_count"] == 0
    assert result["compile_returncode"] == result["execution_returncode"] == 0
    assert result["observation_status"] == "complete"
    assert result["observed_cycles"] == result["check_count"] == 16
    assert result["after"] == SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus)
    assert stimulus.model_dump(mode="json") == original and result["api_calls"] == 0


MUTATIONS = [(case, target) for case, entry in MANIFEST["cases"].items() for target in entry["targets"][1:]]


@pytest.mark.parametrize("case,target", MUTATIONS, ids=[f"{case}-{target['variant']}" for case, target in MUTATIONS])
def test_each_registered_original_mutant_has_a_real_minimal_witness(case, target, tmp_path, icarus):
    witness = target["metadata"]["witness"]
    vectors = [{"name": f"witness_{index}", "inputs": {"rst_n": 1, **item["inputs"]}, "cycles": item["cycles"], "expected": {}, "sample_phase": "after"} for index, item in enumerate(witness["vectors"])]
    stimulus, dut = plan(case, vectors), contract(case)
    assert len(vectors) <= 12 and sum(vector["cycles"] for vector in vectors) == witness["stimulus_cycles"] <= 16
    assert SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus) == witness["reference_after"]
    correct = VALIDATION.simulate(stimulus, dut, ROOT / MANIFEST["cases"][case]["targets"][0]["rtl"], tmp_path / "correct")
    mutated = VALIDATION.simulate(stimulus, dut, ROOT / target["rtl"], tmp_path / "mutant")
    assert correct["status"] == correct["verdict"] == "passed" and correct["failure_count"] == 0
    assert correct["after"] == witness["reference_after"]
    assert mutated["status"] == "passed_with_warnings" and mutated["verdict"] == "failed_checks"
    assert mutated["failure_count"] == 1 and mutated["observation_status"] == "complete"
    assert mutated["compile_returncode"] == mutated["execution_returncode"] == 0
    assert mutated["observed_cycles"] == mutated["check_count"] == witness["stimulus_cycles"]
    failure = mutated["failures"][0]
    assert failure["signal"] == ("rising" if case == "edge_detector" else "pulse_out")
    assert int(failure["actual"], 2) != int(failure["expected"], 2)
    assert mutated["after"] == witness["mutant_after"] and mutated["after"] != correct["after"]


@pytest.mark.parametrize("case", CASES)
def test_actual_manual_reset_and_resume_use_original_core_oracle(case, tmp_path, icarus):
    signal = "signal_in" if case == "edge_detector" else "pulse_in"
    stimulus = plan(case, [{"name": "active", "inputs": {signal: 1}, "cycles": 2}, {"name": "reset", "inputs": {"rst_n": 0}, "cycles": 2}, {"name": "resume", "inputs": {"rst_n": 1}, "cycles": 1}, {"name": "release", "inputs": {signal: 0}, "cycles": 4}])
    result = VALIDATION.simulate(stimulus, contract(case), ROOT / MANIFEST["cases"][case]["targets"][0]["rtl"], tmp_path / "reset")
    assert result["status"] == "passed" and result["after"] == SEMANTICS.expected_outputs(case, stimulus) == core_after(case, stimulus)
    assert result["after"][2:4] == [0, 0] and result["after"][4] == 1


@pytest.mark.parametrize("case", CASES)
def test_actual_reset_assertion_clears_active_output_between_clock_edges(case, tmp_path, icarus):
    signal, output = ("signal_in", "rising") if case == "edge_detector" else ("pulse_in", "pulse_out")
    parameters = "#(.WIDTH(4)) " if case == "pulse_stretcher" else ""
    testbench = tmp_path / f"tb_{case}_async_reset.v"
    testbench.write_text(f'''`timescale 1ns / 1ps
module tb_{case}_async_reset;
reg clk=0; reg rst_n=1; reg {signal}=0; wire {output};
{case} {parameters}dut(.clk(clk),.rst_n(rst_n),.{signal}({signal}),.{output}({output}));
always #5 clk=~clk;
initial begin
 #1 rst_n=0; #1 $display("MODULE_HOLDOUT_RESET %0d",{output});
 #1 rst_n=1; {signal}=1;
 @(posedge clk); #1 $display("MODULE_HOLDOUT_ACTIVE %0d",{output});
 #1 rst_n=0; #1 $display("MODULE_HOLDOUT_ASYNC %0d",{output});
 $finish;
end
endmodule
''', encoding="utf-8")
    rtl = ROOT / MANIFEST["cases"][case]["targets"][0]["rtl"]
    binary = tmp_path / "reset.vvp"
    command = [TEST_TOOLS.iverilog, "-g2001", "-s", f"tb_{case}_async_reset", "-o", str(binary), str(rtl), str(testbench)]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    record = {"case": case, "rtl": str(rtl), "api_calls": 0, "command": command, "compile_returncode": compiled.returncode, "compile_stdout": compiled.stdout, "compile_stderr": compiled.stderr}
    if compiled.returncode == 0:
        executed = subprocess.run([TEST_TOOLS.vvp, str(binary)], capture_output=True, text=True, timeout=30, check=False)
        record.update(execution_returncode=executed.returncode, stdout=executed.stdout, stderr=executed.stderr)
    (tmp_path / "asynchronous_reset_validation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert record["compile_returncode"] == 0 and record["execution_returncode"] == 0
    assert "MODULE_HOLDOUT_RESET 0" in record["stdout"] and "MODULE_HOLDOUT_ACTIVE 1" in record["stdout"] and "MODULE_HOLDOUT_ASYNC 0" in record["stdout"]


def test_validation_refuses_to_replace_an_existing_run(tmp_path):
    directory = tmp_path / "preserved"
    directory.mkdir()
    marker = directory / "marker.txt"
    marker.write_text("preserved", encoding="utf-8")
    dut = contract("edge_detector")
    with pytest.raises(ValueError, match="validation_output_exists"):
        VALIDATION.simulate(plan("edge_detector", [{"name": "one", "inputs": {"signal_in": 0}}]), dut, ROOT / MANIFEST["cases"]["edge_detector"]["reference_rtl"], directory)
    assert marker.read_text(encoding="utf-8") == "preserved"
