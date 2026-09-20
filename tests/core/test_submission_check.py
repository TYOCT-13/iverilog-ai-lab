"""提交材料体检脚本的回归测试。

为什么这些用例值得钉住：规则第（九）条要求评审材料不出现学校名称、校徽与指导教师信息，
页数与体积也有硬上限。真实教训是——正文已经匿名的往届报告，**PDF 元数据里却写着作者
真名**。这类问题只有脚本能稳定发现，所以脚本本身的行为必须有测试守着。
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from scripts.check_submission import (
    DEFAULT_FORBIDDEN,
    KIND_LIMITS,
    KindLimit,
    Report,
    check_pdf,
    check_repo,
    main,
)


def _make_pdf(path: Path, pages: list[str], metadata: dict[str, str] | None = None) -> Path:
    """造一份最小的 PDF。

    必须用 PyMuPDF 内置的简体中文字体（`china-s`）：默认的 helv 画不出汉字，
    文本抽取会返回空串，于是"扫描敏感词"的用例会假通过——这个坑踩过一次。
    """

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((56, 72), text, fontsize=11, fontname="china-s")
    if metadata:
        doc.set_metadata(metadata)
    doc.save(path)
    doc.close()
    return path


def test_flags_identity_in_pdf_metadata(tmp_path: Path) -> None:
    """元数据里的作者真名必须被报出来——这正是往届报告踩过的坑。"""

    pdf = _make_pdf(tmp_path / "r.pdf", ["正文"], {"author": "某某某", "producer": "WPS 文字"})
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    codes = {item.code for item in report.findings}
    assert "metadata/identity" in codes
    message = next(item.message for item in report.findings if item.code == "metadata/identity")
    assert "author" in message and "某某某" in message


def test_clean_metadata_produces_no_identity_warning(tmp_path: Path) -> None:
    """空元数据不该被误报。我们自己生成的 PDF 就应该是这一档。"""

    pdf = _make_pdf(tmp_path / "clean.pdf", ["正文"], {"author": "", "subject": "", "keywords": ""})
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    assert not [item for item in report.findings if item.code == "metadata/identity"]


def test_page_overrun_is_a_warning_by_default(tmp_path: Path) -> None:
    """超页默认只是 warning——大纲写的是"建议"，且明确"不以报告篇幅作为评分依据"。

    早期版本把它当 error，代价是为了凑页数把消融实验、事故复盘、测试条件表一路砍进附录。
    **为一个自己声明"不作为评分依据"的建议去削弱证据，比超出两页糟得多。**
    """

    pdf = _make_pdf(tmp_path / "long.pdf", [f"第 {i} 页" for i in range(1, 18)])
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    hits = [item for item in report.findings if item.code == "pages/over-recommended"]
    assert len(hits) == 1 and hits[0].level == "warning"
    assert "17 页" in hits[0].message
    assert not report.errors


def test_page_overrun_can_be_made_an_error_on_request(tmp_path: Path) -> None:
    """想要严格模式的人可以显式打开——约束级别交给调用方，而不是替他们定死。"""

    pdf = _make_pdf(tmp_path / "long.pdf", [f"第 {i} 页" for i in range(1, 18)])
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report, fail_on_page_overrun=True)
    assert [item.level for item in report.findings if item.code == "pages/over-recommended"] == ["error"]
    assert report.errors


def test_size_limit_is_still_a_hard_error(tmp_path: Path) -> None:
    """体积是**硬约束**（10MB），与页数不同——这条不能也跟着放宽。"""

    pdf = _make_pdf(tmp_path / "big.pdf", ["正文"])
    original = KIND_LIMITS["report"]
    KIND_LIMITS["report"] = KindLimit(max_pages=original.max_pages, max_bytes=10)
    try:
        report = Report()
        check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
        assert any(item.code == "size/too-large" and item.level == "error" for item in report.findings)
    finally:
        KIND_LIMITS["report"] = original


def test_under_limit_reports_room_left_as_info(tmp_path: Path) -> None:
    """页数没用满只提示不报错——14 页是合规的。"""

    pdf = _make_pdf(tmp_path / "ok.pdf", ["正文"])
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    info = [item for item in report.findings if item.code == "pages/room-left"]
    assert info and info[0].level == "info"
    assert not report.errors


def test_anonymity_keywords_are_warnings_with_context(tmp_path: Path) -> None:
    """敏感词命中要给上下文片段，且只能是 warning（"实验室"这类词常有正当用法）。"""

    pdf = _make_pdf(tmp_path / "kw.pdf", ["本作品由某某大学计算机学院指导教师张三指导完成"])
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    hits = [item for item in report.findings if item.code == "anonymity/keyword"]
    assert {item.level for item in hits} == {"warning"}
    assert any("大学" in item.message for item in hits)
    assert any("指导教师" in item.message for item in hits)
    # 必须带上下文，否则用户无法判断是误报还是真泄露
    assert any("…" in item.message for item in hits)
    # 匿名性问题是 warning，不该把退出码变成失败
    assert not report.errors


def test_size_limit_differs_per_kind(tmp_path: Path) -> None:
    """视频上限 300MB、报告 10MB——同一份文件在不同 kind 下结论不同。"""

    assert KIND_LIMITS["report"].max_bytes == 10 * 1024 * 1024
    assert KIND_LIMITS["video"].max_bytes == 300 * 1024 * 1024
    assert KIND_LIMITS["report"].max_pages == 15
    assert KIND_LIMITS["video"].max_pages is None


def test_main_returns_nonzero_only_for_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """退出码语义：error → 1，只有 warning → 0。CI 依赖这个区分。"""

    clean = _make_pdf(tmp_path / "clean.pdf", ["正文"])
    assert main([str(clean)]) == 0

    # 页面超建议值只是 warning，不该让退出码变红
    long_doc = _make_pdf(tmp_path / "many.pdf", [f"p{i}" for i in range(20)])
    assert main([str(long_doc)]) == 0
    # 但显式要求严格时就是了
    assert main([str(long_doc), "--fail-on-page-overrun"]) == 1
    # 真正的 error（文件不存在）必须变红
    assert main([str(tmp_path / "nope.pdf")]) == 1


def test_main_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """`--json` 要能被脚本消费：含 ok / findings / checked。"""

    pdf = _make_pdf(tmp_path / "a.pdf", ["正文"])
    main([str(pdf), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checked"][0]["pages"] == 1
    assert isinstance(payload["findings"], list)


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    """路径写错必须报错，不能静默跳过——否则"检查通过"是假的。"""

    assert main([str(tmp_path / "nope.pdf")]) == 1


def test_max_pages_override(tmp_path: Path) -> None:
    """PPT 等材料可以显式覆盖页数建议值，并配 `--fail-on-page-overrun` 变成硬约束。"""

    pdf = _make_pdf(tmp_path / "ppt.pdf", [f"p{i}" for i in range(1, 21)])
    assert main([str(pdf), "--kind", "ppt"]) == 0
    assert main([str(pdf), "--kind", "ppt", "--max-pages", "10", "--fail-on-page-overrun"]) == 1


def test_repo_scan_flags_placeholders_in_shipped_files(tmp_path: Path) -> None:
    """交付面里的占位符必须挡住提交——"参赛期间私有、之后再填"最容易在提交当天忘掉。"""

    (tmp_path / "CITATION.cff").write_text(
        'repository-code: "https://example.invalid/repo"\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# 正常内容\n", encoding="utf-8")
    report = Report()
    info = check_repo(tmp_path, report)
    assert info["files_scanned"] == 2
    assert info["placeholders"] == 1
    assert any(item.code == "placeholder/unresolved" for item in report.errors)


def test_repo_scan_ignores_tests_and_doc_templates(tmp_path: Path) -> None:
    """测试夹具与文档模板里的保留域是**有意为之**，不该被报成问题。

    真实教训：第一版扫全仓库，19 条命中里 17 条来自 tests/ 的 fixture 和文档里
    `<你的文件.v>` 这类约定写法。一个天天误报的门禁，等于没有门禁。
    """

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        'endpoint = "https://example.invalid/v1"\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "upstream").mkdir(parents=True)
    (tmp_path / "docs" / "upstream" / "guide.md").write_text(
        "- uses: <你的账号>/repo@main\n", encoding="utf-8"
    )
    report = Report()
    info = check_repo(tmp_path, report)
    assert info["placeholders"] == 0
    assert info["files_scanned"] == 0
    assert not report.errors


def test_repo_scan_respects_the_inline_allow_marker(tmp_path: Path) -> None:
    """需要保留占位符的行可以显式放行，但必须写明理由——放行是有痕迹的。"""

    (tmp_path / "CITATION.cff").write_text(
        'repository-code: "https://example.invalid/repo"  # allow-placeholder: 转公开后替换\n',
        encoding="utf-8",
    )
    report = Report()
    info = check_repo(tmp_path, report)
    assert info["placeholders"] == 0
    assert not report.errors


def test_repo_scan_also_catches_todo_markers(tmp_path: Path) -> None:
    """待办标记同样是"会交出去"的一部分，一并挡住。"""

    (tmp_path / "README.md").write_text("# 项目\n\nTODO 补上安装说明\n", encoding="utf-8")
    report = Report()
    assert check_repo(tmp_path, report)["placeholders"] == 1


def test_repo_scan_rejects_a_file_path(tmp_path: Path) -> None:
    """`--repo` 收到文件而不是目录时要明确报错，不能静默扫出 0 处就当通过。"""

    target = _make_pdf(tmp_path / "x.pdf", ["正文"])
    assert main([str(target), "--repo"]) == 1
