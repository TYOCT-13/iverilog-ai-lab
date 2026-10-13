"""Create and render the v4 report from reviewed, evidence-bound content."""
from __future__ import annotations

from pathlib import Path
import hashlib
import html
import json
import re
import sys

from PIL import Image as PILImage, ImageDraw, ImageFont
from pypdf import PdfReader
import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
import reportlab.lib.textsplit as textsplit
import reportlab.platypus.paragraph as paragraph_impl

# ReportLab's bundled CJK rules omit several Chinese full-width punctuation marks.
# Extend line-start prohibitions only for this authoring process.
textsplit.ALL_CANNOT_START += "，；：！？"
paragraph_impl.ALL_CANNOT_START += "，；：！？"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE / "ICARUS_AI_IC_technical_report_v4.pdf"
REVIEW = ROOT / ".iverilog-ai" / "materials-v4-review" / "report"
REVIEW.mkdir(parents=True, exist_ok=True)
INK = colors.HexColor("#17212B")
MUTED = colors.HexColor("#536474")
CYAN = colors.HexColor("#008BA4")
PALE = colors.HexColor("#EFF5F7")
LINE = colors.HexColor("#D5DEE5")
PW, PH = A4
LEFT, RIGHT, TOP, BOTTOM = 42, 42, 46, 44
WIDTH = PW - LEFT - RIGHT
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD_FONT = "C:/Windows/Fonts/msyhbd.ttc"
pdfmetrics.registerFont(TTFont("CJK", FONT, subfontIndex=0))
pdfmetrics.registerFont(TTFont("CJKBold", BOLD_FONT, subfontIndex=0))


def esc(text: str) -> str:
    # CJK word wrapping also wraps long source paths, without visible hyphenation.
    return html.escape(text).replace("\n", "<br/>")


def para(text: str, size=11.1, leading=17.6, color=INK, bold=False):
    from reportlab.lib.styles import ParagraphStyle
    style = ParagraphStyle(
        "p", fontName="CJKBold" if bold else "CJK", fontSize=size,
        leading=leading, textColor=color, alignment=TA_LEFT, wordWrap="CJK",
        splitLongWords=True, allowWidows=False, allowOrphans=False,
    )
    return Paragraph(esc(text), style)


def evidence_table(data, fontsize=8.35):
    n = len(data["headers"])
    ratios = {2: [0.63, 0.37], 3: [0.24, 0.39, 0.37], 4: [0.30, 0.17, 0.25, 0.28],
              5: [0.23, 0.16, 0.22, 0.15, 0.24]}.get(n, [1/n]*n)
    rows = [[para(x, fontsize, fontsize*1.46, colors.white, True) for x in data["headers"]]]
    rows += [[para(str(x).replace("src/iverilog_ai/core/", "src/iverilog_ai/core/\n"),
                   fontsize, fontsize*1.46) for x in row] for row in data["rows"]]
    t = Table(rows, colWidths=[WIDTH*v for v in ratios], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 1, CYAN),
        ("LINEBELOW", (0, 1), (-1, -1), .35, LINE),
    ]))
    return t


def page_content(page, body_size=11.1):
    flow = []
    if page["number"] == 1:
        flow += [Spacer(1, 8), para("AI＋集成电路", 13, 20, CYAN, True), Spacer(1, 14),
                 para("ICARUS", 38, 43, INK, True),
                 para("数字IP验证智能体", 25, 34, INK, True), Spacer(1, 12),
                 para("从规格与测试规划，到真实仿真与独立证据", 11.6, 19, MUTED),
                 Spacer(1, 14), para("技术报告  ·  v4  ·  2026-10-13", 9.4, 16, MUTED), Spacer(1, 25),
                 para("摘要", 15, 23, INK, True), Spacer(1, 7)]
    else:
        flow += [para(page["title"], 18.8, 26, INK, True), Spacer(1, 8),
                 para(page["lead"], 10.3, 16, CYAN, True), Spacer(1, 12)]
    for p in page["paragraphs"]:
        flow.extend([para(p, body_size, body_size*1.56), Spacer(1, 5.3)])
    if page["figure"]:
        path = HERE / "figures" / (page["figure"] + ".png")
        flow += [Spacer(1, 4), Image(str(path), width=WIDTH*.96, height=WIDTH*.96*660/1800),
                 Spacer(1, 4), para(page["caption"], 8.3, 12.2, MUTED), Spacer(1, 8)]
    for block in page.get("figure_blocks", []):
        path = ROOT / block["path"]
        with PILImage.open(path) as im:
            iw, ih = im.size
        w = block["width_pt"]
        flow += [Spacer(1, 7), Image(str(path), width=w, height=w*ih/iw),
                 Spacer(1, 3), para(block["caption"], 8.3, 12.2, MUTED), Spacer(1, 4)]
    if page.get("table"):
        flow.extend([evidence_table(page["table"], 8.05 if page["number"] == 4 else 8.35), Spacer(1, 8)])
    if page["number"] == 1:
        flow += [para("关键词：数字IP；RTL功能验证；结构化AI规划；独立参考；证据归档", 9.2, 15, CYAN),
                 Spacer(1, 9),
                 para("阅读路线：需求分析02 · 系统与实施03-09 · 应用成效10-14 · 资源与展望15 · 总结与来源16", 8.2, 13, MUTED), Spacer(1, 7)]
    flow.append(para(page["source_note"], 7.15, 9.7, MUTED))
    return flow


def height(flow):
    return sum(item.wrap(WIDTH, PH)[1] for item in flow)


def build():
    data = json.loads((HERE / "report_content.json").read_text(encoding="utf-8-sig"))
    data["pages"] += json.loads((HERE / "appendix_content.json").read_text(encoding="utf-8-sig"))["pages"]
    audit = []
    c = canvas.Canvas(str(OUT), pagesize=A4, pageCompression=1)
    c.setTitle("ICARUS数字IP验证智能体 - AI＋集成电路技术报告 v4")
    c.setAuthor("ICARUS Project")
    c.setSubject("真实RTL仿真、独立判据、AI测试规划与迭代工程证据")
    c.setCreator("Evidence-bound ReportLab build_report.py")
    for page in data["pages"]:
        flow, chosen = None, None
        available = PH-TOP-BOTTOM
        for size in (11.1, 10.8, 10.5):
            trial = page_content(page, size)
            if height(trial) <= available:
                flow, chosen = trial, size
                break
        if flow is None:
            raise ValueError(f"Page {page['number']} overflows: {height(trial):.1f} > {available:.1f}")
        c.setStrokeColor(LINE)
        c.setLineWidth(.5)
        c.line(LEFT, PH-35, PW-RIGHT, PH-35)
        c.setFont("CJKBold", 7.6)
        c.setFillColor(CYAN)
        c.drawString(LEFT, PH-26, "ICARUS  /  DIGITAL IP VERIFICATION")
        c.setFont("CJK", 7.4)
        c.setFillColor(MUTED)
        c.drawRightString(PW-RIGHT, PH-26, "AI＋集成电路技术报告")
        y = PH-TOP
        for item in flow:
            _, h = item.wrap(WIDTH, PH)
            x = LEFT + (WIDTH-item.drawWidth)/2 if isinstance(item, Image) else LEFT
            item.drawOn(c, x, y-h)
            y -= h
        if y < BOTTOM-0.1:
            raise RuntimeError(f"Page {page['number']} bottom overflow")
        c.setStrokeColor(LINE)
        c.line(LEFT, 36, PW-RIGHT, 36)
        c.setFillColor(MUTED)
        c.setFont("CJK", 7.3)
        c.drawString(LEFT, 23, "材料更新至2026-10-13；实验与当前工程状态按版本分开报告")
        c.setFont("CJKBold", 8)
        c.drawRightString(PW-RIGHT, 23, f"{page['number']:02d} / {len(data['pages']):02d}")
        c.bookmarkPage(f"p{page['number']}")
        c.addOutlineEntry(page["title"], f"p{page['number']}", 0)
        c.showPage()
        audit.append({"page": page["number"], "title": page["title"], "body_font_pt": chosen,
                      "used_height_pt": round(height(flow), 2), "remaining_height_pt": round(y-BOTTOM, 2)})
    c.save()
    reader = PdfReader(OUT)
    if len(reader.pages) != len(data["pages"]) or len(reader.pages) < 10:
        raise ValueError("Unexpected report page count")
    if OUT.stat().st_size > 10_000_000:
        raise ValueError("Report exceeds official 10 MB limit")
    render = pdfium.PdfDocument(OUT)
    for i, page in enumerate(render):
        pil = page.render(scale=1.8).to_pil()
        pil.save(REVIEW / f"page-{i+1:02d}.png")
    # Contact sheets are previews only; full pages remain available for inspection.
    font = ImageFont.truetype(FONT, 22)
    for batch in range(0, len(data["pages"]), 4):
        sheet = PILImage.new("RGB", (1000, 1440), "#D9E0E5")
        d = ImageDraw.Draw(sheet)
        for k in range(batch, min(batch+4, len(data["pages"]))):
            im = PILImage.open(REVIEW / f"page-{k+1:02d}.png")
            im.thumbnail((470, 665))
            slot = k-batch
            x, y = 15+(slot%2)*495, 35+(slot//2)*710
            sheet.paste(im, (x, y))
            d.text((x, y-28), f"PAGE {k+1:02d}", font=font, fill="#17212B")
        sheet.save(REVIEW / f"contact-{batch//4+1:02d}.png")
    receipt = {"output": OUT.name, "pages": len(reader.pages), "bytes": OUT.stat().st_size,
               "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(), "figures": 18,
               "body_chinese_chars": sum(len(re.findall(r"[\u4e00-\u9fff]", p)) for page in data["pages"] for p in page["paragraphs"]),
               "content_sha256": hashlib.sha256((HERE/"report_content.json").read_bytes()).hexdigest(),
               "appendix_sha256": hashlib.sha256((HERE/"appendix_content.json").read_bytes()).hexdigest(),
               "rendered_pages": len(data["pages"]), "page_layout": audit,
               "visual_review": "pending actual inspection of all rendered pages", "python": sys.version}
    (HERE / "report_build_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in receipt.items() if k not in {"page_layout", "python"}}, ensure_ascii=False))


if __name__ == "__main__":
    build()
