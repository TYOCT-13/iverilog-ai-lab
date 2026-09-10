// 缺陷：紧急模式只改变下一状态，当前输出仍可能显示主路绿灯。
module traffic_light_emergency(input wire clk,input wire rst_n,input wire emergency,output reg [1:0] main_light,output reg [1:0] side_light);
    localparam RED=0,YELLOW=1,GREEN=2; localparam MG=0,MY=1,SG=2,SY=3;
    reg [1:0] state,next_state;
    always @(posedge clk or negedge rst_n) if(!rst_n) state<=MG; else state<=next_state;
    always @(*) begin next_state=state; if(emergency) next_state=MY; else case(state) MG:next_state=MY; MY:next_state=SG; SG:next_state=SY; SY:next_state=MG; default:next_state=MG; endcase end
    always @(*) begin main_light=RED;side_light=RED; case(state) MG:main_light=GREEN; MY:main_light=YELLOW; SG:side_light=GREEN; SY:side_light=YELLOW; endcase end
endmodule
