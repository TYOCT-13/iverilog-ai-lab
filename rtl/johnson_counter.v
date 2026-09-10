// Icarus 智测参考设计：4 位约翰逊（扭环）计数器
`timescale 1ns/1ps
module johnson_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] q
);
    // 反馈位取最高位的**反相**，因此 0000 不是吸收态：复位后能自行进入
    // 0000 → 0001 → 0011 → 0111 → 1111 → 1110 → 1100 → 1000 → 0000 的 8 状态循环。
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'd0;
        else if (enable) q <= {q[2:0], ~q[3]};
    end
endmodule
