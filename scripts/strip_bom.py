"""文本卫生检查：UTF-8 BOM 与编码损坏（mojibake）。

两个都是**真实事故**留下的门禁：

1. PowerShell 的 `Set-Content -Encoding utf8` 会写入 UTF-8 BOM（即使只替换一行），
   而 Python 的 `ast.parse` / `json.loads` 对文件开头的 BOM 不容忍，会直接
   SyntaxError。事故现场：`tests/core/test_pipeline.py` 带 BOM 后，网页读取测试
   数量拿到 None。
2. 中文注释被按非 UTF-8 编码写回时会退化成成串问号。事故现场：
   `rtl/sync_reset_bug_single_stage_only.v` 与 `rtl/sync_reset_bug_never_release.v`
   的第一行注释变成 `// ???rst_n ??? 0????????`，注释语义永久丢失——而编译器
   不会报错，评审也未必发现。

用法：
    python scripts/strip_bom.py            # 清理 BOM，并报告编码损坏
    python scripts/strip_bom.py --check    # 只检查（CI 门禁），有问题退出码 1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"
SUFFIXES = {".py", ".md", ".json", ".v", ".sv", ".yml", ".yaml", ".txt", ".toml", ".cff"}
SKIP_PARTS = {".git", ".iverilog-ai", ".dsh-tmp", "__pycache__", "node_modules"}
#: 本文件自身会引用损坏样本作为例子，扫自己必然自报，因此显式排除。
SELF = Path(__file__).resolve()

#: 注释里成串的问号：中文被写坏时的典型残留。Verilog 注释里不会出现这种东西。
_QMARK_RUN = re.compile(r"(?://|/\*)[^\n]*\?{3,}")
#: GBK 解码 UTF-8、或反复转码的经典产物。
_GBK_MOJIBAKE = re.compile(r"锟斤拷|烫烫烫|屯屯屯|ï¿½|锘匡拷")


def _scan_mojibake(path: Path) -> list[str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"不是合法 UTF-8：{exc}"]
    findings: list[str] = []
    for pattern, label in ((_QMARK_RUN, "注释含成串问号（疑似编码损坏）"), (_GBK_MOJIBAKE, "疑似 mojibake")):
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            findings.append(f"{label} 第 {line} 行：{match.group(0)[:60]!r}")
    return findings


check_only = "--check" in sys.argv
targets = [
    path
    for path in ROOT.rglob("*")
    if path.is_file()
    and path.suffix in SUFFIXES
    and not (SKIP_PARTS & set(path.parts))
    and path.resolve() != SELF
]

bom_found: list[Path] = []
mojibake: dict[Path, list[str]] = {}
for path in targets:
    raw = path.read_bytes()
    if raw.startswith(BOM):
        bom_found.append(path)
        if not check_only:
            path.write_bytes(raw[len(BOM) :])
    issues = _scan_mojibake(path)
    if issues:
        mojibake[path] = issues

for path in bom_found:
    action = "发现" if check_only else "已清理"
    print(f"{action} BOM: {path.relative_to(ROOT)}")
print(f"共 {len(bom_found)} 个文件带 BOM（{'仅检查' if check_only else '已清理'}）")

for path, issues in mojibake.items():
    for issue in issues:
        print(f"编码损坏: {path.relative_to(ROOT)} —— {issue}")
print(f"共 {len(mojibake)} 个文件存在编码损坏")

failed = bool(mojibake) or (check_only and bool(bom_found))
raise SystemExit(1 if failed else 0)
