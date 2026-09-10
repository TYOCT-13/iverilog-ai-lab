// 缺陷：检测下降沿（~signal_in & signal_d），上升沿不再产生脉冲。
`timescale 1ns/1ps
module edge_detector(input wire clk, input wire rst_n, input wire signal_in, output reg rising);
    reg signal_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin signal_d <= 1'b0; rising <= 1'b0; end
        else begin rising <= ~signal_in & signal_d; signal_d <= signal_in; end
    end
endmodule
