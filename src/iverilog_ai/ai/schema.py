"""严格、版本化的 AI 测试计划交换格式。

该模型是生成器的第一道边界：未知字段、危险信号名、控制字符和非 JSON
标量会在进入 Verilog 生成阶段前被拒绝。模型输出永远只是数据，不能携带
命令或任意 HDL。
"""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SIGNAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_PATH_OR_COMMAND_CHARS = set("\\/:*?\"<>|;&$(){}[]") | {chr(96)}

#: 受控断言模板 → 该模板允许出现的字段（**唯一事实来源**）。
#:
#: 三处必须永远一致：本文件的严格校验、`core.assertions` 的执行期校验、
#: 以及 `ai.planner` 发给模型的提示词。提示词直接由这张表渲染，所以不可能再出现
#: "提示词写着一套、校验器接受另一套"：
#: 真实事故——提示词写成 `signal_implies{kind,signal,when_signal,then_signal}`，
#: 而校验器不接受 `signal`（implication 只有 when/then 两个信号名）。模型严格照提示词
#: 写，却被我们自己的严格校验拒绝，用户看到一句 `assertions[0] contains unsupported
#: field(s): signal`，一次付费请求也白花了。
ASSERTION_FIELDS: dict[str, tuple[str, ...]] = {
    "signal_equals": ("kind", "signal", "value"),
    "signal_stable": ("kind", "signal", "cycles"),
    "never_high": ("kind", "signal"),
    "signal_sequence": ("kind", "signal", "values", "cycles"),
    "signal_implies": ("kind", "when_signal", "when_value", "then_signal", "then_value", "within_cycles"),
}

#: 允许的模板名集合（供校验与提示词共用）。
ASSERTION_KINDS: frozenset[str] = frozenset(ASSERTION_FIELDS)


def _printable(value: Any, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} must be printable and at most {max_length} characters")
    return value


def _scalar(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str):
            _printable(value, name, max_length=200)
        return value
    if isinstance(value, float) and math.isfinite(value):
        raise ValueError(f"{name} must be a boolean, integer, or string")
    raise ValueError(f"{name} must be a JSON scalar")


def _signal_map(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    result: dict[str, Any] = {}
    for signal, item in value.items():
        if not isinstance(signal, str) or not _SIGNAL_RE.fullmatch(signal):
            raise ValueError(f"{name} contains an unsafe signal name: {signal!r}")
        result[signal] = _scalar(item, f"{name}.{signal}")
    return result


class TestVector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    inputs: dict[str, int | bool | str] = Field(default_factory=dict)
    cycles: int = Field(default=1, ge=1, le=1000)
    sample_phase: Literal["before", "after"] = "after"
    expected: dict[str, int | bool | str] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        return _printable(value, "vector.name", max_length=80)

    @field_validator("inputs", "expected", mode="before")
    @classmethod
    def safe_signal_values(cls, value: Any, info) -> dict[str, Any]:
        return _signal_map(value, f"vector.{info.field_name}")

    @field_validator("rationale")
    @classmethod
    def safe_rationale(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("vector.rationale must be a string")
        if len(value) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("vector.rationale must be printable and at most 500 characters")
        return value


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 告诉 pytest "这不是测试类"：类名以 Test 开头，测试模块 import 它时代码里
    # 就会冒出 PytestCollectionWarning（`cannot collect test class 'TestPlan'`）。
    # 这类噪声会让"测试输出全绿"看起来不干净，也让真正的告警被埋掉。
    __test__: ClassVar[bool] = False
    schema_version: Literal["1.0"] = "1.0"
    design: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1000)
    clock_period_ns: int = Field(default=10, ge=1, le=10000)
    reset: dict[str, bool | int | str] = Field(default_factory=dict)
    # 复位前观测：为真时，testbench 在任何复位和激励之前先采样一次输出。
    # 这是唯一能看到"上电初值"的时刻；初值本身不符合规格的缺陷只有在这里
    # 才会暴露。期望值来自 contract 中端口声明的 initial，不由模型推断。
    sample_before_reset: bool = False
    pre_reset_expected: dict[str, int | bool | str] = Field(default_factory=dict)
    vectors: list[TestVector] = Field(min_length=1, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    # Optional controlled assertions. These are data templates only; arbitrary
    # Verilog/SVA text is rejected and never reaches the testbench generator.
    assertions: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_vector_names(self) -> "TestPlan":
        names = [vector.name for vector in self.vectors]
        if len(names) != len(set(names)):
            raise ValueError("vectors must have unique names")
        return self

    @field_validator("pre_reset_expected", mode="before")
    @classmethod
    def safe_pre_reset_expected(cls, value: Any) -> dict[str, Any]:
        return _signal_map(value, "plan.pre_reset_expected")

    @field_validator("design")
    @classmethod
    def safe_design_name(cls, value: str) -> str:
        value = _printable(value, "design", max_length=120)
        if any(ch in value for ch in _PATH_OR_COMMAND_CHARS):
            raise ValueError("design must be a logical name, not a path or command")
        return value

    @field_validator("objective")
    @classmethod
    def safe_objective(cls, value: str) -> str:
        return _printable(value, "objective", max_length=1000)

    @field_validator("clock_period_ns", mode="before")
    @classmethod
    def strict_period(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("clock_period_ns must be an integer")
        return value

    @field_validator("reset", mode="before")
    @classmethod
    def safe_reset(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("reset must be an object")
        allowed = {"signal", "active_level", "active_low", "synchronous", "assert_cycles"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError("reset contains unsupported field(s): " + ", ".join(unknown))
        if "active_level" in value and "active_low" in value:
            raise ValueError("reset cannot contain both active_level and active_low")
        for key, item in value.items():
            if key == "signal":
                if not isinstance(item, str) or not _SIGNAL_RE.fullmatch(item):
                    raise ValueError("reset.signal must be a safe Verilog identifier")
            elif key in {"active_level", "assert_cycles"}:
                if isinstance(item, bool) or not isinstance(item, int):
                    raise ValueError(f"reset.{key} must be an integer")
            elif key in {"active_low", "synchronous"} and not isinstance(item, bool):
                raise ValueError(f"reset.{key} must be a boolean")
            else:
                _scalar(item, f"reset.{key}")
        return value

    @field_validator("assumptions", mode="before")
    @classmethod
    def safe_assumptions(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("assumptions must be an array")
        if len(value) > 30:
            raise ValueError("assumptions must contain at most 30 items")
        result = []
        for index, item in enumerate(value):
            result.append(_printable(item, f"assumptions[{index}]", max_length=500))
        return result

    @field_validator("assertions", mode="before")
    @classmethod
    def safe_assertions(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or len(value) > 50:
            raise ValueError("assertions must be an array with at most 50 items")
        signal_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
        checked = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"assertions[{index}] must be an object")
            kind = item.get("kind")
            if kind not in ASSERTION_KINDS:
                raise ValueError(f"assertions[{index}] uses unsupported template")
            # 字段表来自 ASSERTION_FIELDS（唯一事实来源），不再各写一份字面量。
            fields = ASSERTION_FIELDS[str(kind)]
            unknown = set(item) - set(fields)
            if unknown:
                raise ValueError(f"assertions[{index}] contains unsupported field(s): {', '.join(sorted(unknown))}")
            # `signal` 标识符检查**只对真的带 signal 字段的模板做**。
            # 这里曾经无条件检查 `item["signal"]`，于是 signal_implies 陷入死局：
            # 写了 signal → 上面报"不支持的字段"；不写 signal → 这里报"signal 必须是
            # 合法标识符"（`None` 不是 str）。两条路都被堵死 = 该模板根本无法通过校验，
            # 而它同时出现在提示词、使用手册与 core.assertions 的执行路径里。
            # （`core.assertions.build_assertion` 早就把 signal_implies 提前分支处理了，
            # 两个校验器因此还互相矛盾——这正是 r10 实验里 5 次计划失败的真正原因。）
            if "signal" in fields:
                if not isinstance(item.get("signal"), str) or not signal_re.fullmatch(str(item["signal"])):
                    raise ValueError(f"assertions[{index}].signal must be a safe Verilog identifier")
            if kind == "signal_equals":
                if "value" not in item or not isinstance(item["value"], (bool, int, str)):
                    raise ValueError(f"assertions[{index}] signal_equals requires a scalar value")
            elif kind == "signal_sequence":
                values = item.get("values")
                if not isinstance(values, list) or not values or len(values) > 100 or any(not isinstance(v, (bool, int, str)) for v in values):
                    raise ValueError(f"assertions[{index}].values must be a non-empty scalar array")
                if item.get("cycles", len(values)) != len(values):
                    raise ValueError(f"assertions[{index}].cycles must equal values length")
            elif kind == "signal_implies":
                if any(not isinstance(item.get(k), str) or not signal_re.fullmatch(item[k]) for k in ("when_signal", "then_signal")):
                    raise ValueError(f"assertions[{index}] signal names must be safe identifiers")
                within = item.get("within_cycles", 1)
                if isinstance(within, bool) or not isinstance(within, int) or not 1 <= within <= 10000:
                    raise ValueError(f"assertions[{index}].within_cycles must be in [1, 10000]")
            else:
                cycles = item.get("cycles", 1)
                if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 10000:
                    raise ValueError(f"assertions[{index}].cycles must be in [1, 10000]")
            checked.append(dict(item))
        return checked


def json_schema() -> dict:
    return TestPlan.model_json_schema()
