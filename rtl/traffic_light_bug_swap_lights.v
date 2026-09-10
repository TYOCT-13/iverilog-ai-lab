module traffic_light_emergency(input wire clk,rst_n,emergency,output reg [1:0] main_light,side_light);
always @(posedge clk or negedge rst_n) begin if(!rst_n) begin main_light<=2;side_light<=0;end else if(emergency) begin main_light<=1;side_light<=0;end else begin main_light<=side_light;side_light<=main_light;end end
endmodule
