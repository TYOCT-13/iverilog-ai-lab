"""Load repository verification rules as auditable model context.

Rule files are guidance only: they are never executed as code.  The loader
returns both bounded prompt text and file fingerprints so experiments can be
reproduced after the rules evolve.

除手写规则外，本模块还会在存在时自动加载**从开源项目实测的约定**（见
``core.conventions`` 与 ``data/opensource_conventions.json``）。两者都会进入
发给模型的上下文，也都只影响"模型怎么写测试计划"，不参与任何判决。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .conventions import load_conventions, render_conventions_context

#: 实测约定的默认产物位置（相对仓库根）
CONVENTIONS_PATH = Path("data") / "opensource_conventions.json"

#: 环境变量：设为 ``0`` 可关闭实测约定的注入（用于对照实验）
CONVENTIONS_ENV = "IVERILOG_AI_CONVENTIONS"


def rule_manifest(root: str | Path, case: str) -> list[dict[str, str]]:
    root_path = Path(root).expanduser().resolve()
    if not isinstance(case, str) or not case or any(ch in case for ch in "\\/:*?\"<>|;&$(){}[]"):
        raise ValueError("case must be a logical name")
    items: list[dict[str, str]] = []
    for path in (root_path / "verification_rules" / "common.md", root_path / "verification_rules" / f"{case}.md"):
        if path.is_file() and path.is_relative_to(root_path):
            raw = path.read_bytes()
            items.append({"file": str(path.relative_to(root_path)).replace("\\", "/"), "sha256": hashlib.sha256(raw).hexdigest()})
    conventions = root_path / CONVENTIONS_PATH
    if conventions.is_file() and conventions.is_relative_to(root_path):
        items.append(
            {
                "file": CONVENTIONS_PATH.as_posix(),
                "sha256": hashlib.sha256(conventions.read_bytes()).hexdigest(),
            }
        )
    return items


def conventions_enabled() -> bool:
    """是否注入实测约定。默认开启；``IVERILOG_AI_CONVENTIONS=0`` 关闭。"""

    return os.environ.get(CONVENTIONS_ENV, "1").strip() != "0"


def conventions_context(root: str | Path, *, min_confidence: str = "moderate") -> str:
    """加载实测约定并渲染成提示片段；没有产物时返回空串（不报错）。"""

    if not conventions_enabled():
        return ""
    payload = load_conventions(Path(root).expanduser().resolve() / CONVENTIONS_PATH)
    if not payload.get("sources"):
        return ""
    return render_conventions_context(payload, min_confidence=min_confidence)


def rules_context(
    root: str | Path,
    case: str,
    contract: Mapping[str, Any] | str,
    *,
    spec_text: str = "",
    include_conventions: bool | None = None,
    min_confidence: str = "moderate",
) -> tuple[str, list[dict[str, str]]]:
    root_path = Path(root).expanduser().resolve()
    manifest = rule_manifest(root_path, case)
    parts = [spec_text] if spec_text else []
    for item in manifest:
        path = root_path / item["file"]
        if not path.is_file():  # 实测约定由下面的专用渲染器注入，不走原文拼接
            continue
        parts.append(f"\n--- {item['file']} (sha256:{item['sha256'][:16]}) ---\n{path.read_text(encoding='utf-8')}")
    measured = conventions_context(root_path, min_confidence=min_confidence) if include_conventions is not False else ""
    if measured:
        conventions_sha = next(
            (item["sha256"][:16] for item in manifest if item["file"] == CONVENTIONS_PATH.as_posix()),
            "unknown",
        )
        parts.append(f"\n--- 实测开源约定 (sha256:{conventions_sha}) ---\n{measured}")
    contract_text = contract if isinstance(contract, str) else json.dumps(contract, ensure_ascii=False)
    parts.append("\n--- DUT contract ---\n" + contract_text)
    return "受控验证规则：" + "".join(parts), manifest


def rules_fingerprint(manifest: list[dict[str, str]]) -> str:
    canonical = "\n".join(f"{item['file']}:{item['sha256']}" for item in manifest)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "CONVENTIONS_ENV",
    "CONVENTIONS_PATH",
    "conventions_context",
    "conventions_enabled",
    "rule_manifest",
    "rules_context",
    "rules_fingerprint",
]
