// 缺陷：历史移位方向错误，输入时间顺序被反转。
`timescale 1ns/1ps
module sequence_101_overlap(input wire clk,input wire rst_n,input wire bit_in,output reg detected);
    reg [1:0] history;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin history<=0; detected<=0; end else begin detected<=({history,bit_in}==3'b101); history<={bit_in,history[1]}; end
    end
endmodule
