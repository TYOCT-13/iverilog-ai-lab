"""Publish byte-exact reviewed material artifacts; never execute an experiment."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REVISION = sys.argv[1]
if REVISION != "r3":
    raise SystemExit("This publication records the visually inspected r3 only")
BUILD_ROOT = ROOT / ".iverilog-ai/defense-v3-build"
BUILD = BUILD_ROOT / REVISION
PIN = "33a11bcce08331a5ccf18ee1c7da05059a8978a4a233a87661ff409d2d1dc8b4"
def digest(raw):
    return hashlib.sha256(raw).hexdigest()
def record(target):
    raw = target.read_bytes()
    return {"path": target.relative_to(ROOT).as_posix(), "sha256": digest(raw),
            "size_bytes": len(raw)}
def read_json(target):
    return json.loads(target.read_text(encoding="utf-8"))
def write_json(target, value):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
def copy_exact(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    with destination.open("xb") as stream:
        stream.write(raw)
    assert destination.read_bytes() == raw
    return {"original": record(source), "published": record(destination)}

build_result = read_json(BUILD / "build_result.json")
machine = read_json(BUILD / "artifact_machine_qa.json")
validation = read_json(BUILD / "defense-r3.validation.json")
source_manifest = read_json(BUILD / "source_checksums.json")
assert build_result["revision"] == REVISION and build_result["slides"] == 12
assert source_manifest["material_source_sha256"] == PIN
assert digest((ROOT / "docs/competition/ic/v3/material_data.json").read_bytes()) == PIN
for item in source_manifest["items"]:
    original = ROOT / item["relative_path"]
    snapshot = ROOT / item["private_snapshot"]
    assert record(original)["sha256"] == record(snapshot)["sha256"] == item["sha256"]
    assert original.stat().st_size == snapshot.stat().st_size == item["size_bytes"]
assert validation["packageIntegrity"]["status"] == "pass"
assert validation["presentationLayout"]["findingCount"] == 0
assert validation["firstPartyImport"]["passed"]
assert validation["nativeQuantitativeCharts"]["report"]["passed"]
assert validation["chartDataPackaging"]["converted_chart_count"] == 3
assert validation["nativeTableArithmetic"]["native_table_count"] == 7
assert validation["nativeTableArithmetic"]["checked_column_count"] == 0
assert len(machine["renders"]) == 12
assert all(page["pixel_identical"] and page["maximum_channel_difference"] == 0
           for page in machine["renders"])
assert machine["PDF_document_metadata_empty"] and machine["PPTX_core_metadata_empty"]
assert machine["embedded_literal_workbooks"] == 3
pptx = ROOT / build_result["final_pptx"]
pdf = ROOT / build_result["final_pdf"]
assert record(pptx)["sha256"] == machine["PPTX"]["sha256"] == validation["finalSha256"]
assert record(pdf)["sha256"] == machine["PDF"]["sha256"]

# A material-specific check of the actual OOXML cache, separately from provenance.
NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
chart_values = []
with zipfile.ZipFile(pptx) as package:
    parts = sorted((name for name in package.namelist()
        if re.fullmatch(r"ppt/(?:slides/)?charts/chart\d+\.xml", name)),
        key=lambda name: int(re.search(r"chart(\d+)", name)[1]))
    for part in parts:
        document = ET.fromstring(package.read(part))
        values = [float(value.text) for value in document.findall(
            ".//c:ser/c:val/c:numRef/c:numCache/c:pt/c:v", NS)]
        chart_values.append({"part": part, "values_in_native_cache_order": values})
    assert [item["values_in_native_cache_order"] for item in chart_values] == [
        [10, 11, 8, 8, 10, 12], [0, 66], [15, 13]]
    assert not list(ET.fromstring(package.read("docProps/core.xml")))

public_pptx = HERE.parent / "ICARUS_答辩材料_v3.pptx"
public_pdf = HERE.parent / "ICARUS_答辩材料_v3.pdf"
for destination in [public_pptx, public_pdf, HERE / "source_checksums.json",
                    HERE / "qa_report.json", HERE / "finalization_summary.json",
                    HERE / "finalization_receipt.original.json",
                    HERE / "artifact_machine_qa.original.json",
                    HERE / "assets/final_slides", HERE / "build_attempts"]:
    if destination.exists():
        raise SystemExit("Do not overwrite any existing published material: " + destination.name)

bindings = [copy_exact(pptx, public_pptx), copy_exact(pdf, public_pdf),
    copy_exact(BUILD / "defense-r3.validation.json", HERE / "finalization_receipt.original.json"),
    copy_exact(BUILD / "artifact_machine_qa.json", HERE / "artifact_machine_qa.original.json")]
slide_bindings = []
for page in machine["renders"]:
    stem = "slide-" + str(page["slide"]).zfill(2)
    original = ROOT / page["pptx_slide_png"]["path"]
    assert record(original) == page["pptx_slide_png"]
    image_binding = copy_exact(original, HERE / "assets/final_slides" / (stem + ".png"))
    layout_binding = copy_exact(BUILD / "final-render" / (stem + ".layout.json"),
        HERE / "assets/final_slides" / (stem + ".layout.json"))
    slide_bindings.append({"slide": page["slide"], "PNG": image_binding,
                           "layout": layout_binding, "PDF_rerender": page["pdf_page_png"]})
attempts = []
for revision, status, limitation, repair in [
    ("r1", "failed", "literal snapshot conflicted with required original workbook policy",
     "Remove inapplicable original-source-workbook policy; keep literal materialization true"),
    ("r2", "failed_after_PPTX_finalize_and_PDF_export", "bundled Python has no fitz",
     "Use already installed pypdfium2; match artifact-tool chart part paths"),
    ("r3", "completed", None, None)]:
    original_dir = BUILD_ROOT / revision
    public_dir = HERE / "build_attempts" / revision
    originals = [copy_exact(BUILD_ROOT / (revision + "-build.log"), public_dir / "build.log"),
        copy_exact(original_dir / "source_checksums.json", public_dir / "source_checksums.original.json")]
    for item in read_json(original_dir / "source_checksums.json")["items"]:
        if item["key"] == "authoring_source":
            relative = Path(item["relative_path"]).relative_to(HERE.relative_to(ROOT))
            originals.append(copy_exact(ROOT / item["private_snapshot"], public_dir / "authoring" / relative))
    receipt = original_dir / ("defense-" + revision + ".validation.json")
    if receipt.exists():
        originals.append(copy_exact(receipt, public_dir / "finalization_receipt.original.json"))
    attempts.append({"revision": revision, "status": status, "limitation": limitation,
                     "repair": repair, "original_byte_bindings": originals})

manifest = dict(source_manifest)
manifest["schema"] = "icarus-defense-v3-public-source-byte-bindings-v1"
manifest["original_build_source_manifest"] = record(BUILD / "source_checksums.json")
manifest["additional_publication_sources"] = [record(HERE / filename)
    for filename in ["README.md", "publish_final.py"]]
manifest["final_artifacts"] = [record(public_pptx), record(public_pdf)]
manifest["attempts"] = attempts
write_json(HERE / "source_checksums.json", manifest)

# These observations record the actual full r3 PNGs viewed by the authoring agent.
observations = [
    "匿名文字封面，中文与英文可读，无署名机构队号",
    "两栏公开合约要点和使用对象清晰，限制文字完整",
    "五阶段原生流程箭头完整，公开输入和私有信息边界可读",
    "两新模块原生表格与108算式完整，同团队及选型时间戳限制可见",
    "339624和87请求及预算表可读，收费补提共用cap、未知0明确",
    "六策略原生图表值12/10/8/8/11/10与0–12轴完整，固定最好与因果限制可见",
    "保存反馈与真正发送STATE数分开，31个无反馈STATE隔离和unsupported可见",
    "付费拒绝子集表与第108行14拍后终态格式失败完整，保留分母",
    "原件证据流程和核心/entry作者身份分开，strict资格限制可见",
    "旧432独立页、全48分母、414实际/18无DUT及143/144正确任务明确",
    "FIFO 66→0与人工SPEC 13→15的两图值、轴和手工范围可见，不记AI成绩",
    "工程记录、缺失证据、残项和截止完整，不将机器记录视作真人/H02"
]
qa = {
    "schema": "icarus-defense-v3-final-artifact-qa-v1",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "passed_with_explicit_application_limitations",
    "material_source_sha256": PIN,
    "source_checksums": record(HERE / "source_checksums.json"),
    "artifacts": {"PPTX": record(public_pptx), "PDF": record(public_pdf)},
    "slides": 12, "PDF_pages": 12, "PDF_image_only": True,
    "editable_native_chart_count": 3, "literal_embedded_workbook_count": 3,
    "editable_native_table_count": 7,
    "native_chart_values_checked": chart_values,
    "native_chart_owner_slides": [6, 11],
    "native_table_owner_slides": [4, 5, 7, 8, 9, 10, 12],
    "all_12_final_PPTX_slides_reimported_and_rendered": True,
    "all_12_final_PNGs_individually_viewed": True,
    "render_size_pixels": [2560, 1440],
    "all_12_PDF_pages_rerendered_pixel_identical_to_PPTX_PNG": True,
    "PDF_document_metadata_empty": True, "PPTX_core_metadata_empty": True,
    "reviewer_kind": "authoring_agent; also experiment entry code author",
    "independent_review_of_entry_author": False, "human_review": False, "H02": False,
    "native_Office_open_edit_or_slideshow_verified": False,
    "google_slides_verified": False,
    "unresolved_visual_findings": [],
    "visual_observations": [{"slide": index+1, "status": "viewed_no_visual_issue",
        "observation": text, "artifacts": slide_bindings[index]}
        for index, text in enumerate(observations)],
    "original_machine_report": bindings[3],
    "original_machine_report_visual_pending_meaning":
        "The original builder report preceded this actual per-slide authoring-agent visual inspection; it was preserved unchanged",
    "original_finalization_receipt": bindings[2],
    "native_table_arithmetic_scope": {
        "native_tables": 7, "eligible_automatic_sum_tables": 0, "checked_column_count": 0,
        "displayed_token_and_denominator_equations_checked_by_builder": True,
        "all_7_tables_automatic_arithmetic_pass_claim": False},
    "materials_only": True, "new_API_requests": 0, "credential_file_reads": 0,
    "DUT_executions": 0, "engineering_tests_reexecuted": 0, "commits": 0, "pushes": 0}
write_json(HERE / "qa_report.json", qa)
summary = {
    "schema": "icarus-defense-v3-finalization-summary-v1",
    "revision": REVISION, "status": qa["status"],
    "formal_human_reviewed": False, "native_application_open_verified": False,
    "artifacts": qa["artifacts"], "slide_count": 12, "PDF_page_count": 12,
    "PDF_image_only": True, "font_policy": validation["fontSelection"],
    "native_table_owner_slides": qa["native_table_owner_slides"],
    "native_chart_owner_slides": qa["native_chart_owner_slides"],
    "native_chart_count": 3, "native_table_count": 7, "literal_workbooks": 3,
    "native_table_arithmetic_checked_column_count": 0,
    "literal_workbook_claim":
        "New literal snapshots of the frozen slide data; original source workbooks/formulas were not preserved or claimed",
    "package_findings": 0, "layout_findings": 0, "layout_warnings": 0,
    "finalization_receipt": record(HERE / "finalization_receipt.original.json"),
    "QA_report": record(HERE / "qa_report.json"),
    "source_checksums": record(HERE / "source_checksums.json"),
    "final_slide_PNG_directory": (HERE / "assets/final_slides").relative_to(ROOT).as_posix(),
    "private_final_slide_PNG_directory": (BUILD / "final-render").relative_to(ROOT).as_posix(),
    "failed_attempts_preserved": [{"revision": item["revision"], "status": item["status"],
        "limitation": item["limitation"], "repair": item["repair"]} for item in attempts],
    "boundary":
        "Structure, cache/workbook agreement, artifact-tool import/render and authoring-agent visual QA; no Native Office or independent human/H02 validation",
    "submission_filename_status":
        "Internal v3 names retained; real team number not supplied; use real-team-number–topic–work–material on submission",
    "source_material_data_sha256": PIN,
    "new_API_requests": 0, "credential_file_reads": 0, "DUT_executions": 0,
    "engineering_tests_reexecuted": 0}
write_json(HERE / "finalization_summary.json", summary)
write_json(BUILD / "publication_result.json", {
    "schema": "icarus-defense-v3-publication-result-v1",
    "original_byte_bindings": bindings, "final_PNG_byte_bindings": slide_bindings,
    "public_records": [record(HERE / filename) for filename in
        ["source_checksums.json", "qa_report.json", "finalization_summary.json"]],
    "private_originals_retained": True, "new_API_requests": 0, "DUT_executions": 0})
print(json.dumps({"revision": REVISION, "PPTX": record(public_pptx), "PDF": record(public_pdf),
    "slide_count": 12, "final_slide_PNG_directory": summary["final_slide_PNG_directory"],
    "public_records": [record(HERE / filename) for filename in
        ["source_checksums.json", "qa_report.json", "finalization_summary.json"]],
    "Native_Office_verified": False}, ensure_ascii=False))
