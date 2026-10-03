"""Build two trial handout ZIPs from explicit public-template allowlists only."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
TASK_FILES = (
    "T01_install.md", "T02_builtin_offline.md", "T03_variant_review.md",
    "T04_custom_contract.md", "T05_compare_versions.md", "T06_static_review.md",
    "T07_state_and_input_change.md", "T08_archive_export.md", "T09_cli_reproduction.md",
    "T10_optional_api.md", "T11_narrow_keyboard.md", "T12_environment_recovery.md",
)
PARTICIPANT_FILES = (
    "LICENSE",
    "docs/trial/participant_start.md",
    *("docs/trial/tasks/" + name for name in TASK_FILES),
    "docs/trial/forms/participant_feedback.md",
    "docs/trial/forms/participant_feedback.docx",
)
ORGANIZER_FILES = PARTICIPANT_FILES + (
    "docs/trial/README.md", "docs/trial/personas_and_coverage.md",
    "docs/trial/organizer_workflow.md",
    "docs/trial/task_card.md", "docs/trial/feedback_template.json",
    "docs/trial/tasks/organizer_checks.md",
    "docs/trial/forms/session_feedback_template.json",
    "docs/trial/forms/observer_log.md", "docs/trial/forms/issue_log.md",
    "docs/review/README.md", "docs/review/independent_review_guide.md",
    "docs/review/review_record_template.md", "docs/review/variant_review_template.json",
    "docs/demo/demo_script.md", "docs/demo/recording_workflow.md",
    "scripts/summarize_trial_feedback.py", "scripts/summarize_trial_sessions.py",
    "scripts/build_trial_kit.py",
)
PARTICIPANT_START = """ICARUS 真人试用材料 · 参与者

先读 docs/trial/participant_start.md，只做组织者实际分配的任务卡。
本包只有任务与反馈表，不包含可运行的项目代码。请另向组织者取得代码包、
安装环境或可访问的网页地址；不要把本包当作完整的软件发行版。

反馈表：docs/trial/forms/participant_feedback.docx（或同名 Markdown）。
任务状态记录你是否达到试用目标，与被测 RTL 的 PASS/FAIL 分开。
遇到困难和中途停止都按实际情况记录，不需要证明工具表现良好。
任务卡涉及的源码、运行日志和仓库外链接需从另提供的项目副本访问。

SHA256SUMS.txt 列出本包其余文件的 SHA-256；本清单不包含自身。
"""
ORGANIZER_START = """ICARUS 真人试用材料 · 组织者

先读 docs/trial/README.md，再按试用者角色选择任务。
参与者请单独发 icarus-trial-participant.zip，不要把本组织者包当作盲测试用材料：
docs/trial/tasks/organizer_checks.md 含核对要点，供组织者使用。

本包仅包含项目指南、空模板和汇总脚本；不包含项目代码、真人反馈原件、
运行证据或视频。源码与冻结证据需单独准备，不代表试用或独立审核已完成。
真人原件保存到项目的 .iverilog-ai/trial-sessions/，不要提交进公开仓库。
公开摘要使用 summarize_trial_sessions.py --public，并复核授权范围。

SHA256SUMS.txt 列出本包其余文件的 SHA-256；本清单不包含自身。
"""


class KitError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    """Read only known relative paths. Never walk the repository or private data."""
    contents = {}
    missing = []
    for relative in sorted(set(ORGANIZER_FILES)):
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        if path.resolve() != path or not path.resolve().is_relative_to(root):
            raise KitError(f"拒绝链接或重定向的来源路径：{relative}")
        contents[relative] = path.read_bytes()
    if missing:
        raise KitError("材料未齐，未生成包：\n" + "\n".join(missing))
    _check_blank_templates(contents)
    return contents


def _check_blank_templates(contents: dict[str, bytes]) -> None:
    """A filled template must not accidentally become distributable feedback."""
    try:
        v2 = json.loads(contents["docs/trial/forms/session_feedback_template.json"])
        v1 = json.loads(contents["docs/trial/feedback_template.json"])
        review = json.loads(contents["docs/review/variant_review_template.json"])
        valid = (
            v2.get("record_kind") == "template"
            and not v2["session"]["session_id"]
            and not v2["session"]["participant_alias"]
            and not v2["task_records"]
            and not v2["overall_feedback"]
            and not v1["trial"]["trial_id"]
            and not v1["trial"]["tester_alias"]
            and review.get("record_kind") == "blank_human_review_template"
            and not review["review_id"]
            and not review["reviewer"]["alias"]
            and all(not record["record_id"] and record["review"]["verdict"] is None for record in review["records"])
        )
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise KitError("JSON 模板结构不符合空白模板要求") from exc
    if not valid:
        raise KitError("模板已有试用或审核记录，拒绝打包；请恢复项目空模板")


def _archive(contents: dict[str, bytes], paths: tuple[str, ...], start: str) -> tuple[bytes, list[dict[str, Any]]]:
    members = {path: contents[path] for path in paths}
    members["START_HERE.txt"] = start.encode("utf-8")
    sums = "".join(f"{_sha(raw)}  {name}\n" for name, raw in sorted(members.items()))
    members["SHA256SUMS.txt"] = sums.encode("utf-8")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, raw in sorted(members.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    manifest = [{"path": name, "bytes": len(raw), "sha256": _sha(raw)} for name, raw in sorted(members.items())]
    return buffer.getvalue(), manifest


def build(root: Path, output: Path, *, check_only: bool = False) -> dict[str, Any]:
    root = root.resolve()
    contents = _source_files(root)
    manifest: dict[str, Any] = {"schema_version": "1.0", "purpose": "blank_trial_handouts_not_results", "packages": []}
    artifacts = {}
    for audience, paths, start in (
        ("participant", PARTICIPANT_FILES, PARTICIPANT_START),
        ("organizer", ORGANIZER_FILES, ORGANIZER_START),
    ):
        name = f"icarus-trial-{audience}.zip"
        data, members = _archive(contents, paths, start)
        artifacts[name] = data
        manifest["packages"].append({"archive": name, "audience": audience, "sha256": _sha(data), "bytes": len(data), "files": members})
    if check_only:
        return manifest
    output = output.resolve()
    # All output names are owned by this builder; no source file or result is touched.
    output.mkdir(parents=True, exist_ok=True)
    artifacts["trial-kit-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    artifacts["SHA256SUMS.txt"] = "".join(f"{_sha(data)}  {name}\n" for name, data in sorted(artifacts.items())).encode("utf-8")
    for name, data in artifacts.items():
        destination = output / name
        if destination.is_symlink():
            raise KitError(f"输出文件不能为符号链接：{name}")
        destination.write_bytes(data)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="validate materials and show counts without writing ZIPs")
    args = parser.parse_args(argv)
    try:
        output = args.output_dir or args.repo / "dist/trial-kit"
        manifest = build(args.repo, output, check_only=args.check)
        for package in manifest["packages"]:
            print(f"{package['archive']}: {len(package['files'])} files, SHA256 {package['sha256']}")
        if not args.check:
            print(f"Output: {output.resolve()}")
    except (OSError, KitError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
