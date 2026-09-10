// Icarus 智测受控基准：模十计数器
module mod10_counter (
    input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) count <= 4'd0;
        else if (enable) begin
            if (count == 4'd9) count <= 4'd0;
            else count <= count + 4'd1;
        end
    end
endmodule
