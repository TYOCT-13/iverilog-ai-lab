from iverilog_ai.core.models import FailureRecord, ResultRecord
from iverilog_ai.core.waveform import render_failure_window, summarize_failure_window


def test_summary_selects_deterministic_failure_window():
    records = (
        ResultRecord(ok=True, test_id="t", cycle=1, signal="q", expected=0, actual=0),
        ResultRecord(ok=False, test_id="t", cycle=3, signal="q", expected=1, actual=0, severity="warn"),
        ResultRecord(ok=True, test_id="t", cycle=5, signal="q", expected=1, actual=1),
    )
    failure = FailureRecord("t", 3, "q", 1, 0, "m", "warn")
    summary = summarize_failure_window(records, (failure,), radius=1)
    assert summary["failure_cycles"] == [3]
    assert [r["cycle"] for r in summary["rows"]] == [3]
    assert "失败周期：3" in render_failure_window(summary)


def test_summary_handles_missing_cycle_and_truncation():
    records = [ResultRecord(ok=True, test_id="t", cycle=i) for i in range(10)]
    failure = FailureRecord("t", None, None, None, None, "unknown", "warn")
    summary = summarize_failure_window(records, [failure], max_rows=2)
    assert summary["rows"] == []
    assert len(summary["uncorrelated_failures"]) == 1


def test_summary_rejects_invalid_limits():
    try:
        summarize_failure_window([], radius=-1)
    except ValueError as exc:
        assert "radius" in str(exc)
    else:
        raise AssertionError("expected ValueError")
