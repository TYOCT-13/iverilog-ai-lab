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
    Report,
    check_pdf,
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


def test_page_limit_is_an_error_not_a_warning(tmp_path: Path) -> None:
    """超页是 error：规则写的是"正文建议 15 页以内"，超了要挡住而不是提示。"""

    pdf = _make_pdf(tmp_path / "long.pdf", [f"第 {i} 页" for i in range(1, 18)])
    report = Report()
    check_pdf(pdf, "report", DEFAULT_FORBIDDEN, report)
    errors = [item for item in report.findings if item.code == "pages/too-many"]
    assert len(errors) == 1
    assert "17 页" in errors[0].message
    assert report.errors


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

    dirty = _make_pdf(tmp_path / "many.pdf", [f"p{i}" for i in range(20)])
    assert main([str(dirty)]) == 1


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
    """PPT 等材料可以显式覆盖页数上限。"""

    pdf = _make_pdf(tmp_path / "ppt.pdf", [f"p{i}" for i in range(1, 21)])
    assert main([str(pdf), "--kind", "ppt"]) == 0
    assert main([str(pdf), "--kind", "ppt", "--max-pages", "10"]) == 1
