module simple_alu(input wire [7:0] a,b,input wire [2:0] op,output reg [7:0] result,output reg carry,zero);
always @(*) begin result=0;carry=0;case(op) 0:result=a+b;1:begin result=a-b;carry=(a>=b);end 2:result=a&b;3:result=a|b;4:result=a^b;5:result=a<<2;6:result=a>>2;default:result=0;endcase zero=(result==0);end
endmodule
