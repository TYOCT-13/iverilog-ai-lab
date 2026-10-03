"""校验 `docs/INDEX.md` 里登记的材料路径是否仍然存在。

为什么需要：索引最容易变成"过期路标"——文件改名/删掉之后索引照旧，读者按图索骥却找不到。
这个脚本把索引里的行内代码路径抽出来逐个检查，缺一个就报一个，退出码非 0。

用法：
    python scripts/check_doc_index.py [索引文件]

识别规则（刻意为窄，避免把命令和术语误判成路径）：
- 带盘符（`G:\\...`）或含路径分隔符的，按路径处理；
- 不带分隔符但扩展名在 `_EXTENSIONS` 里的，按路径处理；
- 以命令动词开头的整串（`python ...`、`git ...`、`normify_...`）不当路径；
- 含 `*` 的按通配处理；末尾 `[.zip]` 视为"目录或同名 zip 均可"。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_EXTENSIONS = {
    ".md", ".pdf", ".json", ".py", ".yml", ".yaml", ".cff", ".toml", ".cmd", ".ps1",
    ".exe", ".lnk", ".v", ".sv", ".txt", ".png", ".html", ".csv", ".cfg",
}
_COMMAND_WORDS = ("python", "python3", "pip", "git", "pytest", "mypy", "uv", "normify")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _is_command(token: str) -> bool:
    head = token.strip().split(" ")[0].lower()
    return head.startswith(_COMMAND_WORDS)


def looks_like_path(token: str) -> bool:
    token = token.strip()
    if not token:
        return False
    if " " in token and not re.search(r"[/\\]", token):
        return False
    if _is_command(token):
        return False
    if re.match(r"^[A-Za-z]:[/\\]", token):
        return True
    if "/" in token or "\\" in token:
        return True
    return Path(token).suffix.lower() in _EXTENSIONS


def candidates(text: str) -> list[str]:
    found: list[str] = []
    for raw in _INLINE_CODE.findall(text):
        token = raw.strip()
        if looks_like_path(token) and token not in found:
            found.append(token)
    return found


def resolve(token: str, repo: Path = REPO) -> tuple[bool, str]:
    """返回 (是否存在, 实际检查的路径描述)。"""
    if re.match(r"^[A-Za-z]:[/\\]", token):
        base = Path(token.replace("[.zip]", ""))
        if base.exists():
            return True, str(base)
        return base.with_suffix(".zip").exists(), f"{base}[.zip]"

    cleaned = token.replace("[.zip]", "").rstrip("/")
    if "*" in cleaned:
        return bool(list(repo.glob(cleaned))), f"{cleaned}（通配）"
    target = repo / cleaned
    if target.exists():
        return True, cleaned
    return target.with_suffix(".zip").exists(), f"{cleaned}[.zip]"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    index = Path(args[0]) if args else REPO / "docs" / "INDEX.md"
    if not index.is_absolute():
        index = REPO / index
    if not index.exists():
        print(f"找不到索引文件：{index}")
        return 2

    tokens = candidates(index.read_text(encoding="utf-8"))
    missing = [t for t in tokens if not resolve(t)[0]]
    print(f"索引：{index}")
    print(f"抽出的材料路径：{len(tokens)} 条")
    for token in missing:
        print(f"  [缺失] {token}")
    print(f"结论：{len(tokens) - len(missing)}/{len(tokens)} 条路径存在"
          + (f"，{len(missing)} 条缺失" if missing else "，索引未过期"))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
