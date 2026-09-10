// Icarus 智测参考设计：可重叠 101 序列检测器。
`timescale 1ns/1ps
module sequence_101_overlap (
    input wire clk, input wire rst_n, input wire bit_in, output reg detected
);
    reg [1:0] history;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin history <= 2'b00; detected <= 1'b0; end
        else begin
            detected <= ({history, bit_in} == 3'b101);
            history <= {history[0], bit_in};
        end
    end
endmodule
