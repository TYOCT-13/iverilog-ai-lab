"""从 RTL 源码提取**合约草稿**。

定位（2026-09-29 审查后收紧）：
这是一个**草稿提取器**，不是 Verilog 解析器。它的职责是：凡是能从源码里
*可靠*读出来的，就读出来；读不出来的，**明确标成"要人工确认"**，
而不是猜一个值让流程继续跑下去。

三条踩过坑的规则：

1. **位宽只有字面量才算可靠。** `[31:0]` 是 32 位；`[WIDTH-1:0]` 在没有可解析
   参数时旧实现会算成 **1 位**，并且把 `WIDTH` 当成一个端口。于是合约里多出一个
   不存在的端口、真端口变成 1 位，生成的 testbench"合法"且"通过"，但什么都没测。
   现在这种声明会把该端口的 `width` 写成 ``None``——JSON 里看得见，提交时校验会
   明确报错，绝不会静默变成 1 位。
2. **参数名绝不进端口列表。** 提取标识符前先把整段 `[...]` 去掉，而不是只去掉
   能匹配 `[数字:数字]` 的那些。
3. **复位极性与同步属性来自代码证据，不来自端口名。** 名字只能用来*挑选*候选
   端口；极性/同步性从 `always @(posedge clk or negedge rst_n)`、
   `if (!rst_n)` 这类**结构**里读。读不到就写 ``None`` 要求人工确认。

有限范围内的参数支持（仍然禁止任意表达式）：`module m #(parameter WIDTH = 8)`
里的**十进制字面量**参数，只用于解析 `[WIDTH-1:0]` 这一种形式。参数值是表达式
（`8*2`、`$clog2(N)`）时一律视为不可解析。
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


class RTLImportError(ValueError):
    pass


_FILE_RE = re.compile(r"^[A-Za-z0-9_.$ -]+\.(?:v|sv|vh|svh)$", re.I)
_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\((.*?)\)\s*)?\((.*?)\)\s*;", re.S)
_DECL_RE = re.compile(r"\b(input|output|inout)\b([^;]+);", re.I | re.S)
_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
#: 任何方括号内容。位宽、宏、数组维度都长这样，提取标识符前必须整段去掉。
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
#: 头部参数表里的**十进制字面量**参数。
_PARAMETER_RE = re.compile(r"\b(?:parameter|localparam)\b(?:\s+(?:integer|signed|unsigned|logic|wire|reg))*\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(\d+)\s*(?=,|$)", re.I)
#: `[NAME-1:0]` / `[0:NAME-1]`：唯一允许用参数替换的形式。
_PARAM_RANGE_RE = re.compile(r"^\[\s*([A-Za-z_][A-Za-z0-9_$]*)\s*-\s*1\s*:\s*0\s*\]$")
_PARAM_RANGE_REVERSED_RE = re.compile(r"^\[\s*0\s*:\s*([A-Za-z_][A-Za-z0-9_$]*)\s*-\s*1\s*\]$")
_ALWAYS_RE = re.compile(r"\balways(?:_ff|_comb|_latch)?\s*@\s*\(([^)]*)\)", re.I)
_EDGE_RE = re.compile(r"\b(posedge|negedge)\s+([A-Za-z_][A-Za-z0-9_$]*)", re.I)
#: 时钟/复位端口名的**建议**（只用来挑候选，不用来定极性）。
_CLOCK_HINT_RE = re.compile(r"(^|_)clk($|_)|clock", re.I)
_RESET_HINT_RE = re.compile(r"rst|reset", re.I)


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
    if not isinstance(name, str) or not name or len(name) > 160:
        raise RTLImportError("invalid filename")
    b = Path(name).name
    if b != name or not _FILE_RE.fullmatch(b):
        raise RTLImportError("only .v/.sv/.vh/.svh files are allowed")
    return b


def _ids(text: str) -> list[str]:
    """从声明片段里取标识符。

    ``_BRACKET_RE`` 而不是 ``_RANGE_RE``：只去掉字面位宽的话，`[WIDTH-1:0]` 会留下
    `WIDTH` 并被当成端口名——那正是审查发现的虚假端口来源。
    """

    text = _BRACKET_RE.sub(" ", text)
    text = re.sub(r"\b(?:wire|reg|logic|signed|unsigned|tri|var|input|output|inout)\b", " ", text, flags=re.I)
    return re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", text)


def _width(chunk: str, parameters: Mapping[str, int] | None = None) -> tuple[int | None, bool]:
    """返回 (width, signed)；width 为 ``None`` 表示**无法可靠解析**。

    ``None`` 是刻意的：调用方必须把它写成"要求人工合约"，而不是退化成 1 位。
    """

    signed = bool(re.search(r"\bsigned\b", chunk, re.I))
    brackets = _BRACKET_RE.findall(chunk)
    if not brackets:
        return 1, signed
    if len(brackets) > 1:
        # 多维/打包数组：本期不支持，直接要求人工合约。
        return None, signed
    bracket = brackets[0].strip()
    match = _RANGE_RE.fullmatch(bracket)
    if match:
        return abs(int(match.group(1)) - int(match.group(2))) + 1, signed
    if parameters:
        for pattern in (_PARAM_RANGE_RE, _PARAM_RANGE_REVERSED_RE):
            parameter = pattern.fullmatch(bracket)
            if parameter:
                value = parameters.get(parameter.group(1))
                if isinstance(value, int) and value >= 1:
                    return value, signed
    return None, signed


def available_modules(source: str) -> tuple[str, ...]:
    """Return all module names with a parseable ANSI/non-ANSI port list."""
    if not isinstance(source, str):
        raise RTLImportError("RTL source must be text")
    return tuple(dict.fromkeys(m.group(1) for m in _MODULE_RE.finditer(source)))


def _module_header_parameters(header_parameters: str | None) -> dict[str, int]:
    """从 ``#( ... )`` 里取十进制字面量参数。

    只认 ``parameter NAME = 123``（允许逗号结尾）。任何表达式参数会让它自己不成立，
    于是引用该参数的位宽会变成"不可解析"——这正是我们要的行为。
    """

    if not header_parameters:
        return {}
    return {name: int(value) for name, value in _PARAMETER_RE.findall(header_parameters)}


def _module_body(source: str, start: int) -> str:
    end = source.lower().find("endmodule", start)
    return source[start : end if end >= 0 else len(source)]


def _derive_clock_and_reset(
    body: str,
    inputs: Sequence[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """从 ``always`` 结构里推导时钟边沿与复位极性/同步性。

    为什么值得做这一步：端口名只能*建议*哪个是复位，**极性**必须另有依据。而
    `always @(posedge clk or negedge rst_n)` 与 `if (!rst_n)` 就是代码里的依据，
    比名字强得多。读不到依据时返回 ``None`` 字段（校验会明确拒绝），不猜。

    返回 (clock, reset, evidence_notes)。
    """

    notes: list[str] = []
    blocks = list(_ALWAYS_RE.finditer(body))

    # 1. 时钟：出现在敏感列表里、带边沿限定、且是已声明输入的那个信号。
    clock_votes: dict[tuple[str, str], int] = {}
    async_reset_candidates: dict[str, str] = {}
    for block in blocks:
        edges = _EDGE_RE.findall(block.group(1))
        for edge, signal in edges:
            if signal not in inputs:
                continue
            clock_votes[(signal, edge.lower())] = clock_votes.get((signal, edge.lower()), 0) + 1
        if len(edges) >= 2:
            # 敏感列表里有两个边沿信号：第一个当行是时钟，其余是异步复位。
            for edge, signal in edges[1:]:
                if signal in inputs:
                    async_reset_candidates[signal] = edge.lower()

    clock: dict[str, Any] | None = None
    clock_signal: str | None = None
    if clock_votes:
        (clock_signal, edge), _count = max(clock_votes.items(), key=lambda item: item[1])
        clock = {"signal": clock_signal, "period_ns": 10.0, "edge": edge}
        notes.append(f"时钟 {clock_signal}（{edge}）来自 always 敏感列表；周期 10ns 是默认值，请按需确认")

    # 2. 复位候选：名字像复位、且是已声明输入的端口。
    reset_candidates = [name for name in inputs if _RESET_HINT_RE.search(name) and name != clock_signal]
    reset: dict[str, Any] | None = None
    if reset_candidates:
        signal = reset_candidates[0]
        polarity: int | None = None
        synchronous: bool | None = None
        evidence: str | None = None

        if signal in async_reset_candidates:
            edge = async_reset_candidates[signal]
            polarity = 0 if edge == "negedge" else 1
            synchronous = False
            evidence = f"always 敏感列表含 {edge} {signal}"
        else:
            # 同步复位：时钟块里第一个 if 条件就是这个复位。
            for block in blocks:
                if not _EDGE_RE.search(block.group(1)):
                    continue
                condition = _find_reset_condition(body, block.end(), signal)
                if condition is not None:
                    polarity, literal = condition
                    synchronous = True
                    evidence = f"时钟块内 if 条件 {literal}"
                    break

        reset = {
            "signal": signal,
            "active_level": polarity,
            "synchronous": synchronous,
            "assert_cycles": 2,
        }
        if evidence:
            notes.append(f"复位 {signal}：{evidence}（极性/同步性由代码结构推导，请确认）")
        else:
            notes.append(
                f"复位 {signal}：**未找到代码依据**，active_level 与 synchronous 留空——"
                "请按 RTL 实际语义填写（0=低有效，1=高有效）；端口名不是证据"
            )

    if clock_signal is None:
        hinted = [name for name in inputs if _CLOCK_HINT_RE.search(name)]
        if hinted:
            notes.append(
                f"输入 {hinted[0]} 名字像时钟，但没有找到 `always @(posedge/negedge …)`："
                "无法确认边沿，草稿里没有 clock。如确有时钟，请在合约中显式补充 clock.edge"
            )
    return clock, reset, notes


def _find_reset_condition(body: str, start: int, signal: str) -> tuple[int, str] | None:
    """在时钟块开头附近找 `if (<复位条件>)`，返回 (极性, 条件原文)。

    只扫描块开头一小段：复位分支按惯例在最前面，而"第一个 if"正是要判断的东西。
    扫描范围设上限是为了不把块中间的普通判断（例如 `if (enable)`）误判成复位。
    """

    window = body[start : start + 800]
    for match in re.finditer(r"\bif\s*\(([^()]*)\)", window):
        condition = match.group(1).strip()
        lowered = condition.replace(" ", "")
        if not re.search(rf"\b{re.escape(signal)}\b", condition):
            continue
        if re.fullmatch(rf"[!~]{re.escape(signal)}", lowered) or re.fullmatch(
            rf"{re.escape(signal)}==(?:1'b0|1'd0|0|'b0)", lowered
        ):
            return 0, condition
        if re.fullmatch(re.escape(signal), lowered) or re.fullmatch(
            rf"{re.escape(signal)}==(?:1'b1|1'd1|1|'b1)", lowered
        ):
            return 1, condition
    return None


def extract_contract_draft(
    source: str, *, filename: str = "rtl.v", module_name: str | None = None
) -> tuple[str, dict[str, Any], list[str]]:
    if not isinstance(source, str) or not source.strip():
        raise RTLImportError("empty RTL")
    if module_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", module_name):
        raise RTLImportError("invalid module name")
    matches = list(_MODULE_RE.finditer(source))
    m = next((item for item in matches if module_name is None or item.group(1) == module_name), None)
    if not m:
        raise RTLImportError("module with port list not found")

    module, header, warnings = m.group(1), m.group(3), []
    parameters = _module_header_parameters(m.group(2))
    ports: list[dict[str, Any]] = []
    current_direction = None
    current_width: int | None = 1
    current_signed = False

    for chunk in (x.strip() for x in header.split(",")):
        dm = re.search(r"\b(input|output|inout)\b", chunk, re.I)
        if dm:
            current_direction = dm.group(1).lower()
            current_width, current_signed = _width(chunk, parameters)
            payload = chunk[dm.end() :]
        elif current_direction:
            payload = chunk
        else:
            continue
        names = _ids(payload)
        if not names:
            warnings.append(f"unparsed declaration: {chunk}")
            continue
        if current_width is None:
            declaration = _BRACKET_RE.search(chunk)
            detail = declaration.group(0) if declaration else chunk
            warnings.append(
                f"端口 {'、'.join(names)} 的位宽无法可靠解析（`{detail}`）："
                "符号位宽、宏或表达式参数不在本期支持范围内。宽度已留空，"
                "请在合约里显式填写（不要按 1 位处理）。"
            )
        ports.extend(
            {"name": n, "direction": current_direction, "width": current_width, "signed": current_signed}
            for n in names
        )

    if not ports:
        names = _ids(header)
        body = _module_body(source, m.end())
        declarations: dict[str, tuple[str, int | None, bool]] = {}
        for dm in _DECL_RE.finditer(body):
            direction = dm.group(1).lower()
            width, signed = _width(dm.group(2), parameters)
            for n in _ids(dm.group(2)):
                declarations[n] = (direction, width, signed)
        for n in names:
            if n in declarations:
                direction, width, signed = declarations[n]
            else:
                # 旧实现默认成 input/1bit。现在明确留空：既不是输入也不是 1 位。
                direction, width, signed = None, None, False
                warnings.append(f"端口 {n} 找不到声明：方向与位宽已留空，必须在合约里给人确认的值。")
            ports.append({"name": n, "direction": direction, "width": width, "signed": signed})

    inputs = [str(p["name"]) for p in ports if p["direction"] in {"input", "inout"}]
    body = _module_body(source, m.end())
    clock, reset, notes = _derive_clock_and_reset(body, inputs)
    warnings.extend(notes)

    contract: dict[str, Any] = {"module": module, "ports": ports}
    if parameters:
        contract["parameters"] = dict(parameters)
    if clock is not None:
        contract["clock"] = clock
    if reset is not None:
        contract["reset"] = reset
    warnings.append(
        "draft only：位宽来自声明，时钟边沿与复位极性只采用能从代码结构读出依据的值；"
        "留空（null）的字段必须在合约里补全，校验会拒绝未补全的草稿。"
    )
    return module, contract, warnings


def import_rtl_bytes(filename: str, data: bytes | bytearray, workspace_root: str | Path, *, max_bytes: int = 2_000_000) -> ImportedRTL:
    safe = _safe_filename(filename)
    raw = bytes(data)
    if not raw:
        raise RTLImportError("empty RTL")
    if len(raw) > max_bytes:
        raise RTLImportError("RTL exceeds size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RTLImportError("RTL must be UTF-8") from exc
    if "\x00" in text:
        raise RTLImportError("RTL contains NUL byte")
    root = Path(workspace_root).expanduser().resolve(strict=False)
    d = root / ".iverilog-ai" / "custom_rtl"
    d.mkdir(parents=True, exist_ok=True)
    if d.is_symlink():
        raise RTLImportError("custom RTL directory cannot be symlink")
    stem = re.sub(r"[^A-Za-z0-9_$]+", "_", Path(safe).stem).strip("_") or "rtl"
    stem = stem if re.match(r"^[A-Za-z_]", stem) else "rtl_" + stem
    target = (d / f"{stem[:80]}-{hashlib.sha256(raw).hexdigest()[:12]}{Path(safe).suffix.lower()}").resolve()
    if target.parent != d.resolve():
        raise RTLImportError("target path escapes workspace")
    target.write_bytes(raw)
    module, contract, warnings = extract_contract_draft(text, filename=safe)
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
        target.write_bytes(data)
        source_paths.append(target)
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


__all__ = [
    "ImportedRTL",
    "ImportedRTLProject",
    "RTLImportError",
    "available_modules",
    "extract_contract_draft",
    "import_rtl_bytes",
    "import_rtl_project",
]
