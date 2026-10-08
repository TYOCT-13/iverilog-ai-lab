"""Markdown→PDF 渲染器的回归测试（只测我们加的两条排版指令）。

为什么值得测：这两条指令不只是排版——它们承载了两件**可机械检查的事实**：
`<!-- pagebreak -->` 决定"正文到哪结束"（`check_submission.py --body-end-marker` 依赖它），
`<!-- header -->` 决定每一页是否写着赛道全称（国奖模板的固定做法，翻到任何一页都该看得见）。
指令写错了不会报错，只会静默地少一个页眉或把附录并进正文。
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys

import fitz
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "markdown_to_pdf.py"
_spec = importlib.util.spec_from_file_location("_md2pdf", SCRIPT)
assert _spec and _spec.loader
md2pdf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md2pdf)


def _render(tmp_path: Path, markdown: str) -> Path:
    source = tmp_path / "doc.md"
    source.write_text(markdown, encoding="utf-8")
    output = tmp_path / "doc.pdf"
    md2pdf.render_markdown(source, output)
    return output


def test_header_is_repeated_on_every_page(tmp_path: Path) -> None:
    """页眉必须出现在**每一页**上——这正是它存在的意义（评委随手翻到哪页都知道在评什么）。

    断言用的是**特征子串**而不是整行：CJK 字体做子集化后，`·` 这类符号在文本提取时
    会映射成另一个码位（视觉完全正常，只是 cmap 不同）。拿整行做断言会因为这个原因
    假失败，而它其实什么都没说明。
    """

    pdf = _render(
        tmp_path,
        "<!-- header: 第八届大赛 · 算法主题赛 -->\n"
        "<!-- doctitle: AIC·AI+开源技术报告 -->\n\n"
        "# 标题\n\n" + "\n\n".join(f"第 {i} 段正文。" for i in range(1, 60)) + "\n",
    )
    with fitz.open(pdf) as doc:
        assert doc.page_count >= 2, "样本太短，测不出'每页都有'"
        for index, page in enumerate(doc, 1):
            text = page.get_text("text")
            assert "第八届大赛" in text, f"第 {index} 页缺页眉"
            assert "算法主题赛" in text, f"第 {index} 页页眉不完整"
            assert "开源技术报告" in text, f"第 {index} 页缺文档标识"


def test_no_header_directive_means_no_header(tmp_path: Path) -> None:
    """没写指令就不要凭空造一个页眉——否则普通 Markdown 转 PDF 会多出莫名其妙的一行。"""

    pdf = _render(tmp_path, "# 标题\n\n正文一段。\n")
    with fitz.open(pdf) as doc:
        assert "第八届" not in doc[0].get_text("text")


def test_pagebreak_starts_a_new_page(tmp_path: Path) -> None:
    """`<!-- pagebreak -->` 之后的内容必须落到新页上（"正文到哪结束"靠它变成事实）。"""

    pdf = _render(
        tmp_path,
        "# 正文\n\n正文一段。\n\n<!-- pagebreak -->\n\n以下为附录\n\n附录一段。\n",
    )
    with fitz.open(pdf) as doc:
        assert doc.page_count == 2
        assert "以下为附录" in doc[1].get_text("text")
        assert "以下为附录" not in doc[0].get_text("text")


def test_pagebreak_at_the_very_start_does_not_add_a_blank_page(tmp_path: Path) -> None:
    """首行就是分页符时不该留一张空白页——空页会被页数统计算进去。"""

    pdf = _render(tmp_path, "<!-- pagebreak -->\n\n# 标题\n\n正文一段。\n")
    with fitz.open(pdf) as doc:
        assert doc.page_count == 1
        assert "标题" in doc[0].get_text("text")


@pytest.mark.parametrize("directive", ["<!-- pagebreak -->", "\\pagebreak", "\\newpage"])
def test_all_pagebreak_spellings_work(tmp_path: Path, directive: str) -> None:
    pdf = _render(tmp_path, f"# 正文\n\n一段。\n\n{directive}\n\n附录\n\n附录一段。\n")
    with fitz.open(pdf) as doc:
        assert doc.page_count == 2


# ------------------------------------------------------------------ 交付产物新鲜度

ROOT = Path(__file__).resolve().parents[2]

#: 仓库里**进版本库**的交付 PDF 与各自的 Markdown 源。
TRACKED_REPORTS = [
    ("docs/competition/technical_report_draft.md", "docs/competition/technical_report_draft.pdf"),
    ("docs/project_overview.md", "docs/project_overview.pdf"),
]


@pytest.mark.parametrize("changed", ["source", "pdf"])
def test_font_difference_never_masks_changed_report_bytes(tmp_path: Path, monkeypatch, changed: str) -> None:
    output = _render(tmp_path, "# 一份报告\n\n原始内容。\n")
    source = tmp_path / "doc.md"
    binding_path = tmp_path / "docs/experiment/report_pdf_source_bindings_2026-10-08.json"
    binding_path.parent.mkdir(parents=True)
    binding = {"renderer_font_sha256": ["different-font", "different-mono"], "reports": {
        "doc.md": {"pdf": "doc.pdf", "source_sha256_lf": hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                   "pdf_sha256": hashlib.sha256(output.read_bytes()).hexdigest()},
    }}
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    test_tracked_report_pdf_matches_its_markdown(tmp_path, "doc.md", "doc.pdf")
    if changed == "source":
        source.write_text("# 一份报告\n\n已改变的内容。\n", encoding="utf-8")
        expected = "源绑定"
    else:
        output.write_bytes(output.read_bytes() + b"\n% modified\n")
        expected = "产物绑定"
    with pytest.raises(AssertionError, match=expected):
        test_tracked_report_pdf_matches_its_markdown(tmp_path, "doc.md", "doc.pdf")


@pytest.mark.parametrize(("markdown", "pdf"), TRACKED_REPORTS)
def test_tracked_report_pdf_matches_its_markdown(tmp_path: Path, markdown: str, pdf: str) -> None:
    """交付 PDF 必须与它当前的 Markdown 源对得上——源改了就得重渲染。

    为什么比内容而不是比时间戳：`git clone` 会把检出文件的时间戳统一成同一时刻，
    于是"PDF 比 Markdown 旧"这条判断在别人机器与 CI 上**永远通过**。
    一个只在作者本机有效的门禁等于没有，所以这里现渲染一份逐页比对文本。

    真实事故：技术报告在 9-20 整体改写后没有重渲染，仓库里的 PDF 一直停在 9-11 的
    13 页版本——缺页眉、缺新增的「作品服务谁」「四层结论」「量化成果指标」。
    测试全绿，而读者拿到的是旧报告。
    """

    binding = json.loads((ROOT / "docs/experiment/report_pdf_source_bindings_2026-10-08.json").read_text(encoding="utf-8"))
    pair = binding["reports"][markdown]
    assert pair["pdf"] == pdf
    assert hashlib.sha256((ROOT / markdown).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == pair["source_sha256_lf"], (
        f"{markdown} 与已验收 PDF 的源绑定不一致，必须重新渲染并核验新材料"
    )
    assert hashlib.sha256((ROOT / pdf).read_bytes()).hexdigest() == pair["pdf_sha256"], (
        f"{pdf} 与已验收源的产物绑定不一致，必须重新核验"
    )

    def font_digest(candidates):
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                return hashlib.sha256(path.read_bytes()).hexdigest()
        return None

    current_fonts = [font_digest(md2pdf.FONT_CANDIDATES), font_digest(md2pdf.MONO_CANDIDATES)]
    if current_fonts != binding["renderer_font_sha256"]:
        # Git clone 的字节绑定仍严格校验；缺少相同字体时不能把换行/字形映射差异
        # 判成材料过期。页眉与分页渲染行为由上方独立样本测试继续检查。
        with fitz.open(ROOT / pdf) as document:
            assert document.page_count > 0
            assert all(page.get_text("text").strip() for page in document)
        print(f"{pdf}: 源与PDF字节绑定通过；字体不同，未进行逐页重渲染等同性检查")
        return

    fresh = tmp_path / "fresh.pdf"
    md2pdf.render_markdown(ROOT / markdown, fresh)

    with fitz.open(fresh) as new_doc, fitz.open(ROOT / pdf) as old_doc:
        assert old_doc.page_count == new_doc.page_count, (
            f"{pdf} 是 {old_doc.page_count} 页，当前 {markdown} 渲染出 {new_doc.page_count} 页："
            f"PDF 已过期，请重新渲染（python scripts/markdown_to_pdf.py {markdown} {pdf}）"
        )
        for index, (old_page, new_page) in enumerate(zip(old_doc, new_doc), 1):
            # 去掉所有空白再比：换页处的断行差异不说明内容变了，多一个空格也不说明。
            old_text = "".join(old_page.get_text("text").split())
            new_text = "".join(new_page.get_text("text").split())
            assert old_text == new_text, (
                f"{pdf} 第 {index} 页与当前 {markdown} 不一致：PDF 已过期，请重新渲染"
                f"（python scripts/markdown_to_pdf.py {markdown} {pdf}）"
            )
