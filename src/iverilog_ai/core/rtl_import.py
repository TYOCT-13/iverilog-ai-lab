from __future__ import annotations
from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
class RTLImportError(ValueError): pass
_FILE_RE = re.compile(r"^[A-Za-z0-9_.$ -]+\.(?:v|sv|vh|svh)$", re.I)
_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", re.S)
_DECL_RE = re.compile(r"\b(input|output|inout)\b([^;]+);", re.I | re.S)
_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
@dataclass(frozen=True)
class ImportedRTL:
    path: Path
    module: str
    contract: dict[str, Any]
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ImportedRTLProject:
    """受控导入的多文件 RTL 工程。所有路径均位于 project_dir 下。"""
    project_dir: Path
    source_files: tuple[Path, ...]
    include_dirs: tuple[Path, ...]
    modules: tuple[str, ...]
    warnings: tuple[str, ...] = ()
def _safe_filename(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 160: raise RTLImportError("invalid filename")
    b = Path(name).name
    if b != name or not _FILE_RE.fullmatch(b): raise RTLImportError("only .v/.sv/.vh/.svh files are allowed")
    return b
def _ids(text: str) -> list[str]:
    text = _RANGE_RE.sub(" ", text)
    text = re.sub(r"\b(?:wire|reg|logic|signed|unsigned|tri|var|input|output|inout)\b", " ", text, flags=re.I)
    return re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", text)
def _width(chunk: str) -> tuple[int, bool]:
    m = _RANGE_RE.search(chunk)
    return (abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1, bool(re.search(r"\bsigned\b", chunk, re.I)))
def available_modules(source: str) -> tuple[str, ...]:
    """Return all module names with a parseable ANSI/non-ANSI port list."""
    if not isinstance(source, str):
        raise RTLImportError("RTL source must be text")
    return tuple(dict.fromkeys(m.group(1) for m in _MODULE_RE.finditer(source)))


def extract_contract_draft(source: str, *, filename: str = "rtl.v", module_name: str | None = None):
    if not isinstance(source, str) or not source.strip(): raise RTLImportError("empty RTL")
    if module_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", module_name):
        raise RTLImportError("invalid module name")
    matches = list(_MODULE_RE.finditer(source))
    m = next((item for item in matches if module_name is None or item.group(1) == module_name), None)
    if not m: raise RTLImportError("module with port list not found")
    module, header, warnings, ports = m.group(1), m.group(2), [], []
    current_direction = None; current_width = 1; current_signed = False
    for chunk in (x.strip() for x in header.split(",")):
        dm = re.search(r"\b(input|output|inout)\b", chunk, re.I)
        if dm:
            current_direction = dm.group(1).lower(); current_width, current_signed = _width(chunk)
            payload = chunk[dm.end():]
        elif current_direction:
            payload = chunk
        else:
            continue
        names = _ids(payload)
        if not names: warnings.append(f"unparsed declaration: {chunk}"); continue
        ports.extend({"name": n, "direction": current_direction, "width": current_width, "signed": current_signed} for n in names)
    if not ports:
        names = _ids(header); end = source.lower().find("endmodule", m.end()); body = source[m.end():end if end >= 0 else len(source)]; declarations = {}
        for dm in _DECL_RE.finditer(body):
            direction = dm.group(1).lower(); width, signed = _width(dm.group(2))
            for n in _ids(dm.group(2)): declarations[n] = (direction, width, signed)
        for n in names:
            direction, width, signed = declarations.get(n, ("input", 1, False)); ports.append({"name": n, "direction": direction, "width": width, "signed": signed})
            if n not in declarations: warnings.append(f"port {n} lacks declaration; defaulted to input/1bit")
    inputs = {p["name"] for p in ports if p["direction"] in {"input", "inout"}}
    clock = next((n for n in inputs if re.search(r"(^|_)clk($|_)|clock", n, re.I)), None); reset = next((n for n in inputs if re.search(r"rst|reset", n, re.I)), None)
    contract: dict[str, Any] = {"module": module, "ports": ports}
    if clock: contract["clock"] = {"signal": clock, "period_ns": 10.0, "edge": "posedge"}
    if reset: contract["reset"] = {"signal": reset, "active_level": 0, "synchronous": False, "assert_cycles": 2}
    warnings.append("draft only; verify ports, clock and reset before execution")
    return module, contract, warnings
def import_rtl_bytes(filename: str, data: bytes | bytearray, workspace_root: str | Path, *, max_bytes: int = 2_000_000) -> ImportedRTL:
    safe = _safe_filename(filename); raw = bytes(data)
    if not raw: raise RTLImportError("empty RTL")
    if len(raw) > max_bytes: raise RTLImportError("RTL exceeds size limit")
    try: text = raw.decode("utf-8")
    except UnicodeDecodeError as exc: raise RTLImportError("RTL must be UTF-8") from exc
    if "\x00" in text: raise RTLImportError("RTL contains NUL byte")
    root = Path(workspace_root).expanduser().resolve(strict=False)
    d = root / ".iverilog-ai" / "custom_rtl"; d.mkdir(parents=True, exist_ok=True)
    if d.is_symlink(): raise RTLImportError("custom RTL directory cannot be symlink")
    stem = re.sub(r"[^A-Za-z0-9_$]+", "_", Path(safe).stem).strip("_") or "rtl"; stem = stem if re.match(r"^[A-Za-z_]", stem) else "rtl_" + stem
    target = (d / f"{stem[:80]}-{hashlib.sha256(raw).hexdigest()[:12]}{Path(safe).suffix.lower()}").resolve()
    if target.parent != d.resolve(): raise RTLImportError("target path escapes workspace")
    target.write_bytes(raw); module, contract, warnings = extract_contract_draft(text, filename=safe)
    return ImportedRTL(target, module, contract, tuple(warnings))

def _normalise_files(files: Mapping[str, bytes | bytearray] | Sequence[tuple[str, bytes | bytearray]]) -> list[tuple[str, bytes]]:
    items = list(files.items()) if isinstance(files, Mapping) else list(files)
    out: list[tuple[str, bytes]] = []
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise RTLImportError("files must contain (filename, data) pairs")
        name, data = item
        if not isinstance(data, (bytes, bytearray)):
            raise RTLImportError(f"file {name!r} data must be bytes")
        out.append((_safe_filename(str(name)), bytes(data)))
    return out

def import_rtl_project(
    files: Mapping[str, bytes | bytearray] | Sequence[tuple[str, bytes | bytearray]],
    workspace_root: str | Path,
    *,
    include_files: Mapping[str, bytes | bytearray] | Sequence[tuple[str, bytes | bytearray]] | None = None,
    max_bytes: int = 2_000_000,
    max_total_bytes: int = 8_000_000,
) -> ImportedRTLProject:
    """安全导入多文件 RTL 工程并返回源文件、include 目录和模块清单。

    ``files`` 为 .v/.sv 文件；``include_files`` 为 .vh/.svh（也接受 .v/.sv）文件。
    文件名只能是单层安全名称，禁止绝对路径与目录穿越。
    """
    srcs = _normalise_files(files)
    if not srcs:
        raise RTLImportError("at least one RTL source file is required")
    incs = _normalise_files(include_files or {})
    for name, _ in incs:
        if not re.search(r"\.(?:vh|svh|v|sv)$", name, re.I):
            raise RTLImportError("include files must use .vh/.svh/.v/.sv extension")
    total = sum(len(data) for _, data in srcs + incs)
    if total > max_total_bytes:
        raise RTLImportError("RTL project exceeds total size limit")
    for name, data in srcs + incs:
        if len(data) > max_bytes:
            raise RTLImportError(f"file {name} exceeds size limit")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RTLImportError(f"file {name} must be UTF-8") from exc
        if "\x00" in text:
            raise RTLImportError(f"file {name} contains NUL byte")
    root = Path(workspace_root).expanduser().resolve(strict=False)
    digest = hashlib.sha256(b"".join(n.encode() + b"\0" + d for n, d in srcs + incs)).hexdigest()[:16]
    project_dir = root / ".iverilog-ai" / "custom_rtl" / f"project-{digest}"
    project_dir.mkdir(parents=True, exist_ok=True)
    if project_dir.is_symlink():
        raise RTLImportError("project directory cannot be symlink")
    source_paths: list[Path] = []
    modules: list[str] = []
    warnings: list[str] = []
    for name, data in srcs:
        target = (project_dir / name).resolve()
        if target.parent != project_dir.resolve():
            raise RTLImportError("file path escapes project directory")
        target.write_bytes(data); source_paths.append(target)
        modules.extend(available_modules(data.decode("utf-8")))
    include_dir = project_dir / "include"
    if incs:
        include_dir.mkdir(exist_ok=True)
        for name, data in incs:
            target = (include_dir / name).resolve()
            if target.parent != include_dir.resolve():
                raise RTLImportError("include path escapes project directory")
            target.write_bytes(data)
    if not modules:
        warnings.append("no parseable module declarations found")
    return ImportedRTLProject(project_dir, tuple(source_paths), (include_dir,) if incs else (), tuple(dict.fromkeys(modules)), tuple(warnings))

__all__ = ["ImportedRTL", "ImportedRTLProject", "RTLImportError", "available_modules", "extract_contract_draft", "import_rtl_bytes", "import_rtl_project"]

