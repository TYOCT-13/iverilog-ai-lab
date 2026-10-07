"""Seal current material checks and explicitly confirmed AI visual acceptance.

This is a local byte-binding step, not an experiment, human review or Office test.
It must never overwrite a prior receipt or silently convert pending visual fields.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
OWN = Path(__file__).resolve().parent
V3 = OWN.parent
BINDINGS = {}


def guard(event, args):
    if event.startswith("socket.") or event == "subprocess.Popen":
        raise RuntimeError("Material sealing forbids network and child processes")


sys.addaudithook(guard)


def binding(path):
    path = path.resolve()
    assert path.is_relative_to(ROOT), ("Outside repository", path)
    raw = path.read_bytes()
    result = {"path": path.relative_to(ROOT).as_posix(),
              "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    BINDINGS[result["path"]] = result
    return result


def verified(item):
    actual = binding(ROOT / item["path"])
    assert actual["sha256"] == item["sha256"], ("SHA mismatch", item["path"])
    expected_bytes = item.get("bytes", item.get("size_bytes"))
    if expected_bytes is not None:
        assert actual["bytes"] == expected_bytes, ("Byte size mismatch", item["path"])
    return actual


def read(path):
    binding(path)
    return json.loads(path.read_text(encoding="utf-8"))


def verify_attempt(name, status_key, units_key, passed_key=None):
    directory = OWN / name
    result = read(directory / "result.json")
    receipt = read(directory / "receipt.json")
    for key in ("result", "log", "tool"):
        if key in receipt:
            verified(receipt[key])
    if status_key is not None:
        assert result[status_key] is True
    checks = result["checks"]
    assert len(checks) == result[units_key]
    assert len({item["id"] for item in checks}) == len(checks)
    assert all(item["status"] == "passed" for item in checks)
    if passed_key:
        assert result[passed_key] == len(checks)
    for item in result["artifacts"]:
        verified(item)
    assert result["new_API_requests"] == result["credentials_read"] == result["new_DUT_runs"] == result["new_source_tests"] == 0
    return result, {"attempt": name, "result": binding(directory / "result.json"),
                    "receipt": binding(directory / "receipt.json"),
                    "passed_check_units": len(checks), "failed_check_units": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-visual-acceptance-confirmed", required=True, action="store_true")
    args = parser.parse_args()
    assert args.root_visual_acceptance_confirmed
    target = OWN / "final_receipt.json"
    assert not target.exists(), "Refusing to overwrite sealed final receipt"

    facts, fact_group = verify_attempt("facts-r1", "fact_consistency_passed", "unique_material_check_units", "passed")
    text, text_group = verify_attempt("text-r3", None, "unique_text_check_units", "passed_check_units")
    outputs, output_group = verify_attempt("outputs-r3", "mechanical_checks_passed", "unique_material_output_check_units")
    assert facts["unique_material_check_units"] == 296
    assert text["submission_counts"]["name_unicode_characters"] == 15
    assert text["submission_counts"]["intro_unicode_characters"] == 201
    assert outputs["unique_material_output_check_units"] == 165

    data_binding = binding(V3 / "material_data.json")
    assert data_binding["sha256"] == "33a11bcce08331a5ccf18ee1c7da05059a8978a4a233a87661ff409d2d1dc8b4"
    report_visual = read(V3 / "validation.json")
    second_visual = read(OWN / "report_visual_review_r2.json")
    defense_qa = read(ROOT / "docs/competition/ic/defense_v3/qa_report.json")
    defense_summary = read(ROOT / "docs/competition/ic/defense_v3/finalization_summary.json")
    assert len(report_visual["actual_visual_inspection"]) == 16
    assert all(item["accepted"] for item in report_visual["actual_visual_inspection"])
    assert second_visual["actual_pages_viewed"] == 16
    assert defense_qa["all_12_final_PNGs_individually_viewed"] is True
    assert defense_qa["all_12_PDF_pages_rerendered_pixel_identical_to_PPTX_PNG"] is True
    assert not defense_qa["unresolved_visual_findings"]
    assert defense_summary["native_application_open_verified"] is False
    assert defense_summary["native_chart_count"] == 3
    assert defense_summary["native_table_count"] == 7
    assert defense_summary["literal_workbooks"] == 3

    pages = []
    pdfs = []
    for document in report_visual["documents"]:
        actual = binding(ROOT / document["pdf"])
        assert actual["sha256"] == document["pdf_sha256"]
        assert actual["bytes"] == document["bytes"]
        assert binding(ROOT / document["source"])["sha256"] == document["source_sha256"]
        pdfs.append({"artifact": actual, "pages": document["pages"], "selectable_text": True})
        role = "technical_report" if document["pages"] == 10 else "supporting_evidence"
        assert document["pages"] == {"technical_report": 10, "supporting_evidence": 6}[role]
        for page in document["page_records"]:
            png = binding(ROOT / page["png_path"])
            assert png["sha256"] == page["png_sha256"]
            pages.append({"document": role, "page": page["page"], "PNG": png,
                          "actual_root_viewing": True,
                          "basis": "Actual individual image inspection in prior root turns, recorded in r2 validation; original rendered bytes rechecked at sealing",
                          "finding": "Text, figures, tables and page context readable; no observed overlap or clipping"})
    for item in second_visual["pdfs"]:
        verified(item)
    for page in second_visual["pages"]:
        assert page["actually_viewed"] is True
        verified(page["page_png"])

    for observation in defense_qa["visual_observations"]:
        number = observation["slide"]
        images = observation["artifacts"]["PNG"]
        original = verified(images["original"])
        public = verified(images["published"])
        assert original["sha256"] == public["sha256"]
        pages.append({"document": "defense", "page": number, "PNG": public,
                      "actual_root_viewing": True,
                      "basis": "Root individually viewed slides 1-8 in preceding turns and slides 9-12 in 2026-10-07 continuation; some earlier tool views resized the full image. Complete source bytes equal the public PNG",
                      "finding": "Native tables/charts, numerical caveats and typography legible; no observed clipped text, overlapping objects or numerical conflict"})
    assert len(pages) == len({(page["document"], page["page"]) for page in pages}) == 28
    for item in defense_summary["artifacts"].values():
        verified(item)
    defense_pdf = verified(defense_summary["artifacts"]["PDF"])
    pdfs.append({"artifact": defense_pdf, "pages": 12, "selectable_text": False})
    assert sum(item["pages"] for item in pdfs) == 28

    # The mechanical result remains immutable: actual AI acceptance is recorded separately.
    assert outputs["visual_review_complete"] is False
    assert outputs["final_claim_review_complete"] is False
    root_acceptance = {
        "reviewer": "root AI material packager, not an independent human",
        "root_actual_visual_inspection_complete": True,
        "actual_individual_pages_viewed": 28,
        "page_records": pages,
        "claim_context_review_complete": True,
        "context_basis": "Read candidate lines in context, verified fixed/new/old denominators and full failed-task evidence; no causal, industrial, independently blind or human claims added",
        "unresolved_visual_findings": [],
        "original_pending_mechanical_fields_preserved": True,
        "human_trial": False, "H02_human_review": False,
        "Native_Office_verified": False,
    }
    binding(ROOT / "docs/review/ic_materials_v3_review_2026-10-07.md")
    for relative in ("README.md", "docs/INDEX.md", "docs/competition/ic/gap_checklist.md", "docs/experiment/metric_inventory.md"):
        binding(ROOT / relative)
    binding(Path(__file__))
    result = {
        "schema": "icarus-v3-final-material-delivery-review-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_delivery_date": "2026-10-07",
        "artifact_production_date": "2026-10-05",
        "evidence_base_commit": report_visual["evidence_base_commit"],
        "status": "passed_with_explicit_evidence_and_application_limitations",
        "check_groups": [fact_group, text_group, output_group],
        "groups_not_summed_or_counted_as_model_samples": True,
        "new_API_requests": 0, "credential_file_reads_by_this_sealer": 0,
        "new_DUT_executions": 0, "new_engineering_tests": 0,
        "historical_experiment_or_ledger_rewritten": False,
        "formal_human_review": False, "submission_uploaded": False,
        "root_acceptance": root_acceptance,
        "PDFs": pdfs,
        "editable_PPTX": verified(defense_summary["artifacts"]["PPTX"]),
        "submission_counts": text["submission_counts"],
        "material_data": data_binding,
        "current_source_bindings": list(BINDINGS.values()),
        "limitations": ["Image-only defense PDF; edit the PPTX", "Native Office not verified", "No real participant or H02 records", "No independent external blind test, hardware or complete other-machine reproduction", "Real team number and actual upload not supplied", "12 strict RTL style findings and WaveDrom dependency gap belong to the frozen evaluated source"],
    }
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "groups": [group["passed_check_units"] for group in result["check_groups"]], "actual_pages_viewed": 28, "receipt": binding(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
