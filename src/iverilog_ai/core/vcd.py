"""Small, dependency-free VCD reader for waveform evidence and triage."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence


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
    id_to_scope: dict[str, str] = {}
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
            # 记录声明所在层次：下游据此区分「DUT 内部信号」与「testbench 记账信号」，
            # 后者的跳变节奏由激励脚本决定，不构成电路毛刺。
            id_to_scope[ident] = ".".join(scopes)
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
    signals = [
        {
            "name": name,
            "scope": id_to_scope.get(ident, ""),
            "width": widths.get(ident, 1),
            "changes": transition_counts.get(name, 0),
        }
        for ident, name in sorted(id_to_name.items(), key=lambda item: item[1])
    ]
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


# --------------------------------------------------------------------------
# 波形语义分析：边沿、稳定性、相位（晚/早一拍）与双波形差异
# --------------------------------------------------------------------------
def _signal_timelines(analysis: Mapping[str, Any]) -> dict[str, list[tuple[float, str]]]:
    """把扁平的 changes 列表整理成"信号 → 按时间排序的 (时间, 值)"。

    只保留最后一次采样点之后仍有效的最新值由调用方按需取用。
    """

    timelines: dict[str, list[tuple[float, str]]] = {}
    for item in analysis.get("changes", []) or []:
        name = str(item.get("signal", ""))
        time_ns = item.get("time_ns")
        value = str(item.get("value", ""))
        if not name or not isinstance(time_ns, (int, float)):
            continue
        timelines.setdefault(name, []).append((float(time_ns), value))
    for name in timelines:
        timelines[name].sort(key=lambda pair: pair[0])
    return timelines


def _to_int(value: str) -> int | None:
    """把 VCD 值转成整数；含 x/z 或非法时返回 None。"""

    text = value.strip().lower()
    if not text or any(char in text for char in "xz"):
        return None
    if set(text) <= {"0", "1"}:
        return int(text, 2)
    try:
        return int(text, 2)
    except ValueError:
        return None


def signal_edges(analysis: Mapping[str, Any], signal: str) -> list[dict[str, Any]]:
    """列出某个信号的全部跳变（含方向），用于上升/下降沿识别。"""

    timeline = _signal_timelines(analysis).get(signal, [])
    edges: list[dict[str, Any]] = []
    previous: int | None = None
    for time_ns, raw in timeline:
        value = _to_int(raw)
        if value is None:
            previous = None
            continue
        if previous is None:
            edges.append({"time_ns": time_ns, "value": value, "edge": "initial"})
        elif value != previous:
            edges.append({"time_ns": time_ns, "value": value, "edge": "rise" if value > previous else "fall"})
        previous = value
    return edges


def _glitch_flags(intervals: Sequence[float], skip: Sequence[bool], reference: float | None) -> list[bool]:
    """按常规节奏标记"明显更短"的间隔。

    判据用**全局**基线而不是局部邻域：局部中位数会被突发自身拉低（一段连续
    快翻里，前几个短间隔会把邻居的中位数带下来），导致只有突发的尾部被标记，
    反而凑不满"连续多个"的条件。全局基线对少数短间隔是稳健的。
    """

    if not reference or reference <= 0:
        return [False] * len(intervals)
    threshold = reference / 3.0
    return [
        False if skip[index] else interval < threshold
        for index, interval in enumerate(intervals)
    ]


def _is_glitch_burst(flags: Sequence[bool]) -> bool:
    """只有**连续多个**间隔都异常才算毛刺。

    单次异常间隔是正常现象：脉冲信号的上升沿与下降沿之间本来就很短，
    被测设计的 ``busy`` 就是这样。组合环自激、握手协议错乱这类真问题会
    表现为连续快翻，因此要求至少 3 个相邻的异常间隔。
    """

    run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        if run >= 3:
            return True
    return False


def signal_stability(
    analysis: Mapping[str, Any],
    signal: str,
    *,
    window_ns: float,
    reset_times: Sequence[float] = (),
) -> dict[str, Any]:
    """识别**毛刺型**不稳定：翻转间隔明显短于该信号常规节奏。

    「一个窗口内翻转多次」本身并不代表有问题——计数器每个时钟都在翻转。
    因此判据是相对的：先估出该信号的常规翻转间隔（中位数），只有当某个间隔
    远短于常规间隔时才报不稳定。这样既不会把计数器/时钟误判成毛刺，
    也能抓住真正的抖动。

    复位沿会天然制造一次短间隔（异步复位把计数器直接清零）。``reset_times``
    给出复位信号的跳变时刻，跨过这些时刻的间隔不参与统计，避免把复位当成毛刺。
    """

    timeline = _signal_timelines(analysis).get(signal, [])
    flips: list[float] = []
    previous: int | None = None
    for time_ns, raw in timeline:
        value = _to_int(raw)
        if value is None:
            previous = None
            continue
        if previous is not None and value != previous:
            flips.append(time_ns)
        previous = value

    intervals = [flips[index + 1] - flips[index] for index in range(len(flips) - 1)]
    # 跨过复位跳变时刻的间隔由复位引起，不代表信号自身的翻转节奏
    crosses_reset = [
        bool(reset_times) and any(flips[index] < moment <= flips[index + 1] for moment in reset_times)
        for index in range(len(intervals))
    ]
    baseline = [item for index, item in enumerate(intervals) if not crosses_reset[index]]
    typical = statistics.median(baseline) if baseline else None
    glitch = _glitch_flags(intervals, crosses_reset, typical)

    unstable: list[dict[str, Any]] = []
    if _is_glitch_burst(glitch):
        index = 0
        while index < len(intervals):
            if not glitch[index]:
                index += 1
                continue
            group = [flips[index], flips[index + 1]]
            probe = index + 1
            while probe < len(intervals) and glitch[probe]:
                group.append(flips[probe + 1])
                probe += 1
            if len(group) < 4:
                # 少于 3 个异常间隔只是正常的窄脉冲，不构成结论
                index = probe
                continue
            shortest = min(group[pos + 1] - group[pos] for pos in range(len(group) - 1))
            unstable.append({
                "start_ns": group[0],
                "end_ns": group[-1],
                "flips": len(group),
                "shortest_interval_ns": shortest,
                "typical_interval_ns": typical,
                "reason": (
                    f"连续 {len(group) - 1} 个间隔短于邻近节奏"
                    f"（该信号常规约 {typical:g} ns，此处最短 {shortest:g} ns）"
                    if typical
                    else f"连续快翻，最短间隔仅 {shortest:g} ns"
                ),
            })
            index = probe

    return {
        "signal": signal,
        "flips": len(flips),
        "first_flip_ns": flips[0] if flips else None,
        "last_flip_ns": flips[-1] if flips else None,
        "typical_interval_ns": typical,
        "window_ns": float(window_ns),
        "unstable_windows": unstable,
        "status": "unstable" if unstable else "stable",
    }


def detect_phase_violations(
    analysis: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any] | Sequence[Any]],
    *,
    clock_period_ns: float,
    tolerance_cycles: int = 0,
) -> list[dict[str, Any]]:
    """检测"输出晚一拍/早一拍"：激励沿到响应沿之间的周期数与声明值不符。

    ``pairs`` 支持 ``{"trigger": ..., "response": ..., "expected_delay_cycles": n}``
    或 ``(trigger, response, expected_delay_cycles)``。期望延迟由 contract 显式给出，
    不从波形里推断，避免"用现象解释现象"。
    """

    if not isinstance(clock_period_ns, (int, float)) or clock_period_ns <= 0:
        raise ValueError("clock_period_ns must be positive")
    if tolerance_cycles < 0:
        raise ValueError("tolerance_cycles must be non-negative")
    timelines = _signal_timelines(analysis)
    widths = {
        str(item.get("name", "")): int(item.get("width", 1) or 1)
        for item in analysis.get("signals", []) or []
    }
    findings: list[dict[str, Any]] = []
    for entry in pairs:
        if isinstance(entry, Mapping):
            trigger = str(entry.get("trigger", ""))
            response = str(entry.get("response", ""))
            expected_cycles = int(entry.get("expected_delay_cycles", 1))
            declared_trigger = str(entry.get("declared_trigger", trigger))
            declared_response = str(entry.get("declared_response", response))
        else:
            trigger, response, expected_cycles = str(entry[0]), str(entry[1]), int(entry[2])
            declared_trigger, declared_response = trigger, response
        if not trigger or not response:
            continue
        # 「晚一拍」只对单比特脉冲有意义：多位信号没有上升沿可言，
        # 对它做相位检查只会产出永远不成立的 unobservable 噪声。
        wide = [name for name in (trigger, response) if widths.get(name, 1) > 1]
        if wide:
            findings.append({
                "trigger": declared_trigger,
                "response": declared_response,
                "resolved_trigger": trigger,
                "resolved_response": response,
                "expected_delay_cycles": expected_cycles,
                "observed_delay_cycles": None,
                "status": "not_applicable",
                "message": (
                    f"{'、'.join(wide)} 是多位信号，没有上升沿语义，"
                    "相位检查只适用于单比特的握手/脉冲信号"
                ),
            })
            continue
        trigger_edges = [edge for edge in signal_edges(analysis, trigger) if edge["edge"] == "rise"]
        response_edges = [edge for edge in signal_edges(analysis, response) if edge["edge"] == "rise"]
        # 只统计"响应沿在激励沿之后"的配对，避免把无关沿算进来。取**最小**延迟：
        # 相位问题是"响应最早应该在几个周期后出现"，若某次触发后响应更晚，
        # 那是握手/背压等正常行为，不是相位偏差。
        observed: list[float] = []
        for trigger_edge in trigger_edges:
            following = [edge for edge in response_edges if edge["time_ns"] > trigger_edge["time_ns"]]
            if following:
                observed.append(
                    min(edge["time_ns"] for edge in following) - trigger_edge["time_ns"]
                )
        observed = [item / clock_period_ns for item in observed]
        if not observed:
            findings.append({
                "trigger": declared_trigger,
                "response": declared_response,
                "resolved_trigger": trigger,
                "resolved_response": response,
                "expected_delay_cycles": expected_cycles,
                "observed_delay_cycles": None,
                "status": "unobservable",
                "message": f"{declared_trigger} 的上升沿之后没有观察到 {declared_response} 的上升沿",
            })
            continue
        deltas = [value - expected_cycles for value in observed]
        worst = min(deltas, key=abs)
        status = "ok" if all(abs(delta) <= tolerance_cycles for delta in deltas) else ("late" if worst > 0 else "early")
        findings.append({
            "trigger": declared_trigger,
            "response": declared_response,
            "resolved_trigger": trigger,
            "resolved_response": response,
            "expected_delay_cycles": expected_cycles,
            "observed_delay_cycles": round(min(observed), 3),
            "worst_delta_cycles": round(worst, 3),
            "samples": len(observed),
            "status": status,
            "message": _phase_message(declared_trigger, declared_response, expected_cycles, worst, len(observed)),
        })
    return findings


def _phase_message(trigger: str, response: str, expected: int, worst: float, samples: int) -> str:
    if abs(worst) < 1e-9:
        return f"{trigger} → {response} 的延迟与声明的 {expected} 个周期一致（{samples} 个样本）"
    direction = "晚" if worst > 0 else "早"
    return (
        f"{trigger} → {response} 比声明的 {expected} 个周期{direction} {abs(worst):g} 个周期"
        f"（{samples} 个样本）"
    )


def _in_scope(name: str, scope: str, scopes: Sequence[str]) -> bool:
    """判断信号是否属于给定的 DUT 层次。

    优先用 VCD 声明里的层次；旧版分析结果没有 ``scope`` 字段时退回名字前缀。
    """

    for candidate in scopes:
        if not candidate:
            continue
        if scope:
            if scope == candidate or scope.startswith(candidate + "."):
                return True
        elif name == candidate or name.startswith(candidate + "."):
            return True
    return False


def _full_scope(name: str, scope: str) -> str:
    """由信号名与声明层次拼出完整层次路径。

    VCD 的 ``$scope`` 只记录**相对**层次名，因此 ``tb.check.t_id`` 声明在
    ``check`` 作用域里时，`scope` 字段是 ``check``；这里补回前缀，
    使层次比较可以与完整信号名前缀直接对齐。
    """

    if not scope:
        return ""
    if name.endswith("." + scope):
        return name[: len(name) - len(scope)]
    return scope


def _reset_timeline(analysis: Mapping[str, Any], signal_entries: Sequence[Mapping[str, Any]]) -> list[float]:
    """收集疑似复位信号的跳变时刻，供稳定性分析排除复位沿造成的短间隔。"""

    timelines = _signal_timelines(analysis)
    moments: list[float] = []
    for item in signal_entries:
        name = str(item.get("name", ""))
        leaf = name.rsplit(".", 1)[-1]
        if not re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", leaf, re.I):
            continue
        previous: int | None = None
        for time_ns, raw in timelines.get(name, []):
            value = _to_int(raw)
            if value is None:
                previous = None
                continue
            if previous is not None and value != previous:
                moments.append(time_ns)
            previous = value
    return sorted(moments)


def _resolve_signal_name(
    name: str,
    available: Sequence[str],
    scope_by_name: Mapping[str, str],
    dut_scopes: Sequence[str],
) -> str | None:
    """把 contract 里的裸信号名解析成 VCD 里的层次化名字。

    contract 写的是 `start`/`tx` 这类端口名，而 VCD 里是
    `tb_uart_tx.start`、`tb_uart_tx.dut_i.tx`。同一端口在 testbench 与 DUT
    里各有一份波形，优先取 DUT 内部的那份——相位问题问的是电路行为。
    """

    if not name:
        return None
    if name in scope_by_name or name in available:
        return name
    leaf = name.rsplit(".", 1)[-1]
    candidates = [item for item in available if item.rsplit(".", 1)[-1] == leaf]
    if not candidates:
        return None
    inside = [item for item in candidates if _in_scope(item, scope_by_name.get(item, ""), dut_scopes)]
    pool = inside or candidates
    return sorted(pool, key=len)[0]


def _resolved_phase_pairs(
    analysis: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any] | Sequence[Any]],
    scope_by_name: Mapping[str, str],
    dut_scopes: Sequence[str],
) -> list[dict[str, Any]]:
    """把相位检查的信号名解析到 VCD 层次，保留原始名字用于报告。"""

    available = [str(item.get("name", "")) for item in analysis.get("signals", []) or []]
    resolved: list[dict[str, Any]] = []
    for entry in pairs:
        if isinstance(entry, Mapping):
            trigger = str(entry.get("trigger", ""))
            response = str(entry.get("response", ""))
            expected = int(entry.get("expected_delay_cycles", 1))
        else:
            trigger, response, expected = str(entry[0]), str(entry[1]), int(entry[2])
        trigger_name = _resolve_signal_name(trigger, available, scope_by_name, dut_scopes) or trigger
        response_name = _resolve_signal_name(response, available, scope_by_name, dut_scopes) or response
        resolved.append({
            "trigger": trigger_name,
            "response": response_name,
            "declared_trigger": trigger,
            "declared_response": response,
            "expected_delay_cycles": expected,
        })
    return resolved


def waveform_insights(
    analysis: Mapping[str, Any],
    *,
    clock_period_ns: float = 10.0,
    phase_pairs: Sequence[Mapping[str, Any] | Sequence[Any]] = (),
    stability_signals: Sequence[str] = (),
    dut_scopes: Sequence[str] = (),
    max_signals: int = 40,
) -> dict[str, Any]:
    """把一次 VCD 分析汇总成可读结论：边沿、稳定性与相位。

    ``dut_scopes`` 用于区分「DUT 内部信号」与「testbench 记账信号」：后者
    （例如检查任务的 ``expected``/``actual`` 寄存器）的跳变节奏完全由激励
    脚本决定，把它们报成毛刺只会淹没有用结论。两者分别放进
    ``unstable_signals`` 与 ``unstable_auxiliary``；不传 ``dut_scopes`` 时
    保持旧行为，全部视为 DUT 信号。
    """

    scopes = [str(item) for item in dut_scopes if str(item)]
    signal_entries = [item for item in analysis.get("signals", []) or []]
    signal_names = [str(item.get("name", "")) for item in signal_entries]
    scope_by_name = {
        str(item.get("name", "")): _full_scope(str(item.get("name", "")), str(item.get("scope", "") or ""))
        for item in signal_entries
    }
    selected = list(stability_signals) or signal_names[:max_signals]
    # 复位沿不参与毛刺判定；信号自己就是复位线时也不统计它自身的复位跳变
    reset_times = _reset_timeline(analysis, signal_entries)
    notes: list[str] = []
    stability = []
    for name in selected:
        if not name:
            continue
        leaf = name.rsplit(".", 1)[-1]
        own = (
            reset_times
            if not re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", leaf, re.I)
            else []
        )
        report = signal_stability(analysis, name, window_ns=clock_period_ns, reset_times=own)
        report["scope"] = scope_by_name.get(name, "")
        report["is_dut"] = _in_scope(name, report["scope"], scopes)
        stability.append(report)
        for window in report["unstable_windows"]:
            target = "DUT 信号" if report["is_dut"] else "testbench 记账信号"
            suffix = "" if report["is_dut"] else "；该信号属 testbench 记账，不作为电路结论"
            notes.append(
                f"第 {window['start_ns']:g} ns：{name}（{target}）在 {clock_period_ns:g} ns 内翻转 "
                f"{window['flips']} 次（不稳定）{suffix}"
            )
    phases = detect_phase_violations(
        analysis, _resolved_phase_pairs(analysis, phase_pairs, scope_by_name, scopes), clock_period_ns=clock_period_ns
    ) if phase_pairs else []
    for item in phases:
        # 只把真正的相位偏差写进结论；not_applicable / unobservable 保留在
        # phase_checks 里供审计，不占用结论行的注意力。
        if item["status"] in {"late", "early"}:
            notes.append(f"{item['message']}（状态：{item['status']}）")
    edge_summary = []
    for name in selected:
        if not name:
            continue
        edges = signal_edges(analysis, name)
        edge_summary.append({
            "signal": name,
            "rises": sum(1 for edge in edges if edge["edge"] == "rise"),
            "falls": sum(1 for edge in edges if edge["edge"] == "fall"),
            "first_edge_ns": edges[0]["time_ns"] if edges else None,
        })
    return {
        "schema_version": "1.1",
        "clock_period_ns": float(clock_period_ns),
        "dut_scopes": scopes,
        "signal_edges": edge_summary,
        "stability": stability,
        "phase_checks": phases,
        "unstable_signals": [
            item["signal"] for item in stability if item["status"] == "unstable" and item["is_dut"]
        ],
        "unstable_auxiliary": [
            item["signal"] for item in stability if item["status"] == "unstable" and not item["is_dut"]
        ],
        "phase_violations": [item for item in phases if item["status"] in {"late", "early"}],
        "phase_not_applicable": [item for item in phases if item["status"] == "not_applicable"],
        "notes": notes,
        "disclaimer": "波形结论来自 VCD 数值本身，不替代 Icarus 仿真结论，也不等同综合或时序签核。",
    }


def compare_waveforms(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, clock_period_ns: float = 10.0) -> dict[str, Any]:
    """比较两份 VCD（例如标准 RTL 与自定义/缺陷 RTL）的差异摘要。"""

    reference_signals = {str(item.get("name", "")): item for item in reference.get("signals", []) or []}
    candidate_signals = {str(item.get("name", "")): item for item in candidate.get("signals", []) or []}
    only_reference = sorted(set(reference_signals) - set(candidate_signals))
    only_candidate = sorted(set(candidate_signals) - set(reference_signals))
    shared = sorted(set(reference_signals) & set(candidate_signals))

    reference_timelines = _signal_timelines(reference)
    candidate_timelines = _signal_timelines(candidate)
    differences: list[dict[str, Any]] = []
    for name in shared:
        reference_edges = signal_edges(reference, name)
        candidate_edges = signal_edges(candidate, name)
        if len(reference_edges) != len(candidate_edges):
            differences.append({
                "signal": name,
                "kind": "edge_count",
                "reference": len(reference_edges),
                "candidate": len(candidate_edges),
                "message": f"{name}：参考 {len(reference_edges)} 次跳变，被测 {len(candidate_edges)} 次",
            })
            continue
        shifted = [
            round((candidate_edges[index]["time_ns"] - reference_edges[index]["time_ns"]) / clock_period_ns, 3)
            for index in range(len(reference_edges))
        ]
        if any(abs(value) > 1e-9 for value in shifted):
            first = next(index for index, value in enumerate(shifted) if abs(value) > 1e-9)
            direction = "晚" if shifted[first] > 0 else "早"
            differences.append({
                "signal": name,
                "kind": "timing",
                "first_divergence_ns": candidate_edges[first]["time_ns"],
                "shift_cycles": shifted[first],
                "message": f"{name}：第 {first + 1} 次跳变比参考{direction} {abs(shifted[first]):g} 个周期",
            })
        elif reference_timelines.get(name) != candidate_timelines.get(name):
            differences.append({
                "signal": name,
                "kind": "value",
                "message": f"{name}：跳变时刻一致但数值序列不同",
            })
    return {
        "schema_version": "1.1",
        "clock_period_ns": float(clock_period_ns),
        "shared_signals": shared,
        "only_in_reference": only_reference,
        "only_in_candidate": only_candidate,
        "differences": differences,
        "difference_count": len(differences),
        # ``status`` 只描述**共有信号**的可观测行为：一侧多出内部辅助变量
        # （例如组合中间量 next_count）是实现细节，不是行为差异。信号集合
        # 不一致单独由 only_in_* / same_signal_set 表达。
        "status": "identical" if not differences else "different",
        "same_signal_set": not only_reference and not only_candidate,
        "disclaimer": "波形差异只描述可观测行为差异；是否构成缺陷由规格与 Icarus 判定。",
    }


__all__ = [
    "VCDChange",
    "analyze_failure_windows",
    "analyze_vcd_file",
    "compare_waveforms",
    "detect_phase_violations",
    "signal_edges",
    "signal_stability",
    "waveform_insights",
]
