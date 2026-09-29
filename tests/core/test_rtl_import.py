"""`rtl_import` 的合约草稿提取回归。

本文件在 2026-09-29 的审查后重写，钉住三件**曾经静默出错**的事：

1. 符号位宽 `[WIDTH-1:0]` 被当成 1 位，并且 `WIDTH` 被当成一个端口；
2. 复位极性与同步属性靠端口名猜（`rst_n` 就当低有效、当同步）；
3. 未声明的端口被默认成 `input` / 1 位。

判据是"**要么读对，要么明确要求人工合约**"：读不出来时草稿里留 ``None``，
`DutContract.from_dict` 会带着字段名报错，而不是让一个错误合约进入执行器。
"""
from __future__ import annotations

import pytest

from iverilog_ai.core.contracts import ContractValidationError, DutContract
from iverilog_ai.core.rtl_import import RTLImportError, extract_contract_draft, import_rtl_bytes


def _ports(contract: dict) -> list[tuple[str, str, int | None]]:
    return [(p["name"], p["direction"], p["width"]) for p in contract["ports"]]


# --------------------------------------------------------------- 位宽（验收表第 1、2 行）


def test_literal_widths_are_recognised():
    """字面量位宽必须照旧识别——这是不能改坏的部分。"""

    _, contract, _ = extract_contract_draft(
        "module demo(input wire clk, rst_n, input wire [7:0] data, extra, output logic [3:0] y); endmodule"
    )
    assert _ports(contract) == [
        ("clk", "input", 1),
        ("rst_n", "input", 1),
        ("data", "input", 8),
        # 共享方向声明：`extra` 沿用前一个声明的位宽
        ("extra", "input", 8),
        ("y", "output", 4),
    ]


def test_thirty_two_bit_port_is_recognised():
    _, contract, _ = extract_contract_draft("module wide(input [31:0] data, output [31:0] q); endmodule")
    assert _ports(contract) == [("data", "input", 32), ("q", "output", 32)]


def test_symbolic_width_is_not_silently_one_bit_and_parameter_is_not_a_port():
    """`[WIDTH-1:0]`：旧实现给出 1 位端口 + 一个叫 WIDTH 的假端口。"""

    _, contract, warnings = extract_contract_draft(
        "module p(input clk, input [WIDTH-1:0] data, output [WIDTH-1:0] q); endmodule"
    )
    names = [p["name"] for p in contract["ports"]]
    assert "WIDTH" not in names, "参数名不能变成端口"
    assert _ports(contract) == [("clk", "input", 1), ("data", "input", None), ("q", "output", None)]
    assert any("无法可靠解析" in w for w in warnings)
    with pytest.raises(ContractValidationError) as error:
        DutContract.from_dict(contract)
    assert "位宽未确定" in str(error.value) and "'data'" in str(error.value)


def test_literal_parameter_resolves_the_symbolic_width():
    """有限范围内的参数支持：`parameter WIDTH = 16` + `[WIDTH-1:0]` → 16 位。"""

    _, contract, _ = extract_contract_draft(
        "module p #(parameter WIDTH = 16) (input [WIDTH-1:0] data, output [WIDTH-1:0] q); endmodule"
    )
    assert _ports(contract) == [("data", "input", 16), ("q", "output", 16)]
    assert contract["parameters"] == {"WIDTH": 16}
    assert DutContract.from_dict(contract).port_map["data"].width == 16


def test_expression_parameter_is_rejected_rather_than_guessed():
    _, contract, _ = extract_contract_draft(
        "module p #(parameter WIDTH = 8*2) (input [WIDTH-1:0] data, output q); endmodule"
    )
    assert _ports(contract) == [("data", "input", None), ("q", "output", 1)]
    with pytest.raises(ContractValidationError):
        DutContract.from_dict(contract)


def test_multidimensional_declaration_requires_manual_contract():
    _, contract, _ = extract_contract_draft("module p(input [3:0][7:0] words, output q); endmodule")
    assert _ports(contract) == [("words", "input", None), ("q", "output", 1)]


# --------------------------------------------------- 时钟与复位（验收表第 4 行）


def test_active_low_async_reset_polarity_comes_from_code():
    _, contract, _ = extract_contract_draft(
        "module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q);\n"
        "  always @(posedge clk or negedge rst_n) begin\n"
        "    if (!rst_n) q <= 8'd0; else q <= d;\n"
        "  end\nendmodule"
    )
    assert contract["clock"] == {"signal": "clk", "period_ns": 10.0, "edge": "posedge"}
    assert contract["reset"]["active_level"] == 0
    assert contract["reset"]["synchronous"] is False


def test_active_high_sync_reset_polarity_comes_from_code():
    _, contract, _ = extract_contract_draft(
        "module m(input clk, input rst, input [7:0] d, output reg [7:0] q);\n"
        "  always @(posedge clk) begin\n"
        "    if (rst) q <= 8'd0; else q <= d;\n"
        "  end\nendmodule"
    )
    assert contract["reset"]["active_level"] == 1
    assert contract["reset"]["synchronous"] is True


def test_negedge_clock_is_derived():
    _, contract, _ = extract_contract_draft(
        "module m(input clk, input [7:0] d, output reg [7:0] q);\n  always @(negedge clk) q <= d;\nendmodule"
    )
    assert contract["clock"]["edge"] == "negedge"


def test_reset_polarity_is_not_guessed_from_the_port_name():
    """名字像复位但没有代码依据：留空并要求确认，**不能**默认低有效。"""

    _, contract, warnings = extract_contract_draft(
        "module m(input clk, input rst_n, input [7:0] d, output [7:0] q); assign q = d; endmodule"
    )
    assert contract["reset"]["signal"] == "rst_n"
    assert contract["reset"]["active_level"] is None
    assert contract["reset"]["synchronous"] is None
    assert any("端口名不是证据" in w for w in warnings)
    with pytest.raises(ContractValidationError):
        DutContract.from_dict(contract)


def test_clock_without_edge_evidence_is_omitted_and_reported():
    _, contract, warnings = extract_contract_draft(
        "module m(input clk, input [7:0] d, output [7:0] q); assign q = d; endmodule"
    )
    assert "clock" not in contract
    assert any("无法确认边沿" in w for w in warnings)


def test_manual_contract_enters_validation_after_filling_the_gaps():
    """验收表第 3 行：人工给出正确合约后必须能进入后续验证。"""

    _, draft, _ = extract_contract_draft(
        "module m(input clk, input rst_n, input [7:0] d, output [7:0] q); assign q = d; endmodule"
    )
    fixed = dict(draft)
    fixed["clock"] = {"signal": "clk", "period_ns": 10, "edge": "posedge"}
    fixed["reset"] = {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2}
    contract = DutContract.from_dict(fixed)
    assert contract.reset is not None and contract.reset.active_level == 0


# --------------------------------------------------- 非 ANSI 与导入安全


def test_undeclared_port_is_not_defaulted_to_input_one_bit():
    _, contract, warnings = extract_contract_draft("module m(a, b, c); input a; output b; endmodule")
    assert _ports(contract) == [("a", "input", 1), ("b", "output", 1), ("c", None, None)]
    assert any("找不到声明" in w for w in warnings)
    with pytest.raises(ContractValidationError):
        DutContract.from_dict(contract)


def test_import_hash_path_and_rejects_unsafe(tmp_path):
    result = import_rtl_bytes("demo.v", b"module demo(input a, output y); endmodule", tmp_path)
    assert result.path.parent == (tmp_path / ".iverilog-ai" / "custom_rtl").resolve()
    assert result.path.read_bytes().startswith(b"module demo")
    with pytest.raises(RTLImportError):
        import_rtl_bytes("../evil.v", b"x", tmp_path)
    with pytest.raises(RTLImportError):
        import_rtl_bytes("x.v", b"\x00", tmp_path)
