"""Actual port feedback is bounded and value-neutral, with fail-closed bindings."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket

import pytest

from iverilog_ai.core.toolchain import locate_tools as _locate_test_tools
TEST_TOOLS = _locate_test_tools()

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.models import ProcessResult, ProcessStatus, ResultStatus, SimulationResult
from iverilog_ai.core.observations import OBSERVATION_PREFIX, collect_observed_samples
from iverilog_ai.core.observation_feedback import build_observation_feedback, MAX_FEEDBACK_CHARACTERS
from iverilog_ai.core.pipeline import PipelineResult, VerificationPipeline
from iverilog_ai.core.testbench import _encode_value

ROOT = Path(__file__).resolve().parents[2]
RTL_SHA = hashlib.sha256(b"explicit synthetic unit fixture identity, not a DUT execution").hexdigest()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("port-feedback tests never use a network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fixture(tmp_path, *, count=24, widths=(8, 1), clock=True, edge="posedge", active=0,
             input_value=5, unknown_cycle=None, phase="after", output_offset=0):
    """Synthetic process evidence for unit checks; not a claimed Icarus run."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ports = [{"name": "drive", "direction": "input", "width": 4},
             {"name": "q", "direction": "output", "width": widths[0]},
             {"name": "status", "direction": "output", "width": widths[1]}]
    data = {"module": "arbitrary_ports", "ports": ports}
    if clock:
        ports.extend([{"name": "tick", "direction": "input"}, {"name": "reset", "direction": "input"}])
        data.update(clock={"signal": "tick", "period_ns": 10, "edge": edge},
                    reset={"signal": "reset", "active_level": active, "assert_cycles": 2, "synchronous": False})
    contract = DutContract.from_dict(data)
    plan = Plan.model_validate({"design": contract.module, "objective": "private fixture objective must not be echoed",
                               "vectors": [{"name": "sample", "inputs": {"drive": input_value}, "cycles": count,
                                            "sample_phase": phase, "expected": {"q": 1}}]})
    artifacts = {name: str(tmp_path / file) for name, file in (("testplan", "testplan.json"), ("dut_contract", "contract.json"),
                 ("testbench", "testbench.v"), ("observed_samples", "observed.json"), ("result_json", "executor.json"))}
    Path(artifacts["testplan"]).write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")
    Path(artifacts["dut_contract"]).write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    Path(artifacts["testbench"]).write_text("// synthetic unit binding only\nmodule fixture; endmodule\n", encoding="utf-8")
    hashes = {"rtl_sha256": RTL_SHA, **{name: _sha(artifacts[key]) for name, key in
              (("plan_sha256", "testplan"), ("contract_sha256", "dut_contract"), ("testbench_sha256", "testbench"))}}
    samples = []
    for index in range(count):
        inputs = {"drive": _encode_value(contract.port_map["drive"], input_value, context="fixture").bits}
        if clock:
            inputs.update(tick="1" if edge == "posedge" else "0", reset=str(1-active))
        samples.append({"cycle": index, "time_ns": (26 + index * 10) if clock else (1 + index),
                        "test_id": "sample", "sample_phase": phase, "inputs": inputs,
                        "outputs": {"q": "x" * widths[0] if index == unknown_cycle else format((index+output_offset) % (1 << widths[0]), f"0{widths[0]}b"),
                                    "status": format(index % (1 << widths[1]), f"0{widths[1]}b")}})
    stdout = "\n".join(OBSERVATION_PREFIX + json.dumps(sample) for sample in samples) + "\n"
    packet = collect_observed_samples(stdout, plan, contract, provenance=hashes, execution_complete=True)
    Path(artifacts["observed_samples"]).write_text(json.dumps(packet), encoding="utf-8")
    compiled = ProcessResult(ProcessStatus.PASSED, 0, ("synthetic-unit-compile",))
    run = ProcessResult(ProcessStatus.PASSED, 0, ("synthetic-unit-run",), stdout=stdout)
    config = {"rtl_sha256": RTL_SHA, "testbench_sha256": hashes["testbench_sha256"],
              "observed_samples": {"sha256": _sha(artifacts["observed_samples"])}}
    simulation = SimulationResult("unit_fact_run_001", ResultStatus.PASSED, compiled, run, config=config)
    Path(artifacts["result_json"]).write_text(json.dumps(simulation.to_dict()), encoding="utf-8")
    return PipelineResult(plan, contract, Path(artifacts["testbench"]), simulation, artifacts=artifacts)


def _rewrite(result, change, *, stdout=False, saved_execution=False):
    path = Path(result.artifacts["observed_samples"])
    packet = json.loads(path.read_text(encoding="utf-8"))
    change(packet)
    path.write_text(json.dumps(packet), encoding="utf-8")
    result.simulation.config["observed_samples"]["sha256"] = _sha(path)
    if stdout:
        text = "\n".join(OBSERVATION_PREFIX + json.dumps(sample) for sample in packet["samples"]) + "\n"
        result = replace(result, simulation=replace(result.simulation, run=replace(result.simulation.run, stdout=text)))
    if saved_execution:
        record = json.loads(Path(result.artifacts["result_json"]).read_text(encoding="utf-8"))
        record["run"] = result.simulation.run.to_dict()
        Path(result.artifacts["result_json"]).write_text(json.dumps(record), encoding="utf-8")
    return result


def _feedback(result):
    return build_observation_feedback(result, rtl_sha256=RTL_SHA)


def _empty(report, code=None):
    assert report["status"] == "inconclusive" and report["samples"] == [] and report["returned_samples"] == 0
    assert report["reason"] and report["provenance"] == {} and report["execution"] == {}
    assert len(json.dumps(report, ensure_ascii=False, indent=2)) <= MAX_FEEDBACK_CHARACTERS
    if code:
        assert report["reason"] == code


@pytest.mark.parametrize("count", (1, 2, 12, 13, 24, 120, 500))
def test_uniform_sample_selection_is_bounded_complete_and_value_neutral(tmp_path, count):
    result = _fixture(tmp_path / "first", count=count)
    original = deepcopy(result.plan.model_dump(mode="json"))
    report = _feedback(result)
    assert report["status"] == "complete" and report["total_samples"] == count
    indices = list(range(count)) if count <= 12 else [index * (count-1) // 11 for index in range(12)]
    assert [sample["cycle"] for sample in report["samples"]] == indices
    assert report["returned_samples"] == len(indices) and report["omitted_samples"] == count-len(indices)
    assert result.plan.model_dump(mode="json") == original
    assert report["input_bits_known"] and report["output_bits_known"] and not report["contains_unknown_bits"]
    assert len(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)) <= MAX_FEEDBACK_CHARACTERS
    changed = _feedback(_fixture(tmp_path / "different_outputs", count=count, output_offset=17))
    assert [sample["cycle"] for sample in changed["samples"]] == indices
    text = json.dumps(report)
    assert str(tmp_path) not in text and "expected" not in text and "private fixture" not in text
    assert "bins" not in report and "oracle" not in report and "internal_state" not in report


@pytest.mark.parametrize("clock,edge,active", ((False, "posedge", 0), (True, "negedge", 0), (True, "posedge", 1)))
def test_generic_contract_supports_combination_negative_edge_and_active_high(tmp_path, clock, edge, active):
    report = _feedback(_fixture(tmp_path, count=4, clock=clock, edge=edge, active=active))
    assert report["status"] == "complete" and report["returned_samples"] == 4


@pytest.mark.parametrize("input_value", ("4'b10xz", "4'bxxxx", "4'bzzzz"))
def test_unknown_input_and_output_bits_are_preserved_without_known_claim(tmp_path, input_value):
    report = _feedback(_fixture(tmp_path, count=3, input_value=input_value, unknown_cycle=0))
    assert report["status"] == "complete" and report["contains_unknown_bits"]
    assert report["input_bits_known"] is False and report["output_bits_known"] is False
    assert report["samples"][0]["inputs"]["drive"] == input_value.split("b")[1]
    assert report["samples"][0]["outputs"]["q"] == "xxxxxxxx"


def test_unknown_omitted_sample_still_marks_complete_stream_as_unknown(tmp_path):
    report = _feedback(_fixture(tmp_path, count=120, unknown_cycle=1))
    assert 1 not in [sample["cycle"] for sample in report["samples"]]
    assert report["contains_unknown_bits"] and report["output_bits_known"] is False


@pytest.mark.parametrize("widths,count", (((512, 128), 24), ((1024, 1024), 12)))
def test_size_limit_fails_closed_instead_of_clipping_ports_or_bits(tmp_path, widths, count):
    _empty(_feedback(_fixture(tmp_path, widths=widths, count=count)), "feedback_size_limit")


def test_many_outputs_and_nonbyte_widths_remain_full_exact_bits(tmp_path):
    report = _feedback(_fixture(tmp_path, widths=(129, 7), count=2))
    assert report["status"] == "complete"
    assert [len(value) for value in report["samples"][0]["outputs"].values()] == [129, 7]


@pytest.mark.parametrize("field,value", (("returncode", 1), ("returncode", False), ("status", ProcessStatus.ERROR),
                         ("timed_out", True), ("output_truncated", True), ("error", "untrusted path and secret-like marker")))
@pytest.mark.parametrize("process", ("compile", "run"))
def test_incomplete_compile_or_execution_never_returns_samples(tmp_path, field, value, process):
    result = _fixture(tmp_path)
    changed = replace(getattr(result.simulation, process), **{field: value})
    result = replace(result, simulation=replace(result.simulation, **{process: changed}))
    report = _feedback(result)
    _empty(report, "execution_not_complete")
    assert "untrusted path" not in json.dumps(report)


@pytest.mark.parametrize("artifact", ("observed_samples", "testplan", "dut_contract", "testbench", "result_json"))
def test_missing_artifact_is_inconclusive_without_paths(tmp_path, artifact):
    result = _fixture(tmp_path)
    Path(result.artifacts[artifact]).unlink()
    report = _feedback(result)
    _empty(report)
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize("change", ("outputs", "missing", "reverse", "same_time", "width", "status"))
def test_packet_and_digest_tampering_cannot_bypass_stdout_binding(tmp_path, change):
    result = _fixture(tmp_path)
    def damage(packet):
        if change == "outputs": packet["samples"][0]["outputs"]["q"] = "11111111"
        if change == "missing": packet["samples"].pop()
        if change == "reverse": packet["samples"].reverse()
        if change == "same_time": packet["samples"][1]["time_ns"] = packet["samples"][0]["time_ns"]
        if change == "width": packet["samples"][0]["outputs"]["status"] = "00"
        if change == "status": packet["status"] = "inconclusive"
    _empty(_feedback(_rewrite(result, damage)), "observed_samples_stdout_mismatch")


def test_stdout_and_packet_digest_tampering_cannot_bypass_saved_execution(tmp_path):
    result = _fixture(tmp_path)
    changed = _rewrite(result, lambda packet: packet["samples"][0]["outputs"].update(q="11111111"), stdout=True)
    _empty(_feedback(changed), "execution_record_mismatch")


def test_replaced_testbench_and_synced_packet_provenance_do_not_rewrite_executed_input(tmp_path):
    result = _fixture(tmp_path)
    Path(result.artifacts["testbench"]).write_text("module different; endmodule", encoding="utf-8")
    changed = _rewrite(result, lambda packet: packet["provenance"].update(testbench_sha256=_sha(result.artifacts["testbench"])))
    _empty(_feedback(changed), "execution_input_digest_mismatch")


@pytest.mark.parametrize("case", ("held_input", "clock_level", "time_gap"))
def test_consistent_stream_still_must_match_plan_and_contract_timing(tmp_path, case):
    result = _fixture(tmp_path)
    def damage(packet):
        if case == "held_input": packet["samples"][1]["inputs"]["drive"] = "0110"
        if case == "clock_level": packet["samples"][1]["inputs"]["tick"] = "0"
        if case == "time_gap":
            for sample in packet["samples"][1:]: sample["time_ns"] += 1
    # This is a coherent synthetic fixture, not an alleged real run. Even all
    # file digests agreeing cannot waive held-input or clock-period semantics.
    changed = _rewrite(result, damage, stdout=True, saved_execution=True)
    code = "sample_time_gap_mismatch" if case == "time_gap" else "observed_inputs_do_not_match_held_plan"
    _empty(_feedback(changed), code)


def test_before_samples_are_not_misrepresented_as_after(tmp_path):
    _empty(_feedback(_fixture(tmp_path, phase="before")), "unsupported_sampling_phase")


def test_inout_contract_is_not_silently_omitted(tmp_path):
    result = _fixture(tmp_path)
    mapping = result.contract.to_dict()
    mapping["ports"].append({"name": "shared", "direction": "inout", "width": 1})
    _empty(_feedback(replace(result, contract=DutContract.from_dict(mapping))), "inout_observations_unsupported")


@pytest.mark.parametrize("artifact,field", (("testplan", "objective"), ("dut_contract", "module")))
def test_semantic_mismatch_cannot_be_hidden_by_updating_artifact_sha(tmp_path, artifact, field):
    result = _fixture(tmp_path)
    path = Path(result.artifacts[artifact])
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = "changed_semantics"
    path.write_text(json.dumps(data), encoding="utf-8")
    key = "plan_sha256" if artifact == "testplan" else "contract_sha256"
    changed = _rewrite(result, lambda packet: packet["provenance"].update({key: _sha(path)}))
    _empty(_feedback(changed), "provenance_semantic_mismatch")


@pytest.mark.parametrize("case", ("credit_guard", "rotating_arbiter"))
def test_actual_icarus_bound_sampling_supports_prior_modules_without_protocol_bins(tmp_path, case):
    compiler, runtime = Path(TEST_TOOLS.iverilog or ""), Path(TEST_TOOLS.vvp or "")
    if not compiler.is_file() or not runtime.is_file():
        pytest.skip("local Icarus unavailable; no real simulator pass claimed")
    contract = DutContract.from_dict(json.loads((ROOT / "examples" / f"{case}_contract.json").read_text(encoding="utf-8")))
    sequences = ([({"acquire": 1, "release_req": 0}, 4), ({"acquire": 0, "release_req": 1}, 5), ({"acquire": 1, "release_req": 1}, 2)]
                 if case == "credit_guard" else [({"request": 15, "advance": 0}, 4), ({"advance": 1}, 6), ({"request": 0}, 2)])
    plan = Plan.model_validate({"design": case, "objective": "Real mechanical port-observation validation, zero API", "vectors":
                               [{"name": f"phase_{index}", "inputs": inputs, "cycles": count} for index, (inputs, count) in enumerate(sequences)]})
    rtl = ROOT / "rtl" / f"{case}.v"
    result = VerificationPipeline().run(plan, contract, rtl, tmp_path / case,
        capture_observations=True, reference_sampling="per_cycle", emit_vcd=False,
        iverilog_path=compiler, vvp_path=runtime, allowed_roots=(ROOT, tmp_path), max_output_chars=2_000_000)
    assert result.simulation.verdict == "passed" and not result.simulation.failures
    report = build_observation_feedback(result, rtl_sha256=_sha(rtl))
    (tmp_path / f"{case}-feedback.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["status"] == "complete" and report["total_samples"] == sum(count for _, count in sequences)
    raw = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert report["samples"] == raw["samples"]
    assert report["execution"]["run_id"] == result.simulation.run_id
    assert report["provenance"]["run_stdout_sha256"] == hashlib.sha256(result.simulation.run.stdout.encode("utf-8")).hexdigest()
    assert all("expected" not in sample and "coverage" not in sample for sample in report["samples"])
