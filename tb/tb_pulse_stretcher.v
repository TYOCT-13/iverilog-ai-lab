`timescale 1ns/1ps
// 功能 testbench：复位后输出为 0；一个脉冲后输出为 1（展宽生效）。
//
// 参数必须与 examples/pulse_stretcher_contract.json 一致（WIDTH=4），否则"合约声明
// 的电路"与"这条 testbench 驱动的电路"是两个不同配置。展宽长度、展宽期内重触发、
// 输入保持与异步复位等边界见 tb/tb_pulse_stretcher_boundary.v。
//
// 复位必须先拉高再拉低：`rst_n` 初值即为 0 时再赋 0 不会产生 negedge，异步复位
// 永远不触发，输出会停在 X——而 X 值不能直接进 JSON（`"actual":x` 是非法 JSON），
// 记录会被严格解析器判为 malformed。这里统一把不确定值标注为 unknown。
module tb_pulse_stretcher;
  reg clk=0, rst_n=0, pulse_in=0;
  wire pulse_out;

  pulse_stretcher #(.WIDTH(4)) dut(clk, rst_n, pulse_in, pulse_out);
  always #5 clk=~clk;

  task check;
    input [255:0] name;
    input [63:0] expected;
    input [63:0] actual;
    begin
      if (actual !== expected) begin
        if ((^actual) === 1'bx) begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"signal\":\"pulse_out\",\"expected\":%0d,\"actual\":\"unknown\"}", name, expected);
        end else begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"signal\":\"pulse_out\",\"expected\":%0d,\"actual\":%0d}", name, expected, actual);
        end
      end else begin
        $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"%0s\"}", name);
      end
    end
  endtask

  initial begin
    rst_n = 1; #2; rst_n = 0; #1;
    check("reset_low", 0, pulse_out);

    rst_n = 1;
    @(negedge clk); pulse_in = 1;
    @(posedge clk); #1;
    check("stretch_high", 1, pulse_out);

    @(negedge clk); pulse_in = 0;
    repeat (8) @(negedge clk);
    check("stretch_falls_low", 0, pulse_out);
    $finish(0);
  end
endmodule
