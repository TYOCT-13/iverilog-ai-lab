"""`SimulationResult.verdict`：把 `passed` 的歧义收敛成一个结论词。

背景（真实事故）：按裁决策略，功能不匹配记为 WARN，所以一次"检出 3 个缺陷"的运行
会输出 `status="passed_with_warnings"`、`passed=True`、`failures=3`。只看 `passed`
的人会以为设计通过了。`verdict` 就是为此存在的单一结论词。
"""

from __future__ import annotations

import pytest

from iverilog_ai.core.models import (
    FailureRecord,
    ProcessResult,
    ProcessStatus,
    ResultStatus,
    SimulationResult,
)


def _result(status: ResultStatus, failures: tuple[FailureRecord, ...] = ()) -> SimulationResult:
    process = ProcessResult(status=ProcessStatus.PASSED, returncode=0, command=("iverilog",))
    return SimulationResult(run_id="t", status=status, compile=process, run=process, failures=failures)

VERDICT_CASES = [
    (ResultStatus.PASSED, False, "passed"),
    (ResultStatus.PASSED, True, "passed"),
    # 仿真跑通但有功能不匹配 = 缺陷被检出
    (ResultStatus.PASSED_WITH_WARNINGS, True, "failed_checks"),
    # 有警告但没有不匹配记录：仍然算 passed
    (ResultStatus.PASSED_WITH_WARNINGS, False, "passed"),
    (ResultStatus.FAILED, True, "failed"),
    (ResultStatus.COMPILE_FAILED, False, "failed"),
    (ResultStatus.CONFIGURATION_ERROR, False, "failed"),
    (ResultStatus.TIMEOUT, False, "inconclusive"),
    (ResultStatus.INCONCLUSIVE, False, "inconclusive"),
]


@pytest.mark.parametrize(
    "status,has_failure,expected",
    VERDICT_CASES,
    ids=[f"{status.value}-{expected}" for status, _has, expected in VERDICT_CASES],
)
def test_verdict_maps_every_status(status, has_failure, expected):
    failures = (
        (
            FailureRecord(
                test_id="check",
                cycle=1,
                signal="q",
                expected=1,
                actual=0,
                message="mismatch",
            ),
        )
        if has_failure
        else ()
    )
    assert _result(status, failures).verdict == expected


def test_verdict_is_serialized_alongside_passed():
    payload = _result(ResultStatus.PASSED).to_dict()
    assert payload["verdict"] == "passed"
    assert payload["passed"] is True


def test_every_status_value_is_covered_by_the_mapping():
    """新增状态时必须显式决定它的结论词，而不是默默落进 inconclusive。"""

    covered = {status for status, _has, _expected in VERDICT_CASES}
    assert covered == set(ResultStatus), f"未覆盖的状态：{set(ResultStatus) - covered}"
