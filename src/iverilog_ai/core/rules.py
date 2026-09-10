"""Load repository verification rules as auditable model context.

Rule files are guidance only: they are never executed as code.  The loader
returns both bounded prompt text and file fingerprints so experiments can be
reproduced after the rules evolve.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


def rule_manifest(root: str | Path, case: str) -> list[dict[str, str]]:
    root_path = Path(root).expanduser().resolve()
    if not isinstance(case, str) or not case or any(ch in case for ch in "\\/:*?\"<>|;&$(){}[]"):
        raise ValueError("case must be a logical name")
    items: list[dict[str, str]] = []
    for path in (root_path / "verification_rules" / "common.md", root_path / "verification_rules" / f"{case}.md"):
        if path.is_file() and path.is_relative_to(root_path):
            raw = path.read_bytes()
            items.append({"file": str(path.relative_to(root_path)).replace("\\", "/"), "sha256": hashlib.sha256(raw).hexdigest()})
    return items


def rules_context(root: str | Path, case: str, contract: Mapping[str, Any] | str, *, spec_text: str = "") -> tuple[str, list[dict[str, str]]]:
    root_path = Path(root).expanduser().resolve()
    manifest = rule_manifest(root_path, case)
    parts = [spec_text] if spec_text else []
    for item in manifest:
        path = root_path / item["file"]
        parts.append(f"\n--- {item['file']} (sha256:{item['sha256'][:16]}) ---\n{path.read_text(encoding='utf-8')}")
    contract_text = contract if isinstance(contract, str) else __import__("json").dumps(contract, ensure_ascii=False)
    parts.append("\n--- DUT contract ---\n" + contract_text)
    return "受控验证规则：" + "".join(parts), manifest


def rules_fingerprint(manifest: list[dict[str, str]]) -> str:
    canonical = "\n".join(f"{item['file']}:{item['sha256']}" for item in manifest)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


__all__ = ["rule_manifest", "rules_context", "rules_fingerprint"]
