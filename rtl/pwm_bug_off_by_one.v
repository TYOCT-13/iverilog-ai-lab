// 缺陷 pwm_bug_off_by_one：由 rtl/pwm.v 单点修改生成，用于验证测试能否检出。
`timescale 1ns/1ps
module pwm #(parameter WIDTH=8)(input wire clk,input wire rst_n,input wire [WIDTH-1:0] duty,output reg pwm_out);
 reg [WIDTH-1:0] counter;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin counter<=0;pwm_out<=0;end else begin counter<=counter+1'b1;pwm_out<=(counter<duty-1'b1);end end
endmodule
