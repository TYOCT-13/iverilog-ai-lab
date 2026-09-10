import json
from pathlib import Path

from scripts.create_evidence_pack import create_evidence_pack


def test_create_evidence_pack_copies_and_hashes_files(tmp_path):
    artifact = tmp_path / "report.md"
    artifact.write_text("# report\n", encoding="utf-8")
    result = tmp_path / "pipeline_result.json"
    result.write_text(json.dumps({"artifacts": {"report": str(artifact)}, "simulation": {"run_id": "abc", "status": "passed"}}), encoding="utf-8")
    manifest = create_evidence_pack(result, tmp_path / "pack")
    assert manifest["run_id"] == "abc"
    assert (tmp_path / "pack" / "evidence_manifest.json").is_file()
    assert (tmp_path / "pack" / "README.md").is_file()
    assert any(item["name"] == "report" for item in manifest["files"])
    assert Path(manifest["zip_file"]).is_file()
