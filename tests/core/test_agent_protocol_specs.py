"""Protocol metadata must remain compatible with actual case contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.reference_model import INPUT_DEFAULTS

ROOT = Path(__file__).resolve().parents[2]
PROTOCOLS = json.loads((ROOT / "spec/agent_protocols.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", ("sync_fifo", "uart_tx", "spi_master", "handshake_stage"))
def test_protocol_metadata_matches_case_contract_and_has_a_complete_spec(case):
    assert PROTOCOLS["schema_version"] == "agent-protocols-v1"
    metadata = PROTOCOLS["cases"][case]
    contract = DutContract.from_dict(json.loads((ROOT / f"examples/{case}_contract.json").read_text()))
    assert metadata["default_parameters"] == contract.parameters
    assert metadata["input_defaults"] == INPUT_DEFAULTS[case]
    path = (ROOT / metadata["spec_path"]).resolve()
    assert path.is_relative_to(ROOT / "spec") and path.is_file()
    text = path.read_text(encoding="utf-8")
    assert len(text) >= 1000 and "复位" in text and "sample_phase=after" in text
    assert metadata["cycle_budget"] >= 3 * metadata["timing"].get("minimum_frame_observation_cycles", 1)


def test_uart_budget_contains_acceptance_completion_and_multiple_frames():
    metadata = PROTOCOLS["cases"]["uart_tx"]
    period = metadata["default_parameters"]["CLKS_PER_BIT"]
    # A 40-cycle vector ending at E39 does not check E40 busy release.
    assert metadata["timing"]["minimum_frame_observation_cycles"] == 10 * period + 1
    assert metadata["cycle_budget"] > 40


def test_fifo_spec_records_corrected_count_and_retains_historical_version_boundary():
    metadata = PROTOCOLS["cases"]["sync_fifo"]
    assert metadata["timing"]["simultaneous_accepted_count_delta"] == 0
    text = (ROOT / metadata["spec_path"]).read_text(encoding="utf-8")
    assert "净变化为 **0**" in text and "旧成绩不追溯改写" in text


def test_v2_fifo_controls_have_exactly_one_registered_mutation_and_verified_provenance():
    import hashlib

    manifest = json.loads((ROOT / "benchmarks/agent_v2/mutation_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "agent-v2-mutations-v1"
    assert manifest["independent_holdout"] is False
    baseline = manifest["baseline"]
    source = (ROOT / baseline["path"]).read_bytes()
    assert source == (ROOT / baseline["snapshot_path"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == baseline["sha256"]
    assert len(manifest["defects"]) == manifest["defect_count"] == 2
    old = json.loads((ROOT / "benchmarks/manifest.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in manifest["defects"]] == [d["id"] for d in old["defects"] if d["type"] == "sync_fifo"][:2]
    for item in manifest["defects"]:
        operator = item["operator"]
        anchor, replacement = operator["anchor"].encode(), operator["replacement"].encode()
        assert source.count(anchor) == operator["expected_occurrences"] == 1
        # Stronger than token equivalence: all bytes outside that one operator
        # remain identical, including the corrected simultaneous-operation case.
        candidate = (ROOT / item["file"]).read_bytes()
        assert candidate == source.replace(anchor, replacement, 1)
        assert hashlib.sha256(candidate).hexdigest() == item["sha256"]
        assert hashlib.sha256((ROOT / item["legacy_file"]).read_bytes()).hexdigest() == item["legacy_sha256"]
        assert source[:operator["byte_offset"]].count(b"\n") + 1 == operator["source_line"]
