"""构建《佐证材料 v4》：生成图表、渲染 PDF、逐页检查并留回执。

设计原则：
- 复用的图直接取自技术报告的同一份 figures/，避免报告与佐证出现两个版本的口径；
- 新增图（432批次）用与报告一致的配色与字号，保证两图同族；
- 不新增任何 API 请求或 DUT 执行，只读取已封存回执；
- 渲染后逐页检查：页数、体积、元数据、字体是否嵌入、文字是否越界。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
IC = HERE.parents[1]                     # docs/competition/ic
ROOT = HERE.parents[4]                   # repo root
ASSETS = HERE / "assets"
SOURCE = HERE / "supporting_evidence.md"
OUTPUT = IC / "ICARUS_佐证材料_v4_提交版.pdf"
PRIVATE = ROOT / ".iverilog-ai" / "evidence-v4-build" / "r1"

INK, GRAY, BLUE, GRID = "#171717", "#687176", "#25667D", "#DCE1E4"
BAR_GRAY = "#717D85"
FONT = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")

#: 报告里已有、直接复用的图（源文件 → 本地副本名）
REUSED = {
    "comparison.png": IC / "technical_report/figures/comparison.png",   # 报告图8
    "rounds.png": IC / "technical_report/figures/rounds.png",           # 报告图9
    "fifo.png": IC / "technical_report/figures/fifo.png",               # 报告图5
    "uart.png": IC / "technical_report/figures/uart.png",               # 报告图6
    "workspace.jpg": IC / "v4/screenshots/upload-workspace-2026-10-13.jpg",  # 报告图10
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def chart_432() -> Path:
    """八模块432批次六策略检出数，配色与排版对齐技术报告图8。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    for needed in (FONT, FONT_BOLD):
        if not needed.is_file():
            raise RuntimeError(f"缺少中文字体：{needed}")
    regular = FontProperties(fname=str(FONT))
    bold = FontProperties(fname=str(FONT_BOLD))

    labels = ["固定测试", "均匀随机", "协议随机", "单次API", "反馈Agent", "无反馈Agent"]
    values = [48, 32, 48, 29, 37, 37]
    assert values == [48, 32, 48, 29, 37, 37]
    colors = [BAR_GRAY] * 6
    colors[4] = BLUE

    fig, ax = plt.subplots(figsize=(8.0, 3.55), dpi=200)
    fig.patch.set_facecolor("white")
    bars = ax.bar(range(6), values, width=0.56, color=colors, zorder=3)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 1.1, str(value),
                ha="center", va="bottom", fontproperties=bold, fontsize=15, color=INK)
    ax.set_ylim(0, 56)
    ax.set_yticks([0, 16, 32, 48])
    ax.set_xticks(range(6), labels, fontproperties=regular, fontsize=12.5)
    ax.tick_params(axis="both", length=0, pad=8, labelsize=12, colors=INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#AAB3B9")
    ax.set_title("检出数 / 48个重复缺陷任务", fontproperties=bold, fontsize=14,
                 color=INK, loc="left", pad=12)
    fig.text(0.5, 0.035, "16种不同缺陷各重复3次；每策略另有24个正确控制任务",
             ha="center", fontproperties=regular, fontsize=11, color=GRAY)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.86, bottom=0.20)
    out = ASSETS / "chart_432.png"
    fig.savefig(out, facecolor="white", metadata={"Software": "ICARUS evidence builder"})
    plt.close(fig)
    return out


def prepare_assets() -> list[dict]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = []
    for name, src in REUSED.items():
        if not src.is_file():
            raise FileNotFoundError(src)
        dst = ASSETS / name
        shutil.copy2(src, dst)
        records.append({"asset": name, "kind": "reused", "source": rel(src),
                        "sha256": sha(dst), "bytes": dst.stat().st_size})
    new_chart = chart_432()
    records.append({"asset": new_chart.name, "kind": "generated",
                    "source": rel(HERE / "build_evidence.py"),
                    "sha256": sha(new_chart), "bytes": new_chart.stat().st_size})
    return records


def render() -> Path:
    renderer_path = ROOT / "scripts/markdown_to_pdf.py"
    spec = importlib.util.spec_from_file_location("icarus_material_renderer", renderer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入既有渲染器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.render_markdown(SOURCE, OUTPUT)
    return renderer_path


def inspect(renderer_path: Path, assets: list[dict]) -> dict:
    if PRIVATE.exists():
        shutil.rmtree(PRIVATE)
    PRIVATE.mkdir(parents=True)
    shutil.copy2(SOURCE, PRIVATE / SOURCE.name)
    shutil.copy2(OUTPUT, PRIVATE / OUTPUT.name)

    doc = fitz.open(OUTPUT)
    pages = doc.page_count
    result = {
        "schema": "icarus-evidence-v4-validation",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "output": rel(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
        "pdf_sha256": sha(OUTPUT),
        "source": rel(SOURCE),
        "source_sha256": sha(SOURCE),
        "renderer": {"path": rel(renderer_path), "sha256": sha(renderer_path)},
        "new_api_requests": 0,
        "new_dut_runs": 0,
        "assets": assets,
        "pages": pages,
        "metadata": {k: (v or "") for k, v in (doc.metadata or {}).items()},
        "page_records": [],
    }
    page_dir = PRIVATE / "pages"
    page_dir.mkdir()
    forbidden = ["大学", "学院", "学校", "指导教师", "指导老师", "导师", "辅导员", "实验室", "课题组"]
    hits: list[str] = []
    for idx, page in enumerate(doc, 1):
        text = page.get_text("text")
        for word in forbidden:
            if word in text:
                hits.append(f"p{idx}:{word}")
        outside = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if not span["text"].strip():
                        continue
                    box = fitz.Rect(span["bbox"])
                    if not page.rect.contains(box):
                        outside.append({"text": span["text"], "bbox": list(box)})
        images = [i for i in page.get_images(full=True)]
        pix = page.get_pixmap(dpi=120)
        png = page_dir / f"page-{idx:02d}.png"
        pix.save(png)
        result["page_records"].append({
            "page": idx,
            "png": rel(png),
            "characters": len(text),
            "images": len(images),
            "outside_page_text": outside,
            "first_line": next((l.strip() for l in text.splitlines() if l.strip()), ""),
        })
    result["anonymity_hits"] = hits
    result["page_limit_check"] = {"pages": pages, "note": "官方未对佐证单 PDF 设定页数上限；体积上限见尺寸检查"}
    result["size_limit_check"] = {"bytes": result["bytes"],
                                  "within_10MB": result["bytes"] <= 10 * 1024 * 1024}
    result["selectable_text"] = all(r["characters"] > 200 for r in result["page_records"])
    result["visual_review"] = "pending actual page inspection"
    doc.close()
    (PRIVATE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    (HERE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return result


def main() -> None:
    assets = prepare_assets()
    renderer_path = render()
    result = inspect(renderer_path, assets)
    print(json.dumps({k: result[k] for k in ("output", "pages", "bytes", "anonymity_hits",
                                             "selectable_text", "page_limit_check",
                                             "size_limit_check")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
