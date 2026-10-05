"""Bounded, provenance-checked port facts from an actual completed execution.

This helper does not inspect RTL, expected outputs, protocol bins or internal
state. Uniform sample selection is independent of values and assertion failures.
Unknown bits remain unknown; incomplete evidence produces no sample feedback.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .contracts import DutContract
from .models import ProcessResult, ProcessStatus
from .observations import collect_observed_samples
from .pipeline import PipelineResult
from .testbench import _encode_value

MAX_FEEDBACK_CHARACTERS = 8_000
MAX_FEEDBACK_SAMPLES = 12
MAX_ARTIFACT_BYTES = 100_000_000
DISCLAIMER = "Actual port samples only; not protocol coverage, internal state or proof of correctness. Unknown x/z bits remain unknown."


class _EvidenceError(ValueError):
    """Only helper-authored fixed codes can become model-visible reasons."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: str | Path, *, code: str) -> bytes:
    artifact = Path(path)
    if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size > MAX_ARTIFACT_BYTES:
        raise _EvidenceError(code)
    return artifact.read_bytes()


def _complete(process: ProcessResult | None) -> bool:
    return (isinstance(process, ProcessResult) and process.status is ProcessStatus.PASSED
            and type(process.returncode) is int and process.returncode == 0
            and process.timed_out is False and process.output_truncated is False and process.error is None)


def _uniform_indices(count: int) -> list[int]:
    if count <= MAX_FEEDBACK_SAMPLES:
        return list(range(count))
    # Exact integer arithmetic: endpoints and ten interior points, no value bias.
    return [index * (count - 1) // (MAX_FEEDBACK_SAMPLES - 1) for index in range(MAX_FEEDBACK_SAMPLES)]


def _validate_rows(result: PipelineResult, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if (payload.get("schema_version") != "1.0" or payload.get("source") != "testbench_sample_statement"
            or payload.get("status") != "complete" or payload.get("errors")):
        raise _EvidenceError("incomplete_observations")
    plan, contract = result.plan, result.contract
    expected = [(vector.name, vector) for vector in plan.vectors for _ in range(vector.cycles)]
    samples = payload.get("samples")
    if (not expected or not isinstance(samples, list) or len(samples) != len(expected)
            or type(payload.get("expected_cycles")) is not int or payload["expected_cycles"] != len(expected)
            or type(payload.get("observed_cycles")) is not int or payload["observed_cycles"] != len(expected)):
        raise _EvidenceError("sample_count_mismatch")
    held = {port.name: "0" * port.width for port in contract.ports if port.is_input}
    if contract.reset is not None:
        held[contract.reset.signal] = _encode_value(contract.port_map[contract.reset.signal],
                                                   1 - contract.reset.active_level, context="feedback.reset").bits
    if contract.clock is not None:
        held[contract.clock.signal] = "1" if contract.clock.edge == "posedge" else "0"
    last_time = -1.0
    for index, (sample, (test_id, vector)) in enumerate(zip(samples, expected)):
        if not isinstance(sample, dict) or set(sample) != {"cycle", "time_ns", "test_id", "sample_phase", "inputs", "outputs"}:
            raise _EvidenceError("sample_fields_mismatch")
        if (type(sample["cycle"]) is not int or sample["cycle"] != index or sample["test_id"] != test_id
                or sample["sample_phase"] != "after" or vector.sample_phase != "after"):
            raise _EvidenceError("sample_order_or_phase_mismatch")
        at = sample["time_ns"]
        if type(at) not in (int, float) or not math.isfinite(at) or at <= last_time:
            raise _EvidenceError("sample_time_mismatch")
        if index and contract.clock is not None and abs(float(at) - last_time - contract.clock.period_ns) > 0.0011:
            raise _EvidenceError("sample_time_gap_mismatch")
        last_time = float(at)
        for group, direction in (("inputs", "input"), ("outputs", "output")):
            ports = {port.name: port for port in contract.ports if port.direction.value == direction}
            actual = sample[group]
            if not isinstance(actual, dict) or set(actual) != set(ports):
                raise _EvidenceError("sample_port_mismatch")
            for name, port in ports.items():
                bits = actual[name]
                if not isinstance(bits, str) or len(bits) != port.width or any(bit not in "01xz" for bit in bits):
                    raise _EvidenceError("sample_bits_mismatch")
        for name, value in vector.inputs.items():
            driven_port = contract.port_map.get(name)
            if driven_port is None or not driven_port.is_input or (contract.clock is not None and name == contract.clock.signal):
                raise _EvidenceError("invalid_plan_input")
            held[name] = _encode_value(driven_port, value, context="feedback.inputs").bits
        if sample["inputs"] != held:
            raise _EvidenceError("observed_inputs_do_not_match_held_plan")
    return samples


def build_observation_feedback(result: PipelineResult, *, rtl_sha256: str) -> dict[str, Any]:
    """Return only bound actual port data; artifact errors never disclose paths/text.

    The trusted caller supplies the already-bound RTL SHA. The helper reads only
    observation, executor process record, plan, contract and testbench artifacts,
    never the RTL itself or expected-output fields for sample selection.
    ``complete`` describes the full evidence stream, not exhaustive correctness
    or full transmission: at most twelve uniformly selected samples are returned.
    """
    report: dict[str, Any] = {
        "schema_version": "1.0", "feedback_type": "port_observations",
        "source": "testbench_sample_statement", "status": "inconclusive", "reason": None,
        "sampling_phase": "after", "selection": "endpoints_uniform_v1",
        "total_samples": 0, "returned_samples": 0, "omitted_samples": 0,
        "contains_unknown_bits": None, "input_bits_known": None, "output_bits_known": None,
        "samples": [], "provenance": {}, "execution": {}, "disclaimer": DISCLAIMER,
    }
    try:
        if not isinstance(result, PipelineResult) or not isinstance(result.contract, DutContract):
            raise _EvidenceError("unsupported_result_contract")
        contract = result.contract
        if any(port.direction.value == "inout" for port in contract.ports):
            raise _EvidenceError("inout_observations_unsupported")
        if not contract.outputs or result.plan.design != contract.module:
            raise _EvidenceError("unsupported_result_contract")
        if any(vector.sample_phase != "after" for vector in result.plan.vectors):
            raise _EvidenceError("unsupported_sampling_phase")
        compile_result, run = result.simulation.compile, result.simulation.run
        if not _complete(compile_result) or not _complete(run) or run is None or not isinstance(run.stdout, str) or not run.stdout:
            raise _EvidenceError("execution_not_complete")
        run_id = result.simulation.run_id
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", run_id):
            raise _EvidenceError("invalid_execution_identity")
        if not isinstance(rtl_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", rtl_sha256):
            raise _EvidenceError("provenance_mismatch")
        artifacts = result.artifacts
        execution_raw = _read(artifacts["result_json"], code="execution_record_unavailable")
        execution_record = json.loads(execution_raw)
        if (not isinstance(execution_record, dict) or execution_record.get("run_id") != run_id
                or execution_record.get("compile") != compile_result.to_dict()
                or execution_record.get("run") != run.to_dict()):
            raise _EvidenceError("execution_record_mismatch")
        raw = _read(artifacts["observed_samples"], code="observations_unavailable_or_oversized")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise _EvidenceError("invalid_observation_document")
        saved_digest = result.simulation.config.get("observed_samples", {}).get("sha256")
        if not isinstance(saved_digest, str) or saved_digest != _sha(raw):
            raise _EvidenceError("observed_samples_digest_mismatch")
        hashes = {"rtl_sha256": rtl_sha256}
        inputs: dict[str, bytes] = {}
        for name, key in (("plan_sha256", "testplan"), ("contract_sha256", "dut_contract"), ("testbench_sha256", "testbench")):
            inputs[key] = _read(artifacts[key], code="provenance_artifact_unavailable")
            hashes[name] = _sha(inputs[key])
        saved_config = execution_record.get("config")
        if (not isinstance(saved_config, dict)
                or any(result.simulation.config.get(name) != hashes[name] or saved_config.get(name) != hashes[name]
                       for name in ("rtl_sha256", "testbench_sha256"))):
            raise _EvidenceError("execution_input_digest_mismatch")
        if payload.get("provenance") != hashes:
            raise _EvidenceError("provenance_mismatch")
        if json.loads(inputs["testplan"]) != result.plan.model_dump(mode="json") or json.loads(inputs["dut_contract"]) != contract.to_dict():
            raise _EvidenceError("provenance_semantic_mismatch")
        rebuilt = collect_observed_samples(run.stdout, result.plan, contract, provenance=hashes,
                                           execution_complete=True, output_truncated=False)
        if payload != rebuilt:
            raise _EvidenceError("observed_samples_stdout_mismatch")
        samples = _validate_rows(result, payload)
        known = {group: all("x" not in bits and "z" not in bits for sample in samples for bits in sample[group].values())
                 for group in ("inputs", "outputs")}
        indices = _uniform_indices(len(samples))
        report.update(status="complete", total_samples=len(samples), returned_samples=len(indices),
                      omitted_samples=len(samples) - len(indices), samples=[samples[index] for index in indices],
                      contains_unknown_bits=not all(known.values()), input_bits_known=known["inputs"], output_bits_known=known["outputs"],
                      provenance={**hashes, "observed_samples_sha256": saved_digest,
                                  "run_stdout_sha256": _sha(run.stdout.encode("utf-8")),
                                  "executor_result_sha256": _sha(execution_raw)},
                      execution={"run_id": run_id, "compile_status": compile_result.status.value, "compile_returncode": 0,
                                 "run_status": run.status.value, "run_returncode": 0})
        # Indented representation is the larger usual caller serialization.
        if len(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)) > MAX_FEEDBACK_CHARACTERS:
            raise _EvidenceError("feedback_size_limit")
    except _EvidenceError as exc:
        report.update(status="inconclusive", reason=str(exc), samples=[], returned_samples=0,
                      omitted_samples=report["total_samples"], provenance={}, execution={},
                      contains_unknown_bits=None, input_bits_known=None, output_bits_known=None)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        report.update(status="inconclusive", reason="observations_unavailable_or_invalid", samples=[],
                      returned_samples=0, omitted_samples=report["total_samples"], provenance={}, execution={},
                      contains_unknown_bits=None, input_bits_known=None, output_bits_known=None)
    return report


__all__ = ["MAX_FEEDBACK_CHARACTERS", "MAX_FEEDBACK_SAMPLES", "build_observation_feedback"]
