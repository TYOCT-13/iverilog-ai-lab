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
