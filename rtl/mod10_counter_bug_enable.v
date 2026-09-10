// 缺陷：忽略enable，暂停请求仍会改变计数。
module mod10_counter (input wire clk, input wire rst_n, input wire enable, output reg [3:0] count);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) count <= 4'd0;
        else if (count == 4'd9) count <= 4'd0;
        else count <= count + 4'd1;
    end
endmodule
