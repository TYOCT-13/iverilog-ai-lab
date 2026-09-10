module mod10_counter(input wire clk,input wire rst_n,input wire enable,output reg [3:0] count);
always @(posedge clk or negedge rst_n) begin if(!rst_n) count<=0; else if(enable) begin if(count==9) count<=4'd1; else count<=count+1'b1; end end
endmodule
