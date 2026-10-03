"""Handout packages contain only allowlisted public material, never real trials."""

import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("trial_kit", ROOT / "scripts/build_trial_kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


@pytest.fixture
def kit_repo(tmp_path):
    root = tmp_path / "SYNTHETIC-kit-repo"
    root.mkdir()
    templates = {
        "docs/trial/forms/session_feedback_template.json",
        "docs/trial/feedback_template.json",
        "docs/review/variant_review_template.json",
    }
    for relative in kit.ORGANIZER_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative in templates:
            path.write_bytes((ROOT / relative).read_bytes())
        else:
            path.write_bytes(("SYNTHETIC PUBLIC HANDOUT: " + relative).encode())
    for relative in (
        ".env", ".iverilog-ai/trial-sessions/real-feedback.json", "docs/trial/results.md",
        "docs/trial/forms/feedback-private.json", "docs/trial/tasks/T13_secret_answers.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SYNTHETIC-PRIVATE-SENTINEL", encoding="utf-8")
    return root


def test_participant_allowlist_excludes_answers_and_private_records(kit_repo, tmp_path):
    output = tmp_path / "out"
    manifest = kit.build(kit_repo, output)
    with ZipFile(output / "icarus-trial-participant.zip") as archive:
        assert set(archive.namelist()) == set(kit.PARTICIPANT_FILES) | {"START_HERE.txt", "SHA256SUMS.txt"}
        assert "LICENSE" in archive.namelist()
        assert not any(name.endswith(".json") or "organizer" in name or "results" in name for name in archive.namelist())
        assert "另向组织者取得代码包" in archive.read("START_HERE.txt").decode()
        assert all(b"SYNTHETIC-PRIVATE-SENTINEL" not in archive.read(name) for name in archive.namelist())
    with ZipFile(output / "icarus-trial-organizer.zip") as archive:
        assert set(archive.namelist()) == set(kit.ORGANIZER_FILES) | {"START_HERE.txt", "SHA256SUMS.txt"}
        assert "docs/trial/tasks/organizer_checks.md" in archive.namelist()
        assert "docs/trial/organizer_workflow.md" in archive.namelist()
        assert all(b"SYNTHETIC-PRIVATE-SENTINEL" not in archive.read(name) for name in archive.namelist())
        assert not any(name.startswith(".iverilog-ai/") for name in archive.namelist())
    assert manifest["purpose"] == "blank_trial_handouts_not_results"


def test_every_archived_file_and_archive_has_verified_sha256(kit_repo, tmp_path):
    output = tmp_path / "out"
    manifest = kit.build(kit_repo, output)
    disk_manifest = json.loads((output / "trial-kit-manifest.json").read_text(encoding="utf-8"))
    assert manifest == disk_manifest
    for package in manifest["packages"]:
        zip_path = output / package["archive"]
        assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == package["sha256"]
        with ZipFile(zip_path) as archive:
            for file in package["files"]:
                raw = archive.read(file["path"])
                assert hashlib.sha256(raw).hexdigest() == file["sha256"] and len(raw) == file["bytes"]
            sums = archive.read("SHA256SUMS.txt").decode().splitlines()
            assert len(sums) == len(archive.namelist()) - 1
            for line in sums:
                digest, name = line.split("  ", 1)
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    for line in (output / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_check_mode_and_missing_required_docx_do_not_write_partial_package(kit_repo, tmp_path):
    output = tmp_path / "out"
    kit.build(kit_repo, output, check_only=True)
    assert not output.exists()
    (kit_repo / "docs/trial/forms/participant_feedback.docx").unlink()
    with pytest.raises(kit.KitError, match="participant_feedback.docx"):
        kit.build(kit_repo, output)
    assert not output.exists()


def test_filled_json_template_is_not_distributed(kit_repo, tmp_path):
    path = kit_repo / "docs/trial/forms/session_feedback_template.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["session"]["participant_alias"] = "SYNTHETIC-FILLED-ALIAS"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(kit.KitError, match="拒绝打包"):
        kit.build(kit_repo, tmp_path / "out")


def test_archives_are_repeatable_for_identical_materials(kit_repo, tmp_path):
    first = kit.build(kit_repo, tmp_path / "first")
    second = kit.build(kit_repo, tmp_path / "second")
    assert [p["sha256"] for p in first["packages"]] == [p["sha256"] for p in second["packages"]]
