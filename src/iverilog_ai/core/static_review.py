"""Deterministic RTL static quality review.

This is a conservative lint-like pass for teaching and triage.  It reports
evidence with line numbers and never claims synthesis/timing success.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class StaticFinding:
    rule_id: str
    severity: str
    line: int
    message: str
    suggestion: str
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
            "snippet": self.snippet,
        }


_SEVERITY_WEIGHT = {"error": 20, "warn": 5, "info": 1}


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _snippet(lines: list[str], line: int) -> str:
    return lines[line - 1].strip()[:240] if 1 <= line <= len(lines) else ""


def _finding(source: str, lines: list[str], rule_id: str, severity: str, offset: int, message: str, suggestion: str) -> StaticFinding:
    line = _line_number(source, offset)
    return StaticFinding(rule_id, severity, line, message, suggestion, _snippet(lines, line))


def _always_blocks(source: str) -> Iterable[tuple[re.Match[str], str]]:
    pattern = re.compile(r"\balways\s*@\s*\((?P<sens>[^)]*)\)(?P<body>.*?)(?=\bend\s*\n|\bend\s*;|\bend\s*$)", re.I | re.S)
    yield from ((match, match.group("body")) for match in pattern.finditer(source))


def review_rtl_source(source: str, *, filename: str = "rtl.v") -> dict[str, Any]:
    if not isinstance(source, str):
        raise TypeError("source must be text")
    lines = source.splitlines()
    findings: list[StaticFinding] = []

    # Delay constructs in synthesizable RTL are a common simulation/synthesis trap.
    for match in re.finditer(r"#\s*\d", source):
        findings.append(_finding(source, lines, "synth-delay", "error", match.start(), "RTL contains a #delay construct", "Remove delays from synthesizable RTL; model timing in the testbench."))

    for match in re.finditer(r"\binitial\s*(?:begin)?", source, re.I):
        findings.append(_finding(source, lines, "initial-block", "warn", match.start(), "Initial block may not synthesize consistently on the target FPGA", "Use reset-driven initialization; keep initial blocks in testbench files."))

    for match in re.finditer(r"\bcase\s*\([^)]*\)(?P<body>.*?)(?:\bendcase\b)", source, re.I | re.S):
        body = match.group("body")
        if not re.search(r"\bdefault\s*:", body, re.I):
            findings.append(_finding(source, lines, "missing-default-case", "warn", match.start(), "Case statement has no default branch", "Add a safe default assignment or recovery state."))

    for match, body in _always_blocks(source):
        sens = match.group("sens")
        if re.search(r"\bposedge\b|\bnegedge\b", sens, re.I):
            # Exclude comparisons (==) and non-blocking assignments (<=).
            if re.search(r"(?<![=!<>])=(?!=|>)", body):
                findings.append(_finding(source, lines, "blocking-in-sequential", "warn", match.start(), "Sequential always block contains blocking assignment", "Use non-blocking <= for registered state updates."))
            if re.search(r"\bnegedge\s+[A-Za-z_]\w*rst\w*\b", sens, re.I) and not re.search(r"sync|synchron", source, re.I):
                findings.append(_finding(source, lines, "async-reset-no-sync", "warn", match.start(), "Asynchronous reset is used without an obvious synchronizer", "Use asynchronous assertion with synchronized de-assertion when the design requires clean reset release."))
        elif "*" in sens:
            if "<=" in body:
                findings.append(_finding(source, lines, "non-blocking-combinational", "warn", match.start(), "Combinational always block contains non-blocking assignment", "Use blocking = assignments in combinational logic."))
        else:
            findings.append(_finding(source, lines, "incomplete-sensitivity", "warn", match.start(), "Explicit combinational sensitivity list may be incomplete", "Use always @(*) or always_comb for combinational logic."))

    # Compact one-line always blocks are common in small examples and are not
    # captured reliably by the multiline block heuristic above.
    for match in re.finditer(r"\balways\s*@\s*\([^)]*\b(?:posedge|negedge)\b[^)]*\)[^\n;{}]*\b[A-Za-z_]\w*\s*=(?!=|>)", source, re.I):
        line = _line_number(source, match.start())
        if not any(item.rule_id == "blocking-in-sequential" and item.line == line for item in findings):
            findings.append(_finding(source, lines, "blocking-in-sequential", "warn", match.start(), "Sequential always block contains blocking assignment", "Use non-blocking <= for registered state updates."))

    # Signals named as synchronizers should carry a placement hint in FPGA RTL.
    for match in re.finditer(r"\b(?:reg|logic)\s+[^;\n]*\b\w*sync\w*\b", source, re.I):
        declaration_line = _line_number(source, match.start())
        nearby = source[max(0, match.start() - 180):match.start()]
        if "ASYNC_REG" not in nearby:
            findings.append(StaticFinding("missing-async-reg", "info", declaration_line, "Synchronizer-like register lacks ASYNC_REG attribute", "Add the vendor placement attribute when this register is part of a CDC synchronizer.", _snippet(lines, declaration_line)))

    # Multiple procedural assignments to the same simple identifier are a useful warning.
    assigned: dict[str, list[tuple[int, int]]] = {}
    always_offsets = [m.start() for m in re.finditer(r"\balways\b", source, re.I)]
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*(?<![=!<>])=(?!=|>)|\b([A-Za-z_]\w*)\s*<=", source):
        name = match.group(1) or match.group(2)
        block = max((offset for offset in always_offsets if offset <= match.start()), default=-1)
        assigned.setdefault(name, []).append((block, _line_number(source, match.start())))
    for name, positions in assigned.items():
        blocks = {block for block, _ in positions if block >= 0}
        unique = sorted({line for _, line in positions})
        if len(blocks) > 1:
            findings.append(StaticFinding("multiple-procedural-drivers", "error", unique[0], f"Signal {name!r} is assigned in multiple procedural blocks", "Keep one procedural driver per register; combine conditions in one always block.", _snippet(lines, unique[0])))

    counts = {level: sum(item.severity == level for item in findings) for level in ("error", "warn", "info")}
    score = max(0, 100 - sum(_SEVERITY_WEIGHT[item.severity] for item in findings))
    return {
        "schema_version": "1.0",
        "filename": filename,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "line_count": len(lines),
        "finding_count": len(findings),
        "counts": counts,
        "quality_score": score,
        "status": "error" if counts["error"] else ("warn" if counts["warn"] else "passed"),
        "findings": [item.to_dict() for item in sorted(findings, key=lambda item: (item.line, item.rule_id))],
        "disclaimer": "静态规则审查不等同于综合、时序收敛或 FPGA 上板验证。",
    }


def review_rtl_file(path: str | Path) -> dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file() or source_path.is_symlink():
        raise FileNotFoundError(source_path)
    return review_rtl_source(source_path.read_text(encoding="utf-8"), filename=source_path.name)


def render_static_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# RTL 静态质量审查报告", "",
        f"- 文件：`{result.get('filename', '')}`",
        f"- SHA-256：`{result.get('source_sha256', '')}`",
        f"- 质量评分：**{result.get('quality_score', 0)}/100**",
        f"- 状态：`{result.get('status', 'unknown')}`",
        f"- 行数：{result.get('line_count', 0)}",
        "", "> 静态规则审查不等同于综合、时序收敛或 FPGA 上板验证。", "",
        "## 问题统计", "",
        f"- error：{result.get('counts', {}).get('error', 0)}",
        f"- warn：{result.get('counts', {}).get('warn', 0)}",
        f"- info：{result.get('counts', {}).get('info', 0)}", "",
        "## 发现项", "",
        "| 级别 | 规则 | 行号 | 问题 | 建议 |", "|---|---|---:|---|---|",
    ]
    for item in result.get("findings", []):
        def cell(value: Any) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {cell(item['severity'])} | `{cell(item['rule_id'])}` | {item['line']} | {cell(item['message'])} | {cell(item['suggestion'])} |")
    if not result.get("findings"):
        lines.append("| - | - | - | 未发现规则问题 | - |")
    lines.extend(["", "## 证据片段", ""])
    for item in result.get("findings", []):
        lines.append(f"- 第 {item['line']} 行：`{item.get('snippet', '')}`")
    return "\n".join(lines) + "\n"


__all__ = ["StaticFinding", "review_rtl_source", "review_rtl_file", "render_static_markdown"]
