"""Deterministic RTL static quality review.

This is a conservative lint-like pass for teaching and triage.  It reports
evidence with line numbers and never claims synthesis/timing success.

规则按"能否可靠判定"分组，`_RULE_REGISTRY` 是唯一事实来源：每条规则在这里
登记 id、默认严重级别、说明与来源。报告和文档都从它生成，避免"代码改了文档没改"。

Severity 校准原则：
- ``error``：几乎必然导致综合/实现问题，或明确的多驱动/锁存器语义错误；
- ``warn``：常见陷阱或可综合性风险，需要人工判断但不必然错；
- ``info``：风格与可维护性建议。

风格类规则只在文件名看起来是**设计文件**时启用；``tb_*.v``、``*_tb.v``、
``*_test.v`` 这类测试平台里的延迟、``initial``、``$display`` 都是正常写法。
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


@dataclass(frozen=True)
class RuleSpec:
    """一条静态规则的元数据：唯一事实来源。"""

    rule_id: str
    severity: str
    title: str
    source: str
    applies_to: str = "design"  # design | any
    once_per_file: bool = False  # 文件级提示（如缺少 `timescale）无需逐行重复


# 规则注册表：新增规则必须在这里登记，并配一条正例与一条反例测试。
_RULE_REGISTRY: tuple[RuleSpec, ...] = (
    # ---- 可综合性：明确的综合陷阱 ----
    RuleSpec("synth-delay", "error", "可综合 RTL 中出现 #delay", "lowRISC Verilog 风格指南 / 通用综合实践"),
    RuleSpec("initial-block", "warn", "设计文件中的 initial 块", "lowRISC Verilog 风格指南 / FPGA 综合实践"),
    RuleSpec("real-type", "warn", "使用 real/shortreal 类型", "可综合 Verilog 子集（IEEE 1364 综合子集）"),
    RuleSpec("time-type", "warn", "使用 time 类型", "可综合 Verilog 子集（IEEE 1364 综合子集）"),
    RuleSpec("event-type", "warn", "使用 event 类型", "可综合 Verilog 子集（IEEE 1364 综合子集）"),
    RuleSpec("division-operator", "warn", "使用除法或取模运算符", "FPGA 综合实践（除/模通常不可映射为单个 DSP 或逻辑）"),
    RuleSpec("real-division", "warn", "使用实数除法 /", "可综合 Verilog 子集"),
    RuleSpec("system-task-display", "info", "设计文件中出现 $display/$write 等仿真系统任务", "lowRISC Verilog 风格指南", "design"),
    RuleSpec("system-task-file-io", "warn", "使用 $fopen/$readmemh 等文件 IO 系统任务", "可综合 Verilog 子集"),
    RuleSpec("system-task-time", "warn", "使用 $time/$stime/$realtime", "可综合 Verilog 子集"),
    RuleSpec("fork-join", "warn", "使用 fork/join 并行块", "可综合 Verilog 子集"),
    RuleSpec("wait-statement", "warn", "使用 wait 语句", "可综合 Verilog 子集"),
    RuleSpec("disable-statement", "warn", "使用 disable 语句", "可综合 Verilog 子集"),
    RuleSpec("while-loop", "warn", "使用 while 循环", "可综合 Verilog 子集（综合需要可静态展开的循环边界）"),
    RuleSpec("forever-loop", "warn", "使用 forever 循环", "可综合 Verilog 子集"),
    RuleSpec("repeat-loop", "warn", "使用 repeat 循环", "可综合 Verilog 子集（需检查能否静态展开）"),

    # ---- 时序与复位 ----
    RuleSpec("blocking-in-sequential", "warn", "时序 always 块中使用阻塞赋值", "lowRISC Verilog 风格指南 / 通用 RTL 实践"),
    RuleSpec("non-blocking-combinational", "warn", "组合 always 块中使用非阻塞赋值", "lowRISC Verilog 风格指南 / 通用 RTL 实践"),
    RuleSpec("incomplete-sensitivity", "warn", "显式组合敏感列表可能不完整", "lowRISC Verilog 风格指南 / 通用 RTL 实践"),
    RuleSpec("async-reset-no-sync", "warn", "使用异步复位但没有明显同步器", "ZipCPU wb2axip / 通用 CDC 实践", "design", True),
    RuleSpec("reset-polarity-mixed", "warn", "同一模块混用高有效与低有效复位", "lowRISC Verilog 风格指南"),
    RuleSpec("clock-in-always-sensitivity", "warn", "时钟信号出现在 always 敏感列表但未作为边沿", "通用 RTL 实践"),
    RuleSpec("reset-in-data-path", "warn", "复位信号出现在时钟 always 的数据路径条件中", "通用 RTL 实践"),

    # ---- 组合逻辑与锁存器 ----
    RuleSpec("inferred-latch", "error", "组合 always 块存在未赋值路径（推断锁存器）", "通用 RTL 实践 / FPGA 综合实践"),
    RuleSpec("missing-default-case", "warn", "case 语句没有 default 分支", "lowRISC Verilog 风格指南 / 通用 RTL 实践"),
    RuleSpec("incomplete-case-assignment", "warn", "case 分支未覆盖输出或没有默认赋值", "通用 RTL 实践"),
    RuleSpec("comb-loop", "warn", "always 块内存在看似自身的组合反馈", "通用 RTL 实践"),

    # ---- 多驱动与时钟域 ----
    RuleSpec("multiple-procedural-drivers", "error", "信号在多个过程块中被赋值", "通用 RTL 实践 / verilog-axi 接口约定"),
    RuleSpec("mixed-block-assignment", "error", "同一信号同时用阻塞与非阻塞赋值", "通用 RTL 实践"),
    RuleSpec("missing-async-reg", "info", "疑似同步器寄存器缺少 ASYNC_REG 属性", "Xilinx/Intel 厂商 CDC 指南 / ZipCPU wb2axip"),

    # ---- 位宽与常量 ----
    RuleSpec("width-truncation", "warn", "赋值右侧常量超出左侧位宽（会被截断）", "verilog-axi 位宽约定 / 通用 RTL 实践"),
    RuleSpec("unsized-literal", "info", "使用未指定位宽的常量字面量", "lowRISC Verilog 风格指南"),
    RuleSpec("parameter-no-default", "info", "parameter 未给出默认值", "通用 RTL 实践"),
    RuleSpec("localparam-missing", "info", "状态编码使用 parameter 而非 localparam", "lowRISC Verilog 风格指南"),

    # ---- 接口与可读性 ----
    RuleSpec("missing-timescale", "info", "文件缺少 `timescale 指令", "lowRISC Verilog 风格指南", "design", True),
    RuleSpec("missing-port-direction", "warn", "端口声明缺少方向", "通用 Verilog 语法要求"),
    RuleSpec("non-ansi-port-list", "info", "使用非 ANSI 端口列表（端口与方向分开声明）", "lowRISC Verilog 风格指南 / SystemVerilog 实践"),
    RuleSpec("long-line", "info", "行宽超过 120 字符", "lowRISC Verilog 风格指南"),
    RuleSpec("trailing-whitespace", "info", "行尾有多余空白", "lowRISC Verilog 风格指南"),
    RuleSpec("tab-indent", "info", "使用制表符缩进", "lowRISC Verilog 风格指南"),
    RuleSpec("floating-net", "warn", "声明了 wire 但从未被驱动", "通用 RTL 实践", "design", True),
    RuleSpec("unused-signal", "info", "信号被声明但未使用", "lowRISC Verilog 风格指南"),
    RuleSpec("empty-port-connection", "info", "实例化时存在空端口连接", "lowRISC Verilog 风格指南"),
    RuleSpec("generate-no-label", "info", "generate 块缺少标号", "lowRISC Verilog 风格指南"),
)

RULE_REGISTRY: dict[str, RuleSpec] = {spec.rule_id: spec for spec in _RULE_REGISTRY}

_SEVERITY_WEIGHT = {"error": 20, "warn": 5, "info": 1}

_TESTBENCH_NAME_RE = re.compile(r"(^tb_|_tb\.v$|_test\.v$|^tb)", re.I)


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _snippet(lines: list[str], line: int) -> str:
    return lines[line - 1].strip()[:240] if 1 <= line <= len(lines) else ""


def _finding(source: str, lines: list[str], rule_id: str, severity: str, offset: int, message: str, suggestion: str) -> StaticFinding:
    line = _line_number(source, offset)
    return StaticFinding(rule_id, severity, line, message, suggestion, _snippet(lines, line))


_ALWAYS_HEAD_RE = re.compile(r"\balways\s*@\s*\((?P<sens>[^)]*)\)", re.I)
_WORD_RE = re.compile(r"[A-Za-z_]\w*")
_END_TOKENS = {"end", "endcase", "join", "endgenerate", "endfunction", "endtask"}


def _consume_statement(text: str, position: int) -> int:
    """消费一条完整语句，返回结束偏移。

    处理 begin/end 块、case/endcase、if/else 链与单语句三种形态。
    ``if`` 后面必须继续消费 ``else`` 部分，否则含 else 的时序块会被截断，
    使复位判定之类的规则看不到完整分支。
    """

    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text):
        return position

    word = _WORD_RE.match(text, position)
    keyword = word.group(0).lower() if word else ""

    if keyword in {"begin", "fork"}:
        depth = 0
        while position < len(text):
            match = _WORD_RE.search(text, position)
            if match is None:
                return len(text)
            token = match.group(0).lower()
            if token in {"begin", "fork", "case", "casez", "casex"}:
                depth += 1
            elif token in _END_TOKENS:
                depth -= 1
                if depth <= 0:
                    return match.end()
            position = match.end()
        return len(text)

    if keyword in {"case", "casez", "casex"}:
        depth = 0
        while position < len(text):
            match = _WORD_RE.search(text, position)
            if match is None:
                return len(text)
            token = match.group(0).lower()
            if token in {"case", "casez", "casex"}:
                depth += 1
            elif token == "endcase":
                depth -= 1
                if depth <= 0:
                    return match.end()
            position = match.end()
        return len(text)

    if keyword == "if":
        # 跳过条件表达式
        open_index = text.find("(", position)
        if open_index < 0:
            return len(text)
        depth = 0
        position = open_index
        while position < len(text):
            char = text[position]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    position += 1
                    break
            position += 1
        position = _consume_statement(text, position)
        # 继续消费 else 分支；循环只能从内部的 return 退出（else 链消费完毕）。
        while True:
            after = text[position:].lstrip()
            if not after.lower().startswith("else"):
                return position
            position = text.index("else", position) + len("else")
            position = _consume_statement(text, position)

    semicolon = text.find(";", position)
    return len(text) if semicolon < 0 else semicolon + 1


def _always_block_body(source: str, start: int) -> str:
    """从 always 头部之后提取完整块体。

    早期实现用"body 以 ``end`` + 换行结尾"的正则，导致**单行 always 块完全解析
    不出来**（``always @(*) y = a; endmodule`` 里的 ``end`` 属于 ``endmodule``），
    于是所有按块分析的规则在这些写法上静默失效。这里改为按语句消费，
    单语句块与 begin/end 块都能正确处理。
    """

    return source[start:_consume_statement(source, start)]


def _always_blocks(source: str) -> Iterable[tuple[re.Match[str], str]]:
    for match in _ALWAYS_HEAD_RE.finditer(source):
        yield match, _always_block_body(source, match.end())


def _is_testbench(filename: str) -> bool:
    return bool(_TESTBENCH_NAME_RE.search(Path(filename).name))


def _strip_comments(source: str) -> str:
    """去掉注释，避免注释里的示例代码触发规则（保留换行以维持行号）。"""

    without_block = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
    return re.sub(r"//[^\n]*", "", without_block)


# --------------------------------------------------------------------------
# 词法层规则：明确的不可综合构造、系统任务、数值字面量
# --------------------------------------------------------------------------
_LEXICAL_RULES: tuple[tuple[str, str, str, str], ...] = (
    # (rule_id, 正则, 消息, 建议)
    ("real-type", r"\b(?:real|shortreal|realtime)\b", "Design uses real/shortreal/realtime", "Use integer or fixed-point arithmetic; real types are not synthesizable."),
    ("time-type", r"\btime\b", "Design uses the time type", "Use integer counters for timing; the time type is not synthesizable."),
    ("event-type", r"\bevent\b", "Design declares an event type", "Use an explicit handshake signal instead of event triggers."),
    ("fork-join", r"\bfork\b", "Design contains a fork block", "Replace fork/join with a single clocked process and explicit state."),
    ("wait-statement", r"\bwait\s*\(", "Design uses a wait statement", "Use an explicit state machine or clocked condition instead of wait."),
    ("disable-statement", r"\bdisable\b", "Design uses the disable statement", "Use an explicit state variable instead of disable."),
    ("forever-loop", r"\bforever\b", "Design contains a forever loop", "Only testbenches should use forever; use a clocked process for RTL."),
    ("repeat-loop", r"\brepeat\s*\(", "Design contains a repeat loop", "Prefer a for loop with static bounds so synthesis can unroll it."),
    ("while-loop", r"\bwhile\s*\(", "Design contains a while loop", "Prefer a for loop with static bounds so synthesis can unroll it."),
    ("system-task-display", r"\$(?:display|write|strobe|monitor)\b", "Design contains a simulation display task", "Keep $display in testbenches; remove it from synthesizable RTL."),
    ("system-task-file-io", r"\$(?:fopen|fclose|fdisplay|fwrite|readmemh|readmemb|sformat)\b", "Design uses file IO system tasks", "File IO is not synthesizable; keep it in the testbench."),
    ("system-task-time", r"\$(?:time|stime|realtime)\b", "Design uses simulation time system functions", "Simulation time is not synthesizable; use a counter for on-chip timing."),
)

_FILE_IO_TASK_RE = re.compile(r"\$(?:fopen|fclose|fdisplay|fwrite|readmemh|readmemb|sformat)\b")


def _lexical_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    for rule_id, pattern, message, suggestion in _LEXICAL_RULES:
        # $display 在设计文件里只是风格问题，在 testbench 里完全正常。
        for match in re.finditer(pattern, source, re.I):
            findings.append(_finding(source, lines, rule_id, RULE_REGISTRY[rule_id].severity, match.start(), message, suggestion))


def _numeric_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    """位宽截断与未指定宽度的常量字面量。"""

    # 带位宽的赋值目标：reg/wire [N-1:0] name ... ; 之后找 name <=/=<常量>
    declared_width: dict[str, int] = {}
    for match in re.finditer(r"\b(?:reg|wire|logic)\s*(?:signed\s*)?\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*([A-Za-z_]\w*)", source, re.I):
        high, low = int(match.group(1)), int(match.group(2))
        if high >= low:
            declared_width[match.group(3)] = high - low + 1

    for name, width in declared_width.items():
        assignment = re.compile(rf"\b{re.escape(name)}\s*(?:<=|=)\s*(?:(\d+)\s*)?'([bBoOdDhH])([0-9a-fA-F_xXzZ]+)")
        for match in assignment.finditer(source):
            digits = match.group(3).replace("_", "")
            if any(ch in digits.lower() for ch in "xz"):
                continue
            try:
                base = {"b": 2, "o": 8, "d": 10, "h": 16}[match.group(2).lower()]
                value = int(digits, base)
            except ValueError:
                continue
            if value >= (1 << width):
                findings.append(_finding(
                    source, lines, "width-truncation", "warn", match.start(),
                    f"Constant {value} does not fit in {width}-bit signal {name!r} and will be truncated",
                    "Size the literal explicitly and confirm the truncation is intended.",
                ))

    # 未指定宽度的十进制常量（排除端口位宽、参数默认值、延时与下标等上下文）
    for match in re.finditer(r"(?<![\w'\]])(\d{1,3})(?![\w'\]])", source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        context = source[line_start:match.start()]
        if re.search(r"(?:#|\[|\bparameter\b|\blocalparam\b|\bfor\b|,|\(|:)\s*$", context):
            continue
        key = re.search(r"(?:<=|=)\s*$", context)
        if not key:
            continue
        findings.append(_finding(
            source, lines, "unsized-literal", "info", match.start(),
            f"Unsized decimal literal {match.group(1)}",
            "Use a sized literal such as 8'd255 so width is explicit.",
        ))


def _style_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    """风格类规则：每条规则只报第一次出现，避免噪声淹没真正的问题。"""

    for index, line in enumerate(lines, start=1):
        if len(line) > 120:
            findings.append(StaticFinding("long-line", "info", index, "Line longer than 120 characters", "Wrap long expressions for reviewability.", line.strip()[:240]))
            break
    for index, line in enumerate(lines, start=1):
        if line.rstrip() != line and line.strip():
            findings.append(StaticFinding("trailing-whitespace", "info", index, "Trailing whitespace", "Trim trailing whitespace.", line.strip()[:240]))
            break
    for index, line in enumerate(lines, start=1):
        if line.startswith("\t") or "\t" in line[: len(line) - len(line.lstrip())]:
            findings.append(StaticFinding("tab-indent", "info", index, "Tab character used for indentation", "Use spaces (2 per level) for consistent diffs.", line.strip()[:240]))
            break


def _module_clocks_and_resets(source: str) -> tuple[set[str], set[str]]:
    """按常见命名约定推断模块内的时钟与复位信号名。

    命名习惯既可能是前缀（``clk``、``clk_div2``）也可能是后缀（``sys_clk``、
    ``rst_n``、``arst``），早期只匹配前缀的写法导致复位/时钟相关规则从未生效。
    """

    clocks = {
        match.group(0)
        for match in re.finditer(r"\b[A-Za-z_]\w*\b", source)
        if re.search(r"(?:^|_)(?:clk|clock)(?:_|$)", match.group(0), re.I)
    }
    resets = {
        match.group(0)
        for match in re.finditer(r"\b[A-Za-z_]\w*\b", source)
        if re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", match.group(0), re.I)
    }
    return clocks, resets


def _port_list_spans(source: str) -> list[tuple[int, int]]:
    """返回所有 module 端口列表的偏移区间。

    端口列表里的 ``=`` 是端口/信号声明的初值（例如 ``output reg [3:0] c = 4'd15``），
    不是过程赋值，必须排除在多驱动与赋值混用判定之外。
    """

    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\bmodule\b[^;(]*\(", source, re.I):
        depth = 0
        for position in range(match.end() - 1, len(source)):
            char = source[position]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    spans.append((match.start(), position))
                    break
    return spans


def _procedural_assignment_sites(source: str) -> tuple[dict[str, list[int]], dict[str, set[str]]]:
    """统计每个信号的过程赋值位置与所用赋值符类型（排除声明与端口列表初值）。"""

    offsets: dict[str, list[int]] = {}
    kinds: dict[str, set[str]] = {}
    port_spans = _port_list_spans(source)
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*(<=|(?<![=!<>+\-*/%&|^])=(?!=|>))")
    for match in pattern.finditer(source):
        name = match.group(1)
        # 端口列表内的初值不是过程赋值
        if any(start <= match.start() < end for start, end in port_spans):
            continue
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.start())
        line = source[line_start: line_end if line_end >= 0 else len(source)]
        # 声明行里的初始化（reg x = 0）不是过程赋值
        if re.match(r"\s*(?:reg|wire|logic|input|output|inout|integer|parameter|localparam)\b", line):
            continue
        if re.search(r"\b(?:input|output|inout)\b[^;]*$", source[line_start:match.start()]):
            continue
        kind = "nonblocking" if match.group(2) == "<=" else "blocking"
        offsets.setdefault(name, []).append(match.start())
        kinds.setdefault(name, set()).add(kind)
    return offsets, kinds


def _split_control_head(body: str, keyword: str) -> tuple[str, str, str] | None:
    """解析 ``if (cond) stmt [else stmt]`` 或 ``case (expr) ... endcase``。

    返回 ``(head, then_part, else_part)``；``else_part`` 为空表示没有 else。
    解析失败时返回 ``None``，调用方据此放弃该块的分析（宁可漏报也不误报）。
    """

    text = body.strip()
    if not text.lower().startswith(keyword):
        return None
    index = len(keyword)
    open_index = text.find("(", index)
    if open_index < 0:
        return None
    depth = 0
    close_index = -1
    for position in range(open_index, len(text)):
        char = text[position]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = position
                break
    if close_index < 0:
        return None
    head = text[: close_index + 1]
    rest = text[close_index + 1:].strip()
    if keyword == "if":
        then_part, else_part = _split_statement(rest)
        return head, then_part, else_part
    # case：整体直到 endcase
    end = re.search(r"\bendcase\b", rest, re.I)
    return head, rest[: end.start()] if end else rest, ""


def _split_statement(text: str) -> tuple[str, str]:
    """把一个语句切成 (语句本体, else 之后的部分)。"""

    text = text.lstrip()
    if text.lower().startswith("begin"):
        depth = 0
        for position, char in enumerate(text):
            if char == "b" and text[position:position + 5].lower() == "begin":
                depth += 1
            if text[position:position + 3].lower() == "end" and (position + 3 >= len(text) or not text[position + 3].isalnum()):
                depth -= 1
                if depth == 0:
                    body = text[: position + 3]
                    remainder = text[position + 3:].lstrip()
                    return body, _strip_else(remainder)
        return text, ""
    semicolon = text.find(";")
    if semicolon < 0:
        return text, ""
    return text[: semicolon + 1], _strip_else(text[semicolon + 1:].lstrip())


def _strip_else(remainder: str) -> str:
    if remainder.lower().startswith("else"):
        return remainder[4:].lstrip()
    return ""


def _assigned_identifiers(statement: str) -> set[str]:
    """取出一个语句里被赋值的信号名。"""

    return {
        match.group(1)
        for match in re.finditer(r"\b([A-Za-z_]\w*)\s*(?:<=|(?<![=!<>+\-*/%&|^])=(?!=|>))", statement)
    }


def _definitely_assigned(body: str) -> set[str]:
    """返回在该代码块中**所有执行路径**上都会被赋值的信号集合。

    只做保守判定：解析不出来就当作"不确定"，宁可漏报也不误报。
    """

    text = body.strip()
    if not text:
        return set()
    # begin/end 块：先看无条件前缀，再看第一个控制语句
    if text.lower().startswith("begin"):
        inner = re.sub(r"^\s*begin\b", "", text, count=1, flags=re.I)
        inner = re.sub(r"\bend\s*$", "", inner, count=1, flags=re.I)
        return _definitely_assigned(inner)

    for keyword in ("if", "case", "casez", "casex"):
        if text.lower().startswith(keyword):
            parsed = _split_control_head(text, keyword)
            if parsed is None:
                return set()
            _head, then_part, else_part = parsed
            if keyword == "if":
                if not else_part:
                    return set()
                return _definitely_assigned(then_part) & _definitely_assigned(else_part)
            # case 有 default 分支才认为覆盖完整
            if re.search(r"\bdefault\s*:", then_part, re.I):
                return _assigned_identifiers(then_part)
            if re.search(r"\bdefault\b", then_part, re.I):
                return _assigned_identifiers(then_part)
            return set()

    # 普通赋值语句（可能一条语句里给多个信号赋值）
    if ";" in text:
        return _assigned_identifiers(text)
    return set()


def _structural_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    """过程块级规则：锁存器、敏感列表、复位、多驱动、组合环路。"""

    clocks, resets = _module_clocks_and_resets(source)
    assigned_offsets, assigned_kinds = _procedural_assignment_sites(source)
    always_offsets = [match.start() for match in re.finditer(r"\balways\b", source, re.I)]

    for name, kinds in assigned_kinds.items():
        if len(kinds) > 1:
            findings.append(_finding(
                source, lines, "mixed-block-assignment", "error", assigned_offsets[name][0],
                f"Signal {name!r} is assigned with both blocking and non-blocking forms",
                "Use non-blocking <= for sequential state and blocking = for combinational values, never both on one signal.",
            ))

    blocks_seen: dict[str, set[int]] = {}
    for name, sites in assigned_offsets.items():
        for offset in sites:
            block = max((item for item in always_offsets if item <= offset), default=-1)
            if block >= 0:
                blocks_seen.setdefault(name, set()).add(block)
    for name, blocks in blocks_seen.items():
        if len(blocks) > 1:
            findings.append(StaticFinding(
                "multiple-procedural-drivers", "error", _line_number(source, min(assigned_offsets[name])),
                f"Signal {name!r} is assigned in multiple procedural blocks",
                "Keep one procedural driver per register; combine conditions in one always block.",
                _snippet(lines, _line_number(source, min(assigned_offsets[name]))),
            ))

    for match, body in _always_blocks(source):
        sens = match.group("sens")
        line = _line_number(source, match.start())
        snippet = _snippet(lines, line)

        if re.search(r"\bposedge\b|\bnegedge\b", sens, re.I):
            if re.search(r"(?<![=!<>])=(?!=|>)", body):
                findings.append(_finding(source, lines, "blocking-in-sequential", "warn", match.start(), "Sequential always block contains blocking assignment", "Use non-blocking <= for registered state updates."))
            # 时钟/复位名可能是后缀形式（clk_n、rst_n），因此先把边沿后的标识符
            # 整体捕获出来再判断，不能用 `[A-Za-z_]\w*(?:rst|reset)` 这种写法——
            # `\w*` 会把后缀一起吃掉，导致永不匹配。
            negedge_names = [item.group(1) for item in re.finditer(r"\bnegedge\s+([A-Za-z_]\w*)", sens, re.I)]
            if negedge_names and not re.search(r"sync|synchron", source, re.I):
                reset_like = [name for name in negedge_names if re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", name, re.I)]
                if reset_like:
                    findings.append(_finding(source, lines, "async-reset-no-sync", "warn", match.start(), "Asynchronous reset is used without an obvious synchronizer", "Use asynchronous assertion with synchronized de-assertion when the design requires clean reset release."))
            for reset in resets:
                if re.search(rf"\belse\s+if\s*\([^)]*\b{re.escape(reset)}\b", body, re.I):
                    findings.append(_finding(source, lines, "reset-in-data-path", "warn", match.start(), f"Reset signal {reset!r} is evaluated in the data path", "Keep reset handling in the first branch of the clocked block; do not gate data on reset later."))
                    break
            for clock in clocks:
                if re.search(rf"(?<!\b(?:pos|neg)edge\s)\b{re.escape(clock)}\b", sens, re.I) and not re.search(rf"\b(?:pos|neg)edge\s+{re.escape(clock)}\b", sens, re.I):
                    findings.append(_finding(source, lines, "clock-in-always-sensitivity", "warn", match.start(), f"Clock {clock!r} appears in the sensitivity list without an edge qualifier", "Trigger sequential logic on a clock edge, not on the clock level."))
                    break
            continue

        if "<=" in body:
            findings.append(_finding(source, lines, "non-blocking-combinational", "warn", match.start(), "Combinational always block contains non-blocking assignment", "Use blocking = assignments in combinational logic."))

        # 时钟出现在敏感列表但未加边沿限定：这比"敏感列表不完整"更具体，先报它。
        level_clock = None
        for clock in clocks:
            if re.search(rf"(?<!\b(?:pos|neg)edge\s)\b{re.escape(clock)}\b", sens, re.I):
                level_clock = clock
                break
        if level_clock is not None:
            findings.append(_finding(source, lines, "clock-in-always-sensitivity", "warn", match.start(), f"Clock {level_clock!r} appears in the sensitivity list without an edge qualifier", "Trigger sequential logic on a clock edge, not on the clock level."))
        elif "*" not in sens:
            findings.append(_finding(source, lines, "incomplete-sensitivity", "warn", match.start(), "Explicit combinational sensitivity list may be incomplete", "Use always @(*) or always_comb for combinational logic."))

        # 推断锁存器：只有在确认"存在某条路径没有赋值"时才报。
        # 判定方式是保守的：解析不出来的结构一律不报，宁可漏报也不误报。
        conditional = bool(re.search(r"\bif\b|\bcase\b", body, re.I))
        targets = _assigned_identifiers(body)
        if conditional and targets:
            covered = _definitely_assigned(body)
            latched = sorted(targets - covered)
            if latched:
                findings.append(StaticFinding(
                    "inferred-latch", "error", line,
                    f"Combinational block may infer a latch for {latched[0]!r} (not assigned on every path)",
                    "Assign every combinational output on all paths, or add a default assignment before the if/case.",
                    snippet,
                ))

        for statement in re.finditer(r"\b([A-Za-z_]\w*)\s*=(?!=)\s*([^;\n]+)", body):
            name, expression = statement.group(1), statement.group(2)
            if re.search(rf"\b{re.escape(name)}\b", expression):
                offset = match.start() + statement.start()
                findings.append(StaticFinding(
                    "comb-loop", "warn", _line_number(source, offset),
                    f"Combinational assignment to {name!r} reads its own value",
                    "Break the feedback path; combinational logic must not depend on its own output.",
                    _snippet(lines, _line_number(source, offset)),
                ))
                break


def _arithmetic_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    """除/模运算与非常数除数的可综合性提示。"""

    # 跳过 `timescale 行：1ns/1ps 里的斜杠是时间单位分隔符，不是除法运算
    searchable = "\n".join(
        "" if line.lstrip().startswith("`timescale") else line for line in source.split("\n")
    )

    # 只用"操作数 / 操作数"的形态判定，避免匹配注释结尾 `*/` 或换行空白
    for match in re.finditer(r"(?<=[\w\)\]])[ \t]*/[ \t]*(?=[\w\(!~])", searchable):
        window = searchable[max(0, match.start() - 16): match.start() + 20]
        if re.search(r"/\s*2\s*\*\*\s*\d", window):
            continue
        findings.append(_finding(
            source, lines, "division-operator", "warn", match.start(),
            "Design contains a division operator",
            "Division rarely maps to a single FPGA primitive; consider shifts or a pipelined divider.",
        ))

    for match in re.finditer(r"(?<=[\w\)\]])[ \t]*%[ \t]*(?=[\w\(!~])", searchable):
        findings.append(_finding(
            source, lines, "division-operator", "warn", match.start(),
            "Design contains a modulo operator",
            "Modulo rarely maps to a single FPGA primitive; consider a counter or a pipelined remainder.",
        ))

    for match in re.finditer(r"(?:<=|=)(?=[^;\n])[^;\n]*?/[ \t]*(\d+)", searchable):
        divisor = int(match.group(1))
        if divisor > 0 and divisor & (divisor - 1) == 0:
            continue
        findings.append(_finding(
            source, lines, "real-division", "warn", match.start(),
            "Truncating division by a non-power-of-two constant",
            "Use a shift for powers of two, or make the truncation explicit and covered by a test.",
        ))


def _interface_findings(source: str, lines: list[str], findings: list[StaticFinding], *, raw_source: str = "") -> None:
    """接口与可读性规则。

    ``raw_source`` 是未剥离注释的原文：`timescale 这类预处理指令必须看原文，
    否则注释剥离会把反引号指令一并吃掉。
    """

    if "`timescale" not in (raw_source or source):
        findings.append(StaticFinding("missing-timescale", "info", 1, "File has no `timescale directive", "Add `timescale 1ns/1ps so delays and waveform units are explicit.", _snippet(lines, 1)))

    for match in re.finditer(r"\bmodule\s+([A-Za-z_]\w*)\s*\((?P<ports>[^;]*)\)", source, re.I):
        ports = match.group("ports")
        if not ports.strip():
            continue
        if not re.search(r"\b(?:input|output|inout)\b", ports, re.I):
            findings.append(_finding(source, lines, "non-ansi-port-list", "info", match.start(), "Module uses a non-ANSI port list", "Prefer ANSI style: declare direction and width inline in the port list."))

    # 非 ANSI 风格：端口名出现在端口列表里，但方向声明分开写在模块体内。
    # 若某个端口名在体内既没有方向声明也没有被赋值，说明方向缺失。
    for match in re.finditer(r"\bmodule\s+([A-Za-z_]\w*)\s*\((?P<ports>[^;]*)\)\s*;", source, re.I):
        ports = match.group("ports")
        if re.search(r"\b(?:input|output|inout)\b", ports, re.I):
            continue
        body = source[match.end():]
        end = re.search(r"\bendmodule\b", body, re.I)
        body = body[: end.start()] if end else body
        for name in [item.strip() for item in ports.split(",") if item.strip()]:
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                continue
            declared = re.search(rf"\b(?:input|output|inout)\b[^;\n]*\b{re.escape(name)}\b", body)
            assigned = re.search(rf"\b{re.escape(name)}\b\s*(?:<=|=(?!=))", body)
            if not declared and not assigned:
                findings.append(_finding(source, lines, "missing-port-direction", "warn", match.start(), f"Port {name!r} has no declared direction", "Declare the port direction (input/output/inout); an undeclared port defaults to a wire with no direction."))
                break

    for match in re.finditer(r"\.\s*([A-Za-z_]\w*)\s*\(\s*\)", source):
        findings.append(_finding(source, lines, "empty-port-connection", "info", match.start(), f"Instance connects .{match.group(1)}() with nothing", "Remove the unused connection or document why the port is intentionally left open."))

    # generate 块缺少标号：只在模块体内出现 generate 关键字、且其后没有 `: label` 时提示。
    for match in re.finditer(r"\bgenerate\b(?P<tail>[^\n;]*)", source, re.I):
        if ":" in match.group("tail"):
            continue
        # 标号也可能写在下一行（begin : gen_x）
        following = source[match.end(): match.end() + 200]
        if re.search(r"^\s*[^\n]*\bbegin\s*:", following) or re.search(r"\bbegin\s*:", source[match.start(): match.start() + 200], re.I):
            continue
        findings.append(_finding(source, lines, "generate-no-label", "info", match.start(), "generate block has no label", "Label generate blocks (gen_*) so tools and reviewers can reference them."))

    for match in re.finditer(r"\bparameter\s+([A-Za-z_]\w*)\s*(?P<tail>[^;,\n]*)", source, re.I):
        if "=" not in match.group("tail"):
            findings.append(_finding(source, lines, "parameter-no-default", "info", match.start(), f"parameter {match.group(1)} has no default value", "Give parameters a safe default so the module elaborates standalone."))

    for match in re.finditer(r"\bparameter\s+[^;\n]*\b(?:IDLE|S_[A-Z_]+|[A-Z]{2,}_STATE)\b", source):
        if not re.search(r"\blocalparam\b", source):
            findings.append(_finding(source, lines, "localparam-missing", "info", match.start(), "State encodings are declared as parameter instead of localparam", "Use localparam for internal state encodings so they cannot be overridden."))

    declared: dict[str, tuple[int, str]] = {}
    port_spans = _port_list_spans(source)
    for match in re.finditer(r"\b(reg|wire|logic)\s*(?:signed\s*)?(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*(?:=|;|,)", source, re.I):
        # 端口列表里的 input/output 声明不是内部信号，不能按"未驱动/未使用"判定
        if any(start <= match.start() < end for start, end in port_spans):
            continue
        declared.setdefault(match.group(2), (match.start(), match.group(1).lower()))
    for name, (offset, kind) in declared.items():
        uses = len(re.findall(rf"\b{re.escape(name)}\b", source))
        if uses <= 1:
            findings.append(_finding(source, lines, "unused-signal", "info", offset, f"Signal {name!r} is declared but never used", "Remove the declaration or connect it; unused declarations hide intent."))
            continue
        if kind == "wire" and not re.search(rf"\bassign\s+{re.escape(name)}\b|\b{re.escape(name)}\s*<=|\.\s*{re.escape(name)}\s*\(", source):
            findings.append(_finding(source, lines, "floating-net", "warn", offset, f"Wire {name!r} is never driven", "Drive the wire with an assign or connect it to a module output."))

    # 同一个模块里混用高有效与低有效复位。
    # 先匹配完整标识符、再单独判断它是否是复位名：不能写成
    # `(?:rst|reset)\w*\b`——`\w*` 会吃掉 `_n` 后缀，回溯后又不满足词边界，
    # 导致 `rst_n` 这类常见命名永远匹配不到。
    low_match = None
    for match in re.finditer(r"!\s*([A-Za-z_]\w*)", source):
        if re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", match.group(1), re.I):
            low_match = match
            break
    high_match = None
    for match in re.finditer(r"\bif\s*\(\s*([A-Za-z_]\w*)\s*\)", source, re.I):
        if re.search(r"(?:^|_)(?:rst|reset|arst|nrst)(?:_|$)", match.group(1), re.I):
            high_match = match
            break
    if low_match is not None and high_match is not None:
        findings.append(_finding(source, lines, "reset-polarity-mixed", "warn", low_match.start(), "Module mixes active-low and active-high reset checks", "Use one reset polarity consistently and name the signal accordingly (rst_n vs rst)."))


def _numeric_findings(source: str, lines: list[str], findings: list[StaticFinding]) -> None:
    """位宽截断与未指定宽度的常量字面量。"""

    declared_width: dict[str, int] = {}
    for match in re.finditer(r"\b(?:reg|wire|logic)\s*(?:signed\s*)?\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*([A-Za-z_]\w*)", source, re.I):
        high, low = int(match.group(1)), int(match.group(2))
        if high >= low:
            declared_width[match.group(3)] = high - low + 1

    for name, width in declared_width.items():
        assignment = re.compile(rf"\b{re.escape(name)}\s*(?:<=|=)\s*(?:\d+\s*)?'([bBoOdDhH])([0-9a-fA-F_xXzZ]+)")
        for match in assignment.finditer(source):
            digits = match.group(2).replace("_", "")
            if any(ch in digits.lower() for ch in "xz"):
                continue
            try:
                base = {"b": 2, "o": 8, "d": 10, "h": 16}[match.group(1).lower()]
                value = int(digits, base)
            except ValueError:
                continue
            if value >= (1 << width):
                findings.append(_finding(
                    source, lines, "width-truncation", "warn", match.start(),
                    f"Constant does not fit in {width}-bit signal {name!r} and will be truncated",
                    "Size the literal explicitly and confirm the truncation is intended.",
                ))

    # 未指定宽度的常量：只在"写进已知宽度的信号"时才提示，且跳过 0/1 这类
    # 位宽无关的写法，避免对 `counter <= 0;` 这类完全正常的代码刷屏。
    for name, width in declared_width.items():
        for match in re.finditer(rf"\b{re.escape(name)}\s*(?:<=|=)\s*(?P<value>\d{{1,3}})\s*(?P<tail>[;,)]|$)", source):
            value = int(match.group("value"))
            if value in (0, 1):
                continue
            if width >= 32:
                continue
            findings.append(_finding(
                source, lines, "unsized-literal", "info", match.start("value"),
                f"Unsized decimal literal {value} assigned to {width}-bit signal {name!r}",
                f"Use a sized literal such as {width}'d{value} so the width is explicit.",
            ))


def rule_manifest() -> list[dict[str, str]]:
    """返回规则清单（id/严重级别/标题/来源），供报告与文档复用。"""

    return [
        {"rule_id": spec.rule_id, "severity": spec.severity, "title": spec.title, "source": spec.source}
        for spec in _RULE_REGISTRY
    ]


def review_rtl_source(source: str, *, filename: str = "rtl.v") -> dict[str, Any]:
    if not isinstance(source, str):
        raise TypeError("source must be text")
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    clean = _strip_comments(normalized)
    findings: list[StaticFinding] = []
    is_tb = _is_testbench(filename)

    # Delay constructs in synthesizable RTL are a common simulation/synthesis trap.
    # 测试平台里的 #delay 是正常写法（时钟与激励都需要），只在设计文件里报。
    if not is_tb:
        for match in re.finditer(r"#\s*\d", clean):
            findings.append(_finding(clean, lines, "synth-delay", "error", match.start(), "RTL contains a #delay construct", "Remove delays from synthesizable RTL; model timing in the testbench."))

    if not is_tb:
        for match in re.finditer(r"\binitial\s*(?:begin)?", clean, re.I):
            findings.append(_finding(clean, lines, "initial-block", "warn", match.start(), "Initial block may not synthesize consistently on the target FPGA", "Use reset-driven initialization; keep initial blocks in testbench files."))

    for match in re.finditer(r"\bcase\s*\([^)]*\)(?P<body>.*?)(?:\bendcase\b)", clean, re.I | re.S):
        body = match.group("body")
        if not re.search(r"\bdefault\s*:", body, re.I):
            findings.append(_finding(clean, lines, "missing-default-case", "warn", match.start(), "Case statement has no default branch", "Add a safe default assignment or recovery state."))
        elif not re.search(r"\bdefault\s*:[^;]*?[=;]", body, re.I) or re.search(r"\bdefault\s*:\s*(?:;|endcase)", body, re.I):
            findings.append(_finding(clean, lines, "incomplete-case-assignment", "warn", match.start(), "Default branch does not assign anything", "Assign the same signals in the default branch as in the explicit branches."))

    # Compact one-line always blocks are common in small examples and are not
    # captured reliably by the multiline block heuristic above.
    for match in re.finditer(r"\balways\s*@\s*\([^)]*\b(?:posedge|negedge)\b[^)]*\)[^\n;{}]*\b[A-Za-z_]\w*\s*=(?!=|>)", clean, re.I):
        line = _line_number(clean, match.start())
        if not any(item.rule_id == "blocking-in-sequential" and item.line == line for item in findings):
            findings.append(_finding(clean, lines, "blocking-in-sequential", "warn", match.start(), "Sequential always block contains blocking assignment", "Use non-blocking <= for registered state updates."))

    # Signals named as synchronizers should carry a placement hint in FPGA RTL.
    for match in re.finditer(r"\b(?:reg|logic)\s+[^;\n]*\b\w*sync\w*\b", clean, re.I):
        declaration_line = _line_number(clean, match.start())
        nearby = clean[max(0, match.start() - 180):match.start()]
        if "ASYNC_REG" not in nearby:
            findings.append(StaticFinding("missing-async-reg", "info", declaration_line, "Synchronizer-like register lacks ASYNC_REG attribute", "Add the vendor placement attribute when this register is part of a CDC synchronizer.", _snippet(lines, declaration_line)))

    if not is_tb:
        _lexical_findings(clean, lines, findings)
        _style_findings(clean, lines, findings)
        _arithmetic_findings(clean, lines, findings)
    _structural_findings(clean, lines, findings)
    if not is_tb:
        _interface_findings(clean, lines, findings, raw_source=normalized)
    _numeric_findings(clean, lines, findings)

    # 去重：同一规则同一行只保留一条，避免嵌套匹配刷屏；
    # 标记了 once_per_file 的规则（文件级提示）整个文件只保留一条。
    unique: dict[tuple[str, int], StaticFinding] = {}
    seen_once: set[str] = set()
    for item in findings:
        spec = RULE_REGISTRY.get(item.rule_id)
        if spec is not None and spec.once_per_file:
            if item.rule_id in seen_once:
                continue
            seen_once.add(item.rule_id)
        unique.setdefault((item.rule_id, item.line), item)
    findings = sorted(unique.values(), key=lambda item: (item.line, item.rule_id))

    counts = {level: sum(item.severity == level for item in findings) for level in ("error", "warn", "info")}
    score = max(0, 100 - sum(_SEVERITY_WEIGHT[item.severity] for item in findings))
    return {
        "schema_version": "1.0",
        "filename": Path(filename).name,
        "source_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "line_count": len(lines),
        "rule_count": len(_RULE_REGISTRY),
        "is_testbench": is_tb,
        "finding_count": len(findings),
        "counts": counts,
        "quality_score": score,
        "status": "error" if counts["error"] else ("warn" if counts["warn"] else "passed"),
        "findings": [item.to_dict() for item in findings],
        "rule_set": rule_manifest(),
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
        f"- 规则总数：{result.get('rule_count', 0)}",
        "",
        "> 静态规则审查不等同于综合、时序收敛或 FPGA 上板验证。", "",
        "## 问题统计", "",
        f"- error：{result.get('counts', {}).get('error', 0)}",
        f"- warn：{result.get('counts', {}).get('warn', 0)}",
        f"- info：{result.get('counts', {}).get('info', 0)}", "",
        "## 发现项", "",
        "| 级别 | 规则 | 行号 | 问题 | 建议 |", "|---|---|---:|---|---|",
    ]

    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    for item in result.get("findings", []):
        lines.append(f"| {cell(item['severity'])} | `{cell(item['rule_id'])}` | {item['line']} | {cell(item['message'])} | {cell(item['suggestion'])} |")
    if not result.get("findings"):
        lines.append("| - | - | - | 未发现规则问题 | - |")
    lines.extend(["", "## 证据片段", ""])
    for item in result.get("findings", []):
        lines.append(f"- 第 {item['line']} 行：`{item.get('snippet', '')}`")
    rule_set = result.get("rule_set")
    if rule_set:
        lines.extend(["", "## 本次启用的规则集", "", "| 规则 | 级别 | 说明 | 来源 |", "|---|---|---|---|"])
        for spec in rule_set:
            lines.append(f"| `{cell(spec['rule_id'])}` | {cell(spec['severity'])} | {cell(spec['title'])} | {cell(spec['source'])} |")
    return "\n".join(lines) + "\n"


__all__ = [
    "RULE_REGISTRY",
    "RuleSpec",
    "StaticFinding",
    "render_static_markdown",
    "review_rtl_file",
    "review_rtl_source",
    "rule_manifest",
]
