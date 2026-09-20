"""Markdown→PDF 渲染器的回归测试（只测我们加的两条排版指令）。

为什么值得测：这两条指令不只是排版——它们承载了两件**可机械检查的事实**：
`<!-- pagebreak -->` 决定"正文到哪结束"（`check_submission.py --body-end-marker` 依赖它），
`<!-- header -->` 决定每一页是否写着赛道全称（国奖模板的固定做法，翻到任何一页都该看得见）。
指令写错了不会报错，只会静默地少一个页眉或把附录并进正文。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

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
