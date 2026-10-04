"""Shared study-spec rendering, using public files and local fixtures only."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.agent_study_specs import OLD_BUDGET_PREFIX, STUDY_SPEC_PROFILE, render_study_spec


CASES = (("sync_fifo", 16), ("uart_tx", 48), ("spi_master", 20), ("handshake_stage", 8))
TIMING_MARKERS = {
    "sync_fifo": ("DEPTH=4", "净变化为 **0**", "边沿前的空满状态"),
    "uart_tx": ("CLKS_PER_BIT=4", "E40 后", "E41"),
    "spi_master": ("WIDTH=8", "E15", "E16", "17 个采样边沿"),
    "handshake_stage": ("in_valid && in_ready", "out_valid && out_ready", "out_data 保持上次数据"),
}


@pytest.mark.parametrize("case,cycles", CASES)
def test_public_spec_keeps_all_text_except_exact_old_budget_and_is_read_only(case, cycles):
    path = ROOT / "spec" / f"{case}_spec.md"
    before = path.read_bytes()
    original = before.decode("utf-8")
    old_lines = [line for line in original.splitlines(keepends=True)
                 if line.startswith(OLD_BUDGET_PREFIX[case])]
    assert len(old_lines) == 1
    body = original.replace(old_lines[0], "", 1)
    result = render_study_spec(case, cycles, original)
    assert result.endswith(body)
    assert OLD_BUDGET_PREFIX[case] not in result
    assert f"is {cycles} cycles across all executed" in result
    assert all(marker in result for marker in TIMING_MARKERS[case])
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
    assert render_study_spec(case, cycles, original) == result


@pytest.mark.parametrize("case,cycles", CASES)
def test_strategy_neutral_guidance_preserves_model_choice_and_strict_decision_schema(case, cycles):
    original = f"# Fixture\n\n{OLD_BUDGET_PREFIX[case]} old scope.\n\nUnchanged timing.\n"
    text = render_study_spec(case, cycles, original)
    assert "max_new_cycles" in text and "remaining_stimulus_cycles" in text
    assert "remaining_rounds" in text and "request cap" in text
    assert "independent" in text and "not continued or replayed" in text
    assert "sample_phase=after" in text and "known binary input" in text
    assert "automatic initial reset is outside stimulus accounting" in text
    assert "manually proposed reset" in text
    assert "top-level action, reason and vectors" in text
    assert "privately" in text and "Do not add vector_count" in text
    assert "combined prompt optimization" in text and "development-set comparison" in text
    assert "single-factor causal effect" in text and "held-out generalization" in text
    for banned in ("one API proposal", "first-proposal", "fifo_bug_", "uart_bug_", "spi_bug_",
                   "handshake_bug_", '"inputs":', '"expected":'):
        assert banned not in text
    assert STUDY_SPEC_PROFILE == "short-budget-protocol-priority-combined-v1"


@pytest.mark.parametrize("case,cycles", CASES)
def test_old_budget_paragraph_can_wrap_without_consuming_the_next_semantics(case, cycles):
    continuation = "continued old budget rationale.\n"
    if OLD_BUDGET_PREFIX[case].startswith("- "):
        continuation = "  " + continuation
    original = ("Unchanged start.\n\n" + OLD_BUDGET_PREFIX[case] + " old rationale.\n"
                + continuation + "\nUnchanged end.\n")
    result = render_study_spec(case, cycles, original)
    assert result.endswith("Unchanged start.\n\n\nUnchanged end.\n")
    assert "old rationale" not in result and "continued old budget" not in result


def test_adjacent_list_items_and_unrelated_historical_budgets_are_preserved():
    original = ("Historical 160-cycle result remains recorded.\n\n"
                "- Preserve first protocol item.\n"
                + OLD_BUDGET_PREFIX["sync_fifo"] + " old budget rationale.\n"
                "- Preserve next protocol item.\n")
    text = render_study_spec("sync_fifo", 16, original)
    assert text.endswith("Historical 160-cycle result remains recorded.\n\n"
                         "- Preserve first protocol item.\n- Preserve next protocol item.\n")


def test_crlf_and_a_source_without_final_newline_are_retained():
    original = "Before.\r\n\r\n" + OLD_BUDGET_PREFIX["uart_tx"] + " budget.\r\n\r\nAfter."
    text = render_study_spec("uart_tx", 48, original)
    assert text.endswith("Before.\r\n\r\n\r\nAfter.")
    assert "\n" not in text.replace("\r\n", "")
    assert not text.endswith("\n")


@pytest.mark.parametrize("case,cycles", CASES)
@pytest.mark.parametrize("count", [0, 2])
def test_absent_or_duplicate_old_budget_fails_instead_of_sending_conflicting_text(case, cycles, count):
    original = "Protocol remains.\n\n" + (OLD_BUDGET_PREFIX[case] + " obsolete.\n\n") * count
    with pytest.raises(ValueError, match="exactly one old budget paragraph"):
        render_study_spec(case, cycles, original)


@pytest.mark.parametrize("case", ["unknown", None, {}, True])
def test_unknown_case_is_rejected(case):
    with pytest.raises(ValueError, match="four supported study modules"):
        render_study_spec(case, 16, "source")


@pytest.mark.parametrize("cycles", [0, -1, True, "16", 1.5, None])
def test_cycle_cap_requires_a_positive_integer(cycles):
    with pytest.raises(ValueError, match="positive integer"):
        render_study_spec("sync_fifo", cycles, "source")


@pytest.mark.parametrize("original", ["", None, b"source"])
def test_original_source_requires_text(original):
    with pytest.raises(ValueError, match="nonempty text"):
        render_study_spec("sync_fifo", 16, original)
