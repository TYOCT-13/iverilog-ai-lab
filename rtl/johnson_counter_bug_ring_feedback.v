// 缺陷：反馈位未取反，约翰逊计数器退化成环形计数器，0000 成为吸收态。
`timescale 1ns/1ps
module johnson_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'd0;
        else if (enable) q <= {q[2:0], q[3]};
    end
endmodule
