// 缺陷：脉冲被多打一拍，rising 比正确的上升沿晚一个周期。
`timescale 1ns/1ps
module edge_detector(input wire clk, input wire rst_n, input wire signal_in, output reg rising);
    reg signal_d, pulse_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin signal_d <= 1'b0; pulse_d <= 1'b0; rising <= 1'b0; end
        else begin pulse_d <= signal_in & ~signal_d; signal_d <= signal_in; rising <= pulse_d; end
    end
endmodule
