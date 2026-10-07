// 缺陷 uart_bug_msb_first：由 rtl/uart_tx.v 单点修改生成，用于验证测试能否检出。
`timescale 1ns/1ps
module uart_tx #(parameter CLKS_PER_BIT=4)(input wire clk,input wire rst_n,input wire start,input wire [7:0] data_in,output reg tx,output reg busy);
 reg [3:0] bit_idx; reg [15:0] tick; reg [9:0] frame;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin tx<=1;busy<=0;bit_idx<=0;tick<=0;frame<=0;end else if(!busy) begin tx<=1;if(start) begin frame<={1'b1,data_in,1'b0};busy<=1;bit_idx<=0;tick<=0;tx<=0;end end else if(tick==CLKS_PER_BIT-1) begin tick<=0;bit_idx<=bit_idx+1'b1; if(bit_idx==9) begin busy<=0;tx<=1;end else tx<=frame[9-bit_idx]; end else tick<=tick+1'b1; end
endmodule
