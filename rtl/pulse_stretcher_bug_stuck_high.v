// 缺陷 pstr_bug_stuck_high：由 rtl/pulse_stretcher.v 单点修改生成，用于验证测试能否检出。
// 计数归零后不再把输出拉低（改为保持原值），输出在首个脉冲后永久为高。
`timescale 1ns/1ps
module pulse_stretcher #(parameter WIDTH=4)(input wire clk, input wire rst_n, input wire pulse_in, output reg pulse_out);
    reg [WIDTH-1:0] count;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin count <= 0; pulse_out <= 0; end
        else if (pulse_in) begin count <= WIDTH-1; pulse_out <= 1; end
        else if (count != 0) begin count <= count - 1'b1; pulse_out <= 1; end
        else pulse_out <= pulse_out;
    end
endmodule
