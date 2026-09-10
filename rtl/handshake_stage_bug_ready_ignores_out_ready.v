// 缺陷 hs_bug_ready_ignores_out_ready：由 rtl/handshake_stage.v 单点修改生成，用于验证测试能否检出。
module handshake_stage #(parameter WIDTH=8)(input wire clk,input wire rst_n,input wire in_valid,output wire in_ready,input wire [WIDTH-1:0] in_data,output reg out_valid,input wire out_ready,output reg [WIDTH-1:0] out_data);
 assign in_ready=~out_valid;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin out_valid<=0;out_data<=0;end else if(in_ready) begin out_valid<=in_valid;if(in_valid) out_data<=in_data;end end
endmodule
