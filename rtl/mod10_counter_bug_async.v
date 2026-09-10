module mod10_counter(input wire clk, input wire rst_n, input wire enable, output reg [3:0] count = 4'd15);
always @(posedge clk) begin if(!rst_n) count<=0; else if(enable) count <= (count==9)?0:count+1'b1; end
endmodule
