// 缺陷 pstr_bug_no_retrigger：由 rtl/pulse_stretcher.v 单点修改生成，用于验证测试能否检出。
// 展宽期内忽略新的脉冲（只在 count==0 时才装载计数），重触发无法延长展宽。
`timescale 1ns/1ps
module pulse_stretcher #(parameter WIDTH=4)(input wire clk, input wire rst_n, input wire pulse_in, output reg pulse_out);
    reg [WIDTH-1:0] count;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin count <= 0; pulse_out <= 0; end
        else if (pulse_in && count == 0) begin count <= WIDTH-1; pulse_out <= 1; end
        else if (count != 0) begin count <= count - 1'b1; pulse_out <= 1; end
        else pulse_out <= 0;
    end
endmodule
