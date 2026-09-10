// 缺陷 deb_bug_reset_state：由 rtl/debounce.v 单点修改生成，用于验证测试能否检出。
`timescale 1ns/1ps
module debounce #(parameter COUNT_MAX=3)(input wire clk,input wire rst_n,input wire key_in,output reg key_state);
 reg [3:0] count; reg sample;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin count<=0;sample<=0;key_state<=0;end else if(key_in==sample) count<=0; else if(count==COUNT_MAX-1) begin sample<=key_in;key_state<=key_in;count<=0;end else count<=count+1'b1; end
endmodule
