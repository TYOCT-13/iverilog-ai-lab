"""安全、确定性的向量式 Verilog testbench 生成器。

生成器只处理已经通过 ai.schema.TestPlan 校验的标量数据和显式
DutContract。它不会解析或拼接模型提供的 Verilog、命令、路径或其他代码。
生成结果是普通 Verilog-2001 testbench，每一个断言都输出一行
IVERILOG_AI_RESULT JSON，供 IcarusExecutor 的严格解析器消费。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..ai.schema import TestPlan
from .contracts import ContractValidationError, DutContract, PortSpec


class TestbenchGenerationError(ValueError):
    """测试计划不能安全地映射到指定 DUT 合约。"""


# 生成的 testbench 里 DUT 实例名固定，波形分析据此区分「DUT 内部信号」
# 与「testbench 记账信号」。改名时必须同步 pipeline 的层次判定。
DUT_INSTANCE = "dut_i"


_INTEGER_RE = re.compile(r"^-?[0-9]+$")
_BASE_RE = re.compile(r"^(?:(?P<size>[0-9]+))?'(?P<base>[bBoOdDhH])(?P<digits>[0-9a-fA-F_xXzZ]+)$")
_VERILOG_BINARY_RE = re.compile(r"^[01xXzZ_]+$")
_HEX_RE = re.compile(r"^0[xX][0-9a-fA-F_xXzZ]+$")
_OCT_RE = re.compile(r"^0[oO][0-7_xXzZ]+$")
_BIN_RE = re.compile(r"^0[bB][01_xXzZ]+$")
_VCD_FILENAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\.vcd$")


@dataclass(frozen=True)
class _EncodedValue:
    """一个值的受控 Verilog 表示和可审计 bit-string 表示。"""

    literal: str
    bits: str


def _bits_from_integer(value: int, width: int, *, signed: bool) -> str:
    mask = (1 << width) - 1
    if value < 0:
        if not signed:
            raise TestbenchGenerationError("negative value is not valid for an unsigned port")
        value &= mask
    if value > mask:
        raise TestbenchGenerationError(f"value {value} does not fit in a {width}-bit port")
    return format(value, f"0{width}b")


def _digits_to_bits(digits: str, base: str, width: int) -> str:
    compact = digits.replace("_", "")
    if not compact:
        raise TestbenchGenerationError("numeric literal cannot be empty")
    lower = compact.lower()
    if any(char in lower for char in "xz"):
        if set(lower) <= {"x"}:
            return "x" * width
        if set(lower) <= {"z"}:
            return "z" * width
        if base == "b" and len(compact) <= width:
            return compact.lower().rjust(width, "0")
        raise TestbenchGenerationError("mixed x/z values must use a binary literal")
    try:
        number = int(compact, {"b": 2, "o": 8, "d": 10, "h": 16}[base])
    except (KeyError, ValueError) as exc:
        raise TestbenchGenerationError("invalid numeric literal") from exc
    if number >= (1 << width):
        raise TestbenchGenerationError(f"numeric literal does not fit in a {width}-bit port")
    return format(number, f"0{width}b")


def _encode_value(port: PortSpec, value: Any, *, context: str) -> _EncodedValue:
    """Convert a JSON scalar into a fixed-width, safe Verilog literal.

    The generated source uses only a canonical width-qualified binary literal.
    In particular, no caller string is inserted verbatim into Verilog.
    """

    width = port.width
    if isinstance(value, bool):
        bits = _bits_from_integer(int(value), width, signed=port.signed)
    elif isinstance(value, int):
        try:
            bits = _bits_from_integer(value, width, signed=port.signed)
        except TestbenchGenerationError as exc:
            raise TestbenchGenerationError(f"{context}: {exc}") from exc
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise TestbenchGenerationError(f"{context}: value is not a printable scalar")
        if _INTEGER_RE.fullmatch(text):
            try:
                number = int(text, 10)
                bits = _bits_from_integer(number, width, signed=port.signed)
            except TestbenchGenerationError as exc:
                raise TestbenchGenerationError(f"{context}: {exc}") from exc
        elif _BIN_RE.fullmatch(text) or _HEX_RE.fullmatch(text) or _OCT_RE.fullmatch(text):
            if text[1].lower() == "b":
                base = "b"
            elif text[1].lower() == "o":
                base = "o"
            else:
                base = "h"
            bits = _digits_to_bits(text[2:], base, width)
        elif _VERILOG_BINARY_RE.fullmatch(text):
            bits = _digits_to_bits(text, "b", width)
        else:
            match = _BASE_RE.fullmatch(text)
            if not match:
                raise TestbenchGenerationError(
                    f"{context}: unsupported value spelling; use an integer or a bounded binary/hex literal"
                )
            size_text = match.group("size")
            if size_text is not None:
                size = int(size_text, 10)
                if not 1 <= size <= 4096 or size > width:
                    raise TestbenchGenerationError(
                        f"{context}: literal width must be in [1, {width}]"
                    )
            bits = _digits_to_bits(match.group("digits"), match.group("base").lower(), width)
    else:
        raise TestbenchGenerationError(f"{context}: value must be a boolean, integer, or string scalar")
    return _EncodedValue(literal=f"{width}'b{bits}", bits=bits)


def _verilog_string(value: str) -> str:
    """Quote a fixed generator string for a Verilog string literal."""

    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'


def _result_display(
    *,
    ok: bool,
    test_id: str,
    has_signal: bool,
    signal: str | None = None,
    expected_bits: str | None = None,
) -> str:
    """Return a display statement; all dynamic values are DUT observations."""

    fields = [
        '{"ok":' + ("true" if ok else "false"),
        ',"test_id":' + json.dumps(test_id, ensure_ascii=False),
        ',"cycle":%0d',
    ]
    arguments = ["cycle"]
    if has_signal:
        assert signal is not None and expected_bits is not None
        fields.extend(
            [
                ',"signal":' + json.dumps(signal, ensure_ascii=False),
                ',"expected":' + json.dumps(expected_bits),
                ',"actual":"%b"',
            ]
        )
        arguments.append(signal)
    fields.append("}")
    format_string = "IVERILOG_AI_RESULT " + "".join(fields)
    return f"$display({_verilog_string(format_string)}, {', '.join(arguments)});"


def _target(port: PortSpec) -> str:
    return port.name if port.direction.value == "input" else f"{port.name}_drive"


def _declaration(port: PortSpec) -> list[str]:
    if port.direction.value == "input":
        suffix = " signed" if port.signed else ""
        return [f"  reg{suffix} [{port.width - 1}:0] {port.name};"]
    if port.direction.value == "output":
        suffix = " signed" if port.signed else ""
        return [f"  wire{suffix} [{port.width - 1}:0] {port.name};"]
    suffix = " signed" if port.signed else ""
    return [
        f"  reg{suffix} [{port.width - 1}:0] {port.name}_drive;",
        f"  reg {port.name}_oe;",
        f"  tri{suffix} [{port.width - 1}:0] {port.name};",
        f"  assign {port.name} = {port.name}_oe ? {port.name}_drive : {port.width}'bz;",
    ]


def _coerce_plan(plan: Any) -> TestPlan:
    if isinstance(plan, TestPlan):
        return plan
    if isinstance(plan, Mapping):
        try:
            return TestPlan.model_validate(plan)
        except Exception as exc:
            raise TestbenchGenerationError(f"invalid ai.schema.TestPlan: {exc}") from exc
    raise TestbenchGenerationError("plan must be an ai.schema.TestPlan or its JSON object")


def _planned_expected_at_zero(
    plan: TestPlan,
    contract: DutContract,
) -> dict[str, _EncodedValue]:
    """计算复位前采样要检查的输出：计划显式声明优先，否则用 contract 的 initial。

    期望值只来自人工确认的 contract（或经过严格校验的计划字段），不由参考
    模型或模型输出推断；两者都没有时返回空字典，此时生成器会退化为
    "只观测、不断言"，不会伪造通过。
    """

    port_map = contract.port_map
    declared: dict[str, Any] = dict(plan.pre_reset_expected)
    for port in contract.ports:
        if port.is_output and port.initial is not None:
            declared.setdefault(port.name, port.initial)
    encoded: dict[str, _EncodedValue] = {}
    for signal, value in declared.items():
        # 名字不要复用上面的 `port`（那是 PortSpec）：同一个作用域里混用两种类型
        # 会让静态检查失效，也容易在后续修改里读错。
        declared_port = port_map.get(signal)
        if declared_port is None or not declared_port.is_output:
            continue
        encoded[signal] = _encode_value(
            declared_port, value, context=f"plan.pre_reset_expected.{signal}"
        )
    return encoded


def _validate_vectors(
    plan: TestPlan,
    contract: DutContract,
) -> list[tuple[Any, dict[str, _EncodedValue], dict[str, _EncodedValue]]]:
    port_map = contract.port_map
    vectors: list[tuple[Any, dict[str, _EncodedValue], dict[str, _EncodedValue]]] = []
    total_cycles = 0
    seen_names: set[str] = set()
    for index, vector in enumerate(plan.vectors):
        name = vector.name
        if name in seen_names:
            raise TestbenchGenerationError(f"vectors[{index}].name is duplicated: {name!r}")
        seen_names.add(name)
        if vector.cycles < 1:
            raise TestbenchGenerationError(f"vectors[{index}].cycles must be positive")
        total_cycles += vector.cycles
        if total_cycles > 100_000:
            raise TestbenchGenerationError("the test plan contains more than 100000 generated cycles")
        encoded_inputs: dict[str, _EncodedValue] = {}
        for signal, value in vector.inputs.items():
            port = port_map.get(signal)
            if port is None:
                raise TestbenchGenerationError(f"vectors[{index}].inputs contains unknown port {signal!r}")
            if not port.is_input:
                raise TestbenchGenerationError(f"vectors[{index}].inputs cannot drive output port {signal!r}")
            if contract.clock is not None and signal == contract.clock.signal:
                raise TestbenchGenerationError("the clock is generated by the contract and cannot be in a vector")
            encoded_inputs[signal] = _encode_value(port, value, context=f"vectors[{index}].inputs.{signal}")
        encoded_expected: dict[str, _EncodedValue] = {}
        for signal, value in vector.expected.items():
            port = port_map.get(signal)
            if port is None:
                raise TestbenchGenerationError(f"vectors[{index}].expected contains unknown port {signal!r}")
            if not port.is_output:
                raise TestbenchGenerationError(f"vectors[{index}].expected cannot check input port {signal!r}")
            encoded_expected[signal] = _encode_value(port, value, context=f"vectors[{index}].expected.{signal}")
        vectors.append((vector, encoded_inputs, encoded_expected))
    return vectors


@dataclass(frozen=True)
class TestbenchGenerator:
    """Generate a deterministic testbench under an explicitly chosen directory."""

    max_total_cycles: int = 100_000

    def generate(
        self,
        plan: TestPlan | Mapping[str, Any],
        contract: DutContract | Mapping[str, Any],
        output_dir: str | Path,
        *,
        filename: str | None = None,
        emit_vcd: bool = False,
        vcd_filename: str = "waveform.vcd",
    ) -> Path:
        try:
            dut_contract = contract if isinstance(contract, DutContract) else DutContract.from_dict(contract)
        except ContractValidationError as exc:
            raise TestbenchGenerationError(str(exc)) from exc
        ai_plan = _coerce_plan(plan)
        vectors = _validate_vectors(ai_plan, dut_contract)
        if self.max_total_cycles < 1 or self.max_total_cycles > 1_000_000:
            raise TestbenchGenerationError("max_total_cycles must be in [1, 1000000]")
        if sum(vector.cycles for vector, _, _ in vectors) > self.max_total_cycles:
            raise TestbenchGenerationError(
                f"test plan exceeds generator max_total_cycles={self.max_total_cycles}"
            )
        root = Path(output_dir).expanduser().resolve(strict=False)
        if root.exists() and not root.is_dir():
            raise TestbenchGenerationError(f"output_dir is not a directory: {root}")
        root.mkdir(parents=True, exist_ok=True)
        selected_name = filename or f"tb_{dut_contract.module}.v"
        if not re.fullmatch(r"tb_[A-Za-z_][A-Za-z0-9_$]*\.v", selected_name):
            raise TestbenchGenerationError("filename must be a safe tb_<module>.v basename")
        if not isinstance(emit_vcd, bool):
            raise TestbenchGenerationError("emit_vcd must be a boolean")
        if emit_vcd and not _VCD_FILENAME_RE.fullmatch(vcd_filename):
            raise TestbenchGenerationError("vcd_filename must be a safe .vcd basename")
        target = root / selected_name
        if target.exists() and target.is_symlink():
            raise TestbenchGenerationError("generated testbench path must not be a symbolic link")
        if target.resolve(strict=False).parent != root:
            raise TestbenchGenerationError("generated testbench must remain directly under output_dir")
        source = self._render(ai_plan, dut_contract, vectors, emit_vcd=emit_vcd, vcd_filename=vcd_filename)
        target.write_text(source, encoding="utf-8", newline="\n")
        return target

    def _render(
        self,
        plan: TestPlan,
        contract: DutContract,
        vectors: list[tuple[Any, dict[str, _EncodedValue], dict[str, _EncodedValue]]],
        *, emit_vcd: bool = False, vcd_filename: str = "waveform.vcd",
    ) -> str:
        top = f"tb_{contract.module}"
        lines = [
            "`timescale 1ns/1ps",
            "",
            f"module {top};",
        ]
        for port in contract.ports:
            lines.extend(_declaration(port))
        lines.extend(["  integer failures;", "  integer checks;", "  integer cycle;", ""])
        connections = ", ".join(f".{port.name}({port.name})" for port in contract.ports)
        parameter_override = ""
        if contract.parameters:
            parameter_override = " #(" + ", ".join(f".{name}({value})" for name, value in contract.parameters.items()) + ")"
        lines.extend([f"  {contract.module}{parameter_override} {DUT_INSTANCE} ({connections});", ""])
        if emit_vcd:
            lines.extend(["  initial begin", f"    $dumpfile({_verilog_string(vcd_filename)});", f"    $dumpvars(0, {top});", "  end", ""])
        if contract.clock is not None:
            clock = contract.clock
            half_period = clock.period_ns / 2.0
            delay = format(half_period, ".12g")
            lines.extend(
                [
                    f"  initial {clock.signal} = 1'b0;",
                    f"  always #{delay} {clock.signal} = ~{clock.signal};",
                    "",
                ]
            )
        lines.extend(["  initial begin", "    failures = 0;", "    checks = 0;", "    cycle = 0;"])
        for port in contract.inputs:
            if port.direction.value == "input":
                lines.append(f"    {port.name} = {port.width}'b0;")
            else:
                lines.append(f"    {port.name}_drive = {port.width}'b0;")
                lines.append(f"    {port.name}_oe = 1'b1;")
        if plan.sample_before_reset:
            # 复位前观测：抓"上电初值不符合规格"这类缺陷。此时输入刚被置为
            # 确定值，DUT 的 initial 值仍然有效，是唯一能看到初值的时刻。
            lines.append("    #1;")
            pre_reset_expected = _planned_expected_at_zero(plan, contract)
            if pre_reset_expected:
                for signal, encoded in pre_reset_expected.items():
                    lines.extend(
                        [
                            "    checks = checks + 1;",
                            f"    if ({signal} !== {encoded.literal}) begin",
                            "      failures = failures + 1;",
                            "      "
                            + _result_display(
                                ok=False,
                                test_id="pre_reset",
                                has_signal=True,
                                signal=signal,
                                expected_bits=encoded.bits,
                            ),
                            "    end else begin",
                            "      "
                            + _result_display(
                                ok=True,
                                test_id="pre_reset",
                                has_signal=True,
                                signal=signal,
                                expected_bits=encoded.bits,
                            ),
                            "    end",
                        ]
                    )
            else:
                lines.append("    " + _result_display(ok=True, test_id="pre_reset", has_signal=False))
        if contract.reset is not None:
            reset = contract.reset
            reset_port = contract.port_map[reset.signal]
            active = f"{reset_port.width}'b{reset.active_level}"
            inactive = f"{reset_port.width}'b{1 - reset.active_level}"
            lines.append(f"    {_target(reset_port)} = {active};")
            if contract.clock is not None:
                for _ in range(reset.assert_cycles):
                    lines.append(f"    @( {contract.clock.edge} {contract.clock.signal} );")
                lines.append("    #1;")
            else:
                delay = format(reset.assert_cycles, ".12g")
                lines.append(f"    #{delay};")
            lines.append(f"    {_target(reset_port)} = {inactive};")
            lines.append("    #1;")
        for vector, encoded_inputs, encoded_expected in vectors:
            # 多周期向量的 expected 描述的是该向量结束时的稳态输出。逐周期
            # 检查会把合法的中间状态判成失败（例如「7 个周期后 count=9」
            # 会在第 2 个周期就期望 9）。因此只在最后一个周期采样断言。
            for index in range(vector.cycles):
                is_final_cycle = index == vector.cycles - 1
                for signal, encoded in encoded_inputs.items():
                    lines.append(f"    {_target(contract.port_map[signal])} = {encoded.literal};")
                if contract.clock is not None:
                    if vector.sample_phase == "before":
                        lines.append("    #1;")
                    else:
                        lines.append(f"    @( {contract.clock.edge} {contract.clock.signal} );")
                        lines.append("    #1;")
                else:
                    lines.append("    #1;")
                if encoded_expected and is_final_cycle:
                    for signal, encoded in encoded_expected.items():
                        lines.extend(
                            [
                                "    checks = checks + 1;",
                                f"    if ({signal} !== {encoded.literal}) begin",
                                "      failures = failures + 1;",
                                "      "
                                + _result_display(
                                    ok=False,
                                    test_id=vector.name,
                                    has_signal=True,
                                    signal=signal,
                                    expected_bits=encoded.bits,
                                ),
                                "    end else begin",
                                "      "
                                + _result_display(
                                    ok=True,
                                    test_id=vector.name,
                                    has_signal=True,
                                    signal=signal,
                                    expected_bits=encoded.bits,
                                ),
                                "    end",
                            ]
                        )
                elif not encoded_expected:
                    lines.append("    " + _result_display(ok=True, test_id=vector.name, has_signal=False))
                lines.append("    cycle = cycle + 1;")
                if contract.clock is not None and vector.sample_phase == "before":
                    lines.append(f"    @( {contract.clock.edge} {contract.clock.signal} );")
                    lines.append("    #1;")
        lines.extend(
            [
                "    if (failures == 0) begin",
                "      $finish(0);",
                "    end else begin",
                "      $finish(1);",
                "    end",
                "  end",
                "endmodule",
                "",
            ]
        )
        return "\n".join(lines)


def generate_testbench(
    plan: TestPlan | Mapping[str, Any],
    contract: DutContract | Mapping[str, Any],
    output_dir: str | Path,
    *,
    filename: str | None = None,
    max_total_cycles: int = 100_000,
    emit_vcd: bool = False,
    vcd_filename: str = "waveform.vcd",
) -> Path:
    """生成 testbench 的函数式 API；工件只写入调用方指定的 output_dir。"""

    return TestbenchGenerator(max_total_cycles=max_total_cycles).generate(
        plan, contract, output_dir, filename=filename, emit_vcd=emit_vcd, vcd_filename=vcd_filename
    )


__all__ = ["TestbenchGenerationError", "TestbenchGenerator", "generate_testbench"]
