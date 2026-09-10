`timescale 1ns/1ps
module tb_sequence_101_overlap;
    reg clk = 1'b0; // 串行时钟，从确定的 0 开始产生边沿。
    reg rst_n = 1'b1; // 低有效异步复位，先产生下降沿再释放。
    reg bit_in = 1'b0; // 串行输入比特。
    wire detected; // 被测序列检测脉冲输出。
    integer errors = 0,i; // 错误计数与串行位索引。
    reg [7:0] stream = 8'b10101000; // 固定输入序列 10101000。
    reg [7:0] expected = 8'b00101000; // 第 3、5 个采样沿命中 101。
    sequence_101_overlap dut(.clk(clk),.rst_n(rst_n),.bit_in(bit_in),.detected(detected)); // 连接串行激励与被测设计。
    always #5 clk=~clk; // 生成连续运行的十纳秒采样时钟。
    initial begin // 施加复位并逐位比较重叠检测结果。
        #1 rst_n = 1'b0; // 显式产生复位下降沿，清零 DUT 历史状态。
        #2 rst_n = 1'b1; // 释放复位后再开始采样。
        for(i=7;i>=0;i=i-1) begin @(negedge clk);bit_in=stream[i];@(posedge clk);#1;if(detected!==expected[i]) begin errors=errors+1;$display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"seq_%0d\",\"expected\":%0d,\"actual\":%0d}",8-i,expected[i],detected);end else $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"seq_%0d\"}",8-i); end
        if(errors==0)$display("> INFO: [Verilog] PASS sequence_101_overlap"); else $display("> ERR: [Verilog] FAIL sequence_101_overlap errors=%0d",errors);$finish; end
endmodule
