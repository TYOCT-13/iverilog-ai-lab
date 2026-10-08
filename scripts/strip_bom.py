"""文本卫生检查：UTF-8 BOM、编码损坏（mojibake），以及 PowerShell/cmd 脚本的编码约定。

三条规则来自三个**真实事故**：

1. **`.py` / `.md` / `.json` 等不得带 UTF-8 BOM。** PowerShell 的
   `Set-Content -Encoding utf8` 会写入 BOM（即使只替换一行），而 Python 的 `ast.parse`
   与 `json.loads` 对开头的 BOM 不容忍，直接 SyntaxError。事故现场：
   `tests/core/test_pipeline.py` 带 BOM 后，网页读取测试数量拿到 None。
2. **中文注释被按非 UTF-8 编码写回时会退化成成串问号。** 事故现场：
   `rtl/sync_reset_bug_single_stage_only.v` 的第一行注释变成 `// ???rst_n ??? 0????`——
   语义永久丢失，而编译器不会报错。
3. **`.ps1` 带中文时必须有 BOM；`.cmd` / `.bat` 必须纯 ASCII。**（本文件新增）
   - Windows PowerShell 5.1 读**无 BOM** 的 `.ps1` 时按系统 ANSI 代码页（中文 Windows 上是
     GBK）解码，脚本里的中文全部乱码——而用户看到的正是这些提示。pwsh 7+ 不受影响，
     所以这个问题只在"右键 → 使用 PowerShell 运行"时暴露，**最容易被漏掉**。
     事故现场：`start_ui.ps1` 加完 BOM 后，一次普通的文本编辑又把 BOM 弄掉，
     脚本随即在 5.1 下报 `The string is missing the terminator`——一个看起来像语法错误、
     实际是编码问题的报错。
   - `.cmd` / `.bat` 由 cmd.exe 按 **OEM 代码页**解码，BOM 反而会让它把第一行读坏，
     所以那里的中文只能去掉（改成 ASCII）。

用法：
    python scripts/strip_bom.py            # 清理（仅第 1 条的 BOM），并报告全部问题
    python scripts/strip_bom.py --check    # 只检查（CI 门禁），有问题退出码 1
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

#: 不得带 BOM 的类型（Python / 数据 / 文档：解析器对 BOM 不容忍）。
NO_BOM_SUFFIXES = {".py", ".md", ".json", ".v", ".sv", ".yml", ".yaml", ".txt", ".toml", ".cff"}
#: 带中文就必须带 BOM 的类型（Windows PowerShell 5.1 按 ANSI 解码无 BOM 文件）。
NEEDS_BOM_SUFFIXES = {".ps1"}
#: 必须纯 ASCII 的类型（cmd.exe 按 OEM 代码页解码，BOM 与 UTF-8 中文都会坏）。
ASCII_ONLY_SUFFIXES = {".cmd", ".bat"}

SKIP_PARTS = {
    ".git", ".iverilog-ai", ".dsh-tmp", "__pycache__", "node_modules",
    # 下面这些是环境与缓存目录：文件多、且不是我们写的。漏掉 `.venv` 会让这条门禁
    # 从"秒级"变成"一分钟"（实测 47 秒），而慢门禁的下场是被跳过。
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", "runs", "build", "dist", "htmlcov",
}
#: 本文件自身会引用损坏样本作为例子，扫自己必然自报，因此显式排除。
SELF = Path(__file__).resolve()

# 历史失败响应必须保留原文。只承认这个文件的原有乱码，并核验 Git LF 字节；
# Windows checkout 的 CRLF 可规范化用于计算，但绝不写回、重编码或放宽其他文件。
FROZEN_ENCODING_EVIDENCE = {
    "docs/competition/repository-readiness-2026-10-08/attempt-1-incomplete.json":
        "c1f03f9288b99aaf73c720bab43ae9b41b2092bf8d0b8666456b1c00840e995f",
}

#: 注释里成串的问号：中文被写坏时的典型残留。Verilog 注释里不会出现这种东西。
_QMARK_RUN = re.compile(r"(?://|/\*)[^\n]*\?{3,}")

#: 替换字符 U+FFFD。**这是最可靠的信号**：任何一次用错解码器都会留下它，而正常源码里
#: 不该出现它。实测两条常见错误路径都会产出它——
#: `"中文".encode("utf-8").decode("gbk", "replace")` → `'涓�鏂�'`，
#: `"中文".encode("gbk").decode("utf-8", "replace")` → `'����'`。
_REPLACEMENT = "\ufffd"

#: 已知的 mojibake 片段。**从编码操作本身推导，不手打**。
#:
#: 手打的教训：这条正则原先写的是手打的中日韩字符，其中一个"看起来一样但码位不同"
#: （U+9535 vs 实际产物 U+951F），于是它**永远不会命中**——而测试与文档都显示它在
#: 那儿站岗。凡是靠"照着记忆敲字符"的匹配规则，都可能这样静默失效。
_MOJIBAKE_LITERALS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            b"\xef\xbf\xbd".decode("gbk", errors="replace"),        # U+FFFD 的 UTF-8 字节被当 GBK 读
            "中文".encode("utf-8").decode("gbk", errors="replace"),  # UTF-8 中文被当 GBK 读
            "中文".encode("gbk").decode("utf-8", errors="replace"),  # GBK 中文被当 UTF-8 读
        ]
    )
)
_MOJIBAKE = re.compile("|".join(re.escape(item) for item in _MOJIBAKE_LITERALS))


def scan_mojibake(path: Path) -> list[str]:
    """检查一个文件是不是合法 UTF-8，以及有没有 mojibake 特征。"""

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"不是合法 UTF-8：{exc}"]
    findings: list[str] = []
    checks = (
        (_QMARK_RUN, "注释含成串问号（疑似编码损坏）"),
        (re.compile(re.escape(_REPLACEMENT)), "含替换字符 U+FFFD（某处用错了解码器）"),
        (_MOJIBAKE, "疑似 mojibake"),
    )
    for pattern, label in checks:
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            findings.append(f"{label} 第 {line} 行：{match.group(0)[:60]!r}")
    return findings


def scan_encoding_conventions(path: Path) -> list[str]:
    """按后缀检查第 1 / 第 3 条规则。返回问题描述（空列表表示合规）。"""

    raw = path.read_bytes()
    has_bom = raw.startswith(BOM)
    suffix = path.suffix.lower()

    if suffix in NO_BOM_SUFFIXES and has_bom:
        return ["带 UTF-8 BOM（Python/JSON/Markdown 解析器会因此报错）"]

    if suffix in NEEDS_BOM_SUFFIXES:
        body = raw[len(BOM):] if has_bom else raw
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            return [f"不是合法 UTF-8：{exc}"]
        if any(ord(char) > 127 for char in text) and not has_bom:
            return [
                "含非 ASCII 字符但没有 UTF-8 BOM——Windows PowerShell 5.1 会按系统 ANSI "
                "代码页解码，脚本里的中文会变成乱码（且报错像语法错误）"
            ]

    if suffix in ASCII_ONLY_SUFFIXES:
        # BOM 先判：带 BOM 的文件按 ASCII 解码一定失败，若先查 ASCII 就会把
        # "带了 BOM"这个真因报成"含非 ASCII 字符"，用户照着改也改不对。
        if has_bom:
            return ["带 UTF-8 BOM——cmd.exe 会把 BOM 当成命令的一部分，第一行直接报错"]
        try:
            raw.decode("ascii")
        except UnicodeDecodeError:
            return ["含非 ASCII 字符——cmd.exe 按 OEM 代码页解码，中文在这里必然乱码，请改成英文"]

    return []


def _targets() -> list[Path]:
    """列出要检查的文件。

    用 `os.walk` 而不是 `Path.rglob`：rglob **无法剪枝**，跳过目录只能靠事后过滤，
    于是它仍然会走遍 `.venv` 与 `.git` 里的几万个文件——实测这让门禁从"秒级"变成
    **35 秒**。慢门禁的下场是被跳过或被并行掉，所以这里必须真的不进去。
    """

    suffixes = NO_BOM_SUFFIXES | NEEDS_BOM_SUFFIXES | ASCII_ONLY_SUFFIXES
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_PARTS]
        for filename in filenames:
            path = Path(current) / filename
            if path.suffix.lower() in suffixes and path.resolve() != SELF:
                found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    check_only = "--check" in args

    problems: dict[str, list[str]] = {}
    stripped: list[Path] = []
    added: list[Path] = []
    frozen_verified: list[str] = []

    for path in _targets():
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()

        if relative in FROZEN_ENCODING_EVIDENCE:
            digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
            if digest != FROZEN_ENCODING_EVIDENCE[relative]:
                problems[relative] = ["历史失败原件的 Git LF SHA256 不匹配，不能改写已冻结证据"]
            else:
                issues = scan_encoding_conventions(path)
                if issues:
                    problems[relative] = issues
                else:
                    frozen_verified.append(relative)
            continue

        # 第 1 条是唯一可以自动修的：只在"该没有 BOM 却带了"时清掉。
        # 第 3 条里，`.ps1` 补 BOM 也是**确定性**的（有非 ASCII 就该有 BOM），所以一并自动修；
        # 但 `.cmd` 去中文等于替作者改文案，必须人来决定，绝不自动改。
        suffix = path.suffix.lower()
        if suffix in NO_BOM_SUFFIXES and raw.startswith(BOM):
            if not check_only:
                path.write_bytes(raw[len(BOM):])
                stripped.append(path)
                raw = path.read_bytes()
        elif suffix in NEEDS_BOM_SUFFIXES and not raw.startswith(BOM):
            if not check_only:
                issues_before = scan_encoding_conventions(path)
                if issues_before:  # 只处理"缺 BOM"这一种，编码本身坏掉的不碰
                    path.write_bytes(BOM + raw)
                    added.append(path)
                    raw = path.read_bytes()

        issues = scan_encoding_conventions(path) + scan_mojibake(path)
        if issues:
            problems[relative] = issues

    for relative in FROZEN_ENCODING_EVIDENCE:
        if not (ROOT / relative).is_file():
            problems[relative] = ["缺少已冻结的历史失败原件"]

    if stripped:
        for path in stripped:
            print(f"已清理 BOM: {path.relative_to(ROOT).as_posix()}")
        print(f"共清理 {len(stripped)} 个文件的 BOM")
    else:
        print(f"BOM 清理：无需处理（{'仅检查' if check_only else '已检查'}）")
    for path in added:
        print(f"已补 UTF-8 BOM: {path.relative_to(ROOT).as_posix()}")
    if added:
        print(f"共补 {len(added)} 个 .ps1 的 BOM（Windows PowerShell 5.1 需要它才能正确读中文）")

    for relative in sorted(frozen_verified):
        print(f"已核验历史失败原件（Git LF SHA256 匹配，仅保留原有乱码）: {relative}")

    for relative, issues in sorted(problems.items()):
        for issue in issues:
            print(f"编码问题: {relative} —— {issue}")
    print(f"共 {len(problems)} 个文件存在问题")

    if problems:
        print()
        print("修法：.py/.md 等去掉 BOM；含中文的 .ps1 补 UTF-8 BOM；.cmd/.bat 改成英文。")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
