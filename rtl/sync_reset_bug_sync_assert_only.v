// 缺陷 srst_bug_sync_assert_only：由 rtl/sync_reset.v 单点修改生成，用于验证测试能否检出。
// 第二级触发器改成纯同步复位：复位**释放**仍然两级同步，但复位**断言**要等时钟沿，
// 时钟停摆或断言发生在两个时钟沿之间时复位失效（异步断言是复位同步器的硬要求）。
`timescale 1ns/1ps
module sync_reset(input wire clk,input wire ext_rst_n,output reg rst_n);
 reg sync_ff;
 always @(posedge clk or negedge ext_rst_n) begin if(!ext_rst_n) sync_ff<=0; else sync_ff<=1; end
 always @(posedge clk) begin if(!ext_rst_n) rst_n<=0; else rst_n<=sync_ff; end
endmodule
