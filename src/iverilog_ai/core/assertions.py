"""受控的结构化即时断言模板。

断言是数据对象，不是 Verilog/SVA 代码。调用方可将其交给受控 testbench
适配器，或使用 :func:`evaluate_assertion` 在 Python 中检查采样结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping
import re

from ..ai.schema import ASSERTION_FIELDS, ASSERTION_KINDS

_SIGNAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
#: 模板与字段表都取自 `ai.schema`（唯一事实来源）：这里的执行期校验、那边的严格 Schema
#: 校验、以及发给模型的提示词三者共用一张表，不会再出现"提示词允许、校验器拒绝"的漂移。
_KINDS = ASSERTION_KINDS


class AssertionValidationError(ValueError):
    """断言描述不符合受控模板时抛出。"""


@dataclass(frozen=True)
class StructuredAssertion:
    kind: str
    signal: str
    value: Any = None
    cycles: int = 1
    values: tuple[Any, ...] = ()
    when_signal: str = ""
    when_value: Any = None
    then_signal: str = ""
    then_value: Any = None
    within_cycles: int = 1

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "signal": self.signal}
        if self.kind == "signal_equals":
            result["value"] = self.value
        elif self.kind == "signal_sequence":
            result["values"] = list(self.values)
            result["cycles"] = self.cycles
        elif self.kind == "signal_implies":
            result.update({"when_signal": self.when_signal, "when_value": self.when_value, "then_signal": self.then_signal, "then_value": self.then_value, "within_cycles": self.within_cycles})
        else:
            result["cycles"] = self.cycles
        return result


@dataclass(frozen=True)
class AssertionCheckResult:
    passed: bool
    kind: str
    signal: str
    checked_samples: int
    observed: Any = None
    message: str = ""


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and (len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise AssertionValidationError("assertion value must be printable and at most 200 characters")
        return value
    raise AssertionValidationError("assertion value must be a JSON scalar")


def build_assertion(description: Mapping[str, Any] | StructuredAssertion) -> StructuredAssertion:
    """解析并严格校验一个模板描述；未知字段和任意代码均被拒绝。"""
    if isinstance(description, StructuredAssertion):
        return description
    if not isinstance(description, Mapping):
        raise AssertionValidationError("assertion must be an object")
    kind = description.get("kind")
    if kind not in _KINDS:
        raise AssertionValidationError(f"unsupported assertion template: {kind!r}")
    if kind == "signal_implies": allowed = set(ASSERTION_FIELDS["signal_implies"])
    else: allowed = set(ASSERTION_FIELDS[str(kind)])
    unknown = sorted(set(description) - allowed)
    if unknown:
        raise AssertionValidationError("unsupported assertion field(s): " + ", ".join(unknown))
    # 先处理 signal_implies（它没有单一 `signal` 字段，只有 when/then 两个名字），
    # 这样后面的模板都能拿到一个已经校验过的 str 型信号名——把校验写成
    # `kind != ... and (...)` 的复合条件时，静态检查无法收窄类型。
    if kind == "signal_implies":
        when_name = description.get("when_signal")
        then_name = description.get("then_signal")
        if (
            not isinstance(when_name, str)
            or not _SIGNAL_RE.fullmatch(when_name)
            or not isinstance(then_name, str)
            or not _SIGNAL_RE.fullmatch(then_name)
        ):
            raise AssertionValidationError("signal_implies signal names must be safe identifiers")
        within = description.get("within_cycles", 1)
        if isinstance(within, bool) or not isinstance(within, int) or not 1 <= within <= 10000:
            raise AssertionValidationError("within_cycles must be in [1, 10000]")
        return StructuredAssertion(
            kind,
            when_name,
            when_signal=when_name,
            when_value=_scalar(description.get("when_value")),
            then_signal=then_name,
            then_value=_scalar(description.get("then_value")),
            within_cycles=within,
        )
    signal = description.get("signal")
    if not isinstance(signal, str) or not _SIGNAL_RE.fullmatch(signal):
        raise AssertionValidationError("assertion.signal must be a safe Verilog identifier")
    if kind == "signal_equals":
        if "value" not in description:
            raise AssertionValidationError("signal_equals requires value")
        return StructuredAssertion(kind, signal, _scalar(description["value"]))
    if kind == "signal_sequence":
        values = description.get("values")
        if not isinstance(values, list) or not values or len(values) > 100 or any(not isinstance(v, (bool, int, str)) for v in values):
            raise AssertionValidationError("signal_sequence.values must be a non-empty scalar array")
        cycles = description.get("cycles", len(values))
        if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles != len(values):
            raise AssertionValidationError("signal_sequence.cycles must equal values length")
        return StructuredAssertion(kind, signal, cycles=cycles, values=tuple(_scalar(v) for v in values))
    cycles = description.get("cycles", 1)
    if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 10000:
        raise AssertionValidationError("assertion.cycles must be an integer in [1, 10000]")
    return StructuredAssertion(kind, signal, cycles=cycles)


create_assertion = build_assertion


def _comparable(value: Any) -> Any:
    """把采样值与断言值折算到同一形态再比较。

    采样记录里的多比特信号是 **Verilog 位串**（``'0000'``、``'1010'``），而断言里的
    ``value`` 通常写成整数（``0``、``5``）。直接 ``'0000' == 0`` 永远为假，于是**参考设计上
    也会报假失败**——我们自己的推荐断言就踩了这个坑：``mod10_counter`` 的
    ``signal_equals{count: 0}`` 在参考设计上被判成 `expected 0, observed '0000'`。
    这里按"只含 0/1/x/z 的字符串视为二进制位串"折算：含 x/z 的保持文本（不定值只与同形相等），
    其余原样返回。bool 折算成 0/1，与 Verilog 一致。
    """

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text and all(char in "01xz" for char in text):
            if "x" in text or "z" in text:
                return text
            return int(text, 2)
    return value


def evaluate_assertion(assertion: Mapping[str, Any] | StructuredAssertion,
                       samples: Iterable[Mapping[str, Any]]) -> AssertionCheckResult:
    """对采样数据执行模板检查，返回可序列化的结果，不执行代码生成。"""
    a = build_assertion(assertion)
    rows = list(samples)
    if not rows:
        return AssertionCheckResult(False, a.kind, a.signal, 0, message=f"signal {a.signal!r} has no observable samples")
    values = [row.get(a.signal) if isinstance(row, Mapping) else None for row in rows]
    if any(not isinstance(row, Mapping) or a.signal not in row for row in rows):
        return AssertionCheckResult(False, a.kind, a.signal, len(rows), message=f"signal {a.signal!r} missing from sample")
    if a.kind == "signal_equals":
        expected = _comparable(a.value)
        bad = next((v for v in values if _comparable(v) != expected), None)
        ok = bad is None
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), bad if not ok else a.value,
                                    "signal equals expected value" if ok else f"expected {a.value!r}, observed {bad!r}")
    if a.kind == "never_high":
        bad = next((v for v in values if _comparable(v) == 1), None)
        ok = bad is None
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), bad, "signal never high" if ok else "signal became high")
    if a.kind == "signal_sequence":
        expected_sequence = [_comparable(v) for v in a.values]
        observed_sequence = [_comparable(v) for v in values]
        ok = observed_sequence == expected_sequence
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), values, "signal sequence matched" if ok else f"expected sequence {list(a.values)!r}, observed {values!r}")
    if a.kind == "signal_implies":
        missing = [s for s in (a.when_signal, a.then_signal) if any(s not in row for row in rows)]
        if missing:
            return AssertionCheckResult(False, a.kind, a.when_signal, len(rows), message=f"signal(s) missing from sample: {', '.join(missing)}")
        when_value = _comparable(a.when_value)
        then_value = _comparable(a.then_value)
        for index, row in enumerate(rows):
            if _comparable(row.get(a.when_signal)) == when_value:
                window = rows[index + 1:index + 1 + a.within_cycles]
                if not any(_comparable(item.get(a.then_signal)) == then_value for item in window):
                    return AssertionCheckResult(False, a.kind, a.when_signal, len(rows), row.get(a.then_signal), f"{a.when_signal}={a.when_value!r} was not followed by {a.then_signal}={a.then_value!r}")
        return AssertionCheckResult(True, a.kind, a.when_signal, len(rows), message="implication satisfied")
    # signal_stable: every contiguous window of the requested length is constant.
    # cycles=1 表示"每个采样点自身恒定"，恒为真——这是**空检查**，提示词与手册里都提醒过。
    ok = len(values) < a.cycles or all(len(set(values[i:i + a.cycles])) == 1 for i in range(len(values) - a.cycles + 1))
    observed = values[-1] if values else None
    if ok and a.cycles <= 1:
        return AssertionCheckResult(True, a.kind, a.signal, len(values), observed,
                                    "signal remained stable（cycles=1 恒真，等于没有检查）")
    return AssertionCheckResult(ok, a.kind, a.signal, len(values), observed,
                                "signal remained stable" if ok else f"signal changed within {a.cycles} samples")


__all__ = ["AssertionValidationError", "StructuredAssertion", "AssertionCheckResult", "build_assertion", "create_assertion", "evaluate_assertion"]
