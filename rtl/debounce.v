module debounce #(parameter COUNT_MAX=3)(input wire clk,input wire rst_n,input wire key_in,output reg key_state);
 reg [3:0] count; reg sample;
 always @(posedge clk or negedge rst_n) begin if(!rst_n) begin count<=0;sample<=1;key_state<=1;end else if(key_in==sample) count<=0; else if(count==COUNT_MAX-1) begin sample<=key_in;key_state<=key_in;count<=0;end else count<=count+1'b1; end
endmodule
