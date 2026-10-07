"""Build the v3 report/evidence PDFs and render every page for visual review.

Only material artifacts are written. Sealed experiments are read-only.
Requires project Python with PyMuPDF, matplotlib and installed Chinese fonts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DATA_PATH = HERE / "material_data.json"
CHART_PATH = HERE / "assets/new108_detection.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chart(data: dict) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    candidates = [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")]
    font_path = next((p for p in candidates if p.is_file()), None)
    if font_path is None:
        raise RuntimeError("Install a Chinese font and configure this material builder before export")
    font = FontProperties(fname=str(font_path))
    rows = data["latest_new108"]["strategies"]
    values = [r["detected_samples"] for r in rows]
    assert values == [12, 10, 8, 8, 11, 10]
    fig, ax = plt.subplots(figsize=(9.5, 3.7), dpi=200)
    fig.patch.set_facecolor("white")
    colors = ["#3d4448", "#81898e", "#a8aeb2", "#7e8c94", "#009dbb", "#7e8c94"]
    bars = ax.bar(range(6), values, width=0.55, color=colors, zorder=3)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.35, f"{value}/12", ha="center", fontsize=15, color="#20262b", fontweight="bold")
    ax.set_ylim(0, 14)
    ax.set_yticks([0, 4, 8, 12])
    ax.set_ylabel("检出任务数", fontproperties=font, fontsize=13, labelpad=12)
    ax.set_xticks(range(6), [r["label"] for r in rows], fontproperties=font, fontsize=13)
    ax.tick_params(axis="both", length=0, pad=8, labelcolor="#424b52")
    ax.grid(axis="y", color="#dce1e4", linewidth=0.8, zorder=0)
    ax.spines[["left", "right", "top"]].set_visible(False)
    ax.spines["bottom"].set_color("#aab3b9")
    ax.set_axisbelow(True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.94, bottom=0.21)
    CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART_PATH, facecolor="white", metadata={"Software": "ICARUS material builder"})
    plt.close(fig)
    result = {"data": str(DATA_PATH.relative_to(ROOT)).replace("\\", "/"), "data_sha256": sha(DATA_PATH), "chart": str(CHART_PATH.relative_to(ROOT)).replace("\\", "/"), "chart_sha256": sha(CHART_PATH), "strategy_ids": [r["id"] for r in rows], "values": values, "denominator_per_strategy": 12, "distinct_defects": 4, "repeats": 3, "error_bars": "not used; descriptive repeated-task counts, not independent-sample inference", "font": font_path.name}
    (HERE / "assets/chart_source.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def build(attempt: str, data: dict) -> dict:
    private = ROOT / ".iverilog-ai/ic-materials-v3-build" / attempt
    if private.exists():
        raise FileExistsError(f"Attempt exists: {private}; use a fresh attempt ID to preserve earlier artifacts")
    private.mkdir(parents=True)
    renderer_path = ROOT / "scripts/markdown_to_pdf.py"
    module_spec = importlib.util.spec_from_file_location("icarus_material_renderer", renderer_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("Cannot load existing renderer")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    result = {
        "schema": "icarus-ic-material-pdf-validation-v3",
        "attempt": attempt,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_base_commit": data["evidence_base_commit"],
        "new_API_requests": 0,
        "new_DUT_runs": 0,
        "human_trial_or_H02": False,
        "renderer": {"path": str(renderer_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(renderer_path)},
        "material_data": {"path": str(DATA_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(DATA_PATH)},
        "visual_review": "pending actual page inspection; render success alone is not acceptance",
        "documents": [],
    }
    shutil.copy2(DATA_PATH, private / "material_data.json")
    for stem, output_name in [("technical_report", "ICARUS_技术方案_v3.pdf"), ("supporting_evidence", "ICARUS_佐证材料_v3.pdf")]:
        source = HERE / f"{stem}.md"
        source_sha = sha(source)
        shutil.copy2(source, private / source.name)
        output = HERE.parent / output_name
        module.render_markdown(source, output)
        shutil.copy2(output, private / output.name)
        png_dir = private / stem
        png_dir.mkdir()
        poppler = shutil.which("pdftoppm")
        if poppler:
            command = [poppler, "-r", "122.4", "-png", str(output), str(png_dir / "poppler-page")]
            rendered = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
            (png_dir / "poppler.stdout.txt").write_text(rendered.stdout, encoding="utf-8")
            (png_dir / "poppler.stderr.txt").write_text(rendered.stderr, encoding="utf-8")
            if rendered.returncode:
                raise RuntimeError(f"Poppler returned {rendered.returncode}; original logs retained in {png_dir}")
            for image in png_dir.glob("poppler-page-*.png"):
                number = int(image.stem.rsplit("-", 1)[1])
                image.rename(png_dir / f"page-{number:02d}.png")
        document = fitz.open(output)
        record = {"source": str(source.relative_to(ROOT)).replace("\\", "/"), "source_sha256": source_sha, "pdf": str(output.relative_to(ROOT)).replace("\\", "/"), "pdf_sha256": sha(output), "bytes": output.stat().st_size, "pages": len(document), "selectable_text": True, "metadata": document.metadata, "render_backend": "Poppler pdftoppm" if poppler else "PyMuPDF fallback", "page_records": []}
        extracted: list[str] = []
        for idx, page in enumerate(document, 1):
            text = page.get_text("text")
            extracted.append(text)
            image = png_dir / f"page-{idx:02d}.png"
            if not poppler:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
                pix.save(image)
            if not image.is_file():
                raise RuntimeError(f"Missing rendered page {idx}")
            bad_boxes = []
            spans = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if not span["text"].strip():
                            continue
                        box = fitz.Rect(span["bbox"])
                        if not page.rect.contains(box):
                            bad_boxes.append({"text": span["text"], "bbox": list(box)})
                        spans.append({"text": span["text"], "bbox": list(box), "size": span["size"], "font": span["font"]})
            fonts = []
            for f in page.get_fonts(full=True):
                blob = document.extract_font(f[0])
                fonts.append({"xref": f[0], "type": f[2], "name": f[3], "embedded": bool(blob[3])})
            layout = png_dir / f"page-{idx:02d}-layout.json"
            layout.write_text(json.dumps(spans, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            record["page_records"].append({"page": idx, "png_path": str(image.relative_to(ROOT)).replace("\\", "/"), "png_sha256": sha(image), "text_characters": len(text), "fonts": fonts, "outside_page_text": bad_boxes})
        document.close()
        (private / f"{stem}-text.txt").write_text("\n\f\n".join(extracted), encoding="utf-8")
        record["source_unchanged_after_build"] = source_sha == sha(source)
        result["documents"].append(record)
    (private / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart-only", action="store_true")
    parser.add_argument("--attempt", default="r1")
    args = parser.parse_args()
    if not args.attempt or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.attempt):
        parser.error("attempt must contain only letters, digits, '-' and '_'")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    fig = chart(data)
    if args.chart_only:
        print(json.dumps(fig, ensure_ascii=False))
        return
    result = build(args.attempt, data)
    print(json.dumps({"attempt": result["attempt"], "documents": [{k: doc[k] for k in ["pdf", "pages", "bytes", "pdf_sha256"]} for doc in result["documents"]], "visual_review": result["visual_review"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
