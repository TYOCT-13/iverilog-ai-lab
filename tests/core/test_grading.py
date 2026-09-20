"""批量批改与相似度的回归测试。

这一层最危险的不是算错，而是**被当成"自动判抄袭"**。所以除了功能，用例还钉住两件事：
① 报告里必须带"这不是抄袭判定"的声明；② 相似度只用于挑线索，不产生任何分数或判决。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.grading import (
    DISCLAIMER,
    collect_submissions,
    grade_submissions,
    summarise,
)
from iverilog_ai.core.rtl_compare import source_similarity, token_shingles

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "rtl" / "mod10_counter.v"
BUG = ROOT / "rtl" / "mod10_counter_bug_wrap9.v"
OTHER = ROOT / "rtl" / "pwm.v"

pytestmark = pytest.mark.skipif(not GOLDEN.is_file(), reason="需要仓库内的参考 RTL")


# ------------------------------------------------------------------ 相似度


def test_similarity_is_one_for_the_same_source() -> None:
    source = GOLDEN.read_text(encoding="utf-8")
    assert source_similarity(source, source) == {"raw": 1.0, "normalized": 1.0}


def test_similarity_separates_renamed_copy_from_different_design() -> None:
    """归一化高、逐字低 = 改名抄；两列都低 = 各写各的。这是整张表的核心信号。"""

    golden = GOLDEN.read_text(encoding="utf-8")
    other = OTHER.read_text(encoding="utf-8")
    renamed = golden.replace("count", "cnt").replace("enable", "en")
    renamed_score = source_similarity(golden, renamed)
    assert renamed_score["normalized"] > 0.95, renamed_score
    assert renamed_score["raw"] < 0.6, renamed_score

    different = source_similarity(golden, other)
    assert different["normalized"] < 0.4, different
    assert different["raw"] < 0.4, different


def test_comments_do_not_change_similarity() -> None:
    """注释不该影响相似度：它既不该抬高（抄注释）也不该压低（自己的注释）。"""

    golden = GOLDEN.read_text(encoding="utf-8")
    commented = "// 这是我写的注释\n" + golden + "\n// 结尾注释\n"
    assert source_similarity(golden, commented)["raw"] == pytest.approx(1.0)


def test_token_shingles_handles_tiny_sources() -> None:
    """极短源码不能崩，也不能返回空集合导致被判成"完全不同"。"""

    assert token_shingles("") == frozenset()
    assert token_shingles("module m;") != frozenset()
    assert source_similarity("", "")["raw"] == 0.0


# ------------------------------------------------------------------ 批量


def _make_batch(tmp_path: Path) -> Path:
    batch = tmp_path / "submissions"
    batch.mkdir()
    (batch / "a_identical.v").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    (batch / "b_different.v").write_text(BUG.read_text(encoding="utf-8"), encoding="utf-8")
    (batch / "c_renamed.v").write_text(
        GOLDEN.read_text(encoding="utf-8").replace("count", "cnt"), encoding="utf-8"
    )
    (batch / "notes.txt").write_text("这不是 RTL，应被忽略", encoding="utf-8")
    return batch


def test_collect_submissions_filters_and_sorts(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    names = [item.name for item in collect_submissions(batch)]
    assert names == ["a_identical.v", "b_different.v", "c_renamed.v"]
    assert collect_submissions(batch, recursive=True)  # 递归也不能把 .txt 收进来


def test_collect_submissions_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        collect_submissions(tmp_path / "nope")


@pytest.fixture(scope="module")
def batch_report(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("grading")
    batch = _make_batch(tmp)
    return grade_submissions(batch, GOLDEN, tmp / "out")


def test_grade_classifies_each_submission(batch_report) -> None:
    """同一批里三种结论要被分开，且跳过非 RTL 文件。

    `c_renamed.v` 是"把标准实现的端口名改了"——它**不是**行为不同，而是**没法对比**：
    端口对不上，testbench 连不上，候选一条记录都没产出来。这两者在批改里必须分开，
    否则学生看到的会是"你的逻辑和标准不一致"，而实际上他的模块根本没跑起来。
    """

    assert len(batch_report.rows) == 3
    by_name = {item.name: item for item in batch_report.rows}
    assert by_name["a_identical.v"].status == "identical"
    assert by_name["b_different.v"].status == "different"
    assert by_name["b_different.v"].differences > 0
    assert by_name["c_renamed.v"].status == "inconclusive"
    assert batch_report.identical == 1
    assert batch_report.different == 1
    assert batch_report.inconclusive == 1
    assert summarise(batch_report).startswith("3 份提交")


def test_not_running_is_explained_and_not_called_a_difference(batch_report) -> None:
    """"没跑起来"要给出原因，且不能混进"行为不同"。"""

    markdown = batch_report.to_markdown()
    assert "未取得可比证据" in markdown


def test_grade_flags_the_renamed_copy(batch_report) -> None:
    """改名抄要出现在待看清单里，并且被注明是"结构照搬"。"""

    pairs = {(item.left, item.right) for item in batch_report.pairs}
    assert ("a_identical.v", "c_renamed.v") in pairs
    flagged = next(item for item in batch_report.pairs if item.left == "a_identical.v" and item.right == "c_renamed.v")
    assert flagged.normalized > 0.9 and flagged.raw < 0.6
    assert "改了标识符" in flagged.note


def test_report_says_it_is_not_a_plagiarism_verdict(batch_report) -> None:
    """**最关键的一条**：报告必须自己说明这不是抄袭判定、也不给分数。"""

    markdown = batch_report.to_markdown()
    assert DISCLAIMER in markdown
    assert "不构成任何抄袭判定" in markdown
    assert "最终成绩与雷同判定由人作出" in markdown
    # 不能出现"抄袭"的断言式用法，也不能出现分数
    assert "抄袭率" not in markdown
    assert "得分" not in markdown and "分数：" not in markdown


def test_rows_record_why_the_conclusion_holds(batch_report) -> None:
    """能跑起来的那些提交，每份都要能回答"凭什么"：可比检查项数、是否比过波形。"""

    ran = [item for item in batch_report.rows if item.status in {"identical", "different"}]
    assert ran, "这一批里应当至少有能跑起来的提交"
    for row in ran:
        assert row.comparable_checks > 0
        assert row.waveform_compared is True


def test_report_files_are_written(batch_report) -> None:
    payload = json.loads(Path(batch_report.artifacts["json"]).read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 3
    assert payload["disclaimer"] == DISCLAIMER
    assert Path(batch_report.artifacts["markdown"]).is_file()


def test_broken_submission_does_not_break_the_batch(tmp_path: Path) -> None:
    """一份提交崩掉只影响那一行，不能中断整批——50 份作业里坏一份是常态。"""

    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "good.v").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    (batch / "empty.v").write_text("", encoding="utf-8")
    report = grade_submissions(batch, GOLDEN, tmp_path / "out")
    by_name = {item.name: item for item in report.rows}
    assert by_name["good.v"].status == "identical"
    assert by_name["empty.v"].error and "无法对比" in report.to_markdown()
    assert len(report.rows) == 2


def test_golden_itself_is_not_graded_as_a_submission(tmp_path: Path) -> None:
    """标准实现如果也在提交目录里，不能把它自己当成一份学生作业。"""

    batch = tmp_path / "mixed"
    batch.mkdir()
    (batch / "ref.v").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    (batch / "stu.v").write_text(BUG.read_text(encoding="utf-8"), encoding="utf-8")
    report = grade_submissions(batch, batch / "ref.v", tmp_path / "out")
    assert [item.name for item in report.rows] == ["stu.v"]


def test_same_batch_twice_gives_the_same_result(tmp_path: Path) -> None:
    """同一批跑两次必须同结论——判分要一致，这是教师场景的底线。"""

    batch = _make_batch(tmp_path)
    first = grade_submissions(batch, GOLDEN, tmp_path / "out1")
    second = grade_submissions(batch, GOLDEN, tmp_path / "out2")
    assert [item.to_dict() for item in first.rows] == [item.to_dict() for item in second.rows]
