`timescale 1ns/1ps
module sequence_101_overlap(input wire clk,input wire rst_n,input wire bit_in,output reg detected); reg [1:0] history; always @(posedge clk or negedge rst_n) begin if(!rst_n) begin history<=0;detected<=0;end else begin detected<=({history,bit_in}==3'b100);history<={history[0],bit_in};end end endmodule
