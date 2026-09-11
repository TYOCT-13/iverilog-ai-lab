// 缺陷 srst_bug_never_release：由 rtl/sync_reset.v 单点修改生成，用于验证测试能否检出。
// 释放分支把 rst_n 恒接 0：ext_rst_n 拉高后同步链正常，但输出永远不释放。
`timescale 1ns/1ps
module sync_reset(input wire clk,input wire ext_rst_n,output reg rst_n);
 reg sync_ff;
 always @(posedge clk or negedge ext_rst_n) begin if(!ext_rst_n) begin sync_ff<=0;rst_n<=0;end else begin sync_ff<=1;rst_n<=0;end end
endmodule
