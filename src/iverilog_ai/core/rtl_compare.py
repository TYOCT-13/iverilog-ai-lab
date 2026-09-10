"""Deterministic, reviewable comparison between user RTL and a saved reference RTL."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

_MODULE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_PORT = re.compile(r"\b(input|output|inout)\b(?:\s+(?:wire|reg|logic|signed)\s*)?(?:\[[^]]+\]\s*)?([A-Za-z_]\w*)")

def _profile(source: str) -> dict[str, Any]:
    lines = source.splitlines()
    ports = [{"direction": m.group(1), "name": m.group(2)} for m in _PORT.finditer(source)]
    return {
        "modules": _MODULE.findall(source),
        "ports": ports,
        "line_count": len(lines),
        "always_blocks": len(re.findall(r"\balways\s*@", source, re.I)),
        "clocked_blocks": len(re.findall(r"always\s*@\s*\([^)]*posedge", source, re.I)),
        "has_reset": bool(re.search(r"\b(negedge|posedge)\s+[A-Za-z_]\w*rst\w*", source, re.I)),
        "has_default": bool(re.search(r"\bdefault\s*:", source, re.I)),
        "uses_nonblocking": bool(re.search(r"<=", source)),
    }

def compare_rtl_sources(user_source: str, reference_source: str, *, user_name: str = "custom", reference_name: str = "reference") -> dict[str, Any]:
    user, reference = _profile(user_source), _profile(reference_source)
    user_ports = {(p["direction"], p["name"]) for p in user["ports"]}
    ref_ports = {(p["direction"], p["name"]) for p in reference["ports"]}
    strengths, gaps = [], []
    if user["has_reset"]: strengths.append("包含显式复位处理")
    else: gaps.append("未检测到显式复位处理；请确认是否符合 DUT contract")
    if user["clocked_blocks"]: strengths.append("包含时序逻辑块")
    if user["uses_nonblocking"]: strengths.append("时序逻辑使用非阻塞赋值")
    else:
        gaps.append("未检测到非阻塞赋值；时序 always 块建议使用 <=")
    if user["has_default"]: strengths.append("case 语句包含 default 分支")
    if reference["has_default"] and not user["has_default"]: gaps.append("相比参考 RTL 缺少 default 分支，可能存在非法状态未覆盖")
    missing = sorted(name for direction, name in ref_ports - user_ports)
    extra = sorted(name for direction, name in user_ports - ref_ports)
    if missing: gaps.append("缺少参考端口：" + ", ".join(missing))
    if extra: gaps.append("额外端口：" + ", ".join(extra))
    if user["line_count"] <= reference["line_count"] * 2: strengths.append("代码规模处于合理范围")
    else: gaps.append("代码规模明显大于参考实现，建议拆分状态和组合逻辑")
    return {"user": {"name": user_name, **user}, "reference": {"name": reference_name, **reference}, "port_match": not missing and not extra, "missing_ports": missing, "extra_ports": extra, "strengths": strengths, "gaps": gaps, "learning_plan": ["先确认时钟/复位与 contract 一致", "补齐缺失端口和边界条件", "为关键状态转移添加结构化断言", "使用相同 testbench 与参考 RTL 对比仿真波形"]}

__all__ = ["compare_rtl_sources"]
