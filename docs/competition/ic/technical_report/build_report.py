"""Build a continuous, typeset technical report from the reviewed Markdown.

No API or DUT execution. Run with the bundled Python runtime.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents
import reportlab.lib.textsplit as textsplit
import reportlab.platypus.paragraph as paragraph_impl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = HERE / "technical_report.md"
OUTPUT = HERE / "ICARUS_技术报告.pdf"
QA = ROOT / ".iverilog-ai" / "author-style-review" / "final"
FIGURES = HERE / "figures"
PW, PH = A4
WIDTH = PW - 180
INK = "#171717"
BLUE = "#25667D"
GRAY = "#687176"
LIGHT = "#E7ECEE"
WHITE = "#FFFFFF"
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def put(draw, xy, text, size=28, bold=False, color=INK, anchor=None):
    draw.text(xy, text, font=font(size, bold), fill=color, anchor=anchor, spacing=10)


def box(draw, rect, title, detail, accent=False):
    draw.rectangle(rect, fill="#F3F6F7" if accent else WHITE,
                   outline=BLUE if accent else "#9BA6AB", width=3)
    x, y, r, b = rect
    put(draw, ((x+r)/2, y+30), title, 31, True, anchor="mt")
    put(draw, ((x+r)/2, y+93), detail, 25, anchor="mt")


def arrow(draw, points, color=GRAY):
    draw.line(points, fill=color, width=4)
    x, y = points[-1]
    px, py = points[-2]
    if x != px:
        s = 1 if x > px else -1
        draw.polygon([(x,y),(x-s*15,y-8),(x-s*15,y+8)], fill=color)
    else:
        s = 1 if y > py else -1
        draw.polygon([(x,y),(x-8,y-s*15),(x+8,y-s*15)], fill=color)


def canvas(h=650):
    im = PILImage.new("RGB", (1600, h), WHITE)
    return im, ImageDraw.Draw(im)


def save(im, name):
    im.save(FIGURES / f"{name}.png", optimize=True)


def make_figures():
    FIGURES.mkdir(parents=True, exist_ok=True)
    im, d = canvas(560)
    labels = [("验证目标", "优先检查的功能与边界"),
              ("正确规格", "状态规则与时序要求"),
              ("接口合约", "端口、位宽、时钟与复位")]
    for i, (title, detail) in enumerate(labels):
        y = 28+i*172
        box(d, (30,y,650,y+142), title, detail)
        arrow(d, [(650,y+71),(800,y+71),(800,280),(960,280)])
    box(d, (960,185,1565,375), "在线测试规划", "输入值 + 持续拍数 + 采样位置", True)
    put(d, (1262,437), "JSON解析后再按实际接口检查", 26, anchor="mt")
    save(im, "planning")

    im, d = canvas(760)
    box(d, (25,45,455,215), "RTL与接口", "编译预检 / 合约确认")
    box(d, (590,45,1020,215), "在线规划器", "规格 + 目标 → TestPlan", True)
    box(d, (1150,45,1575,215), "测试台与仿真", "Icarus + vvp")
    arrow(d, [(455,130),(590,130)])
    arrow(d, [(1020,130),(1150,130)])
    box(d, (25,425,455,610), "独立参考模型", "输入 + 规格状态 → 期望输出")
    box(d, (590,425,1020,610), "逐拍比较", "周期 / 信号 / 期望 / 实际")
    box(d, (1150,425,1575,610), "执行观察", "真实端口采样与日志")
    arrow(d, [(455,518),(590,518)])
    arrow(d, [(1150,518),(1020,518)])
    arrow(d, [(1362,215),(1362,425)])
    arrow(d, [(805,215),(805,315),(240,315),(240,425)])
    put(d, (400,330), "相同输入与采样条件", 25, anchor="mt")
    d.rectangle((590,660,1020,740),fill="#F3F6F7",outline=BLUE,width=3)
    put(d,(805,700),"报告 / 反例 / 波形",29,True,anchor="mm")
    arrow(d,[(805,610),(805,660)],BLUE)
    arrow(d,[(1362,610),(1362,700),(1020,700)],GRAY)
    put(d, (805,12), "规划输出需要校验；参考判据不由Agent修改", 26, True, anchor="mt")
    save(im, "architecture")

    im, d = canvas(570)
    put(d, (40,15), "相同76周期输入 / 每次228项输出比较", 31, True)
    rows = [("修复前基线",66),("修复后基线",0),
            ("满标志缺陷控制",56),("满时写入缺陷控制",46)]
    x0, x1 = 470, 1460
    for i, (label, val) in enumerate(rows):
        y = 125+i*99
        put(d, (420,y),label,29,anchor="rm")
        d.line((x0,y+28,x1,y+28), fill=LIGHT, width=2)
        if val:
            d.rectangle((x0,y-22,x0+(x1-x0)*val/70,y+22), fill=BLUE if i==1 else "#64747D")
        else:
            d.ellipse((x0-6,y-6,x0+6,y+6),fill=BLUE)
        put(d, (x0+(x1-x0)*val/70+20,y), str(val),31,True,anchor="lm")
    put(d, (1460,530), "与独立队列的差异数（项）", 27,anchor="rt")
    save(im, "fifo")

    im, d = canvas(560)
    put(d, (35,10), "固定外部UART实现的检查关系", 31,True)
    x0, w = 280, 120
    for i, bit in enumerate([0,1,0,1,0,1,0,1,0,1]):
        x = x0+i*w
        d.rectangle((x,125,x+w,267),outline="#88979F",width=2)
        put(d,(x+w/2,160),"START" if i==0 else "STOP" if i==9 else f"D{i-1}",22,True,anchor="mt")
        put(d,(x+w/2,215),str(bit),30,anchor="mt")
    put(d,(245,196),"txd",30,True,anchor="rm")
    d.line((x0,307,x0+9*w,307),fill=BLUE,width=4)
    put(d,(x0+4.5*w,330),"起始位及每个数据位持续 8 × prescale 个周期",28,anchor="mt")
    d.line((x0+9*w,410,x0+10*w,410),fill=BLUE,width=4)
    put(d,(220,402),"busy / ready",26,anchor="lm")
    put(d,(x0+10*w,445),"停止阶段busy保持 8 × prescale + 1 周期",27,anchor="rt")
    put(d,(35,505),"环回字节检查 + 逐周期txd窗口检查 + 完成期限检查",29,True)
    save(im,"uart")

    im, d = canvas(640)
    box(d,(25,100,385,280),"模型动作","append_vectors / stop",True)
    box(d,(600,100,1000,280),"格式与计划检查","字段 / 端口 / 剩余额度")
    box(d,(1200,100,1575,280),"真实执行","新DUT / 复位 / 采样")
    arrow(d,[(385,190),(600,190)])
    arrow(d,[(1000,190),(1200,190)])
    put(d,(1098,142),"通过",24,anchor="mt")
    arrow(d,[(800,280),(800,435),(205,435),(205,280)],BLUE)
    put(d,(530,460),"拒绝原因；剩余请求允许时修正",27,anchor="mt")
    arrow(d,[(1388,280),(1388,555),(10,555),(10,190),(25,190)],GRAY)
    put(d,(1015,578),"执行后的端口观察用于后续补测",27,anchor="mt")
    put(d,(800,25),"每条分支都受同一任务的请求、周期与时间限制",29,True,anchor="mt")
    save(im,"agent")

    im,d = canvas(710)
    vals=[12,10,8,8,11,10]
    names=["固定测试","均匀随机","协议随机","单次API","反馈Agent","无反馈Agent"]
    x0,y0,w=240,595,100
    for tick in [0,4,8,12]:
        y=y0-tick*39
        d.line((185,y,1530,y),fill=LIGHT,width=2)
        put(d,(160,y),str(tick),27,anchor="rm")
    put(d,(50,30),"检出数 / 12个重复缺陷任务",30,True)
    for i,(v,label) in enumerate(zip(vals,names)):
        x=x0+i*213
        col=BLUE if i==4 else "#717D85"
        d.rectangle((x,y0-v*39,x+w,y0),fill=col)
        put(d,(x+w/2,y0-v*39-15),str(v),33,True,anchor="mb")
        put(d,(x+w/2,620),label,26,anchor="mt")
    put(d,(800,675),"4种不同缺陷各重复3次；每组另有6个正确控制",25,anchor="mt")
    save(im,"comparison")

    im,d = canvas(390)
    put(d,(35,20),"反馈Agent的12个重复缺陷任务",31,True)
    x,y,width=60,135,1480
    data=[(6,"首轮检出 6",BLUE),(5,"第二轮首次检出 5","#778891"),(1,"未检出 1","#DDE4E7")]
    for val,lab,col in data:
        seg=width*val/12
        d.rectangle((x,y,x+seg,y+92),fill=col)
        if val>1:
            put(d,(x+seg/2,y+46),lab,28,True,WHITE,anchor="mm")
        else:
            put(d,(x+seg/2,y+46),"1",30,True,INK,anchor="mm")
            put(d,(x+seg/2,y+110),"未检出",25,False,INK,anchor="mt")
        x+=seg
    put(d,(60,285),"后续检出发生在第二轮；请求量与实际激励量同时见正文表格",27)
    save(im,"rounds")


textsplit.ALL_CANNOT_START += "，；：！？"
paragraph_impl.ALL_CANNOT_START += "，；：！？"
pdfmetrics.registerFont(TTFont("Song", "C:/Windows/Fonts/simsun.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("Hei", "C:/Windows/Fonts/simhei.ttf"))
pdfmetrics.registerFont(TTFont("Sans", FONT, subfontIndex=0))
pdfmetrics.registerFontFamily("Song",normal="Song",bold="Hei",italic="Song",boldItalic="Hei")


def style(name, size=11.5, **kw):
    options=dict(fontName="Song", fontSize=size, leading=size*1.62,
                 textColor=colors.HexColor(INK), wordWrap="CJK",
                 allowWidows=False, allowOrphans=False)
    options.update(kw)
    return ParagraphStyle(name, **options)


STYLES = {
    "body":style("body", firstLineIndent=23, spaceAfter=7),
    "h1":style("h1",16,fontName="Hei",leading=25,spaceBefore=18,spaceAfter=11,keepWithNext=True),
    "h2":style("h2",12.5,fontName="Hei",leading=21,spaceBefore=13,spaceAfter=7,keepWithNext=True),
    "caption":style("caption",9.4,alignment=TA_CENTER,leading=14,spaceBefore=5,spaceAfter=10),
    "cell":style("cell",8.4,leading=12.5),
    "cellhead":style("cellhead",8.7,fontName="Hei",leading=13),
    "code":style("code",8.3,fontName="Sans",leading=12.2,spaceAfter=8),
    "small":style("small",9,leading=14,spaceAfter=6),
}


def p(text, kind="body"):
    safe=html.escape(text).replace("\n","<br/>")
    return Paragraph(safe, STYLES[kind])


class Report(BaseDocTemplate):
    def __init__(self,path):
        super().__init__(str(path), pagesize=A4, leftMargin=90,rightMargin=90,
                         topMargin=72,bottomMargin=66,
                         title="ICARUS数字IP验证智能体 技术报告",author="",
                         subject="AI＋集成电路 RTL功能验证",creator="ICARUS report builder")
        self.chapter=""
        self.headings=[]
        self.elements=[]
        frame=Frame(90,66,WIDTH,PH-138,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="report",frames=frame,onPage=self.header_footer))

    def beforeDocument(self):
        self.chapter=""
        self.headings=[]
        self.elements=[]

    def header_footer(self,c,doc):
        if doc.page==1:
            return
        c.saveState()
        c.setFont("Song",8)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawCentredString(PW/2,PH-42,"ICARUS数字IP验证智能体  技术报告")
        c.setStrokeColor(colors.HexColor("#AAAAAA"))
        c.setLineWidth(.35)
        c.line(90,PH-49,PW-90,PH-49)
        c.drawCentredString(PW/2,39,str(doc.page-1))
        c.restoreState()

    def afterFlowable(self,f):
        if isinstance(f,Paragraph) and f.style.name in ("h1","h2"):
            title=f.getPlainText()
            level=0 if f.style.name=="h1" else 1
            key="h"+str(len(self.headings))
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title,key,level,False)
            if title not in ("摘要","目录"):
                self.notify("TOCEntry",(level,title,self.page-1,key))
            self.headings.append({"level":level,"title":title,"page":self.page})
        self.elements.append({"page":self.page,"type":type(f).__name__})


def table(lines):
    cells=[[x.strip() for x in line.strip().strip("|").split("|")] for line in lines]
    cells=[row for row in cells if not all(re.fullmatch(r":?-+:?",x) for x in row)]
    n=len(cells[0])
    if any(len(row)!=n for row in cells):
        raise ValueError("Inconsistent table columns")
    ratios=([.26,.74] if n==2 else [.50,.50/2,.50/2] if n==3 else
            [.46,.18,.18,.18] if n==4 else [.26,.16,.16,.20,.22] if n==5 else
            [.40]+[.10]*6 if n==7 else [1/n]*n)
    if cells[0][0]=="编号":
        ratios=[.09,.58,.33]
    elif cells[0][0]=="代码或资料":
        ratios=[.55,.45]
    t=Table([[p(c,"cellhead" if r==0 else "cell") for c in row] for r,row in enumerate(cells)],
            colWidths=[WIDTH*x for x in ratios],repeatRows=1,hAlign="CENTER")
    padding=4 if cells[0][0]=="代码或资料" else 5
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E9EDEF")),
        ("GRID",(0,0),(-1,-1),.35,colors.HexColor("#C8CFD2")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),padding),("BOTTOMPADDING",(0,0),(-1,-1),padding),
    ]))
    t.spaceBefore=6
    t.spaceAfter=12
    return t


def build():
    make_figures()
    text=SOURCE.read_text(encoding="utf-8-sig")
    story=[]
    cover=ParagraphStyle("cover",fontName="Hei",fontSize=26,leading=42,alignment=TA_CENTER,wordWrap="CJK")
    sub=style("subtitle",16,fontName="Hei",alignment=TA_CENTER,leading=27)
    story += [Spacer(1,75),Paragraph("AI＋集成电路",sub),Spacer(1,48),
              Paragraph("ICARUS数字IP验证智能体",cover),Spacer(1,28),
              Paragraph("技术报告",sub),Spacer(1,155),
              Paragraph("在线模型测试生成与逐拍功能验证",style("cover_note",12,alignment=TA_CENTER)),
              PageBreak()]
    lines=text.splitlines()
    toc=TableOfContents()
    toc.levelStyles=[
        style("toc0",11,fontName="Hei",leading=20,leftIndent=0,firstLineIndent=0,spaceBefore=7),
        style("toc1",9.2,leading=16,leftIndent=12,firstLineIndent=0),
    ]
    i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:
            i+=1
            continue
        if line.startswith("# ") or line=="AI＋集成电路技术报告":
            i+=1
            continue
        if line=="## 摘要":
            story.append(p("摘要","h1"))
            i+=1
            continue
        if line=="## 目录":
            story += [PageBreak(),p("目录","h1")]
            i+=1
            continue
        if line=="<!--TOC-->":
            story += [toc,PageBreak()]
            i+=1
            continue
        if line.startswith("## "):
            story.append(p(line[3:],"h1"))
        elif line.startswith("### "):
            story.append(p(line[4:],"h2"))
        elif line.startswith("!["):
            m=re.fullmatch(r"!\[(.*?)\]\((.*?)\)",line)
            path=(HERE/m[2]).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            with PILImage.open(path) as im:
                iw,ih=im.size
            width=WIDTH
            # Existing small wave diagrams retain legible signal labels.
            h=width*ih/iw
            if h>265:
                h=265
                width=h*iw/ih
            image=Image(str(path),width=width,height=h)
            image.hAlign="CENTER"
            story.append(KeepTogether([Spacer(1,5),image,p(m[1],"caption")]))
        elif line.startswith("|"):
            block=[]
            while i<len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i+=1
            story.append(table(block))
            continue
        elif line.startswith("```"):
            block=[]
            i+=1
            while i<len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i+=1
            # Preserve indentation with visible spaces; permit safe line wrapping.
            code=html.escape("\n".join(block)).replace(" ","&#160;").replace("\n","<br/>")
            story.append(KeepTogether([Spacer(1,3),Paragraph(code,STYLES["code"])]))
        else:
            story.append(p(line,"small" if line.startswith("[7]") or line.startswith("[8]") or line.startswith("[9]") or line.startswith("[10]") else "body"))
        i+=1
    doc=Report(OUTPUT)
    doc.multiBuild(story)
    reader=PdfReader(OUTPUT)
    full="\n".join(x.extract_text() for x in reader.pages)
    if len(reader.pages)<10 or OUTPUT.stat().st_size>10_000_000:
        raise RuntimeError("Submission page/size gate failed")
    if "339,624" not in full or "FIFO" not in full:
        raise RuntimeError("Missing report content")
    receipt={
        "output":str(OUTPUT.relative_to(ROOT)),"pages":len(reader.pages),
        "bytes":OUTPUT.stat().st_size,"sha256":hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "chinese_characters":len(re.findall(r"[\u4e00-\u9fff]",text)),
        "figures":len(re.findall(r"^!\[",text,re.M)),
        "headings":doc.headings,"visual_review":"pending",
        "new_api_requests":0,"new_dut_runs":0,
    }
    QA.mkdir(parents=True,exist_ok=True)
    (HERE/"build_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in receipt.items() if k!="headings"},ensure_ascii=False))


if __name__=="__main__":
    build()
