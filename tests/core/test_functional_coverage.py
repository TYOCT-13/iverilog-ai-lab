"""功能场景必须由真实采样决定；计划意图和波形末值不能替代证据。"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.functional_coverage import analyze_functional_coverage, functional_coverage_profile
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.models import ProcessStatus

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path("D:/iverilog/bin/iverilog.exe")
RUNTIME = Path("D:/iverilog/bin/vvp.exe")


def _contract(module):
    return DutContract.from_dict(json.loads((ROOT / "examples" / f"{module}_contract.json").read_text()))


def _vector(name, inputs, cycles=1, phase="after"):
    return {"name": name, "inputs": inputs, "cycles": cycles, "sample_phase": phase}


def _run(tmp_path, module, vectors, *, name="run", capture=True, reference_policy="builtin", rtl_file=None):
    if not COMPILER.is_file() or not RUNTIME.is_file():
        pytest.skip("Icarus unavailable")
    plan = Plan.model_validate({"design": module, "objective": "audit actual functional scenarios", "vectors": vectors})
    rtl = ROOT / "rtl" / (rtl_file or f"{module}.v")
    result = VerificationPipeline(reference_policy=reference_policy).run(plan, _contract(module), rtl, tmp_path / name,
        capture_observations=capture, iverilog_path=COMPILER, vvp_path=RUNTIME,
        allowed_roots=(ROOT, tmp_path), max_output_chars=2_000_000)
    coverage = analyze_functional_coverage(result, rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(), builtin_profile=True)
    return result, coverage


def _reanalyze(result):
    rtl = ROOT / "rtl" / f"{result.contract.module}.v"
    return analyze_functional_coverage(result, rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(), builtin_profile=True)


def _rewrite(result, change):
    path = Path(result.artifacts["observed_samples"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return _reanalyze(result)


def test_fifo_weak_and_boundary_inputs_have_distinct_real_coverage(tmp_path):
    _, weak = _run(tmp_path, "sync_fifo", [_vector("idle", {}, 2)], name="weak")
    _, strong = _run(tmp_path, "sync_fifo", [
        _vector("idle", {}), _vector("empty_read", {"rd_en": 1}),
        _vector("fill", {"rd_en": 0, "wr_en": 1, "wr_data": 0x66}, 5),
        _vector("drain", {"wr_en": 0, "rd_en": 1}, 5),
        _vector("both", {"wr_en": 1, "rd_en": 1})], name="strong")
    assert weak["status"] == strong["status"] == "measured"
    assert weak["observed"] == ["fifo.empty"]
    assert "fifo.full" in weak["missing"]
    assert set(strong["observed"]) == {b["id"] for b in strong["bins"]}
    full_attempt = next(b for b in strong["bins"] if b["id"] == "fifo.write_full_attempt")
    proof = full_attempt["first_evidence"]
    assert full_attempt["kind"] == "input_attempt"
    assert proof["samples"][0]["outputs"]["full"] == "1"
    assert proof["samples"][1]["inputs"]["wr_en"] == "1"
    assert proof["samples"][1]["cycle"] == proof["samples"][0]["cycle"] + 1


def test_uart_complete_frame_needs_every_observed_symbol_and_busy_release(tmp_path):
    _, weak = _run(tmp_path, "uart_tx", [_vector("idle", {}),
        _vector("start", {"start": 1, "data_in": 0x96}),
        _vector("short", {"start": 0}, 8)], name="weak")
    result, strong = _run(tmp_path, "uart_tx", [_vector("idle", {}),
        _vector("start", {"start": 1, "data_in": 0x96}),
        _vector("busy_request", {"start": 1, "data_in": 0x55}),
        _vector("complete", {"start": 0}, 41)], name="strong")
    assert "uart.complete_frame" not in weak["observed"]
    assert "uart.complete_frame" in weak["unknown"]  # Budget ended before the terminal sample.
    assert "uart.complete_frame" in strong["observed"]
    assert "uart.busy_request_attempt" in strong["observed"]
    proof = next(b for b in strong["bins"] if b["id"] == "uart.complete_frame")["first_evidence"]
    assert len(proof["samples"]) == 41 and proof["last_cycle"] - proof["first_cycle"] == 40
    assert proof["samples"][-1]["outputs"] == {"tx": "1", "busy": "0"}
    # Changing a real sampled data bit cannot retain a claim of a complete known frame.
    corrupted = _rewrite(result, lambda payload: payload["samples"][10]["outputs"].update(tx="x"))
    assert corrupted["status"] == "unknown"  # Editing a saved output is not an actual X observation.
    assert "uart.complete_frame" not in corrupted["observed"]
    assert "uart.complete_frame" in corrupted["unknown"]


def test_spi_completion_uses_intermediate_samples_not_endpoint(tmp_path):
    _, weak = _run(tmp_path, "spi_master", [_vector("idle", {}),
        _vector("start", {"start": 1, "data_in": 0xA5}),
        _vector("short", {"start": 0}, 4)], name="weak")
    result, strong = _run(tmp_path, "spi_master", [_vector("idle", {}),
        _vector("start", {"start": 1, "data_in": 0xA5}),
        _vector("busy_request", {"start": 1}),
        _vector("complete", {"start": 0}, 16)], name="strong")
    assert "spi.complete_transfer" not in weak["observed"]
    assert "spi.complete_transfer" in strong["observed"]
    assert "spi.done" in strong["observed"]
    proof = next(b for b in strong["bins"] if b["id"] == "spi.complete_transfer")["first_evidence"]
    assert len(proof["samples"]) == 16
    assert [s["outputs"]["sclk"] for s in proof["samples"]] == [str(i % 2) for i in range(16)]
    bad = _rewrite(result, lambda payload: payload["samples"][6]["outputs"].update(sclk="x"))
    assert bad["status"] == "unknown"
    assert "spi.complete_transfer" in bad["unknown"]


def test_handshake_backpressure_and_transfer_keep_input_hold_and_first_evidence(tmp_path):
    _, weak = _run(tmp_path, "handshake_stage", [_vector("idle", {}, 3)], name="weak")
    assert not weak["observed"] and len(weak["missing"]) == 5
    result, report = _run(tmp_path, "handshake_stage", [
        _vector("idle", {}), _vector("load", {"in_valid": 1, "in_data": 0x19, "out_ready": 0}),
        _vector("held", {}, 2), _vector("refill", {"out_ready": 1, "in_data": 0x39}),
        _vector("drain", {"in_valid": 0})])
    assert set(report["observed"]) == {b["id"] for b in report["bins"]}
    stall = next(b for b in report["bins"] if b["id"] == "handshake.stalled_pair")["first_evidence"]
    assert stall["last_cycle"] == 2  # First of the two possible held pairs.
    assert stall["samples"][-1]["inputs"]["in_data"] == "00011001"
    assert stall["samples"][0]["outputs"]["out_data"] == stall["samples"][1]["outputs"]["out_data"]
    invalid = _rewrite(result, lambda payload: payload["samples"][2]["inputs"].update(in_data="00000000"))
    assert invalid["status"] == "unknown"
    assert invalid["reason"] == "observed_samples_digest_mismatch"
    assert not invalid["observed"]


@pytest.mark.parametrize("fault", ["zero", "missing", "duplicate", "reverse", "same_time", "width", "provenance", "inconclusive"])
def test_ambiguous_or_incomplete_sample_stream_cannot_hit_any_bin(tmp_path, fault):
    result, _ = _run(tmp_path, "sync_fifo", [_vector("write", {"wr_en": 1}, 3)])
    def damage(payload):
        if fault == "zero": payload["samples"] = []
        if fault == "missing": payload["samples"].pop()
        if fault == "duplicate": payload["samples"][1] = deepcopy(payload["samples"][0])
        if fault == "reverse": payload["samples"].reverse()
        if fault == "same_time": payload["samples"][1]["time_ns"] = payload["samples"][0]["time_ns"]
        if fault == "width": payload["samples"][0]["outputs"]["full"] = "00"
        if fault == "provenance": payload["provenance"]["rtl_sha256"] = "0" * 64
        if fault == "inconclusive": payload["status"] = "inconclusive"
    report = _rewrite(result, damage)
    assert report["status"] == "unknown" and report["reason"]
    assert not report["observed"] and not report["missing"]
    assert len(report["unknown"]) == len(report["bins"])


def test_unknown_request_bits_do_not_become_input_attempts(tmp_path):
    # The integer-only correctness oracle cannot evaluate X; this test exercises
    # actual observation collection with the known builtin RTL, not a verdict.
    _, report = _run(tmp_path, "uart_tx", [_vector("unknown", {"start": "x"}, 3)], reference_policy="disabled")
    assert report["status"] == "measured"
    assert "uart.request" in report["unknown"]
    assert "uart.request" not in report["observed"]


def test_missing_sample_artifact_is_unknown_and_name_alone_is_unsupported(tmp_path):
    result, report = _run(tmp_path, "sync_fifo", [_vector("write", {"wr_en": 1}, 3)], capture=False)
    assert report["status"] == "unknown" and not report["observed"]
    unqualified = analyze_functional_coverage(result, rtl_sha256="a" * 64)
    assert unqualified["status"] == "unsupported" and not unqualified["bins"]


@pytest.mark.parametrize("module,key,value", [("sync_fifo", "DEPTH", 8), ("sync_fifo", "DATA_WIDTH", 16),
                                               ("uart_tx", "CLKS_PER_BIT", 5), ("spi_master", "WIDTH", 4),
                                               ("handshake_stage", "WIDTH", 16)])
def test_unreviewed_parameter_profile_is_not_accepted(module, key, value):
    data = _contract(module).to_dict()
    data["parameters"][key] = value
    assert functional_coverage_profile(DutContract.from_dict(data)) is None


def test_before_sampling_does_not_use_after_profile(tmp_path):
    _, report = _run(tmp_path, "sync_fifo", [_vector("before", {"wr_en": 1}, 2, phase="before")])
    assert report["status"] == "unknown" and not report["observed"]
    assert report["reason"] == "sample_order_or_phase_mismatch"


def test_saved_outputs_cannot_add_fifo_full_without_changing_input_hashes(tmp_path):
    result, original = _run(tmp_path, "sync_fifo", [_vector("idle", {}, 3)])
    assert original["observed"] == ["fifo.empty"]
    original_packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    def forge_full(payload):
        payload["samples"][0]["outputs"].update(full="1", empty="0")
    changed = _rewrite(result, forge_full)
    changed_packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    assert changed_packet["provenance"] == original_packet["provenance"]
    assert changed["status"] == "unknown" and not changed["observed"]
    assert changed["reason"] == "observed_samples_digest_mismatch"


def test_packet_and_metadata_digest_together_cannot_override_real_stdout(tmp_path):
    result, _ = _run(tmp_path, "sync_fifo", [_vector("idle", {}, 3)])
    original_stdout = result.simulation.run.stdout
    _rewrite(result, lambda payload: payload["samples"][0]["outputs"].update(full="1", empty="0"))
    packet_digest = hashlib.sha256(Path(result.artifacts["observed_samples"]).read_bytes()).hexdigest()
    config = {**result.simulation.config,
              "observed_samples": {**result.simulation.config["observed_samples"], "sha256": packet_digest}}
    edited = replace(result, simulation=replace(result.simulation, config=config))
    report = _reanalyze(edited)
    assert edited.simulation.run.stdout == original_stdout
    assert report["status"] == "unknown" and not report["observed"]
    assert report["reason"] == "observed_samples_stdout_mismatch"


@pytest.mark.parametrize("fault", ["none", "not_passed", "returncode", "timeout", "truncated", "empty_stdout"])
def test_without_an_actual_completed_run_no_coverage_bin_is_measured(tmp_path, fault):
    result, _ = _run(tmp_path, "sync_fifo", [_vector("idle", {}, 3)])
    run = result.simulation.run
    if fault == "none": run = None
    if fault == "not_passed": run = replace(run, status=ProcessStatus.NOT_RUN)
    if fault == "returncode": run = replace(run, returncode=None)
    if fault == "timeout": run = replace(run, timed_out=True)
    if fault == "truncated": run = replace(run, output_truncated=True)
    if fault == "empty_stdout": run = replace(run, stdout="")
    altered = replace(result, simulation=replace(result.simulation, run=run))
    report = _reanalyze(altered)
    assert report["status"] == "unknown" and not report["observed"] and not report["missing"]
    assert report["reason"] == "execution_not_complete"


def test_original_packet_is_not_complete_if_actual_stdout_lacks_an_observation(tmp_path):
    result, _ = _run(tmp_path, "sync_fifo", [_vector("idle", {}, 3)])
    stdout = result.simulation.run.stdout
    lines = stdout.splitlines()
    at = next(index for index, line in enumerate(lines) if line.startswith("IVERILOG_AI_OBSERVATION "))
    del lines[at]
    altered_run = replace(result.simulation.run, stdout="\n".join(lines))
    report = _reanalyze(replace(result, simulation=replace(result.simulation, run=altered_run)))
    assert report["status"] == "unknown" and not report["observed"]
    assert report["reason"] == "observed_samples_stdout_mismatch"


def test_functional_failures_do_not_hide_real_observed_scenarios(tmp_path):
    result, report = _run(tmp_path, "sync_fifo", [
        _vector("idle", {}), _vector("fill", {"wr_en": 1, "wr_data": 33}, 3)],
        rtl_file="sync_fifo_bug_full_off_by_one.v")
    assert result.simulation.run.status is ProcessStatus.PASSED
    assert result.simulation.failures
    assert report["status"] == "measured" and "fifo.full" in report["observed"]
    assert report["provenance"]["run_stdout_sha256"] == hashlib.sha256(result.simulation.run.stdout.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("module,complete_bin", [("uart_tx", "uart.complete_frame"),
                                               ("spi_master", "spi.complete_transfer")])
def test_real_unknown_output_data_prevents_complete_frame_claim(tmp_path, module, complete_bin):
    _, report = _run(tmp_path, module, [_vector("idle", {}),
        _vector("start_unknown", {"start": 1, "data_in": "x"}),
        _vector("finish", {"start": 0}, 41 if module == "uart_tx" else 16)], reference_policy="disabled")
    assert report["status"] == "measured"
    assert complete_bin in report["unknown"] and complete_bin not in report["observed"]
