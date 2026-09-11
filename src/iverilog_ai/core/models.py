"""无第三方依赖的核心数据模型。

模型层故意只接受 JSON 可表示的数据，并在进入仿真器前限制数量、标识符和
数值范围。这样即便测试计划来自模型，也不会因为一个格式错误的响应而把
任意参数直接拼进仿真命令。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
import re
from typing import Any, Mapping, Sequence


class ModelValidationError(ValueError):
    """输入 JSON 不符合公开模型合约。"""

    def __init__(self, message: str, errors: Sequence[str] | None = None) -> None:
        self.errors = tuple(errors or (message,))
        super().__init__(message)


class ProcessStatus(str, Enum):
    """单个外部进程的状态。"""

    NOT_RUN = "not_run"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class ResultStatus(str, Enum):
    """一次完整仿真的结论。"""

    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    COMPILE_FAILED = "compile_failed"
    TIMEOUT = "timeout"
    INCONCLUSIVE = "inconclusive"
    CONFIGURATION_ERROR = "configuration_error"


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SIGNAL_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*(?:\[(?:[0-9]+|[0-9]+:[0-9]+)\])?$"
)
_MISSING = object()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str, *, non_empty: bool = True) -> str:
    if not isinstance(value, str) or (non_empty and not value.strip()):
        raise ModelValidationError(f"{name} must be a non-empty string")
    return value.strip() if non_empty else value


def _identifier(value: Any, name: str) -> str:
    value = _require_string(value, name)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ModelValidationError(f"{name} is not a safe Verilog identifier: {value!r}")
    return value


def _label(value: Any, name: str, *, max_length: int = 120) -> str:
    """Validate a human-facing case/test label without making it a command token."""

    value = _require_string(value, name)
    if len(value) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ModelValidationError(f"{name} must be printable and at most {max_length} characters")
    return value


def _signal_name(value: Any, name: str) -> str:
    value = _require_string(value, name)
    if not _SIGNAL_RE.fullmatch(value):
        raise ModelValidationError(f"{name} is not a safe signal name: {value!r}")
    return value


def _json_value(value: Any, name: str) -> Any:
    """Validate a JSON value while rejecting non-finite floating point values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ModelValidationError(f"{name} must not contain NaN or infinity")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ModelValidationError(f"{name} object keys must be strings")
            normalized[key] = _json_value(item, f"{name}.{key}")
        return normalized
    raise ModelValidationError(f"{name} is not JSON serializable")


def _signal_values(value: Any, name: str) -> dict[str, Any]:
    mapping = _require_mapping(value, name)
    result: dict[str, Any] = {}
    for key, item in mapping.items():
        signal = _signal_name(key, f"{name} key")
        if signal in result:
            raise ModelValidationError(f"{name} contains duplicate signal {signal!r}")
        result[signal] = _json_value(item, f"{name}.{signal}")
    return result


def _check_keys(data: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ModelValidationError(f"{name} contains unsupported field(s): {', '.join(unknown)}")


@dataclass(frozen=True)
class ClockSpec:
    """测试平台时钟定义。"""

    signal: str
    period_ns: float = 10.0
    duty_cycle: float = 0.5

    @classmethod
    def from_dict(cls, value: Any) -> "ClockSpec":
        if isinstance(value, str):
            return cls(signal=_signal_name(value, "clock.signal"))
        data = _require_mapping(value, "clock")
        _check_keys(data, {"signal", "name", "period_ns", "period", "duty_cycle"}, "clock")
        signal = data.get("signal", data.get("name", _MISSING))
        if signal is _MISSING:
            raise ModelValidationError("clock.signal is required")
        period = data.get("period_ns", data.get("period", 10.0))
        if isinstance(period, bool) or not isinstance(period, (int, float)):
            raise ModelValidationError("clock.period_ns must be a number")
        period = float(period)
        if not math.isfinite(period) or period <= 0 or period > 1_000_000:
            raise ModelValidationError("clock.period_ns must be in (0, 1000000]")
        duty = data.get("duty_cycle", 0.5)
        if isinstance(duty, bool) or not isinstance(duty, (int, float)):
            raise ModelValidationError("clock.duty_cycle must be a number")
        duty = float(duty)
        if not math.isfinite(duty) or duty <= 0 or duty >= 1:
            raise ModelValidationError("clock.duty_cycle must be strictly between 0 and 1")
        return cls(signal=_signal_name(signal, "clock.signal"), period_ns=period, duty_cycle=duty)

    def to_dict(self) -> dict[str, Any]:
        return {"signal": self.signal, "period_ns": self.period_ns, "duty_cycle": self.duty_cycle}


@dataclass(frozen=True)
class ResetSpec:
    """测试平台复位定义。"""

    signal: str
    active_level: int = 0
    synchronous: bool = False
    assert_cycles: int = 2

    @classmethod
    def from_dict(cls, value: Any) -> "ResetSpec":
        if isinstance(value, str):
            return cls(signal=_signal_name(value, "reset.signal"))
        data = _require_mapping(value, "reset")
        _check_keys(
            data,
            {"signal", "name", "active_level", "active", "synchronous", "assert_cycles"},
            "reset",
        )
        signal = data.get("signal", data.get("name", _MISSING))
        if signal is _MISSING:
            raise ModelValidationError("reset.signal is required")
        active = data.get("active_level", data.get("active", 0))
        if isinstance(active, bool) or active not in (0, 1):
            raise ModelValidationError("reset.active_level must be 0 or 1")
        synchronous = data.get("synchronous", False)
        if not isinstance(synchronous, bool):
            raise ModelValidationError("reset.synchronous must be a boolean")
        cycles = data.get("assert_cycles", 2)
        if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 10_000:
            raise ModelValidationError("reset.assert_cycles must be an integer in [1, 10000]")
        return cls(
            signal=_signal_name(signal, "reset.signal"),
            active_level=int(active),
            synchronous=synchronous,
            assert_cycles=cycles,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "active_level": self.active_level,
            "synchronous": self.synchronous,
            "assert_cycles": self.assert_cycles,
        }


@dataclass(frozen=True)
class TestStep:
    """一个时钟周期的输入驱动及可选断言。"""

    cycle: int
    inputs: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    hold_cycles: int = 1

    @classmethod
    def from_dict(cls, value: Any, *, default_cycle: int = 0) -> "TestStep":
        data = _require_mapping(value, "test step")
        _check_keys(
            data,
            {
                "cycle",
                "at_cycle",
                "inputs",
                "drive",
                "expected",
                "checks",
                "note",
                "hold_cycles",
                "duration",
            },
            "test step",
        )
        if "cycle" in data and "at_cycle" in data:
            raise ModelValidationError("test step cannot contain both cycle and at_cycle")
        cycle = data.get("cycle", data.get("at_cycle", default_cycle))
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0 or cycle > 10_000_000:
            raise ModelValidationError("test step.cycle must be an integer in [0, 10000000]")
        inputs = _signal_values(data.get("inputs", data.get("drive", {})), "test step.inputs")
        expected = _signal_values(data.get("expected", data.get("checks", {})), "test step.expected")
        note = data.get("note")
        if note is not None:
            note = _require_string(note, "test step.note")
            if len(note) > 2_000:
                raise ModelValidationError("test step.note is too long")
        hold = data.get("hold_cycles", data.get("duration", 1))
        if isinstance(hold, bool) or not isinstance(hold, int) or not 1 <= hold <= 10_000:
            raise ModelValidationError("test step.hold_cycles must be an integer in [1, 10000]")
        return cls(cycle=cycle, inputs=inputs, expected=expected, note=note, hold_cycles=hold)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"cycle": self.cycle, "inputs": dict(self.inputs)}
        if self.expected:
            result["expected"] = dict(self.expected)
        if self.note is not None:
            result["note"] = self.note
        if self.hold_cycles != 1:
            result["hold_cycles"] = self.hold_cycles
        return result


@dataclass(frozen=True)
class TestCase:
    """一组有序测试步骤。"""

    id: str
    description: str = ""
    steps: tuple[TestStep, ...] = ()
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Any, *, index: int = 0) -> "TestCase":
        data = _require_mapping(value, f"test case[{index}]")
        _check_keys(
            data,
            {"id", "name", "description", "steps", "actions", "vectors", "tags"},
            f"test case[{index}]",
        )
        case_id = data.get("id", data.get("name", f"case_{index + 1}"))
        case_id = _label(case_id, f"test case[{index}].id")
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ModelValidationError(f"test case[{index}].description must be a string")
        if len(description) > 10_000:
            raise ModelValidationError(f"test case[{index}].description is too long")
        raw_steps = data.get("steps", data.get("actions", data.get("vectors", _MISSING)))
        if raw_steps is _MISSING:
            raise ModelValidationError(f"test case[{index}].steps is required")
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes, bytearray)):
            raise ModelValidationError(f"test case[{index}].steps must be an array")
        if not raw_steps or len(raw_steps) > 100_000:
            raise ModelValidationError(f"test case[{index}].steps must contain 1..100000 items")
        steps: list[TestStep] = []
        next_cycle = 0
        for raw_step in raw_steps:
            step = TestStep.from_dict(raw_step, default_cycle=next_cycle)
            steps.append(step)
            next_cycle = max(next_cycle, step.cycle + step.hold_cycles)
        tags_value = data.get("tags", [])
        if not isinstance(tags_value, Sequence) or isinstance(tags_value, (str, bytes, bytearray)):
            raise ModelValidationError(f"test case[{index}].tags must be an array")
        tags: list[str] = []
        for tag_index, tag in enumerate(tags_value):
            tag = _require_string(tag, f"test case[{index}].tags[{tag_index}]")
            if len(tag) > 100:
                raise ModelValidationError(f"test case[{index}].tags[{tag_index}] is too long")
            tags.append(tag)
        return cls(id=case_id, description=description, steps=tuple(steps), tags=tuple(tags))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.tags:
            result["tags"] = list(self.tags)
        return result


@dataclass(frozen=True)
class TestPlan:
    """AI 测试规划器与确定性 testbench 生成器之间的 JSON 合约。"""

    schema_version: str
    dut_module: str
    design: str = ""
    clock: ClockSpec | None = None
    reset: ResetSpec | None = None
    cases: tuple[TestCase, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "TestPlan":
        data = _require_mapping(value, "test plan")
        _check_keys(
            data,
            {
                "schema_version",
                "version",
                "dut_module",
                "module",
                "design",
                "clock",
                "clock_signal",
                "reset",
                "reset_signal",
                "cases",
                "tests",
                "test_cases",
                "metadata",
            },
            "test plan",
        )
        version = data.get("schema_version", data.get("version", "1.0"))
        version = _require_string(version, "test plan.schema_version")
        if len(version) > 30:
            raise ModelValidationError("test plan.schema_version is too long")
        module = data.get("dut_module", data.get("module", _MISSING))
        if module is _MISSING:
            raise ModelValidationError("test plan.dut_module is required")
        module = _identifier(module, "test plan.dut_module")
        design = data.get("design", "")
        if not isinstance(design, str):
            raise ModelValidationError("test plan.design must be a string")
        if len(design) > 10_000:
            raise ModelValidationError("test plan.design is too long")
        raw_clock = data.get("clock", _MISSING)
        if raw_clock is _MISSING and "clock_signal" in data:
            raw_clock = data["clock_signal"]
        clock = None if raw_clock is _MISSING or raw_clock is None else ClockSpec.from_dict(raw_clock)
        raw_reset = data.get("reset", _MISSING)
        if raw_reset is _MISSING and "reset_signal" in data:
            raw_reset = data["reset_signal"]
        reset = None if raw_reset is _MISSING or raw_reset is None else ResetSpec.from_dict(raw_reset)
        raw_cases = data.get("cases", data.get("tests", data.get("test_cases", _MISSING)))
        if raw_cases is _MISSING:
            raise ModelValidationError("test plan.cases is required")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes, bytearray)):
            raise ModelValidationError("test plan.cases must be an array")
        if not raw_cases or len(raw_cases) > 10_000:
            raise ModelValidationError("test plan.cases must contain 1..10000 items")
        cases = tuple(TestCase.from_dict(item, index=index) for index, item in enumerate(raw_cases))
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ModelValidationError("test plan.cases contains duplicate ids")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ModelValidationError("test plan.metadata must be an object")
        metadata = _json_value(metadata, "test plan.metadata")
        assert isinstance(metadata, dict)
        return cls(
            schema_version=version,
            dut_module=module,
            design=design,
            clock=clock,
            reset=reset,
            cases=cases,
            metadata=metadata,
        )

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> "TestPlan":
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ModelValidationError(f"test plan is not valid JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dut_module": self.dut_module,
            "design": self.design,
            "cases": [case.to_dict() for case in self.cases],
        }
        if self.clock is not None:
            result["clock"] = self.clock.to_dict()
        if self.reset is not None:
            result["reset"] = self.reset.to_dict()
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


@dataclass(frozen=True)
class ResultRecord:
    """testbench 输出的一条结构化记录。

    推荐 testbench 每行输出 IVERILOG_AI_RESULT followed by a JSON object，其中至少包含
    ok 布尔字段；其余字段用于形成可复现的失败反例。
    """

    ok: bool
    test_id: str | None = None
    cycle: int | None = None
    signal: str | None = None
    expected: Any = None
    actual: Any = None
    message: str = ""
    severity: str = "error"
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any, *, index: int = 0) -> "ResultRecord":
        data = _require_mapping(value, f"result record[{index}]")
        _check_keys(
            data,
            {
                "ok",
                "passed",
                "status",
                "test_id",
                "test",
                "name",
                "cycle",
                "signal",
                "expected",
                "actual",
                "message",
                "severity",
                "data",
            },
            f"result record[{index}]",
        )
        bool_value = data.get("ok", data.get("passed", _MISSING))
        if bool_value is _MISSING:
            status = data.get("status", _MISSING)
            if isinstance(status, str) and status.lower() in {"pass", "passed", "ok", "success"}:
                bool_value = True
            elif isinstance(status, str) and status.lower() in {"fail", "failed", "error"}:
                bool_value = False
            else:
                raise ModelValidationError(f"result record[{index}].ok must be a boolean")
        if not isinstance(bool_value, bool):
            raise ModelValidationError(f"result record[{index}].ok must be a boolean")
        raw_test = data.get("test_id", data.get("test", data.get("name")))
        test_id = None if raw_test is None else _label(raw_test, f"result record[{index}].test_id")
        cycle = data.get("cycle")
        if cycle is not None and (isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0):
            raise ModelValidationError(f"result record[{index}].cycle must be a non-negative integer")
        signal = data.get("signal")
        if signal is not None:
            signal = _signal_name(signal, f"result record[{index}].signal")
        message = data.get("message", "")
        if not isinstance(message, str):
            raise ModelValidationError(f"result record[{index}].message must be a string")
        # Functional assertion mismatches are verification findings, not
        # infrastructure failures.  Default failed records to ``warn``;
        # callers may explicitly use ``error`` for fatal testbench issues.
        severity = data.get("severity", "info" if bool_value else "warn")
        if not isinstance(severity, str) or not severity.strip():
            raise ModelValidationError(f"result record[{index}].severity must be a string")
        extra = data.get("data", {})
        if not isinstance(extra, Mapping):
            raise ModelValidationError(f"result record[{index}].data must be an object")
        normalized_extra = _json_value(extra, f"result record[{index}].data")
        assert isinstance(normalized_extra, dict)
        return cls(
            ok=bool_value,
            test_id=test_id,
            cycle=cycle,
            signal=signal,
            expected=_json_value(data.get("expected"), f"result record[{index}].expected"),
            actual=_json_value(data.get("actual"), f"result record[{index}].actual"),
            message=message,
            severity=severity.strip().lower(),
            data=normalized_extra,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": self.ok}
        if self.test_id is not None:
            result["test_id"] = self.test_id
        if self.cycle is not None:
            result["cycle"] = self.cycle
        if self.signal is not None:
            result["signal"] = self.signal
        if self.expected is not None:
            result["expected"] = self.expected
        if self.actual is not None:
            result["actual"] = self.actual
        if self.message:
            result["message"] = self.message
        if self.severity:
            result["severity"] = self.severity
        if self.data:
            result["data"] = dict(self.data)
        return result


@dataclass(frozen=True)
class FailureRecord:
    """面向报告的失败反例。"""

    test_id: str | None
    cycle: int | None
    signal: str | None
    expected: Any
    actual: Any
    message: str
    severity: str = "error"

    @classmethod
    def from_result(cls, record: ResultRecord) -> "FailureRecord":
        return cls(
            test_id=record.test_id,
            cycle=record.cycle,
            signal=record.signal,
            expected=record.expected,
            actual=record.actual,
            message=record.message or "testbench assertion failed",
            severity=record.severity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "cycle": self.cycle,
            "signal": self.signal,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ProcessResult:
    """受控外部进程的可序列化证据。"""

    status: ProcessStatus
    returncode: int | None
    command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    error: str | None = None
    output_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "returncode": self.returncode,
            "command": list(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "error": self.error,
            "output_truncated": self.output_truncated,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ProcessResult":
        data = _require_mapping(value, "process result")
        status = data.get("status", ProcessStatus.ERROR.value)
        try:
            status = ProcessStatus(status)
        except ValueError as exc:
            raise ModelValidationError(f"invalid process status: {status!r}") from exc
        command_value = data.get("command", [])
        if not isinstance(command_value, Sequence) or isinstance(command_value, (str, bytes, bytearray)):
            raise ModelValidationError("process result.command must be an array")
        command = tuple(_require_string(item, "process result.command item") for item in command_value)
        returncode = data.get("returncode")
        if returncode is not None and (isinstance(returncode, bool) or not isinstance(returncode, int)):
            raise ModelValidationError("process result.returncode must be an integer or null")
        duration_ms = data.get("duration_ms", 0)
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
            raise ModelValidationError("process result.duration_ms must be a non-negative integer")
        timed_out = data.get("timed_out", False)
        output_truncated = data.get("output_truncated", False)
        if not isinstance(timed_out, bool) or not isinstance(output_truncated, bool):
            raise ModelValidationError("process result flags must be boolean")
        return cls(
            status=status,
            returncode=returncode,
            command=command,
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            duration_ms=duration_ms,
            timed_out=timed_out,
            error=None if data.get("error") is None else str(data["error"]),
            output_truncated=output_truncated,
        )


CompileResult = ProcessResult


@dataclass(frozen=True)
class SimulationResult:
    """一次 Icarus 编译 + vvp 执行的完整机器可读结果。"""

    run_id: str
    status: ResultStatus
    compile: ProcessResult
    run: ProcessResult | None
    records: tuple[ResultRecord, ...] = ()
    failures: tuple[FailureRecord, ...] = ()
    diagnostics: tuple[str, ...] = ()
    artifacts: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str = field(default_factory=_utc_now)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status in {ResultStatus.PASSED, ResultStatus.PASSED_WITH_WARNINGS}

    @property
    def verdict(self) -> str:
        """给脚本与人看的**单一结论词**，把 `passed` 的歧义说清楚。

        为什么需要它：按裁决策略，功能不匹配记为 WARN，因此缺陷变体的
        `status` 是 `passed_with_warnings`、`passed` 仍是 True——一次跑出 3 条
        失败记录的运行，输出里却写着 `"passed": true`，只有同时看 `failures`
        才看得出来。判断缺陷检测与否的人很容易在这里读错。

        因此额外给出一个不含歧义的结论词：

        - ``passed``：仿真跑通且没有任何不匹配记录；
        - ``failed_checks``：仿真跑通，但存在**不匹配的功能检查**（缺陷检测的正常表现）；
        - ``failed``：编译失败、执行失败或配置错误；
        - ``inconclusive``：超时或结果无法判定。
        """

        if self.status is ResultStatus.PASSED:
            return "passed"
        if self.status is ResultStatus.PASSED_WITH_WARNINGS:
            return "failed_checks" if self.failures else "passed"
        if self.status in {
            ResultStatus.FAILED,
            ResultStatus.COMPILE_FAILED,
            ResultStatus.CONFIGURATION_ERROR,
        }:
            return "failed"
        return "inconclusive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "status": self.status.value,
            "verdict": self.verdict,
            "passed": self.passed,
            "compile": self.compile.to_dict(),
            "run": None if self.run is None else self.run.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "failures": [failure.to_dict() for failure in self.failures],
            "diagnostics": list(self.diagnostics),
            "artifacts": dict(self.artifacts),
            "config": dict(self.config),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "SimulationResult":
        data = _require_mapping(value, "simulation result")
        try:
            status = ResultStatus(data.get("status"))
        except ValueError as exc:
            raise ModelValidationError(f"invalid simulation status: {data.get('status')!r}") from exc
        raw_records = data.get("records", [])
        raw_failures = data.get("failures", [])
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes, bytearray)):
            raise ModelValidationError("simulation result.records must be an array")
        if not isinstance(raw_failures, Sequence) or isinstance(raw_failures, (str, bytes, bytearray)):
            raise ModelValidationError("simulation result.failures must be an array")
        raw_diagnostics = data.get("diagnostics", [])
        if not isinstance(raw_diagnostics, Sequence) or isinstance(
            raw_diagnostics, (str, bytes, bytearray)
        ):
            raise ModelValidationError("simulation result.diagnostics must be an array")
        raw_artifacts = data.get("artifacts", {})
        raw_config = data.get("config", {})
        if not isinstance(raw_artifacts, Mapping):
            raise ModelValidationError("simulation result.artifacts must be an object")
        if not isinstance(raw_config, Mapping):
            raise ModelValidationError("simulation result.config must be an object")
        failures: list[FailureRecord] = []
        for index, raw in enumerate(raw_failures):
            mapping = _require_mapping(raw, f"failure[{index}]")
            failures.append(
                FailureRecord(
                    test_id=mapping.get("test_id"),
                    cycle=mapping.get("cycle"),
                    signal=mapping.get("signal"),
                    expected=mapping.get("expected"),
                    actual=mapping.get("actual"),
                    message=str(mapping.get("message", "")),
                    severity=str(mapping.get("severity", "error")),
                )
            )
        return cls(
            run_id=str(data.get("run_id", "")),
            status=status,
            compile=ProcessResult.from_dict(data.get("compile", {})),
            run=None if data.get("run") is None else ProcessResult.from_dict(data["run"]),
            records=tuple(ResultRecord.from_dict(raw, index=index) for index, raw in enumerate(raw_records)),
            failures=tuple(failures),
            diagnostics=tuple(str(item) for item in raw_diagnostics),
            artifacts={str(key): str(item) for key, item in raw_artifacts.items()},
            config=dict(raw_config),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            error=None if data.get("error") is None else str(data["error"]),
        )

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> "SimulationResult":
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ModelValidationError(f"simulation result is not valid JSON: {exc}") from exc
        return cls.from_dict(value)
def normalize_severity(value: object, *, ok: bool = False) -> str:
    """Normalize record severity while keeping infrastructure errors distinct.

    Functional mismatches default to ``warn``; successful checks to ``info``.
    Explicit ``error`` is retained for fatal testbench/configuration findings.
    """
    if value is None or not str(value).strip():
        return "info" if ok else "warn"
    normalized = str(value).strip().lower()
    aliases = {"warning": "warn", "failure": "error", "fatal": "error"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"info", "warn", "error"} else ("info" if ok else "warn")





