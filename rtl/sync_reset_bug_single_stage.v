// 缺陷 srst_bug_single_stage：由 rtl/sync_reset.v 单点修改生成，用于验证测试能否检出。
module sync_reset(input wire clk,input wire ext_rst_n,output reg rst_n);
 reg sync_ff;
 always @(posedge clk or negedge ext_rst_n) begin if(!ext_rst_n) begin sync_ff<=0;rst_n<=0;end else begin sync_ff<=1;rst_n<=1;end end
endmodule
