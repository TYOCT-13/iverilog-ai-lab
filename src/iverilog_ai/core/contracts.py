"""显式 DUT 接口合约。

testbench 生成器只接受本模块定义的合约，而不会尝试从 RTL 或模型输出中
推断端口。合约是一个小型、无第三方依赖的 JSON 接口：端口名称、方向和
位宽都必须明确，时钟和复位也必须显式声明。这样可以把 AI 产生的测试计划
限制在受控数据范围内。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import re
from typing import Any, Mapping, Sequence


class ContractValidationError(ValueError):
    """DUT 合约缺失字段、包含未知字段或不满足安全约束。"""


class PortDirection(str, Enum):
    """Verilog 模块端口方向。"""

    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be an object")
    return value


def _string(value: Any, name: str, *, max_length: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractValidationError(f"{name} must be printable and at most {max_length} characters")
    return value


def _identifier(value: Any, name: str) -> str:
    value = _string(value, name)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ContractValidationError(f"{name} is not a safe Verilog identifier: {value!r}")
    return value


def _unknown_fields(data: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted((str(key) for key in data if key not in allowed), key=str)
    if unknown:
        raise ContractValidationError(f"{name} contains unsupported field(s): {', '.join(unknown)}")


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True)
class PortSpec:
    """一个 DUT 端口的完整、明确的类型信息。

    width 是 packed vector 的位数，标量使用 1。端口声明不支持任意
    Verilog 类型或表达式；生成器只会使用 name、direction、width、
    signed 和 initial 字段。

    ``initial`` 是该输出端口在**上电后、复位前**的声明初值。它只在
    ``sample_before_reset`` 为真时被使用，用来捕获"初值本身不符合规格"
    这类只有在复位前才可见的缺陷。该字段始终来自人工确认的 contract，
    不会由模型或参考模型推断。
    """

    name: str
    direction: PortDirection
    width: int = 1
    signed: bool = False
    initial: int | None = None

    def __post_init__(self) -> None:
        name = _identifier(self.name, "port.name")
        direction = self.direction
        if isinstance(direction, str):
            try:
                direction = PortDirection(direction.strip().lower())
            except ValueError as exc:
                raise ContractValidationError(
                    "port.direction must be input, output, or inout"
                ) from exc
        if not isinstance(direction, PortDirection):
            raise ContractValidationError("port.direction must be input, output, or inout")
        if isinstance(self.width, bool) or not isinstance(self.width, int) or not 1 <= self.width <= 4096:
            raise ContractValidationError("port.width must be an integer in [1, 4096]")
        signed = _bool(self.signed, "port.signed")
        initial = self.initial
        if initial is not None:
            if isinstance(initial, bool) or not isinstance(initial, int):
                raise ContractValidationError("port.initial must be an integer or null")
            limit = (1 << self.width) - 1
            if signed:
                if not -(1 << (self.width - 1)) <= initial <= limit:
                    raise ContractValidationError(f"port.initial does not fit in a {self.width}-bit port")
            elif not 0 <= initial <= limit:
                raise ContractValidationError(f"port.initial does not fit in a {self.width}-bit port")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "signed", signed)
        object.__setattr__(self, "initial", initial)

    @classmethod
    def from_dict(cls, value: Any, *, index: int = 0) -> "PortSpec":
        data = _mapping(value, f"port[{index}]")
        _unknown_fields(data, {"name", "direction", "width", "bits", "signed", "initial"}, f"port[{index}]")
        if "name" not in data or "direction" not in data:
            raise ContractValidationError(f"port[{index}] requires name and direction")
        if "width" in data and "bits" in data:
            raise ContractValidationError(f"port[{index}] cannot contain both width and bits")
        width = data.get("width", data.get("bits", 1))
        return cls(
            name=_identifier(data["name"], f"port[{index}].name"),
            direction=data["direction"],
            width=width,
            signed=data.get("signed", False),
            initial=data.get("initial"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "direction": self.direction.value,
            "width": self.width,
            "signed": self.signed,
        }
        if self.initial is not None:
            payload["initial"] = self.initial
        return payload

    @property
    def is_input(self) -> bool:
        return self.direction in {PortDirection.INPUT, PortDirection.INOUT}

    @property
    def is_output(self) -> bool:
        return self.direction in {PortDirection.OUTPUT, PortDirection.INOUT}


@dataclass(frozen=True)
class ClockContract:
    """DUT 时钟端口和生成器使用的周期。"""

    signal: str
    period_ns: float = 10.0
    edge: str = "posedge"

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal", _identifier(self.signal, "clock.signal"))
        period = self.period_ns
        if isinstance(period, bool) or not isinstance(period, (int, float)):
            raise ContractValidationError("clock.period_ns must be a number")
        period = float(period)
        if not math.isfinite(period) or period <= 0 or period > 1_000_000:
            raise ContractValidationError("clock.period_ns must be in (0, 1000000]")
        edge = _string(self.edge, "clock.edge").lower()
        if edge not in {"posedge", "negedge"}:
            raise ContractValidationError("clock.edge must be posedge or negedge")
        object.__setattr__(self, "period_ns", period)
        object.__setattr__(self, "edge", edge)

    @classmethod
    def from_dict(cls, value: Any) -> "ClockContract":
        if isinstance(value, str):
            return cls(signal=value)
        data = _mapping(value, "clock")
        _unknown_fields(data, {"signal", "name", "period_ns", "period", "edge"}, "clock")
        signal = data.get("signal", data.get("name"))
        if signal is None:
            raise ContractValidationError("clock.signal is required")
        if "period_ns" in data and "period" in data:
            raise ContractValidationError("clock cannot contain both period_ns and period")
        return cls(
            signal=signal,
            period_ns=data.get("period_ns", data.get("period", 10.0)),
            edge=data.get("edge", "posedge"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"signal": self.signal, "period_ns": self.period_ns, "edge": self.edge}


@dataclass(frozen=True)
class ResetContract:
    """DUT 复位端口以及自动复位阶段的语义。"""

    signal: str
    active_level: int = 0
    synchronous: bool = False
    assert_cycles: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal", _identifier(self.signal, "reset.signal"))
        if isinstance(self.active_level, bool) or self.active_level not in {0, 1}:
            raise ContractValidationError("reset.active_level must be 0 or 1")
        if not isinstance(self.synchronous, bool):
            raise ContractValidationError("reset.synchronous must be a boolean")
        if (
            isinstance(self.assert_cycles, bool)
            or not isinstance(self.assert_cycles, int)
            or not 1 <= self.assert_cycles <= 10_000
        ):
            raise ContractValidationError("reset.assert_cycles must be an integer in [1, 10000]")

    @classmethod
    def from_dict(cls, value: Any) -> "ResetContract":
        if isinstance(value, str):
            return cls(signal=value)
        data = _mapping(value, "reset")
        _unknown_fields(
            data,
            {"signal", "name", "active_level", "active", "active_low", "synchronous", "assert_cycles"},
            "reset",
        )
        signal = data.get("signal", data.get("name"))
        if signal is None:
            raise ContractValidationError("reset.signal is required")
        if "active_level" in data and "active" in data:
            raise ContractValidationError("reset cannot contain both active_level and active")
        active = data.get("active_level", data.get("active"))
        if active is None and "active_low" in data:
            active = 0 if data["active_low"] else 1
        if active is None:
            active = 0
        return cls(
            signal=signal,
            active_level=active,
            synchronous=data.get("synchronous", False),
            assert_cycles=data.get("assert_cycles", 2),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "active_level": self.active_level,
            "synchronous": self.synchronous,
            "assert_cycles": self.assert_cycles,
        }


@dataclass(frozen=True)
class DutContract:
    """受控 testbench 生成所需的 DUT 接口合同。"""

    module: str
    ports: tuple[PortSpec, ...]
    clock: ClockContract | None = None
    reset: ResetContract | None = None
    parameters: dict[str, int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", _identifier(self.module, "contract.module"))
        params = {} if self.parameters is None else dict(self.parameters)
        for name, value in params.items():
            if not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name):
                raise ContractValidationError("contract.parameters contains an unsafe name")
            if isinstance(value, bool) or not isinstance(value, int) or not -(1 << 31) <= value < (1 << 31):
                raise ContractValidationError("contract.parameters values must be 32-bit integers")
        object.__setattr__(self, "parameters", params)
        raw_ports = tuple(self.ports)
        ports_list: list[PortSpec] = []
        for index, port in enumerate(raw_ports):
            if isinstance(port, PortSpec):
                ports_list.append(port)
            elif isinstance(port, Mapping):
                ports_list.append(PortSpec.from_dict(port, index=index))
            else:
                raise ContractValidationError("contract.ports must contain PortSpec values")
        ports = tuple(ports_list)
        if not ports:
            raise ContractValidationError("contract.ports must contain at least one port")
        names = [port.name for port in ports]
        if len(names) != len(set(names)):
            raise ContractValidationError("contract.ports contains duplicate names")
        object.__setattr__(self, "ports", ports)
        clock = self.clock
        if isinstance(clock, Mapping) or isinstance(clock, str):
            clock = ClockContract.from_dict(clock)
            object.__setattr__(self, "clock", clock)
        if clock is not None and not isinstance(clock, ClockContract):
            raise ContractValidationError("contract.clock must be a ClockContract or null")
        reset = self.reset
        if isinstance(reset, Mapping) or isinstance(reset, str):
            reset = ResetContract.from_dict(reset)
            object.__setattr__(self, "reset", reset)
        if reset is not None and not isinstance(reset, ResetContract):
            raise ContractValidationError("contract.reset must be a ResetContract or null")
        by_name = {port.name: port for port in ports}
        if self.clock is not None:
            clock_port = by_name.get(self.clock.signal)
            if clock_port is None:
                raise ContractValidationError(f"clock.signal {self.clock.signal!r} is not a declared port")
            if not clock_port.is_input:
                raise ContractValidationError("clock.signal must be an input or inout port")
            if clock_port.width != 1:
                raise ContractValidationError("clock.signal must be a one-bit port")
        if self.reset is not None:
            reset_port = by_name.get(self.reset.signal)
            if reset_port is None:
                raise ContractValidationError(f"reset.signal {self.reset.signal!r} is not a declared port")
            if not reset_port.is_input:
                raise ContractValidationError("reset.signal must be an input or inout port")
            if reset_port.width != 1:
                raise ContractValidationError("reset.signal must be a one-bit port")
        if self.clock is not None and self.reset is not None and self.clock.signal == self.reset.signal:
            raise ContractValidationError("clock and reset must be different ports")

    @classmethod
    def from_dict(cls, value: Any) -> "DutContract":
        data = _mapping(value, "DUT contract")
        _unknown_fields(data, {"module", "dut_module", "ports", "clock", "reset", "parameters"}, "DUT contract")
        if "module" in data and "dut_module" in data:
            raise ContractValidationError("DUT contract cannot contain both module and dut_module")
        module = data.get("module", data.get("dut_module"))
        if module is None:
            raise ContractValidationError("DUT contract.module is required")
        raw_ports = data.get("ports")
        if isinstance(raw_ports, Mapping):
            compact_ports = []
            for name, spec in raw_ports.items():
                if not isinstance(spec, Mapping):
                    raise ContractValidationError(f"port {name!r} must be an object")
                item = dict(spec)
                if "name" in item:
                    raise ContractValidationError(f"compact port {name!r} cannot set name")
                item["name"] = name
                compact_ports.append(item)
            raw_ports = compact_ports
        if not isinstance(raw_ports, Sequence) or isinstance(raw_ports, (str, bytes, bytearray)):
            raise ContractValidationError("DUT contract.ports must be an array")
        if not raw_ports or len(raw_ports) > 4096:
            raise ContractValidationError("DUT contract.ports must contain 1..4096 items")
        ports = tuple(PortSpec.from_dict(item, index=index) for index, item in enumerate(raw_ports))
        clock = None if data.get("clock") is None else ClockContract.from_dict(data["clock"])
        reset = None if data.get("reset") is None else ResetContract.from_dict(data["reset"])
        parameters = data.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ContractValidationError("DUT contract.parameters must be an object")
        return cls(module=module, ports=ports, clock=clock, reset=reset, parameters=dict(parameters))

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> "DutContract":
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContractValidationError(f"DUT contract is not valid JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "module": self.module,
            "ports": [port.to_dict() for port in self.ports],
        }
        if self.clock is not None:
            result["clock"] = self.clock.to_dict()
        if self.reset is not None:
            result["reset"] = self.reset.to_dict()
        if self.parameters:
            result["parameters"] = dict(self.parameters)
        return result

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @property
    def port_map(self) -> dict[str, PortSpec]:
        return {port.name: port for port in self.ports}

    @property
    def dut_module(self) -> str:
        return self.module

    @property
    def clock_signal(self) -> str | None:
        return None if self.clock is None else self.clock.signal

    @property
    def reset_signal(self) -> str | None:
        return None if self.reset is None else self.reset.signal

    @property
    def inputs(self) -> tuple[PortSpec, ...]:
        return tuple(port for port in self.ports if port.is_input)

    @property
    def outputs(self) -> tuple[PortSpec, ...]:
        return tuple(port for port in self.ports if port.is_output)


# API spellings used by callers and older design notes.
DUTContract = DutContract
DUTPort = PortSpec
DutPort = PortSpec
ClockSpec = ClockContract
ResetSpec = ResetContract


__all__ = [
    "ClockContract",
    "ClockSpec",
    "ContractValidationError",
    "DUTContract",
    "DUTPort",
    "DutPort",
    "DutContract",
    "PortDirection",
    "PortSpec",
    "ResetContract",
    "ResetSpec",
]
