`timescale 1ns/1ps
module pwm #(parameter WIDTH=8)(input wire clk,input wire rst_n,input wire [WIDTH-1:0] duty,output reg pwm_out);
 reg [WIDTH-1:0] counter;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin counter<=0;pwm_out<=0;end else begin counter<=counter+1'b1;pwm_out<=(counter<duty);end end
endmodule
