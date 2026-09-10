`timescale 1ns/1ps
module mod10_counter(input wire clk,input wire rst_n,input wire enable,output reg [2:0] count);
always @(posedge clk or negedge rst_n) begin if(!rst_n) count<=0; else if(enable) count <= (count==6)?0:count+1'b1; end
endmodule
