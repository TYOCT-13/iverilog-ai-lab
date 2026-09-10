// 缺陷：enable 被忽略，暂停期间计数器仍然继续移位。
`timescale 1ns/1ps
module johnson_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'd0;
        else q <= {q[2:0], ~q[3]};
    end
endmodule
