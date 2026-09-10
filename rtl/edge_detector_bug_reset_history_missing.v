// 缺陷：复位分支漏掉历史寄存器 signal_d，复位释放后它仍是不确定值，
// 于是"复位期间 signal_in 已为高"的第一次上升沿无法产生确定的脉冲。
`timescale 1ns/1ps
module edge_detector(input wire clk, input wire rst_n, input wire signal_in, output reg rising);
    reg signal_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) rising <= 1'b0; // 漏掉 signal_d <= 1'b0
        else begin rising <= signal_in & ~signal_d; signal_d <= signal_in; end
    end
endmodule
