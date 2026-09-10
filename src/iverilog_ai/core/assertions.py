"""受控的结构化即时断言模板。

断言是数据对象，不是 Verilog/SVA 代码。调用方可将其交给受控 testbench
适配器，或使用 :func:`evaluate_assertion` 在 Python 中检查采样结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping
import re

_SIGNAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_KINDS = frozenset(("signal_equals", "signal_stable", "never_high", "signal_sequence", "signal_implies"))


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
    if kind == "signal_equals": allowed = {"kind", "signal", "value"}
    elif kind == "signal_sequence": allowed = {"kind", "signal", "values", "cycles"}
    elif kind == "signal_implies": allowed = {"kind", "when_signal", "when_value", "then_signal", "then_value", "within_cycles"}
    else: allowed = {"kind", "signal", "cycles"}
    unknown = sorted(set(description) - allowed)
    if unknown:
        raise AssertionValidationError("unsupported assertion field(s): " + ", ".join(unknown))
    signal = description.get("signal")
    if kind != "signal_implies" and (not isinstance(signal, str) or not _SIGNAL_RE.fullmatch(signal)):
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
    if kind == "signal_implies":
        names = (description.get("when_signal"), description.get("then_signal"))
        if any(not isinstance(v, str) or not _SIGNAL_RE.fullmatch(v) for v in names):
            raise AssertionValidationError("signal_implies signal names must be safe identifiers")
        within = description.get("within_cycles", 1)
        if isinstance(within, bool) or not isinstance(within, int) or not 1 <= within <= 10000:
            raise AssertionValidationError("within_cycles must be in [1, 10000]")
        return StructuredAssertion(kind, names[0], when_signal=names[0], when_value=_scalar(description.get("when_value")), then_signal=names[1], then_value=_scalar(description.get("then_value")), within_cycles=within)
    cycles = description.get("cycles", 1)
    if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 10000:
        raise AssertionValidationError("assertion.cycles must be an integer in [1, 10000]")
    return StructuredAssertion(kind, signal, cycles=cycles)


create_assertion = build_assertion


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
        bad = next((v for v in values if v != a.value), None)
        ok = all(v == a.value for v in values)
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), bad if not ok else a.value,
                                    "signal equals expected value" if ok else f"expected {a.value!r}, observed {bad!r}")
    if a.kind == "never_high":
        bad = next((v for v in values if v is True or v == 1), None)
        ok = bad is None
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), bad, "signal never high" if ok else "signal became high")
    if a.kind == "signal_sequence":
        ok = values == list(a.values)
        return AssertionCheckResult(ok, a.kind, a.signal, len(values), values, "signal sequence matched" if ok else f"expected sequence {list(a.values)!r}, observed {values!r}")
    if a.kind == "signal_implies":
        missing = [s for s in (a.when_signal, a.then_signal) if any(s not in row for row in rows)]
        if missing:
            return AssertionCheckResult(False, a.kind, a.when_signal, len(rows), message=f"signal(s) missing from sample: {', '.join(missing)}")
        for index, row in enumerate(rows):
            if row.get(a.when_signal) == a.when_value:
                window = rows[index + 1:index + 1 + a.within_cycles]
                if not any(item.get(a.then_signal) == a.then_value for item in window):
                    return AssertionCheckResult(False, a.kind, a.when_signal, len(rows), row.get(a.then_signal), f"{a.when_signal}={a.when_value!r} was not followed by {a.then_signal}={a.then_value!r}")
        return AssertionCheckResult(True, a.kind, a.when_signal, len(rows), message="implication satisfied")
    # signal_stable: every contiguous window of the requested length is constant.
    ok = len(values) < a.cycles or all(len(set(values[i:i + a.cycles])) == 1 for i in range(len(values) - a.cycles + 1))
    observed = values[-1] if values else None
    return AssertionCheckResult(ok, a.kind, a.signal, len(values), observed,
                                "signal remained stable" if ok else f"signal changed within {a.cycles} samples")


__all__ = ["AssertionValidationError", "StructuredAssertion", "AssertionCheckResult", "build_assertion", "create_assertion", "evaluate_assertion"]
