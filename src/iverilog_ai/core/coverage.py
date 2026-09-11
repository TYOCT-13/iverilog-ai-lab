"""信号活动覆盖率：由 VCD 事件推导 RTL 里哪些信号真的动过。

## 为什么是这个口径

Icarus Verilog **没有**内建代码覆盖率（语句/分支/条件/翻转），也没有编译期插桩。
因此本模块不去伪造"代码覆盖率"，而是做一个**能用现有证据严格算出来**的口径：

> 仿真期间，RTL 里每个信号是否在 VCD 中产生过变化。

它回答的问题很具体："我写的激励，到底让设计里哪些部分动起来了？"——这对验证是
有用的信息（大量信号从没变化，通常意味着激励没走到那条路径）。

## 必须说清的边界

| 本模块**能**说 | 本模块**不能**说 |
|---|---|
| 某信号在本次仿真中是否发生过变化 | 某一行代码是否被执行过（语句覆盖率） |
| 哪些信号被激励触发了 | 某个分支是否被取过（分支覆盖率） |
| 覆盖率随激励变化（可用于比较激励质量） | 某个条件的所有取值组合是否覆盖（条件覆盖率） |

**一条永不变化的信号不等于"死代码"**：它可能只是本次激励没走到。反过来，信号动了
也不代表那一行的逻辑被验证过——例如复位把信号拉低也会让它"动"。因此本模块只报事实，
不给"已充分验证"这类结论。

另外：只有被 ``$dumpvars`` 记录下来的信号才能参与统计。测试平台未 dump 的内部层次
会显示为"不可观测"，而不是被算成"未覆盖"——两者含义完全不同。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

__all__ = [
    "ModuleSignals",
    "SignalActivity",
    "analyze_signal_activity",
    "module_signals",
    "strip_comments",
    "DISCLAIMER",
]

DISCLAIMER = (
    "本覆盖率是**信号活动覆盖率**（信号在 VCD 中是否变化过），不是语句、分支、条件或"
    "翻转覆盖率。Icarus 不提供编译期覆盖率插桩，因此本项目不声称能给出代码覆盖率。"
    "信号未变化只表示本次激励没触发它，不等于死代码；信号有变化也不等于对应逻辑被验证。"
)

_MODULE_HEAD = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_]\w*)\s*(?:#\s*\(.*?\)\s*)?\((?P<header>.*?)\)\s*;",
    re.S,
)
_ENDMODULE = re.compile(r"\bendmodule\b")
_DECLARATION = re.compile(
    r"\b(?:input|output|inout|wire|reg|logic)\b"
    r"(?:\s+(?:wire|reg|logic|signed|unsigned))*"
    r"(?:\s*\[[^\]]*\])?"
    r"\s+(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
)
#: 参数声明：`parameter`/`localparam` 是**编译期常量**，永远不会变化，
#: 把它们当作"未变化的信号"会让报告出现整片假缺口（实测 traffic_light_emergency
#: 的 7 个 localparam 状态常量曾被全部列为"未变化"）。
#:
#: 取整条声明到分号，再按逗号切分后逐个取 `=` 左侧的名字。**不能**用"名字列表"
#: 正则去匹配：`localparam RED=2'b00, YELLOW=2'b01` 里每个名字后面跟的是 `=`，
#: 名字列表正则在第一个名字后就匹配不下去了，只会得到 RED。
_PARAM_STATEMENT = re.compile(r"\b(?:parameter|localparam)\b[^;]*;", re.S)
_PARAM_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)")
#: 存储体声明：`reg [7:0] mem [0:3];` —— VCD 通常按字展开，整体名不一定出现，
#: 因此单独识别并在报告里说明，而不是笼统算作"未覆盖"。
_MEMORY_DECLARATION = re.compile(r"\b(?:reg|logic|wire)\b[^;\n]*?\s(?P<name>[A-Za-z_]\w*)\s*\[[^\]]+\]\s*;")
_ASSIGN_TARGET = re.compile(r"(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:<=|=(?!=))")


def strip_comments(source: str) -> str:
    """去掉注释但**保留换行与字符位置**，使行号仍然可用。"""

    without_block = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
    return re.sub(r"//[^\n]*", "", without_block)


@dataclass(frozen=True)
class ModuleSignals:
    """一个模块里声明过或被赋值的信号，及其首次出现行号。

    ``parameters`` 是编译期常量（``parameter``/``localparam``），``memories`` 是
    存储体声明——两者都**不参与活动覆盖率统计**，原因见各自的注释。
    """

    name: str
    start_line: int
    end_line: int
    signals: dict[str, int] = field(default_factory=dict)
    parameters: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signal_count": len(self.signals),
            "signals": dict(sorted(self.signals.items())),
            "parameters": list(self.parameters),
            "memories": list(self.memories),
        }


@dataclass(frozen=True)
class SignalActivity:
    """一个模块的信号活动统计。"""

    module: str
    declared: int
    observed: int

    @property
    def unobserved(self) -> int:
        return self.declared - self.observed

    @property
    def ratio(self) -> float:
        return self.observed / self.declared if self.declared else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "declared_signals": self.declared,
            "changed_signals": self.observed,
            "unchanged_signals": self.unobserved,
            "ratio": round(self.ratio, 4),
        }


def _module_spans(source: str) -> list[tuple[str, int, int, str]]:
    """切出每个模块的 (名字, 起始行, 结束行, 模块体)。行号从 1 开始。"""

    spans: list[tuple[str, int, int, str]] = []
    for match in _MODULE_HEAD.finditer(source):
        end = _ENDMODULE.search(source, match.end())
        if end is None:
            continue
        body = source[match.end():end.start()]
        spans.append((
            match.group("name"),
            source.count("\n", 0, match.start()) + 1,
            source.count("\n", 0, end.start()) + 1,
            match.group("header") + "\n" + body,
        ))
    return spans


def module_signals(source: str) -> list[ModuleSignals]:
    """抽取每个模块声明过或被赋值的信号名（含端口与内部信号）。

    未完整解析端口位宽与 ``generate`` 内部结构——本函数的目标是"信号集合"，
    不是语法树；解析不出的构造不会产生错误的信号名，只是可能漏若干。
    """

    cleaned = strip_comments(source)
    results: list[ModuleSignals] = []
    for name, start_line, end_line, body in _module_spans(cleaned):
        names: dict[str, int] = {}
        parameters: set[str] = set()
        memories: set[str] = set()
        for match in _PARAM_STATEMENT.finditer(body):
            statement = match.group(0)
            # 去掉 `parameter` / `localparam` 关键字与类型/位宽，再按逗号切分
            head = re.sub(
                r"^\s*(?:parameter|localparam)\b(?:\s+(?:integer|signed|unsigned))*"
                r"(?:\s*\[[^\]]*\])?",
                "",
                statement,
                flags=re.S,
            )
            for chunk in head.rstrip(";").split(","):
                name_match = _PARAM_ASSIGN.match(chunk)
                if name_match:
                    parameters.add(name_match.group(1))
        for match in _MEMORY_DECLARATION.finditer(body):
            memories.add(match.group("name"))
        for match in _DECLARATION.finditer(body):
            for candidate in match.group("names").split(","):
                candidate = candidate.strip()
                if candidate and candidate not in _KEYWORDS and candidate not in parameters and candidate not in memories:
                    names.setdefault(candidate, start_line)
        for match in _ASSIGN_TARGET.finditer(body):
            candidate = match.group("name")
            if (
                candidate
                and candidate not in _KEYWORDS
                and candidate not in parameters
                and candidate not in memories
            ):
                names.setdefault(candidate, start_line)
        results.append(
            ModuleSignals(
                name=name,
                start_line=start_line,
                end_line=end_line,
                signals=names,
                parameters=sorted(parameters),
                memories=sorted(memories),
            )
        )
    return results


#: 出现在赋值/声明正则里的 Verilog 关键字与常见任务名，必须排除，否则会被当成信号
_KEYWORDS = frozenset({
    "if", "else", "begin", "end", "case", "casex", "casez", "endcase", "default", "for",
    "while", "repeat", "forever", "always", "initial", "assign", "wire", "reg", "logic",
    "input", "output", "inout", "module", "endmodule", "parameter", "localparam",
    "posedge", "negedge", "or", "and", "not", "integer", "genvar", "generate", "endgenerate",
    "function", "endfunction", "task", "endtask", "return", "break", "continue", "disable",
    "display", "finish", "stop", "time", "realtime", "signed", "unsigned", "real", "wait",
})


def _signal_width(source: str, name: str) -> int | None:
    """从声明里取某个信号的位宽；取不到返回 None。

    只识别 ``[msb:lsb]`` 与 ``[n]`` 两种常见写法，且要求是常量范围——
    参数化的位宽（``[WIDTH-1:0]``）无法在纯文本层求值，返回 None 让调用方
    如实标注"位宽未知"，而不是猜一个数字。
    """

    pattern = re.compile(
        rf"\b(?:input|output|inout|wire|reg|logic)\b(?:\s+(?:wire|reg|logic|signed|unsigned))*"
        rf"\s*\[(?P<range>[^\]]*)\]\s+[^\n;]*\b{re.escape(name)}\b"
    )
    match = pattern.search(strip_comments(source))
    if not match:
        # 无位宽声明：按 1 位处理（但只在名字确实被声明时）。
        # 分隔符必须同时接受 `;` 与 `,`——ANSI 端口列表里是逗号分隔：
        # `module m(input wire clk, input wire [3:0] d);` 中的 clk 后面跟的是逗号，
        # 早期只认分号，导致 1 位信号被算成"位宽未知"、取值覆盖显示 None。
        scalar = re.compile(
            rf"\b(?:input|output|inout|wire|reg|logic)\b(?:\s+(?:wire|reg|logic|signed|unsigned))*"
            rf"\s+(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*[,;)]"
        )
        for item in scalar.finditer(strip_comments(source)):
            if name in [part.strip() for part in item.group("names").split(",")]:
                return 1
        return None
    text = match.group("range").strip()
    high, _, low = text.partition(":")
    try:
        if low:
            return abs(int(high.strip()) - int(low.strip())) + 1
        return 1 + int(high.strip())
    except ValueError:
        return None


def _vcd_module_of(signal: str, top: str, *, separator: str = ".") -> str | None:
    """从 VCD 里的完整信号名推断它属于哪个模块实例。

    形如 ``tb_pwm.dut_i.counter`` → 第一段是顶层测试台，第二段是 DUT 实例名。
    本项目生成的 testbench 里 DUT 实例名固定，因此取测试台之后的**第一段**
    作为模块实例名；``tb_pwm.counter`` 这类测试台自己的信号返回 None（不属于 DUT）。
    """

    parts = signal.split(separator)
    if len(parts) < 3 or parts[0] != top:
        return None
    return parts[1]


def analyze_signal_activity(
    source: str,
    analysis: Mapping[str, Any],
    *,
    top: str,
    instance: str | None = None,
) -> dict[str, Any]:
    """把 RTL 信号集合与 VCD 活动记录比对，产出信号活动覆盖率。

    ``instance`` 给定时只统计该实例下的信号（通常是 ``dut_i``）；为 None 时统计
    顶层测试台之下所有实例的信号，并仍按实例名分组报告。
    """

    modules = module_signals(source)
    # RTL 文件里通常只有一个模块；有多个时按第一个报告，其余在 note 里说明
    primary = modules[0] if modules else None

    activity_by_instance: dict[str, set[str]] = {}
    values_by_instance: dict[str, dict[str, int]] = {}
    for item in analysis.get("signals", []) or []:
        name = str(item.get("name", ""))
        changes = item.get("changes")
        if not isinstance(changes, int) or changes <= 0:
            continue
        owner = _vcd_module_of(name, top)
        if owner is None:
            continue
        if instance is not None and owner != instance:
            continue
        leaf = name.rsplit(".", 1)[-1]
        activity_by_instance.setdefault(owner, set()).add(leaf)
        distinct = item.get("distinct_values")
        if isinstance(distinct, int) and distinct > 0:
            values_by_instance.setdefault(owner, {})[leaf] = distinct

    if primary is None:
        return {
            "status": "no_module",
            "disclaimer": DISCLAIMER,
            "note": "RTL 源码里没有解析到 module 声明。",
        }

    declared = set(primary.signals)
    changed_by_instance: dict[str, list[str]] = {}
    for owner, leaves in sorted(activity_by_instance.items()):
        changed_by_instance[owner] = sorted(declared & leaves)

    changed_union: set[str] = set()
    for changed_leaves in changed_by_instance.values():
        changed_union |= set(changed_leaves)

    observed = len(changed_union)
    unchanged = sorted(declared - changed_union)
    unknown = len(activity_by_instance) == 0

    # 取值覆盖：信号到达过多少个不同值，对照其类型可能取值数（1 位 → 2 个）。
    # 「是否变化」的诊断力有限——复位把计数器清零也算"变化过"。取值数能区分
    # "只被复位动过一次"与"被激励驱动遍历过取值空间"。
    distinct_union: dict[str, int] = {}
    for value_counts in values_by_instance.values():
        for leaf, count in value_counts.items():
            if leaf in declared:
                distinct_union[leaf] = max(distinct_union.get(leaf, 0), count)
    value_detail: list[dict[str, Any]] = []
    for name in sorted(declared):
        if name not in distinct_union:
            continue
        width = _signal_width(source, name)
        possible = 2 ** width if width and width <= 16 else None
        value_detail.append({
            "signal": name,
            "distinct_values": distinct_union[name],
            "possible_values": possible,
            "ratio": round(distinct_union[name] / possible, 4) if possible else None,
        })
    measured_values = [item["ratio"] for item in value_detail if item["ratio"] is not None]
    value_coverage = round(sum(measured_values) / len(measured_values), 4) if measured_values else None

    return {
        "status": "unknown" if unknown else "measured",
        "module": primary.name,
        "source_lines": {"start": primary.start_line, "end": primary.end_line},
        "declared_signals": len(declared),
        "changed_signals": observed,
        "unchanged_signals": len(declared) - observed,
        "ratio": round(observed / len(declared), 4) if declared else 0.0,
        "unchanged": unchanged,
        "value_coverage": value_coverage,
        "value_detail": value_detail,
        "excluded_parameters": list(primary.parameters),
        "excluded_memories": list(primary.memories),
        "changed_by_instance": changed_by_instance,
        "note": (
            "未在 VCD 中找到该实例的信号，无法判定活动情况——"
            "这通常意味着 $dumpvars 未覆盖该层次，而不是信号都没变化。"
            if unknown else
            "只统计被 $dumpvars 记录的信号；未 dump 的层次不参与统计，也不被算作未覆盖。"
            f"已排除编译期常量 {len(primary.parameters)} 个"
            f"（它们按定义永不变化，计入会形成假缺口）"
            + (f"，以及存储体 {primary.memories}（VCD 通常按字展开，整体名不一定出现）。"
               if primary.memories else "。")
            + "取值覆盖只统计已知位宽且位宽 ≤16 的信号，且以"
              "「类型可能取值数」为分母——那是理想上限，不是应达目标。"
        ),
        "disclaimer": DISCLAIMER,
    }
