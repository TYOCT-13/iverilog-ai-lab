// Icarus 智测参考设计：四运算简单 ALU。
`timescale 1ns/1ps
module simple_alu (
    input wire [7:0] a, input wire [7:0] b, input wire [2:0] op,
    output reg [7:0] result, output reg carry, output reg zero
);
    reg [8:0] extended_result;
    always @(*) begin
        result = 8'd0;
        extended_result = 9'd0;
        carry = 1'b0;
        case (op)
            3'd0: begin extended_result = {1'b0, a} + {1'b0, b}; result = extended_result[7:0]; carry = extended_result[8]; end
            3'd1: begin extended_result = {1'b0, a} - {1'b0, b}; result = extended_result[7:0]; carry = (a >= b); end
            3'd2: result = a & b;
            3'd3: result = a | b;
            3'd4: result = a ^ b;
            3'd5: result = a << 1;
            3'd6: result = a >> 1;
            default: result = 8'd0;
        endcase
        zero = (result == 8'd0);
    end
endmodule
