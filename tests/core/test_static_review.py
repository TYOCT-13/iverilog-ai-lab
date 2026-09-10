from iverilog_ai.core.static_review import render_static_markdown, review_rtl_source


def test_static_review_reports_rules_and_score():
    result = review_rtl_source("module m(input wire clk, input wire a, output reg y); always @(posedge clk) y = a; endmodule\n", filename="m.v")
    assert result["status"] == "warn"
    assert result["counts"]["warn"] >= 1
    assert result["quality_score"] < 100
    assert "blocking-in-sequential" in render_static_markdown(result)


def test_static_review_clean_combination():
    result = review_rtl_source("module m(input wire a, input wire b, output reg y); always @(*) begin y = 1'b0; if(a) y=b; end endmodule\n")
    assert result["status"] != "error"
