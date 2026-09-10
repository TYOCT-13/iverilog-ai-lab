// 缺陷：左移和右移操作码的方向被交换。
module simple_alu (input wire [7:0] a, input wire [7:0] b, input wire [2:0] op, output reg [7:0] result, output reg carry, output reg zero);
    always @(*) begin
        result=0; carry=0;
        case(op)
            3'd0: result=a+b; 3'd1: result=a-b; 3'd2: result=a&b; 3'd3: result=a|b; 3'd4: result=a^b;
            3'd5: result=a>>1; 3'd6: result=a<<1; default: result=0;
        endcase
        zero=(result==0);
    end
endmodule
