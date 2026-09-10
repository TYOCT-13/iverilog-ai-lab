// 缺陷 spi_bug_done_missing：由 rtl/spi_master.v 单点修改生成，用于验证测试能否检出。
module spi_master #(parameter WIDTH=8)(input wire clk,input wire rst_n,input wire start,input wire [WIDTH-1:0] data_in,output reg sclk,output reg mosi,output reg busy,output reg done);
 reg [WIDTH-1:0] shift; reg [3:0] count;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin sclk<=0;mosi<=0;busy<=0;done<=0;shift<=0;count<=0;end else begin done<=0;if(!busy) begin sclk<=0;if(start) begin busy<=1;shift<=data_in;count<=0;mosi<=data_in[WIDTH-1];end end else begin sclk<=~sclk;if(!sclk) begin if(count==WIDTH-1) begin busy<=0;done<=0;end else begin count<=count+1'b1;shift<={shift[WIDTH-2:0],1'b0};mosi<=shift[WIDTH-2];end end end end end
endmodule
