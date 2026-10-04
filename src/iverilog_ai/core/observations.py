"""Strict, read-only observations from the generated testbench sampling point.

These are execution facts, separate from assertion checks and VCD activity.
Unknown bit values remain unknown; partial or ambiguous samples never describe
a complete run. Enabling collection does not alter stimuli or sampling delays.
"""
from __future__ import annotations

import json
import math
from typing import Any

from ..ai.schema import TestPlan
from .contracts import DutContract

OBSERVATION_PREFIX = "IVERILOG_AI_OBSERVATION "


def collect_observed_samples(
    stdout: str,
    plan: TestPlan,
    contract: DutContract,
    *,
    provenance: dict[str, str],
    execution_complete: bool,
    output_truncated: bool = False,
) -> dict[str, Any]:
    """Require exactly one ordered, width-checked sample per planned cycle."""
    expected = [(vector.name, vector.sample_phase)
                for vector in plan.vectors for _ in range(vector.cycles)]
    ports = {
        kind + "s": {port.name: port.width for port in contract.ports if port.direction.value == kind}
        for kind in ("input", "output")
    }
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    observed_lines = 0
    last_time = -1.0
    for line in stdout.splitlines():
        if not line.startswith(OBSERVATION_PREFIX):
            continue
        observed_lines += 1
        try:
            raw = json.loads(line[len(OBSERVATION_PREFIX):])
            if not isinstance(raw, dict) or set(raw) != {"cycle", "time_ns", "test_id", "sample_phase", "inputs", "outputs"}:
                raise ValueError("invalid_sample_fields")
            cycle = raw["cycle"]
            if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle != observed_lines - 1 or cycle >= len(expected):
                raise ValueError("sample_cycle_mismatch")
            if (raw["test_id"], raw["sample_phase"]) != expected[cycle]:
                raise ValueError("sample_plan_mismatch")
            at = raw["time_ns"]
            if (isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at)
                    or at <= last_time):
                raise ValueError("sample_time_mismatch")
            for group, widths in ports.items():
                bits = raw[group]
                if not isinstance(bits, dict) or set(bits) != set(widths):
                    raise ValueError("sample_port_mismatch")
                for signal, width in widths.items():
                    value = bits[signal]
                    if (not isinstance(value, str) or len(value) != width
                            or any(c not in "01xXzZ" for c in value)):
                        raise ValueError("sample_bit_value_invalid")
                    bits[signal] = value.lower()
            last_time = float(at)
            samples.append(raw)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("sample_") else "invalid_sample_json"
            if code not in errors:
                errors.append(code)
    if observed_lines != len(expected) or len(samples) != len(expected):
        errors.append("sample_count_mismatch")
    if not execution_complete:
        errors.append("execution_incomplete")
    if output_truncated:
        errors.append("output_truncated")
    if any(port.direction.value == "inout" for port in contract.ports):
        errors.append("inout_observations_unsupported")
    return {
        "schema_version": "1.0",
        "source": "testbench_sample_statement",
        "status": "complete" if not errors else "inconclusive",
        "expected_cycles": len(expected),
        "observed_cycles": len(samples),
        "errors": list(dict.fromkeys(errors)),
        "provenance": dict(provenance),
        "samples": samples,
        "limitations": ["Port observations are not assertion checks or proof of correctness",
                        "Unknown x/z bits remain unknown", "Stimulus cycles exclude initial reset"],
    }
