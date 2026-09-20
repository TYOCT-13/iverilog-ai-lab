"""三层结论口径的措辞门禁。

真实事故：同一份 result.json 里 `status="passed_with_warnings"`、`passed=true`、
`failures=3`、`verdict="failed_checks"` 并存。因为 `status` 与 `verdict` 的取值**同名**，
而且"成功检出 3 个缺陷"的正常运行里 `passed` 也是 `true`，读者会把检出读成通过、
把工具故障读成设计错误。修法不是改机器字段名（会破坏已发布的 JSON 合约），
而是给每一层一套**互不重叠**的中文说法，并禁止报告/页面各写一套。

这里钉住四件事：
1. 枚举取值全覆盖——新增一个 `ResultStatus` 或证据等级而忘了配中文，测试立刻失败；
2. 三层**不共用任何词**——共用就说明两层又被混在一起了；
3. 三层的中文说法里**不出现"通过"**——那是最容易被读成"设计对了"的词；
4. 措辞只有一处定义——报告与页面都必须从 `core.labels` 取，不得自带一份。
"""
from __future__ import annotations

import itertools
from pathlib import Path

from iverilog_ai.core.labels import (
    COMPARE_LABELS,
    EVIDENCE_LABELS,
    LAYER_NAMES,
    RUN_STATUS_LABELS,
    VERDICT_LABELS,
    evidence_label,
    layered_conclusion,
    run_status_label,
    verdict_label,
)
from iverilog_ai.core.models import (
    FailureRecord,
    ProcessResult,
    ProcessStatus,
    ResultRecord,
    ResultStatus,
    SimulationResult,
)
from iverilog_ai.core.report import render_html, render_markdown

ROOT = Path(__file__).resolve().parents[2]


def test_every_result_status_has_a_chinese_label() -> None:
    """`ResultStatus` 的每个成员都必须有中文说法，且表里不能有多余的键。"""

    assert {item.value for item in ResultStatus} == set(RUN_STATUS_LABELS), (
        sorted({item.value for item in ResultStatus}),
        sorted(RUN_STATUS_LABELS),
    )


def test_every_verdict_value_has_a_chinese_label() -> None:
    """`verdict` 的取值集合由 `SimulationResult.verdict` 决定，必须与表一致。"""

    assert set(VERDICT_LABELS) == {"passed", "failed_checks", "failed", "inconclusive"}, sorted(VERDICT_LABELS)


def test_every_evidence_level_has_a_chinese_label() -> None:
    """证据等级三态（pipeline 写入 `oracle.expectation_source` 的三个取值）。"""

    assert set(EVIDENCE_LABELS) == {"reference_model", "ai_generated", "none_given"}, sorted(EVIDENCE_LABELS)


def test_labels_of_different_layers_share_no_word() -> None:
    """三层不得共用任何一条说法——共用就意味着两层又被写成了同一件事。"""

    layers = {
        "run": set(RUN_STATUS_LABELS.values()),
        "compare": set(COMPARE_LABELS.values()),
        "design": set(VERDICT_LABELS.values()),
    }
    for left, right in itertools.combinations(sorted(layers), 2):
        shared = layers[left] & layers[right]
        assert not shared, f"{left} 与 {right} 共用了说法：{sorted(shared)}"


def test_no_layer_label_says_tongguo() -> None:
    """三层的中文说法里不能出现「通过」。

    「通过」是歧义的来源：`status.passed`、`passed=true`、`verdict.passed` 三处都会被读成
    "设计对了"，而其中只有第三处是这个意思。三层改说"运行完成 / 比对一致 / 符合预期"后，
    读者看到哪个词就知道是哪一层。
    """

    for table in (RUN_STATUS_LABELS, VERDICT_LABELS):
        for key, value in table.items():
            assert "通过" not in value, f"{key} → {value} 含「通过」"


def test_labels_module_is_the_single_source_of_truth() -> None:
    """报告与页面必须从 `core.labels` 取措辞，不得自带一份中文表。"""

    report = (ROOT / "src" / "iverilog_ai" / "core" / "report.py").read_text(encoding="utf-8")
    assert "from .labels import" in report
    # 旧的两处本地措辞表必须已经删掉，否则会出现"同一个 passed 两种说法"。
    assert "_VERDICT_LABELS" not in report
    assert "总体状态" not in report

    ui = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert "from iverilog_ai.core.labels import" in ui
    assert "_render_run_conclusion" in ui


def test_unknown_values_are_not_silently_mapped() -> None:
    """表里没有的取值要**显式标出未知**，不能兜底成某个已知说法。"""

    assert "未收录" in run_status_label("brand_new_status")
    assert "未收录" in verdict_label("brand_new_verdict")
    assert "未收录" in evidence_label("brand_new_level")


def test_layered_conclusion_separates_three_layers() -> None:
    """一句三层的话必须点名三层，且检出缺陷时不能出现"符合预期"。"""

    good = layered_conclusion(ResultStatus.PASSED, "passed", 0)
    assert "运行状态：运行完成" in good and "设计结果：符合预期" in good

    detected = layered_conclusion(ResultStatus.PASSED_WITH_WARNINGS, "failed_checks", 3)
    assert "运行完成（有告警）" in detected
    assert "3 条比对不一致" in detected and "无错误级失败" in detected
    assert "检出设计问题" in detected
    assert "符合预期" not in detected

    tool_error = layered_conclusion(ResultStatus.COMPILE_FAILED, "failed", 0)
    assert "编译失败" in tool_error and "未得出结论（工具出错）" in tool_error


def _detected_result() -> SimulationResult:
    """一次"成功检出 3 个非 error 级不匹配"的运行：status/passed/verdict 三者看似矛盾。"""

    process = ProcessResult(status=ProcessStatus.PASSED, returncode=0, command=("iverilog",), stdout="ok")
    records = tuple(
        ResultRecord(
            ok=False,
            test_id=f"vector_{index}",
            cycle=index,
            signal="q",
            expected="<0>",
            actual="<1>",
            message="<unexpected>",
        )
        for index in range(3)
    )
    return SimulationResult(
        run_id="labels-gate",
        status=ResultStatus.PASSED_WITH_WARNINGS,
        compile=process,
        run=process,
        records=records,
        failures=tuple(FailureRecord.from_result(item) for item in records),
    )


def test_reports_read_the_three_layers_apart() -> None:
    """端到端：报告里三层各自出现，且不再用"总体状态/结论"这种含糊标题。"""

    result = _detected_result()
    assert result.passed is True and result.verdict == "failed_checks"

    markdown = render_markdown(result)
    assert "运行状态：运行完成（有告警）（`passed_with_warnings`）" in markdown
    assert "设计结果：检出设计问题（`failed_checks`），3 条比对不一致" in markdown
    assert "比对情况：" in markdown and "条比对一致" in markdown
    assert "总体状态" not in markdown
    # 旧口径下这里会写成"结论：仿真跑通，但存在检查不匹配"，读者最容易把它当成"失败"。
    assert "结论：" not in markdown.replace("证据结论：", "")

    html = render_html(result)
    assert "运行状态：" in html and "设计结果：" in html
    assert "总体状态" not in html


def test_report_evidence_level_is_chinese() -> None:
    """证据等级在报告里也必须用中文说法（这是第 4 项要求的落点之一）。"""

    process = ProcessResult(status=ProcessStatus.PASSED, returncode=0, command=("iverilog",), stdout="ok")
    result = SimulationResult(
        run_id="labels-evidence",
        status=ResultStatus.PASSED,
        compile=process,
        run=process,
        records=(ResultRecord(ok=True, test_id="v1", cycle=0, signal="q", expected="<0>", actual="<0>", message=""),),
        failures=(),
        config={"oracle": {"expectation_source": "ai_generated", "evidence_level": "ai_generated"}},
    )
    markdown = render_markdown(result)
    assert "证据等级：AI 生成（`ai_generated`）" in markdown
    assert "证据等级：`ai_generated`" not in markdown


def test_layer_names_describe_the_three_questions() -> None:
    """层的正式名称与它们回答的问题也要固定下来，手册与页面共用。"""

    assert LAYER_NAMES["run"]["zh"] == "运行状态"
    assert LAYER_NAMES["design"]["zh"] == "设计结果"
    assert LAYER_NAMES["compare"]["question"]
    for item in LAYER_NAMES.values():
        assert item["field"]
