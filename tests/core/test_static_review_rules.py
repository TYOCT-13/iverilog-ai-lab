"""静态审查规则集的逐规则测试。

组织方式：`RULE_CASES` 把每条规则映射到一个**最小反例**（必须命中）和一个
**最小正例**（必须不命中）。测试会断言：

1. 注册表里的每条规则都在用例表中出现（防止"加了规则没加测试"）；
2. 反例命中该规则；
3. 正例不命中该规则。

这样规则集扩到 30+ 条时，每条规则都有可核验的行为证据，而不是只靠人工翻代码。
"""

from __future__ import annotations

import pytest

from iverilog_ai.core.static_review import RULE_REGISTRY, review_rtl_source

# (rule_id, 反例源码, 正例源码)
RULE_CASES: tuple[tuple[str, str, str], ...] = (
    # ---- 可综合性 ----
    (
        "synth-delay",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg a; always @(posedge clk) a <= #5 1'b1; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg a; always @(posedge clk) a <= 1'b1; endmodule\n",
    ),
    (
        "initial-block",
        "`timescale 1ns/1ps\nmodule m; reg a; initial a = 1'b0; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n); reg a; always @(posedge clk) a <= rst_n; endmodule\n",
    ),
    (
        "real-type",
        "`timescale 1ns/1ps\nmodule m; real r; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg [31:0] r; endmodule\n",
    ),
    (
        "time-type",
        "`timescale 1ns/1ps\nmodule m; time t; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg [63:0] t; endmodule\n",
    ),
    (
        "event-type",
        "`timescale 1ns/1ps\nmodule m; event ev; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg ev; endmodule\n",
    ),
    (
        "fork-join",
        "`timescale 1ns/1ps\nmodule m; initial fork end join endmodule\n",
        "`timescale 1ns/1ps\nmodule m; initial begin end endmodule\n",
    ),
    (
        "wait-statement",
        "`timescale 1ns/1ps\nmodule m; reg a; initial wait (a) a = 1'b1; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b1; endmodule\n",
    ),
    (
        "disable-statement",
        "`timescale 1ns/1ps\nmodule m; initial begin : blk disable blk; end endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b0; endmodule\n",
    ),
    (
        "forever-loop",
        "`timescale 1ns/1ps\nmodule m; initial forever begin end endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(posedge a) a <= a; endmodule\n",
    ),
    (
        "repeat-loop",
        "`timescale 1ns/1ps\nmodule m; reg a; initial repeat (3) a = 1'b1; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b1; endmodule\n",
    ),
    (
        "while-loop",
        "`timescale 1ns/1ps\nmodule m; reg a; initial while (a) a = 1'b0; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b0; endmodule\n",
    ),
    (
        "system-task-display",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) begin a = 1'b1; $display(\"x\"); end endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b1; endmodule\n",
    ),
    (
        "system-task-file-io",
        "`timescale 1ns/1ps\nmodule m; reg a; initial $readmemh(\"f.hex\", a); endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; always @(*) a = 1'b0; endmodule\n",
    ),
    (
        "system-task-time",
        "`timescale 1ns/1ps\nmodule m; reg [31:0] a; always @(*) a = $time; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg [31:0] a; always @(*) a = 32'd0; endmodule\n",
    ),
    # ---- 时序与复位 ----
    (
        "blocking-in-sequential",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg a; always @(posedge clk) a = 1'b1; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg a; always @(posedge clk) a <= 1'b1; endmodule\n",
    ),
    (
        "non-blocking-combinational",
        "`timescale 1ns/1ps\nmodule m(input wire a); reg y; always @(*) y <= a; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a); reg y; always @(*) y = a; endmodule\n",
    ),
    (
        "incomplete-sensitivity",
        "`timescale 1ns/1ps\nmodule m(input wire a, input wire b); reg y; always @(a) y = a & b; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a, input wire b); reg y; always @(*) y = a & b; endmodule\n",
    ),
    (
        "async-reset-no-sync",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n);\n  reg a;\n  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 1'b0; else a <= 1'b1;\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n);\n  reg a, sync_ff;\n  always @(posedge clk or negedge rst_n) if (!rst_n) begin a <= 1'b0; sync_ff <= 1'b0; end else begin sync_ff <= 1'b1; a <= sync_ff; end\nendmodule\n",
    ),
    (
        "clock-in-always-sensitivity",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d); reg q; always @(clk or d) q = d; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d); reg q; always @(posedge clk) q <= d; endmodule\n",
    ),
    (
        "reset-in-data-path",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n, input wire d); reg q; always @(posedge clk or negedge rst_n) begin if (!rst_n) q <= 1'b0; else if (rst_n && d) q <= 1'b1; end endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n, input wire d); reg q; always @(posedge clk or negedge rst_n) begin if (!rst_n) q <= 1'b0; else q <= d; end endmodule\n",
    ),
    # ---- 组合逻辑与锁存器 ----
    (
        "inferred-latch",
        "`timescale 1ns/1ps\nmodule m(input wire en, input wire d); reg q; always @(*) begin if (en) q = d; end endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire en, input wire d); reg q; always @(*) begin q = 1'b0; if (en) q = d; end endmodule\n",
    ),
    (
        "missing-default-case",
        "`timescale 1ns/1ps\nmodule m(input wire [1:0] s); reg y; always @(*) begin case (s) 2'd0: y = 1'b0; 2'd1: y = 1'b1; endcase end endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire [1:0] s); reg y; always @(*) begin case (s) 2'd0: y = 1'b0; default: y = 1'b1; endcase end endmodule\n",
    ),
    (
        "incomplete-case-assignment",
        "`timescale 1ns/1ps\nmodule m(input wire [1:0] s); reg y; always @(*) begin case (s) 2'd0: y = 1'b0; default: ; endcase end endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire [1:0] s); reg y; always @(*) begin case (s) 2'd0: y = 1'b0; default: y = 1'b1; endcase end endmodule\n",
    ),
    (
        "comb-loop",
        "`timescale 1ns/1ps\nmodule m(input wire a); reg y; always @(*) y = a | y; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a); reg y; always @(*) y = a; endmodule\n",
    ),
    # ---- 多驱动与时钟域 ----
    (
        "multiple-procedural-drivers",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d1, input wire d2); reg q; always @(posedge clk) q <= d1; always @(posedge clk) q <= d2; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d1, input wire d2); reg q; always @(posedge clk) q <= d1 & d2; endmodule\n",
    ),
    (
        "mixed-block-assignment",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d); reg q; always @(posedge clk) begin q = d; q <= d; end endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire d); reg q; always @(posedge clk) q <= d; endmodule\n",
    ),
    (
        "missing-async-reg",
        "`timescale 1ns/1ps\nmodule m; reg data_sync; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; (* ASYNC_REG = \"TRUE\" *) reg data_sync; endmodule\n",
    ),
    # ---- 位宽与常量 ----
    (
        "width-truncation",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg [3:0] c; always @(posedge clk) c <= 4'd20; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg [3:0] c; always @(posedge clk) c <= 4'd9; endmodule\n",
    ),
    (
        "unsized-literal",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg [7:0] c; always @(posedge clk) c <= 200; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk); reg [7:0] c; always @(posedge clk) c <= 8'd200; endmodule\n",
    ),
    (
        "parameter-no-default",
        "`timescale 1ns/1ps\nmodule m #(parameter WIDTH) (input wire [WIDTH-1:0] d); endmodule\n",
        "`timescale 1ns/1ps\nmodule m #(parameter WIDTH = 8) (input wire [WIDTH-1:0] d); endmodule\n",
    ),
    (
        "localparam-missing",
        "`timescale 1ns/1ps\nmodule m(input wire clk); parameter IDLE = 0; reg s; always @(posedge clk) s <= IDLE; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk); localparam IDLE = 0; reg s; always @(posedge clk) s <= IDLE; endmodule\n",
    ),
    # ---- 接口与可读性 ----
    (
        "missing-timescale",
        "module m; reg a; endmodule\n",
        "`timescale 1ns/1ps\nmodule m; reg a; endmodule\n",
    ),
    (
        "non-ansi-port-list",
        "`timescale 1ns/1ps\nmodule m(a); input a; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a); endmodule\n",
    ),
    (
        "missing-port-direction",
        "`timescale 1ns/1ps\nmodule m(a, b);\n  input a;\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m(a, b);\n  input a;\n  output b;\n  assign b = a;\nendmodule\n",
    ),
    (
        "long-line",
        "`timescale 1ns/1ps\nmodule m; // " + "x" * 130 + "\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m; // short\nendmodule\n",
    ),
    (
        "trailing-whitespace",
        "`timescale 1ns/1ps\nmodule m;   \nendmodule\n",
        "`timescale 1ns/1ps\nmodule m;\nendmodule\n",
    ),
    (
        "tab-indent",
        "`timescale 1ns/1ps\nmodule m;\n\treg a;\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m;\n  reg a;\nendmodule\n",
    ),
    (
        "floating-net",
        "`timescale 1ns/1ps\nmodule m(input wire a, output wire y);\n  wire undriven_a, undriven_b;\n  assign y = a ^ undriven_a ^ undriven_b;\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a, output wire y);\n  wire driven_a;\n  wire driven_b;\n  assign driven_a = a;\n  assign driven_b = ~a;\n  assign y = driven_a ^ driven_b;\nendmodule\n",
    ),
    (
        "unused-signal",
        "`timescale 1ns/1ps\nmodule m(input wire a, output wire y); wire spare; assign y = a; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire a, output wire y); assign y = a; endmodule\n",
    ),
    (
        "empty-port-connection",
        "`timescale 1ns/1ps\nmodule sub(input wire a, output wire y); assign y = a; endmodule\nmodule m(input wire a, output wire y); sub u0(.a(a), .y()); endmodule\n",
        "`timescale 1ns/1ps\nmodule sub(input wire a, output wire y); assign y = a; endmodule\nmodule m(input wire a, output wire y); sub u0(.a(a), .y(y)); endmodule\n",
    ),
    (
        "generate-no-label",
        "`timescale 1ns/1ps\nmodule m; generate if (1) begin end endgenerate endmodule\n",
        "`timescale 1ns/1ps\nmodule m; generate if (1) begin : gen_x end endgenerate endmodule\n",
    ),
    (
        "division-operator",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire [7:0] a); reg [7:0] y; always @(posedge clk) y <= a / 3; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire [7:0] a); reg [7:0] y; always @(posedge clk) y <= a >> 1; endmodule\n",
    ),
    (
        "real-division",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire [7:0] a); reg [7:0] y; always @(posedge clk) y <= a / 3; endmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire [7:0] a); reg [7:0] y; always @(posedge clk) y <= a >> 2; endmodule\n",
    ),
    (
        "reset-polarity-mixed",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n, input wire rst);\n  reg a;\n  always @(posedge clk) begin\n    if (rst) a <= 1'b0;\n    else if (!rst_n) a <= 1'b0;\n    else a <= 1'b1;\n  end\nendmodule\n",
        "`timescale 1ns/1ps\nmodule m(input wire clk, input wire rst_n);\n  reg a;\n  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 1'b0; else a <= 1'b1;\nendmodule\n",
    ),
)


def test_every_registered_rule_has_a_case():
    """注册表与用例表必须一一对应，防止加规则不加测试。"""

    registered = set(RULE_REGISTRY)
    covered = {rule_id for rule_id, _bad, _good in RULE_CASES}
    assert registered - covered == set(), f"缺少测试的规则：{sorted(registered - covered)}"
    assert covered - registered == set(), f"测试引用了未注册的规则：{sorted(covered - registered)}"


@pytest.mark.parametrize("rule_id,bad,good", RULE_CASES, ids=[case[0] for case in RULE_CASES])
def test_rule_fires_on_bad_case_and_stays_quiet_on_good_case(rule_id, bad, good):
    bad_result = review_rtl_source(bad, filename="case.v")
    bad_rules = {item["rule_id"] for item in bad_result["findings"]}
    assert rule_id in bad_rules, f"{rule_id} 未命中反例；实际命中 {sorted(bad_rules)}"

    good_result = review_rtl_source(good, filename="case.v")
    good_rules = {item["rule_id"] for item in good_result["findings"]}
    assert rule_id not in good_rules, f"{rule_id} 误报在正例上；实际命中 {sorted(good_rules)}"


def test_registry_metadata_is_complete():
    """每条规则都必须有非空标题与来源，报告才能自解释。"""

    for rule_id, spec in RULE_REGISTRY.items():
        assert spec.title.strip(), f"{rule_id} 缺少 title"
        assert spec.source.strip(), f"{rule_id} 缺少 source"
        assert spec.severity in {"error", "warn", "info"}, f"{rule_id} 严重级别非法"


def test_rule_count_meets_roadmap_target():
    """路线图要求 30+ 条静态检查规则。"""

    assert len(RULE_REGISTRY) >= 30
