module traffic_light_emergency(input wire clk,input wire rst_n,input wire emergency,output reg [1:0] main_light,output reg [1:0] side_light);
localparam RED=0,YELLOW=1,GREEN=2; localparam MAIN_GREEN=0,MAIN_YELLOW=1,SIDE_GREEN=2,SIDE_YELLOW=3; reg [1:0] state,next_state;
always @(posedge clk or negedge rst_n) if(!rst_n) state<=MAIN_GREEN; else state<=next_state;
always @(*) begin next_state=state;if(emergency) next_state=MAIN_YELLOW; else case(state) MAIN_GREEN:next_state=MAIN_YELLOW;MAIN_YELLOW:next_state=SIDE_GREEN;SIDE_GREEN:next_state=SIDE_YELLOW;SIDE_YELLOW:next_state=MAIN_GREEN;default:next_state=MAIN_GREEN;endcase end
always @(*) begin main_light=RED;side_light=RED;if(emergency) begin main_light=YELLOW;side_light=YELLOW;end else case(state) MAIN_GREEN:main_light=GREEN;MAIN_YELLOW:main_light=YELLOW;SIDE_GREEN:side_light=GREEN;SIDE_YELLOW:side_light=YELLOW;default:begin main_light=RED;side_light=RED;end endcase end
endmodule
