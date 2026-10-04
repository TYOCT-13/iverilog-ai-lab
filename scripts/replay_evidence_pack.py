"""Replay a self-contained evidence bundle with Python and Icarus, without an API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid


def replay(pack: Path, *, iverilog: str, vvp: str) -> dict:
    root = pack.resolve(strict=True)
    manifest = json.loads((root / "evidence_manifest.json").read_text(encoding="utf-8"))
    config = manifest.get("replay", {})
    if config.get("status") != "available":
        raise ValueError("bundle does not include all inputs needed for standalone replay")
    files = {entry["file"]: entry for entry in manifest["files"]}
    inputs = []
    for name in (config["rtl_file"], config["testbench_file"]):
        if Path(name).name != name:
            raise ValueError("replay input must be a bundled basename")
        path = root / name
        if path.is_symlink() or path.resolve().parent != root or not path.is_file():
            raise ValueError("replay input is not a regular bundled file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != files[name]["sha256"]:
            raise ValueError("replay input hash differs from evidence manifest")
        inputs.append(path)
    work = root / f"replay-{uuid.uuid4().hex[:12]}"
    work.mkdir(exist_ok=False)
    command = [iverilog, "-g" + config["language"], "-s", config["top_module"], "-o", str(work / "compile.vvp")]
    command.extend("-D" + define for define in config.get("defines", []))
    command.extend(str(path) for path in inputs)
    compiled = subprocess.run(command, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    (work / "compile.stdout.txt").write_text(compiled.stdout, encoding="utf-8")
    (work / "compile.stderr.txt").write_text(compiled.stderr, encoding="utf-8")
    if compiled.returncode:
        return {"status": "compile_failed", "compile_exit_code": compiled.returncode, "output_dir": str(work), "api_requests": 0}
    ran = subprocess.run([vvp, str(work / "compile.vvp")], cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    (work / "run.stdout.txt").write_text(ran.stdout, encoding="utf-8")
    (work / "run.stderr.txt").write_text(ran.stderr, encoding="utf-8")
    checks = failures = 0
    invalid_records = 0
    for line in ran.stdout.splitlines():
        if line.startswith("IVERILOG_AI_RESULT "):
            try:
                item = json.loads(line[len("IVERILOG_AI_RESULT "):])
                if not isinstance(item, dict) or not isinstance(item.get("ok"), bool):
                    raise ValueError("invalid result")
                if item.get("signal") is not None:
                    checks += 1
                    failures += int(not item["ok"])
            except (ValueError, TypeError):
                invalid_records += 1
    status = "execution_failed" if ran.returncode else "inconclusive" if not checks or invalid_records else "failed_checks" if failures else "passed"
    result = {"status": status, "compile_exit_code": 0, "run_exit_code": ran.returncode,
              "checks": checks, "failures": failures, "invalid_records": invalid_records,
              "api_requests": 0, "output_dir": str(work), "note": "Replay checks the saved testbench; it does not extend verification scope"}
    (work / "replay_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", nargs="?", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--iverilog", default=shutil.which("iverilog"))
    parser.add_argument("--vvp", default=shutil.which("vvp"))
    args = parser.parse_args(argv)
    if not args.iverilog or not args.vvp:
        print("Icarus tools unavailable; pass --iverilog and --vvp.")
        return 2
    try:
        result = replay(Path(args.pack), iverilog=args.iverilog, vvp=args.vvp)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "replay_unavailable", "error_type": type(exc).__name__, "api_requests": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"passed", "failed_checks"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
