"""Small, dependency-free VCD reader for waveform evidence and triage."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Any


_TIMESCALE = re.compile(r"\$timescale\s+(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)\s+\$end", re.S)
_VAR = re.compile(r"\$var\s+\S+\s+(?P<width>\d+)\s+(?P<id>\S+)\s+(?P<name>\S+)(?:\s+\S+)?\s+\$end")
_UNIT_TO_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}


@dataclass(frozen=True)
class VCDChange:
    time_ns: float
    signal: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {"time_ns": self.time_ns, "signal": self.signal, "value": self.value}


def _parse_timescale(text: str) -> float:
    match = _TIMESCALE.search(text)
    if not match:
        return 1.0
    unit = match.group("unit").lower()
    if unit not in _UNIT_TO_NS:
        return 1.0
    return float(match.group("num")) * _UNIT_TO_NS[unit]


def analyze_vcd_file(path: str | Path, *, start_ns: float | None = None, end_ns: float | None = None, max_changes: int = 5000) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    if start_ns is not None and end_ns is not None and start_ns > end_ns:
        raise ValueError("start_ns must not exceed end_ns")
    if not isinstance(max_changes, int) or max_changes < 1:
        raise ValueError("max_changes must be positive")
    text = source.read_text(encoding="utf-8", errors="replace")
    timescale_ns = _parse_timescale(text)
    header_end = text.find("$enddefinitions")
    if header_end < 0:
        raise ValueError("VCD is missing $enddefinitions")
    header = text[:header_end]
    id_to_name: dict[str, str] = {}
    widths: dict[str, int] = {}
    scopes: list[str] = []
    for token in re.finditer(r"\$scope\s+\S+\s+(\S+)\s+\$end|\$upscope\s+\$end|\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\S+)?\s+\$end", header):
        if token.group(1):
            scopes.append(token.group(1))
        elif token.group(0).startswith("$upscope"):
            if scopes:
                scopes.pop()
        else:
            width, ident, name = int(token.group(2)), token.group(3), token.group(4)
            id_to_name[ident] = ".".join(scopes + [name]) if scopes else name
            widths[ident] = width
    body = text[header_end:]
    current_time = 0
    changes: list[VCDChange] = []
    transition_counts: dict[str, int] = {name: 0 for name in id_to_name.values()}
    first_time: float | None = None
    last_time: float | None = None
    selected_ids = set(id_to_name)
    pending_time_ns = 0.0
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            try:
                current_time = int(line[1:])
                pending_time_ns = current_time * timescale_ns
            except ValueError:
                continue
            continue
        ident, value = None, None
        if line[0] in "01xXzZ":
            ident, value = line[1:].strip(), line[0].lower()
        elif line[0] in "bBrR":
            pieces = line[1:].split()
            if len(pieces) == 2:
                value, ident = pieces[0].lower(), pieces[1]
        if ident not in selected_ids or value is None:
            continue
        time_ns = pending_time_ns
        if start_ns is not None and time_ns < start_ns:
            continue
        if end_ns is not None and time_ns > end_ns:
            continue
        name = id_to_name[ident]
        transition_counts[name] = transition_counts.get(name, 0) + 1
        first_time = time_ns if first_time is None else min(first_time, time_ns)
        last_time = time_ns if last_time is None else max(last_time, time_ns)
        if len(changes) < max_changes:
            changes.append(VCDChange(time_ns, name, value))
    signals = [{"name": name, "width": widths.get(ident, 1), "changes": transition_counts.get(name, 0)} for ident, name in sorted(id_to_name.items(), key=lambda item: item[1])]
    total_changes = sum(transition_counts.values())
    return {
        "schema_version": "1.0",
        "file": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "timescale_ns": timescale_ns,
        "signal_count": len(signals),
        "signals": signals,
        "start_ns": first_time,
        "end_ns": last_time,
        "total_changes": total_changes,
        "changes": [item.to_dict() for item in changes],
        "truncated": total_changes > len(changes),
    }


def analyze_failure_windows(path: str | Path, failure_cycles: list[int] | tuple[int, ...], *, clock_period_ns: float = 10.0, radius: int = 1, max_changes: int = 2000) -> dict[str, Any]:
    """Map cycle numbers to conservative VCD windows and parse each window."""
    if not isinstance(clock_period_ns, (int, float)) or clock_period_ns <= 0:
        raise ValueError("clock_period_ns must be positive")
    if not isinstance(radius, int) or radius < 0:
        raise ValueError("radius must be non-negative")
    cycles = sorted({int(item) for item in failure_cycles if isinstance(item, int) and item >= 0})
    windows = []
    for cycle in cycles:
        start = max(0.0, (cycle - radius) * float(clock_period_ns))
        end = (cycle + radius + 1) * float(clock_period_ns)
        windows.append({"cycle": cycle, "start_ns": start, "end_ns": end, "analysis": analyze_vcd_file(path, start_ns=start, end_ns=end, max_changes=max_changes)})
    return {"status": "parsed", "clock_period_ns": float(clock_period_ns), "radius": radius, "windows": windows, "disclaimer": "周期到 VCD 时间为基于 contract 时钟周期的估算窗口。"}


__all__ = ["VCDChange", "analyze_vcd_file", "analyze_failure_windows"]
