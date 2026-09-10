"""Package a completed run into a portable, auditable evidence bundle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_pack(target: Path) -> Path:
    archive = target.parent / f"{target.name}.zip"
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=target.parent, base_dir=target.name)
    return archive


def create_evidence_pack(result_json: str | Path, output_dir: str | Path | None = None, *, make_zip: bool = True) -> dict[str, Any]:
    source = Path(result_json).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts", {}) if isinstance(payload, dict) else {}
    if not isinstance(artifacts, dict):
        raise ValueError("result JSON artifacts must be an object")
    target = Path(output_dir).expanduser().resolve() if output_dir else source.parent / "evidence-pack"
    target.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for name, raw_path in artifacts.items():
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            continue
        destination = target / path.name
        # Avoid overwriting a same-named artifact with different content.
        if destination.exists() and _sha256(destination) != _sha256(path):
            destination = target / f"{name}-{path.name}"
        shutil.copy2(path, destination)
        copied.append({"name": name, "file": destination.name, "size": destination.stat().st_size, "sha256": _sha256(destination)})
    # Always include the source result itself, even when it was not listed in artifacts.
    if not any(item["sha256"] == _sha256(source) for item in copied):
        destination = target / "pipeline_result.json"
        shutil.copy2(source, destination)
        copied.append({"name": "source_result", "file": destination.name, "size": destination.stat().st_size, "sha256": _sha256(destination)})
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_result": str(source),
        "run_id": payload.get("simulation", {}).get("run_id") if isinstance(payload.get("simulation"), dict) else payload.get("run_id"),
        "status": payload.get("simulation", {}).get("status") if isinstance(payload.get("simulation"), dict) else payload.get("status"),
        "files": copied,
    }
    if make_zip:
        # ZIP is created after README/manifest below; path is added afterward.
        manifest["zip_file"] = str(target.parent / f"{target.name}.zip")
    (target / "evidence_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = target / "README.md"
    lines = ["# Icarus 智测证据包", "", f"- 运行 ID：`{manifest.get('run_id') or 'unknown'}`", f"- 状态：`{manifest.get('status') or 'unknown'}`", f"- 生成时间：`{manifest['created_at']}`", "", "> 本目录用于复核，不包含 API Key。结果以本地 Icarus/vvp 工具证据为准。", "", "## 文件清单", "", "| 名称 | 文件 | 大小(bytes) | SHA-256 |", "|---|---|---:|---|"]
    lines.extend(f"| {item['name']} | `{item['file']}` | {item['size']} | `{item['sha256']}` |" for item in copied)
    lines.extend(["", "## 复核步骤", "", "1. 打开 `pipeline_result.json` 或 `result.json` 查看结构化结果。", "2. 打开 `report.md` 查看 Markdown 报告。", "3. 使用 `waveform.vcd` 在 GTKWave 中复核波形（若存在）。", "4. 对照 `evidence_manifest.json` 检查文件哈希。", ""])
    report.write_text("\n".join(lines), encoding="utf-8")
    if make_zip:
        archive = _zip_pack(target)
        manifest["zip_file"] = str(archive)
        (target / "evidence_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _zip_pack(target)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, help="pipeline_result.json or result.json")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--no-zip", action="store_true", help="do not create a ZIP archive")
    args = parser.parse_args()
    manifest = create_evidence_pack(args.result, args.output_dir, make_zip=not args.no_zip)
    print(json.dumps({"output_dir": str(Path(args.output_dir or Path(args.result).parent / 'evidence-pack').resolve()), "zip_file": manifest.get("zip_file"), "files": len(manifest["files"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
