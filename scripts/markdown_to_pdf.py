"""把 Markdown 技术报告转成 PDF（离线、确定性、可重跑）。

为什么自己写转换器而不是装 pandoc/LaTeX：
- 环境里只有 PyMuPDF 与中文字体，且报告结构简单（标题/段落/列表/表格/图片）；
- 自写渲染器**可复现**：同一份 Markdown 每次得到同样的 PDF；
- 不引入新的重量级依赖，符合"最小依赖"的项目原则。

用法：python scripts/markdown_to_pdf.py docs/competition/technical_report_draft.md out.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import fitz  # PyMuPDF

# A4 尺寸与页边距（单位：点，1 点 = 1/72 英寸）
PAGE_W, PAGE_H = 595.0, 842.0
MARGIN_X, MARGIN_Y = 56.0, 58.0
CONTENT_W = PAGE_W - 2 * MARGIN_X
BOTTOM_LIMIT = PAGE_H - MARGIN_Y

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)
MONO_CANDIDATES = (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf")

H1_SIZE, H2_SIZE, H3_SIZE = 19.0, 15.0, 13.0
BODY_SIZE, SMALL_SIZE = 10.5, 9.0
LINE_GAP = 1.55


class Renderer:
    """按需分页的极简 Markdown 渲染器（支持标题/段落/列表/表格/图片/引用/代码块）。"""

    def __init__(self, base_dir: Path) -> None:
        self.doc = fitz.open()
        self.base_dir = base_dir
        self.page = None
        self.y = 0.0
        self._new_page()
        # 字体：用 fitz.Font 载入中文字体，配合**每页一个 TextWriter** 累积文字，
        # 最后统一 doc.subset_fonts()。三者缺一不可——早期版本把整份 msyh.ttc
        # （约 12MB）交给每行新建的 TextWriter，字体被整份嵌入，14 页 PDF 达到
        # 12.5MB；现在回落到数百 KB 量级。实测见 scripts/markdown_to_pdf.py 注释。
        self.font = self._load_font(FONT_CANDIDATES)
        self.mono = self._load_font(MONO_CANDIDATES, fallback=self.font)
        self.writer = fitz.TextWriter(self.page.rect)

    def _load_font(self, candidates: tuple[str, ...], *, fallback=None):
        for candidate in candidates:
            if Path(candidate).is_file():
                try:
                    return fitz.Font(fontfile=candidate)
                except Exception:
                    continue
        return fallback if fallback is not None else fitz.Font("helv")

    # ---------------------------------------------------------------- 基础设施
    def _load_font(self, candidates: tuple[str, ...], *, fallback: str | None = None):
        for candidate in candidates:
            if Path(candidate).is_file():
                try:
                    return fitz.Font(fontfile=candidate)
                except Exception:
                    continue
        if fallback is not None:
            return fallback
        return fitz.Font("helv")

    def _new_page(self) -> None:
        self._flush_writer()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.writer = fitz.TextWriter(self.page.rect)
        self.y = MARGIN_Y

    def _flush_writer(self) -> None:
        """把当前页累积的文字一次性写入。

        两个必须注意的点（都踩过）：

        1. ``TextWriter`` **没有** ``text_objects`` 属性（可用属性见 PyMuPDF 的
           ``dir()``）。早期版本用 ``getattr(writer, "text_objects", None)`` 做判空
           守卫，守卫恒为真，导致所有文字都被静默丢弃，渲染出的页面只有表格边框；
        2. 必须显式传入目标页：``write_text(page)`` 需要 page 参数，而 ``_new_page``
           里先 flush 再替换 ``self.page``，顺序不能颠倒。
        """

        writer = getattr(self, "writer", None)
        page = getattr(self, "page", None)
        if writer is None or page is None:
            return
        writer.write_text(page, color=(0.1, 0.12, 0.16))

    def _ensure(self, height: float) -> None:
        if self.y + height > BOTTOM_LIMIT:
            self._new_page()

    def _text_width(self, text: str, size: float, *, bold: bool = False, mono: bool = False) -> float:
        face = self.mono if mono else self.font
        return face.text_length(text, fontsize=size)

    def _draw(self, text: str, x: float, y: float, size: float, *,
              bold: bool = False, mono: bool = False,
              color: tuple[float, float, float] = (0.1, 0.12, 0.16)) -> None:
        """累积一行文本（颜色由翻页时的统一落盘决定）。"""

        face = self.mono if mono else self.font
        self.writer.append(fitz.Point(x, y), text, font=face, fontsize=size)

    # ------------------------------------------------------------------ 行内解析
    @staticmethod
    def _strip_inline(text: str) -> str:
        """去掉行内标记：**加粗**、`代码`、[文字](链接) → 文字（保留链接文字）。"""

        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = text.replace("**", "").replace("`", "")
        text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
        return text.strip()

    def _wrap(self, text: str, size: float, width: float, *, mono: bool = False) -> list[str]:
        """中英混排换行。

        中文没有空格可依赖，必须在字符间断行；但**拉丁词不能被从中间劈开**
        （早期版本会把 `testbench` 拆成 `testb`/`ench`，很难读）。因此策略是：

        1. 有空格时优先在空格处断行（拉丁文按词走）；
        2. 单个词本身就超宽时（常见于没有空格的中文长句与代码），退化为逐字符断行。
        """

        def fits(candidate: str) -> bool:
            return self._text_width(candidate, size, mono=mono) <= width

        tokens: list[str] = []
        for piece in text.split(" "):
            if piece:
                tokens.append(piece)
                tokens.append(" ")
        if tokens and tokens[-1] == " ":
            tokens.pop()

        lines: list[str] = []
        current = ""
        for token in tokens:
            if fits(current + token):
                current += token
                continue
            if current.strip():
                lines.append(current.rstrip())
                current = ""
            if token == " ":
                continue
            # 单个词超宽：逐字符断行（中文长句走这条路径）
            for char in token:
                if fits(current + char):
                    current += char
                else:
                    lines.append(current)
                    current = char
        if current.strip() or not lines:
            lines.append(current.rstrip())
        return lines

    # ------------------------------------------------------------------ 块级渲染
    def heading(self, text: str, level: int) -> None:
        size = {1: H1_SIZE, 2: H2_SIZE, 3: H3_SIZE}.get(level, H3_SIZE)
        text = self._strip_inline(text)
        lines = self._wrap(text, size, CONTENT_W)
        height = len(lines) * size * LINE_GAP + (14 if level <= 2 else 9)
        self._ensure(height)
        if level <= 2 and self.y > MARGIN_Y + 1:
            self.y += 8
        for line in lines:
            self._draw(line, MARGIN_X, self.y + size, size, bold=True)
            self.y += size * LINE_GAP
        if level == 1:
            self.page.draw_line(
                fitz.Point(MARGIN_X, self.y + 2), fitz.Point(PAGE_W - MARGIN_X, self.y + 2),
                color=(0.72, 0.78, 0.85), width=1.2,
            )
            self.y += 6
        self.y += 10 if level <= 2 else 6

    def paragraph(self, text: str) -> None:
        text = self._strip_inline(text)
        if not text:
            return
        lines = self._wrap(text, BODY_SIZE, CONTENT_W)
        self._render_lines(lines, BODY_SIZE, indent=0.0)
        self.y += 7

    def bullet(self, text: str, *, ordered: bool, index: int, indent: float = 0.0) -> None:
        marker = f"{index}." if ordered else "•"
        text = self._strip_inline(text)
        marker_w = 18.0
        lines = self._wrap(text, BODY_SIZE, CONTENT_W - marker_w - indent)
        self._ensure(BODY_SIZE * LINE_GAP)
        self._draw(marker, MARGIN_X + indent, self.y + BODY_SIZE, BODY_SIZE)
        self._render_lines(lines, BODY_SIZE, indent=indent + marker_w, first_line_offset=-marker_w)
        self.y += 5

    def _render_lines(self, lines: list[str], size: float, *, indent: float, first_line_offset: float = 0.0) -> None:
        for position, line in enumerate(lines):
            self._ensure(size * LINE_GAP)
            x = MARGIN_X + indent + (first_line_offset if position == 0 else 0.0)
            self._draw(line, x, self.y + size, size)
            self.y += size * LINE_GAP

    def rule(self) -> None:
        """水平分隔线（Markdown 的 `---`）。"""

        self._ensure(14)
        self.page.draw_line(
            fitz.Point(MARGIN_X, self.y + 4), fitz.Point(PAGE_W - MARGIN_X, self.y + 4),
            color=(0.82, 0.86, 0.9), width=1.0,
        )
        self.y += 14

    def quote(self, text: str) -> None:
        text = self._strip_inline(text)
        if not text:
            return
        lines = self._wrap(text, SMALL_SIZE, CONTENT_W - 22)
        self._ensure(len(lines) * SMALL_SIZE * LINE_GAP + 10)
        top = self.y
        for line in lines:
            self._draw(line, MARGIN_X + 16, self.y + SMALL_SIZE, SMALL_SIZE, color=(0.35, 0.38, 0.44))
            self.y += SMALL_SIZE * LINE_GAP
        self.page.draw_line(fitz.Point(MARGIN_X + 4, top + 2), fitz.Point(MARGIN_X + 4, self.y),
                            color=(0.6, 0.66, 0.74), width=2.4)
        self.y += 7

    def code_block(self, lines: list[str]) -> None:
        size = 8.6
        wrapped: list[str] = []
        for line in lines:
            wrapped.extend(self._wrap(line, size, CONTENT_W - 20, mono=True) or [""])
        height = len(wrapped) * size * 1.42 + 14
        self._ensure(height)
        self.page.draw_rect(
            fitz.Rect(MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y + height),
            color=(0.86, 0.89, 0.92), fill=(0.965, 0.972, 0.978), width=1,
        )
        self.y += 7
        for line in wrapped:
            self._draw(line, MARGIN_X + 10, self.y + size, size, mono=True, color=(0.15, 0.18, 0.22))
            self.y += size * 1.42
        self.y += 9

    def table(self, header: list[str], rows: list[list[str]]) -> None:
        columns = max(len(header), max((len(row) for row in rows), default=0))
        if columns == 0:
            return
        size = 8.8
        padding = 5.0
        weight = [1.0] * columns
        # 第一列稍宽（多为名称），其余等宽
        if columns > 1:
            weight[0] = 1.35
        total = sum(weight)
        widths = [CONTENT_W * (item / total) for item in weight]

        def cell_lines(cells: list[str]) -> list[list[str]]:
            return [self._wrap(self._strip_inline(cell), size, widths[i] - 2 * padding) for i, cell in enumerate(cells)]

        header_lines = cell_lines(header)
        body_lines = [cell_lines(row) for row in rows]
        header_h = max(len(item) for item in header_lines) * size * 1.35 + 2 * padding
        self._ensure(header_h + 20)
        top = self.y
        self.page.draw_rect(fitz.Rect(MARGIN_X, top, PAGE_W - MARGIN_X, top + header_h),
                            fill=(0.94, 0.955, 0.972), color=(0.78, 0.82, 0.87), width=0.8)
        x = MARGIN_X
        for index in range(columns):
            for position, line in enumerate(header_lines[index]):
                self._draw(line, x + padding, top + padding + size * (1 + position * 1.35), size, bold=True)
            x += widths[index]
        x = MARGIN_X
        for width in widths[:-1]:
            x += width
            self.page.draw_line(fitz.Point(x, top), fitz.Point(x, top + header_h), color=(0.8, 0.84, 0.88), width=0.8)
        self.y = top + header_h

        for lines in body_lines:
            row_h = max(len(item) for item in lines) * size * 1.35 + 2 * padding
            if self.y + row_h > BOTTOM_LIMIT:
                self._new_page()
                top = self.y
            self.page.draw_rect(fitz.Rect(MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y + row_h),
                                color=(0.86, 0.89, 0.92), width=0.7)
            x = MARGIN_X
            for index in range(columns):
                for position, line in enumerate(lines[index]):
                    self._draw(line, x + padding, self.y + padding + size * (1 + position * 1.35), size)
                x += widths[index]
            x = MARGIN_X
            for width in widths[:-1]:
                x += width
                self.page.draw_line(fitz.Point(x, self.y), fitz.Point(x, self.y + row_h),
                                    color=(0.88, 0.9, 0.93), width=0.7)
            self.y += row_h
        self.y += 10

    def image(self, relative: str, caption: str | None = None) -> None:
        path = (self.base_dir / relative).resolve()
        if not path.is_file():
            self.paragraph(f"[缺图：{relative}]")
            return
        with fitz.open(path) as source:
            rect = source[0].rect
            scale = min(1.0, CONTENT_W / rect.width)
            width, height = rect.width * scale, rect.height * scale
            caption_h = SMALL_SIZE * 1.5 + 6 if caption else 0
            available = BOTTOM_LIMIT - self.y - caption_h - 6
            # 放不下就按剩余空间等比缩小（最低缩到 62%），避免为一张图整页留白；
            # 缩到下限仍放不下才换页。
            if height > available:
                if available >= height * 0.62 and available > 120:
                    ratio = available / height
                    width, height = width * ratio, available
                else:
                    self._new_page()
            if height > BOTTOM_LIMIT - MARGIN_Y - caption_h - 6:
                ratio = (BOTTOM_LIMIT - MARGIN_Y - caption_h - 6) / height
                width, height = width * ratio, height * ratio
            image_rect = fitz.Rect(MARGIN_X, self.y, MARGIN_X + width, self.y + height)
            self.page.insert_image(image_rect, filename=str(path))
            self.y += height + 6
            if caption:
                self._draw(self._strip_inline(caption), MARGIN_X, self.y + SMALL_SIZE, SMALL_SIZE,
                           color=(0.42, 0.46, 0.52))
                self.y += SMALL_SIZE * 1.5
            self.y += 10

    # ------------------------------------------------------------------ 保存
    def save(self, path: Path) -> Path:
        self._flush_writer()
        # 页码：单独用一次性 writer，避免污染正文的累积器
        total = self.doc.page_count
        for index, page in enumerate(self.doc, start=1):
            writer = fitz.TextWriter(page.rect)
            writer.append(fitz.Point(PAGE_W / 2 - 18, PAGE_H - 28), f"{index} / {total}",
                          font=self.font, fontsize=8.5)
            writer.write_text(page, color=(0.5, 0.54, 0.6))
        path.parent.mkdir(parents=True, exist_ok=True)
        # subset_fonts 是体积的关键：只有它会把嵌入字体裁剪成"用到的字形"。
        self.doc.subset_fonts()
        self.doc.save(str(path), deflate=True, garbage=4, clean=True)
        return path


_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


def render_markdown(markdown_path: Path, output_path: Path) -> tuple[Path, int]:
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    renderer = Renderer(base_dir=markdown_path.parent)
    index = 0
    pending_caption: str | None = None
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()

        if not stripped:
            index += 1
            continue

        # 图片（可带 alt 文本作为图注）
        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if image_match:
            renderer.image(image_match.group(2), image_match.group(1) or pending_caption)
            pending_caption = None
            index += 1
            continue

        # 标题
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            renderer.heading(heading_match.group(2), len(heading_match.group(1)))
            index += 1
            continue

        # 代码块
        if stripped.startswith("```"):
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            renderer.code_block(block)
            continue

        # 表格
        if stripped.startswith("|") and index + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[index + 1].strip()):
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            renderer.table(header, rows)
            continue

        # 水平分隔线（`---` / `***` / `___`）
        if re.fullmatch(r"([-*_])\1{2,}", stripped):
            renderer.rule()
            index += 1
            continue

        # 引用
        if stripped.startswith(">"):
            renderer.quote(stripped.lstrip(">").strip())
            index += 1
            continue

        # 列表
        bullet_match = re.match(r"^(\s*)[-*+]\s+(.*)$", raw)
        ordered_match = re.match(r"^(\s*)(\d+)\.\s+(.*)$", raw)
        if bullet_match:
            indent = min(len(bullet_match.group(1)), 8) * 6.0
            renderer.bullet(bullet_match.group(2), ordered=False, index=0, indent=indent)
            index += 1
            continue
        if ordered_match:
            indent = min(len(ordered_match.group(1)), 8) * 6.0
            renderer.bullet(ordered_match.group(3), ordered=True, index=int(ordered_match.group(2)), indent=indent)
            index += 1
            continue

        # 普通段落（合并连续行）
        paragraph = [stripped]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if (not candidate or candidate.startswith(("#", "|", ">", "```", "!["))
                    or re.match(r"^[-*+]\s+", candidate) or re.match(r"^\d+\.\s+", candidate)):
                break
            paragraph.append(candidate)
            index += 1
        renderer.paragraph(" ".join(paragraph))

    path = renderer.save(output_path)
    return path, renderer.doc.page_count


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 报告渲染为 PDF")
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    path, pages = render_markdown(Path(args.source), Path(args.output))
    print(f"生成 {path}（{pages} 页，{path.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
