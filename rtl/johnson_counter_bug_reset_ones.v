// 缺陷：复位把 q 清成全 1（4'b1111），而不是全 0，复位状态取值错误。
`timescale 1ns/1ps
module johnson_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'b1111;
        else if (enable) q <= {q[2:0], ~q[3]};
    end
endmodule
