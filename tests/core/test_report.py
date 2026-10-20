from iverilog_ai.core.models import ProcessResult, ProcessStatus, ResultRecord, ResultStatus, SimulationResult
from iverilog_ai.core.report import render_html, render_markdown


def _result() -> SimulationResult:
    process = ProcessResult(
        status=ProcessStatus.PASSED,
        returncode=0,
        command=("iverilog",),
        stdout="ok",
    )
    record = ResultRecord(
        ok=False,
        test_id="x",
        cycle=3,
        signal="q",
        expected="<0>",
        actual="<1>",
        message="<unexpected>",
    )
    from iverilog_ai.core.models import FailureRecord

    return SimulationResult(
        run_id="abc",
        status=ResultStatus.FAILED,
        compile=process,
        run=process,
        records=(record,),
        failures=(FailureRecord.from_result(record),),
    )


def test_reports_include_failure_and_escape_html():
    result = _result()
    markdown = render_markdown(result)
    html = render_html(result)
    assert "abc" in markdown and "unexpected" in markdown
    assert "&lt;unexpected&gt;" in html


def test_report_discloses_bounded_window_preview_without_hiding_failure():
    from dataclasses import replace

    result = replace(_result(), config={"vcd_analysis": {"status": "parsed", "failure_windows": {
        "status": "parsed", "truncated": True, "returned_windows": 64, "requested_windows": 80,
        "windows": [{"cycle": 3, "start_ns": 20, "end_ns": 50, "analysis": {}}]}}})
    markdown = render_markdown(result)
    assert "失败窗口预览 64/80" in markdown
    assert "完整失败列表和原始VCD保留" in markdown
    assert "unexpected" in markdown
