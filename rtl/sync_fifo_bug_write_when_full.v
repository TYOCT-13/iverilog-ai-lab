// 缺陷 fifo_bug_write_when_full：由 rtl/sync_fifo.v 单点修改生成，用于验证测试能否检出。
module sync_fifo #(parameter DATA_WIDTH=8, parameter DEPTH=4)(input wire clk,input wire rst_n,input wire wr_en,input wire [DATA_WIDTH-1:0] wr_data,input wire rd_en,output reg [DATA_WIDTH-1:0] rd_data,output wire full,output wire empty);
 reg [DATA_WIDTH-1:0] mem[0:DEPTH-1]; reg [2:0] count; reg [1:0] wr_ptr,rd_ptr;
 assign full=(count==DEPTH); assign empty=(count==0);
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin count<=0;wr_ptr<=0;rd_ptr<=0;rd_data<=0; end else begin if(wr_en) begin mem[wr_ptr]<=wr_data;wr_ptr<=wr_ptr+1'b1;count<=count+1'b1;end if(rd_en&&!empty) begin rd_data<=mem[rd_ptr];rd_ptr<=rd_ptr+1'b1;count<=count-1'b1;end end end
endmodule
