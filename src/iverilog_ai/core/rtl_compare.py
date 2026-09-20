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

__all__ = ["compare_rtl_sources", "source_similarity", "token_shingles"]

#: Verilog 关键字：做"只改标识符"的相似度时，这些词**不**参与改名，否则两份完全不同的
#: 设计会因为共用 `always`/`begin`/`end` 而看起来很像。
_VERILOG_KEYWORDS = frozenset(
    """
    module endmodule input output inout wire reg logic signed unsigned integer parameter localparam
    always initial assign begin end if else case casex casez endcase default for while repeat forever
    posedge negedge or and not xor nand nor xnor buf bufif0 bufif1 notif0 notif1
    timescale define include ifdef ifndef endif else elsif
    posedge_negedge_edge automatic generate endgenerate genvar function endfunction task endtask
    """.split()
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*|\d+'[bBoOdDhH][0-9a-fA-FxXzZ_]+|\d+|[^\sA-Za-z0-9_$]")
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def token_shingles(source: str, *, size: int = 5, normalize_identifiers: bool = False) -> frozenset[tuple[str, ...]]:
    """把源码切成 token n-gram 集合（先去掉注释与空白）。

    ``normalize_identifiers=True`` 时把所有**非关键字**标识符替换成同一个记号，用来抓
    "改了变量名但结构照搬"的情况；关掉则只抓逐字相同。两种都要看：
    **归一化后高、原始低 = 改名抄；两者都高 = 直接抄；两者都低 = 各写各的。**
    """

    text = _COMMENT_RE.sub(" ", source)
    raw = _TOKEN_RE.findall(text)
    if normalize_identifiers:
        tokens = [
            token if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", token) or token.lower() in _VERILOG_KEYWORDS)
            else "ID"
            for token in raw
        ]
    else:
        tokens = raw
    if len(tokens) < size:
        return frozenset({tuple(tokens)}) if tokens else frozenset()
    return frozenset(tuple(tokens[index:index + size]) for index in range(len(tokens) - size + 1))


def source_similarity(first: str, second: str, *, size: int = 5) -> dict[str, float]:
    """两份 RTL 源码的相似度（token 5-gram 的 Jaccard 系数）。

    这是**线索**不是结论：相似度高只说明两段代码长得像，可能是同一份作业被改过名，
    也可能只是都照着同一份实验指导写的。所以它只用于"把需要人看的几对挑出来"，
    真正的判据仍然是人看代码与证据。
    """

    raw_a, raw_b = token_shingles(first, size=size), token_shingles(second, size=size)
    norm_a = token_shingles(first, size=size, normalize_identifiers=True)
    norm_b = token_shingles(second, size=size, normalize_identifiers=True)

    def jaccard(left: frozenset, right: frozenset) -> float:
        if not left and not right:
            return 0.0
        union = len(left | right)
        return round(len(left & right) / union, 4) if union else 0.0

    return {
        "raw": jaccard(raw_a, raw_b),
        "normalized": jaccard(norm_a, norm_b),
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
