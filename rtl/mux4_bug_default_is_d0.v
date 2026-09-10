// 缺陷 mux_bug_default_is_d0：由 rtl/mux4.v 单点修改生成，用于验证测试能否检出。
`timescale 1ns/1ps
module mux4 #(parameter WIDTH=8)(input wire [WIDTH-1:0] d0,d1,d2,d3,input wire [1:0] sel,output reg [WIDTH-1:0] y);
 always @(*) begin case(sel) 2'd0:y=d0;2'd1:y=d1;2'd2:y=d2;default:y=d0;endcase end
endmodule
