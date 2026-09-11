"""去掉文本文件的 UTF-8 BOM。

PowerShell 的 `Set-Content -Encoding utf8` 会写入 BOM（即使只替换一行），
而 Python 的 `ast.parse` / `json.loads` 对文件开头的 BOM 不容忍，会直接
SyntaxError。本脚本用于一次性清理，并可在 CI 里作为检查复用。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"
SUFFIXES = {".py", ".md", ".json", ".v", ".yml", ".yaml", ".txt", ".toml"}

check_only = "--check" in sys.argv
targets = [
    path
    for path in ROOT.rglob("*")
    if path.is_file()
    and path.suffix in SUFFIXES
    and ".git" not in path.parts
    and ".iverilog-ai" not in path.parts
    and ".dsh-tmp" not in path.parts
]

found = []
for path in targets:
    raw = path.read_bytes()
    if raw.startswith(BOM):
        found.append(path)
        if not check_only:
            path.write_bytes(raw[len(BOM):])

for path in found:
    action = "发现" if check_only else "已清理"
    print(f"{action}: {path.relative_to(ROOT)}")
print(f"\n共 {len(found)} 个文件带 BOM（{'仅检查' if check_only else '已清理'}）")
raise SystemExit(1 if (check_only and found) else 0)
