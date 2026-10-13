"""Verify deliverable page counts, byte bindings, fonts, and local source links."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
paths = [HERE / "ICARUS_AI_IC_technical_report_v4.pdf",
         HERE / "presentation/output/ICARUS_AI_IC_defense_v4.pptx",
         HERE / "presentation/output/ICARUS_AI_IC_defense_v4.pdf"]
report = PdfReader(paths[0])
deck = PdfReader(paths[2])
assert len(report.pages) == 18 and len(deck.pages) == 20
assert paths[0].stat().st_size < 10_000_000
with zipfile.ZipFile(paths[1]) as package:
    assert package.testzip() is None
    slides = [n for n in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    charts = [n for n in package.namelist() if re.fullmatch(r"ppt/(?:slides/)?charts/chart\d+\.xml", n)]
    assert len(slides) == 20 and len(charts) == 2
source = json.loads((HERE / "report_content.json").read_text(encoding="utf-8"))
assert len(source["pages"]) == 16
for page in source["pages"]:
    if page["figure"]:
        assert (HERE / "figures" / f"{page['figure']}.png").is_file()
for page in json.loads((HERE / "appendix_content.json").read_text(encoding="utf-8"))["pages"]:
    for figure in page["figure_blocks"]:
        assert (ROOT / figure["path"]).is_file()
assert len(list((HERE / "figures").glob("*.png"))) == 14
report_receipt = json.loads((HERE / "report_build_receipt.json").read_text(encoding="utf-8"))
deck_receipt = json.loads((HERE / "presentation/delivery_receipt.json").read_text(encoding="utf-8"))
assert report_receipt["sha256"] == hashlib.sha256(paths[0].read_bytes()).hexdigest()
assert "pending" not in report_receipt["visual_review"].lower()
assert not report_receipt["visual_findings_remaining"]
assert report_receipt["evidence_audit_sha256"] == hashlib.sha256((HERE / "evidence_audit.json").read_bytes()).hexdigest()
assert deck_receipt["slides"] == 20 and deck_receipt["all_20_slides_individually_visually_reviewed"]
for output in deck_receipt["outputs"]:
    path = HERE / "presentation/output" / Path(output["path"]).name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == output["sha256"]
text = [page.extract_text() for page in report.pages]
assert all(len(t) > 250 for t in text)
assert all("\ufffd" not in t for t in text)
fonts = {}
for page in report.pages:
    for ref in page["/Resources"].get("/Font", {}).values():
        font = ref.get_object()
        descriptor = font.get("/FontDescriptor")
        if descriptor:
            descriptor = descriptor.get_object()
            fonts[str(font.get("/BaseFont"))] = any(k in descriptor for k in ["/FontFile", "/FontFile2", "/FontFile3"])
assert fonts and all(fonts.values())
missing = []
for path in [HERE / "README.md", HERE / "technical_report_full.md"]:
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if "://" not in target and not (path.parent / target.split("#")[0]).exists():
            missing.append([path.name, target])
assert not missing, missing
receipt = {
    "schema": "icarus-v4-material-delivery-validation-v1", "date": "2026-10-13",
    "report_pages": 18, "defense_slides": 20, "report_illustrations": 18,
    "report_body_chinese_chars": report_receipt["body_chinese_chars"],
    "report_fonts_embedded": fonts,
    "all_report_pages_individually_viewed": True,
    "all_deck_slides_individually_viewed": True,
    "native_PowerPoint_verified": False,
    "defense_pdf": "Image-only PDF from validated final slide rendering",
    "new_model_API_requests": 0, "new_functional_simulations": 0,
    "local_UI_compile_preflight": "Icarus -tnull only; not a functional simulation",
    "source_commit_before_materials": "df7ccfa89115cfff532a73e03d447a2fc22af804",
    "current_source_Actions": "verify and CI failed; not changed by material generation",
    "source_markdown_links_checked": True,
    "scope": "Artifact checks and AI-assisted visual review, not human H02 or user retest",
    "outputs": [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in paths
    ],
}
(HERE / "delivery_validation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(receipt, ensure_ascii=False, indent=2))
