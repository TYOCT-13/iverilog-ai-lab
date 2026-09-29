"""抓取候选外部模块，记录来源证据，并**立刻探测本机 Icarus 能不能编译**。

为什么要先探测编译：路线图要求"优先 Icarus 支持的模块"。`common_cells` 是 SystemVerilog，
而本机 Icarus 是 2015 年的 12.0（`s20150603`），SV 支持不完整——先测，别等到写完成
合约与变体才发现编不过。

产物：
  .iverilog-ai/external/<repo>-<sha8>/...        上游源码（不进版本库，不重新分发）
  .iverilog-ai/external/manifest.json            来源证据：URL / commit / 许可 / 每个文件 sha256
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(".").resolve()
OUT = ROOT / ".iverilog-ai" / "external"
IVERILOG = Path(r"D:\iverilog\bin\iverilog.exe")

SOURCE = {
    "repository": "pulp-platform/common_cells",
    "commit": "e73baaec2ca665cd80c3c384e9258e35242b829c",
    "spdx": "Solderpad-0.51",
    "license_url": "https://github.com/pulp-platform/common_cells/blob/master/LICENSE",
    # 选型理由：分别覆盖"参数化输入 / 握手缓冲 / 有限状态控制"三类需求，且都够小。
    "files": [
        "src/counter.sv",
        "src/shift_reg.sv",
        "src/spill_register.sv",
        "src/rr_arb_tree.sv",
        "src/lzc.sv",
    ],
}

#: raw 模板单独放一个显式 str 常量：混在 SOURCE 字典里会让类型推断成 str | list[str]。
RAW_TEMPLATE: str = "https://raw.githubusercontent.com/pulp-platform/common_cells/{commit}/{path}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "iverilog-ai-lab/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def probe_compile(path: Path) -> dict:
    """试着单独编译这个文件（-g2012 是 SystemVerilog）。"""

    for grammar in ("-g2012", "-g2005-sv", "-g2005"):
        done = subprocess.run(
            [str(IVERILOG), grammar, "-o", str(OUT / "_probe.vvp"), str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if done.returncode == 0:
            return {"grammar": grammar, "ok": True, "error": ""}
    return {"grammar": "", "ok": False, "error": (done.stdout + done.stderr).strip()[:400]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"common_cells-{SOURCE['commit'][:8]}"
    target.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    print(f"仓库 {SOURCE['repository']} @{SOURCE['commit'][:8]}  许可 {SOURCE['spdx']}")
    for relative in SOURCE["files"]:
        url = RAW_TEMPLATE.format(commit=SOURCE["commit"], path=relative)
        try:
            data = fetch(url)
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            print(f"  ✗ {relative}: {error}")
            records.append({"path": relative, "url": url, "error": str(error)})
            continue
        local = target / Path(relative).name
        local.write_bytes(data)
        result = probe_compile(local)
        mark = "✓" if result["ok"] else "✗"
        print(f"  {mark} {relative:28s} {len(data):6d} B  sha256={sha256(data)[:16]}  编译={result['grammar'] or '失败'}")
        if not result["ok"]:
            print(f"      {result['error'].splitlines()[0][:150] if result['error'] else ''}")
        records.append(
            {
                "path": relative,
                "url": url,
                "bytes": len(data),
                "sha256": sha256(data),
                "local": str(local.relative_to(ROOT)),
                "compiles": result["ok"],
                "grammar": result["grammar"],
                "compile_error": result["error"],
            }
        )
    manifest_path = OUT / "manifest.json"
    previous = {}
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = dict(previous)
    manifest[SOURCE["repository"]] = {
        "repository": SOURCE["repository"],
        "commit": SOURCE["commit"],
        "spdx": SOURCE["spdx"],
        "license_url": SOURCE["license_url"],
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": "上游源码只落在 .iverilog-ai/（不进版本库、不重新分发）；仓库内只保存本清单的结果与哈希。",
        "files": records,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n清单已写入 {manifest_path.relative_to(ROOT)}")
    ok = sum(1 for item in records if item.get("compiles"))
    print(f"可编译 {ok}/{len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
