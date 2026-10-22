"""Resolve repository-relative manual links for the Streamlit browser view."""
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

REPOSITORY_URL = "https://github.com/TYOCT-13/iverilog-ai-lab"
_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\s]+)\)")


def manual_web_links(text: str, source: Path, root: Path) -> str:
    """Map existing local targets to GitHub, preserving code and external links."""
    root = root.resolve()

    def rewrite(match: re.Match[str]) -> str:
        label, target = match.groups()
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match.group(0)
        path = (source.parent / parsed.path).resolve()
        if not path.is_relative_to(root) or not path.exists():
            return match.group(0)
        relative = quote(path.relative_to(root).as_posix(), safe="/")
        kind = "tree" if path.is_dir() else "blob"
        url = f"{REPOSITORY_URL}/{kind}/main/{relative}"
        if parsed.query:
            url += "?" + parsed.query
        if parsed.fragment:
            url += "#" + parsed.fragment
        return f"[{label}]({url})"

    lines = []
    fence = ""
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            lines.append(line)
            continue
        if fence:
            lines.append(line)
            continue
        # Inline code is literal documentation, including any example links.
        parts = re.split(r"(`+[^`]*`+)", line)
        lines.append("".join(part if i % 2 else _LINK.sub(rewrite, part) for i, part in enumerate(parts)))
    return "".join(lines)
