"""测试用伪 API 记录只存在于 tmp_path，不能当作真实模型实验。"""
import json
from pathlib import Path

import pytest

from iverilog_ai.ai.agent import PROMPT_VERSION
from scripts.export_agent_trajectories import export, main


def trace(tmp_path, family, *, kind="api", source="reference_model", executed=True, rtl_hash=None):
    payload = {"schema_version": "1.0", "prompt_version": PROMPT_VERSION, "record_kind": kind,
               "design_family": family, "rtl_sha256": rtl_hash or family,
               "rounds": [{"round": 1, "observation": {"expectation_source": source, "checks": 3, "status": "passed", "verdict": "passed"}}],
               "decisions": [{"status": "validated", "executed_round": 1 if executed else None,
                              "state": {"design": family}, "action": {"action": "append_vectors", "reason": "test fixture", "vectors": [{"name": "x", "inputs": {"a": 0}}]}}]}
    path = tmp_path / f"{family}-{kind}-{source}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_export_splits_whole_design_families_and_deduplicates_paths(tmp_path):
    first = trace(tmp_path, "counter")
    second = trace(tmp_path, "fifo")
    output = tmp_path / "dataset"
    summary = export([first, first, second], output, {"fifo"})
    assert summary["counts"] == {"train": 1, "validation": 1}
    assert summary["families"] == {"train": ["counter"], "validation": ["fifo"]}
    example = json.loads((output / "train.jsonl").read_text())
    assert example["review_status"] == "pending"
    assert example["messages"][-1]["role"] == "assistant"


@pytest.mark.parametrize("options", [{"kind": "test_provider"}, {"source": "ai_generated"}, {"executed": False}])
def test_untrusted_unexecuted_and_test_records_are_not_training_evidence(tmp_path, options):
    first = trace(tmp_path, "counter", **options)
    second = trace(tmp_path, "fifo")
    with pytest.raises(ValueError, match="both train and validation"):
        export([first, second], tmp_path / "out", {"fifo"})
    assert not (tmp_path / "out").exists()


def test_rejects_identical_rtl_disguised_as_another_family(tmp_path):
    first = trace(tmp_path, "counter", rtl_hash="same-content")
    second = trace(tmp_path, "fifo", rtl_hash="same-content")
    with pytest.raises(ValueError, match="overlaps"):
        export([first, second], tmp_path / "out", {"fifo"})


def test_never_overwrites_a_previous_dataset(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        export([], output, {"fifo"})


def test_windows_wildcards_and_no_match(tmp_path):
    trace(tmp_path, "counter")
    trace(tmp_path, "fifo")
    assert main([str(tmp_path / "*.json"), "--holdout-designs", "fifo", "--output-dir", str(tmp_path / "out")]) == 0
    assert main([str(tmp_path / "missing-*.json"), "--holdout-designs", "fifo", "--output-dir", str(tmp_path / "absent")]) == 2
