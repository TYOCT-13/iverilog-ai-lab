// 缺陷：加法 carry 只比较结果是否为零，无法报告八位溢出。
module simple_alu (input wire [7:0] a, input wire [7:0] b, input wire [2:0] op, output reg [7:0] result, output reg carry, output reg zero);
    reg [8:0] tmp;
    always @(*) begin
        tmp=0; result=0; carry=0;
        case(op)
            3'd0: begin tmp={1'b0,a}+{1'b0,b}; result=tmp[7:0]; carry=(result!=0); end
            3'd1: begin tmp={1'b0,a}-{1'b0,b}; result=tmp[7:0]; carry=(a>=b); end
            3'd2: result=a&b; 3'd3: result=a|b; 3'd4: result=a^b; 3'd5: result=a<<1; 3'd6: result=a>>1; default: result=0;
        endcase
        zero=(result==0);
    end
endmodule
