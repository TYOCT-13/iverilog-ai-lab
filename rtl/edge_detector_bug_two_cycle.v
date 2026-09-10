// 缺陷：历史寄存器 signal_d 从不更新，脉冲退化成"signal_in 的电平"，持续多个周期。
`timescale 1ns/1ps
module edge_detector(input wire clk, input wire rst_n, input wire signal_in, output reg rising);
    reg signal_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin signal_d <= 1'b0; rising <= 1'b0; end
        else rising <= signal_in & ~signal_d; // 漏掉 signal_d <= signal_in
    end
endmodule
