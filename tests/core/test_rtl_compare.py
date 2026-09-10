from iverilog_ai.core.rtl_compare import compare_rtl_sources


def test_rtl_compare_reports_strengths_and_gaps():
    reference = "module dut(input wire clk, input wire rst_n, output reg y); always @(posedge clk or negedge rst_n) begin if(!rst_n) y<=0; end endmodule"
    user = "module dut(input wire clk, output reg y); always @(posedge clk) y = 1; endmodule"
    result = compare_rtl_sources(user, reference)
    assert result["port_match"] is False
    assert result["gaps"]
    assert result["learning_plan"]
