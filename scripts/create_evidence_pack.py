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
    simulation = payload.get("simulation", payload)
    config = simulation.get("config", {}) if isinstance(simulation, dict) else {}
    expected_testbench_hash = config.get("testbench_sha256") if isinstance(config, dict) else None
    if expected_testbench_hash:
        testbench_raw = artifacts.get("testbench") or config.get("testbench_path")
        testbench_path = Path(testbench_raw).expanduser() if isinstance(testbench_raw, str) else None
        if (testbench_path is None or not testbench_path.is_file() or testbench_path.is_symlink()
                or _sha256(testbench_path) != expected_testbench_hash):
            raise ValueError("original testbench changed or is unavailable; refuse to package stale evidence")
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
    replay: dict[str, Any] = {"status": "unavailable", "reason": "original RTL or standalone inputs not recorded"}
    rtl_raw = config.get("rtl_path") if isinstance(config, dict) else None
    expected_rtl_hash = config.get("rtl_sha256") if isinstance(config, dict) else None
    if isinstance(rtl_raw, str) and expected_rtl_hash:
        rtl = Path(rtl_raw).expanduser()
        if not rtl.is_file() or rtl.is_symlink() or _sha256(rtl) != expected_rtl_hash:
            raise ValueError("original RTL changed or is unavailable; refuse to package stale evidence")
        destination = target / rtl.name
        if destination.exists() and _sha256(destination) != expected_rtl_hash:
            destination = target / f"rtl-{rtl.name}"
        shutil.copy2(rtl, destination)
        copied.append({"name": "rtl", "file": destination.name, "size": destination.stat().st_size, "sha256": _sha256(destination)})
        testbench = next((item for item in copied if item["name"] == "testbench"), None)
        if testbench and not config.get("include_dirs"):
            replay = {"status": "available", "rtl_file": destination.name,
                      "testbench_file": testbench["file"], "top_module": config["top_module"],
                      "language": config.get("language", "2012"), "defines": config.get("defines", [])}
        elif config.get("include_dirs"):
            replay = {"status": "unavailable", "reason": "external include directories are not bundled"}
    if replay["status"] == "available":
        runner_path = Path(__file__).with_name("replay_evidence_pack.py")
        destination = target / "replay.py"
        shutil.copy2(runner_path, destination)
        copied.append({"name": "replay_runner", "file": destination.name, "size": destination.stat().st_size, "sha256": _sha256(destination)})
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
        "replay": replay,
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
    if replay["status"] == "available":
        with report.open("a", encoding="utf-8") as handle:
            handle.write("\n## 离线重放\n\n安装 Python 与 Icarus 后，在本目录执行 `python replay.py`。工具不在 PATH 时，使用 `--iverilog`、`--vvp` 指定路径。每次重放保存到新目录，零 API 请求。\n\n退出码0表示重放完成，设计结论另看 `passed` 或 `failed_checks`；原失败检查不会被当成工具执行错误。原 RTL 或测试台哈希不符会拒绝重放。涉及外部 include 的输入不会标记为可独立重放。\n")
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
