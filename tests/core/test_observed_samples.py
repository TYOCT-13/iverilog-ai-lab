"""Actual sampling point evidence, including held inputs and ambiguous VCD times."""
import hashlib
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.observations import OBSERVATION_PREFIX, collect_observed_samples
from iverilog_ai.core.pipeline import PipelineValidationError, VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()


def _contract():
    return DutContract.from_dict({"module": "mux4", "ports": [
        {"name": "d0", "direction": "input", "width": 8},
        {"name": "d1", "direction": "input", "width": 8},
        {"name": "d2", "direction": "input", "width": 8},
        {"name": "d3", "direction": "input", "width": 8},
        {"name": "sel", "direction": "input", "width": 2},
        {"name": "y", "direction": "output", "width": 8}]})


def _plan():
    return Plan.model_validate({"design": "mux4", "objective": "sample held inputs at each executed cycle", "vectors": [
        {"name": "first", "inputs": {"d0": 17, "d1": 34, "sel": 0}, "cycles": 2},
        {"name": "second", "inputs": {"sel": 1}, "cycles": 1}]})


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_every_cycle_snapshot_uses_sample_statement_and_preserves_verdict(tmp_path):
    runner = VerificationPipeline()
    options = {"iverilog_path": TOOLS.iverilog, "vvp_path": TOOLS.vvp}
    plain = runner.run(_plan(), _contract(), ROOT / "rtl/mux4.v", tmp_path / "plain", **options)
    sampled = runner.run(_plan(), _contract(), ROOT / "rtl/mux4.v", tmp_path / "sampled",
                         capture_observations=True, **options)
    record = json.loads(Path(sampled.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert record["status"] == "complete" and record["observed_cycles"] == 3
    assert [s["outputs"]["y"] for s in record["samples"]] == ["00010001", "00010001", "00100010"]
    assert record["samples"][2]["inputs"]["d1"] == "00100010"  # Omitted input holds its previous value.
    assert [s["test_id"] for s in record["samples"]] == ["first", "first", "second"]
    assert plain.verdict == sampled.verdict and len(plain.records) == len(sampled.records)
    assert "observed_samples" not in plain.artifacts
    assert sampled.simulation.config["observed_samples"]["sha256"] == hashlib.sha256(
        Path(sampled.artifacts["observed_samples"]).read_bytes()).hexdigest()
    for key, artifact in (("plan_sha256", "testplan"), ("contract_sha256", "dut_contract"),
                          ("testbench_sha256", "testbench")):
        assert record["provenance"][key] == hashlib.sha256(Path(sampled.artifacts[artifact]).read_bytes()).hexdigest()


def _sample(cycle, *, outputs=None):
    return {"cycle": cycle, "time_ns": cycle + 1.0,
            "test_id": "first" if cycle < 2 else "second", "sample_phase": "after",
            "inputs": {"d0": "00010001", "d1": "00100010", "d2": "00000000", "d3": "00000000", "sel": "00"},
            "outputs": outputs or {"y": "00010001"}}


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_width", "wrong_port", "wrong_test", "truncated", "not_finished", "nan"])
def test_incomplete_ambiguous_or_invalid_observations_do_not_complete(fault):
    samples = [_sample(i) for i in range(3)]
    if fault == "missing": samples.pop()
    if fault == "duplicate": samples.insert(1, dict(samples[0]))
    if fault == "wrong_width": samples[1]["outputs"]["y"] = "1"
    if fault == "wrong_port": samples[1]["outputs"]["other"] = "00000000"
    if fault == "wrong_test": samples[1]["test_id"] = "invented"
    if fault == "nan": samples[1]["time_ns"] = float("nan")
    stdout = "\n".join(OBSERVATION_PREFIX + json.dumps(s) for s in samples)
    result = collect_observed_samples(stdout, _plan(), _contract(), provenance={},
                                     execution_complete=fault != "not_finished", output_truncated=fault == "truncated")
    assert result["status"] == "inconclusive" and result["errors"]


def test_unknown_bits_are_retained_as_unknown_observations():
    stdout = "\n".join(OBSERVATION_PREFIX + json.dumps(_sample(i, outputs={"y": "xxxxzzzz"})) for i in range(3))
    result = collect_observed_samples(stdout, _plan(), _contract(), provenance={}, execution_complete=True)
    assert result["status"] == "complete"
    assert result["samples"][0]["outputs"]["y"] == "xxxxzzzz"


def test_invalid_capture_option_does_not_create_artifacts(tmp_path):
    output = tmp_path / "not-created"
    with pytest.raises(PipelineValidationError, match="boolean"):
        VerificationPipeline().run(_plan(), _contract(), ROOT / "rtl/mux4.v", output, capture_observations=1)
    assert not output.exists()
