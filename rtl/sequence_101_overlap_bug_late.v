// 缺陷：检测条件晚一个采样沿，观察到的是上一拍候选序列。
`timescale 1ns/1ps
module sequence_101_overlap(input wire clk,input wire rst_n,input wire bit_in,output reg detected);
    reg [1:0] history;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin history<=0; detected<=0; end else begin detected<=(history==2'b10); history<={history[0],bit_in}; end
    end
endmodule
