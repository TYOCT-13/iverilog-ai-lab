"""把一条失败记录翻成"下一步该看哪里"的白话，面向刚学 Verilog 的人。

为什么单独做这一层：结构化失败记录已经把事实说全了——检查项、第几拍、期望什么、实际什么
（见 `core/pipeline.py` 的 `explain_failure_record`）。但对第一次写 testbench 的人来说，
"第 12 周期检查 count 失败：期望 0000，实际 0001" 之后仍然不知道手该往哪放：是激励写错了？
是模块错了？该打开哪个文件、看哪一行？

本模块只补三件**可核验**的事，不多说一句：

1. **这次的差别是什么性质**——差 1 / 数值不同 / 出现了 x 或 z（不定值）；
2. **这个信号在 RTL 里被赋值的行**——直接给行号与那一行代码；
3. **怎么复现**——一条能重跑的命令。

**它不猜 bug 在哪一行。** 信号被赋值的位置不等于出错的位置（可能错在激励、在上游信号、
在复位、甚至在 testbench）。所以措辞一律是"先看这里"而不是"这里错了"——这一点必须守住，
否则这个功能就从"有帮助"变成"误导"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

__all__ = [
    "FailureGuide",
    "SourceLine",
    "build_failure_guide",
    "locate_signal",
    "render_failure_guides",
    "reproduce_command",
    "rtl_source_for",
]

#: 一行 RTL 里"谁被赋值"：`count <= count + 1;`、`assign y = a & b;`、`q = d;`
_ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]*\])?\s*(<=|=)(?!=)")
_DECLARE_RE = re.compile(
    r"\b(?:input|output|inout|wire|reg|logic)\b[^;]*\b([A-Za-z_][A-Za-z0-9_$]*)\s*(?:;|,)",
    re.I,
)
_UNDEFINED = set("xXzZ")


@dataclass(frozen=True)
class SourceLine:
    """RTL 里的一行，以及它和当前信号的关系。"""

    line: int
    code: str
    kind: str  # "drives"（给这个信号赋值）| "declares"（声明）

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "code": self.code, "kind": self.kind}


@dataclass(frozen=True)
class FailureGuide:
    """一条失败记录的白话解读。"""

    test_id: str
    cycle: int | None
    signal: str
    expected: Any
    actual: Any
    headline: str
    means: str
    look_at: tuple[SourceLine, ...] = ()
    next_steps: tuple[str, ...] = ()
    reproduce: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "cycle": self.cycle,
            "signal": self.signal,
            "expected": self.expected,
            "actual": self.actual,
            "headline": self.headline,
            "means": self.means,
            "look_at": [item.to_dict() for item in self.look_at],
            "next_steps": list(self.next_steps),
            "reproduce": self.reproduce,
        }

    def to_markdown(self) -> str:
        lines = [f"- **{self.headline}**", f"  - {self.means}"]
        if self.look_at:
            lines.append("  - 先看这些行（**是「被赋值的位置」，不一定是「出错的位置」**）：")
            for item in self.look_at:
                lines.append(f"    - `第 {item.line} 行`：`{item.code}`")
        for step in self.next_steps:
            lines.append(f"    - {step}")
        if self.reproduce:
            lines.append(f"  - 复现：`{self.reproduce}`")
        return "\n".join(lines)


def locate_signal(source: str, signal: str, *, limit: int = 6) -> tuple[SourceLine, ...]:
    """找出 `signal` 在 RTL 里被赋值（以及被声明）的行，按行号排序。

    只做词法匹配，不做语法分析：目标是"给人一个起点"，不是"给工具一个结论"。
    """

    if not signal or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*(?:\s*\[[^\]]*\])?", signal):
        return ()
    name = signal.split("[")[0].strip()
    hits: list[SourceLine] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        code = raw.strip()
        if not code or code.startswith("//"):
            continue
        if any(match.group(1) == name for match in _ASSIGN_RE.finditer(code)):
            hits.append(SourceLine(number, code, "drives"))
        elif name in code and _DECLARE_RE.search(code):
            hits.append(SourceLine(number, code, "declares"))
        if len(hits) >= limit:
            break
    # 赋值行比声明行更值得先看
    hits.sort(key=lambda item: (item.kind != "drives", item.line))
    return tuple(hits[:limit])


def _bit_string(text: Any) -> str | None:
    """把 ``<0001>`` / ``0001`` / ``4'b0001`` 归一成纯 0/1/x/z 串，失败返回 None。"""

    if text is None:
        return None
    raw = str(text).strip().strip("<>")
    raw = re.sub(r"^\d*'[bBdDhHoO]", "", raw)
    return raw if raw and re.fullmatch(r"[01xXzZ]+", raw) else None


def _describe_difference(expected: Any, actual: Any) -> tuple[str, str]:
    """返回（差别性质, 白话说明）。只用能确证的事实，不做因果推断。"""

    if actual is None:
        return "没有实际值", "这条检查记录里没有实际值，说明它可能不是靠比对得出的结果——先确认这条向量是不是真的带了期望值。"

    left, right = _bit_string(expected), _bit_string(actual)
    if right and set(right) & _UNDEFINED:
        return (
            "出现不定值",
            f"实际值是 `{actual}`，含 `x`/`z`：仿真时这个信号**没有被确定地驱动**"
            "（常见原因：忘了在某个分支里赋值、复位没接上、或者被多个 always 块同时驱动）。"
            "这通常不是「算错了」，而是「没算」。",
        )
    if left and right:
        if len(left) != len(right):
            return "位宽不一致", f"期望 `{expected}`（{len(left)} 位），实际 `{actual}`（{len(right)} 位）——先确认位宽与拼接表达式。"
        if left != right:
            diff = sum(1 for a, b in zip(left, right) if a != b)
            try:
                delta = int(right, 2) - int(left, 2)
            except ValueError:
                delta = None
            if delta is not None and abs(delta) == 1:
                direction = "大" if delta > 0 else "小"
                return (
                    "差 1",
                    f"实际比期望{direction} 1（`{expected}` → `{actual}`）。差 1 的问题多半出在边界上："
                    "回绕点、加减 1、比较用 `>` 还是 `>=`。",
                )
            return "取值不同", f"期望 `{expected}`，实际 `{actual}`，有 {diff} 位不同。"
    return "取值不同", f"期望 `{expected}`，实际 `{actual}`。"


def _plain(value: Any) -> str:
    """显示用：去掉结构化记录里的尖括号包装（`<0001>` → `0001`）。"""

    return "—" if value is None else str(value).strip().strip("<>")


def build_failure_guide(
    failure: Any,
    *,
    source: str | None = None,
    reproduce: str = "",
) -> FailureGuide:
    """把一条 `FailureRecord` 变成面向人的解读。

    ``source`` 给了就顺带指出该信号在 RTL 里被赋值的行；不给也不影响其它部分。
    ``reproduce`` 是一条能重跑这次仿真的命令（由调用方按需构造）。
    """

    test_id = str(getattr(failure, "test_id", None) or "未命名检查")
    cycle = getattr(failure, "cycle", None)
    signal = str(getattr(failure, "signal", "") or "")
    expected = getattr(failure, "expected", None)
    actual = getattr(failure, "actual", None)

    when = "未知时刻" if cycle is None else f"第 {cycle} 拍"
    headline = f"{test_id} 在{when}检查 {signal or '整条记录'}：期望 {_plain(expected)}，实际 {_plain(actual)}"
    kind, means = _describe_difference(expected, actual)

    look_at = locate_signal(source, signal) if source and signal else ()

    steps: list[str] = []
    if not signal:
        steps.append("这条记录没有信号名，说明它是整条向量的结果——先确认这条向量是否真的写了 `expected`。")
    elif look_at:
        steps.append("对着上面的行，检查这三个常见原因：① 某个 `if/else` 分支漏了赋值；② 复位那一路没覆盖到；③ 位宽或常量写错（`9` vs `4'd9`）。")
    else:
        steps.append("没在给定 RTL 里找到这个信号的赋值处——确认你给的是**被测模块**的源码，而不是 testbench。")
    steps.append(f"差别性质：**{kind}**。先判断它是「算错了」还是「没算」（后者看不定值与位宽）。")
    steps.append("改完之后跑一次同样的命令，看这一条是否消失——**不要**只看总体状态，缺陷检出时总体状态本来就是有告警的。")

    return FailureGuide(
        test_id=test_id,
        cycle=cycle,
        signal=signal,
        expected=expected,
        actual=actual,
        headline=headline,
        means=means,
        look_at=look_at,
        next_steps=tuple(steps),
        reproduce=reproduce,
    )


def rtl_source_for(result: Any) -> str | None:
    """从一次仿真结果里取出被测 RTL 的源码（取不到就返回 None，不猜）。

    执行器会把 `rtl_path` 写进 `result.config`，所以默认路径不需要用户再传一次；
    读不到文件（换机器、路径失效）时返回 None，调用方退化成"不指行号"。
    """

    config = getattr(result, "config", None)
    if not isinstance(config, dict):
        return None
    path = config.get("rtl_path")
    if not path:
        return None
    candidate = Path(str(path))
    try:
        return candidate.read_text(encoding="utf-8") if candidate.is_file() else None
    except OSError:
        return None


def reproduce_command(result: Any, *, product: str = "iverilog-ai") -> str:
    """从一次仿真结果拼出能重跑它的命令（缺字段就返回空串，不编）。"""

    config = getattr(result, "config", None)
    if not isinstance(config, dict):
        return ""
    rtl, tb, top = config.get("rtl_path"), config.get("testbench_path"), config.get("top_module")
    if not (rtl and tb and top):
        return ""
    return f'{product} run --rtl "{rtl}" --testbench "{tb}" --top {top}'


def render_failure_guides(
    result: Any,
    *,
    source: str | None = None,
    limit: int = 5,
) -> tuple[str, ...]:
    """对一次仿真结果里的失败逐条生成 Markdown 白话解读。

    默认从 ``result.config['rtl_path']`` 读 RTL 源码（执行器写入了这个字段）；
    读不到就退化成"只讲差别性质、不指行号"，不会因此报错。
    """

    failures: Sequence[Any] = tuple(getattr(result, "failures", ()) or ())
    if not failures:
        return ()
    text = source if source is not None else rtl_source_for(result)
    command = reproduce_command(result)
    guides = [
        build_failure_guide(item, source=text, reproduce=command).to_markdown()
        for item in failures[:limit]
    ]
    if len(failures) > limit:
        guides.append(f"- 另有 {len(failures) - limit} 条同类失败，已省略（用 `--json` 看全部）。")
    return tuple(guides)
