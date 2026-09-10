// 缺陷：复位值错误，复位后从1开始而非0。
`timescale 1ns/1ps
module mod10_counter (input wire clk, input wire rst_n, input wire enable, output reg [3:0] count);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) count <= 4'd1;
        else if (enable) begin
            if (count == 4'd9) count <= 4'd0;
            else count <= count + 4'd1;
        end
    end
endmodule
