// 缺陷：用显式状态表实现，漏掉 0000 → 0001 的自启动转移，0000 卡死。
//
// 与 ring_feedback 的差别在根因而不在现象：这里反馈极性正确、其余 8 个状态
// 的转移也正确，只是状态表里的 0000 分支缺了自启动项，于是复位后永远停在 0。
`timescale 1ns/1ps
module johnson_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'd0;
        else if (enable) begin
            case (q)
                4'b0001: q <= 4'b0011;
                4'b0011: q <= 4'b0111;
                4'b0111: q <= 4'b1111;
                4'b1111: q <= 4'b1110;
                4'b1110: q <= 4'b1100;
                4'b1100: q <= 4'b1000;
                4'b1000: q <= 4'b0000;
                default: q <= 4'b0000; // 状态表缺 0000 → 0001 的自启动转移
            endcase
        end
    end
endmodule
