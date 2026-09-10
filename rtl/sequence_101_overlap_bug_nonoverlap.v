// 缺陷：命中后清空历史，无法识别重叠命中。
`timescale 1ns/1ps
module sequence_101_overlap(input wire clk,input wire rst_n,input wire bit_in,output reg detected);
    reg [1:0] history;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin history<=0; detected<=0; end else begin
            detected<=({history,bit_in}==3'b101);
            if ({history,bit_in}==3'b101) history<=0; else history<={history[0],bit_in};
        end
    end
endmodule
