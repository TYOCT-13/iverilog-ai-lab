`timescale 1ns/1ps
// pulse_stretcher 边界测试：展宽长度、展宽期内重触发、输入保持、复位异步生效。
//
// 采样口径：所有检查都在 posedge 之后 #1 采样，因此第一个检查点就是**捕获沿**
// （脉冲被采到的那一拍）。在该口径下，输出采样为高的拍数恰好等于 WIDTH：
//
//   捕获沿：count<=WIDTH-1、pulse_out<=1
//   之后每拍：count 走 WIDTH-1 → … → 1 → 0，期间 pulse_out 保持 1
//   count=0 的那一拍：pulse_out 才算 0
//
// 也就是说"高 WIDTH 拍"来自 count 的旧值判断（非阻塞语义），不是 WIDTH+1。
// 该判据已由 tests/core/test_reference_model_alignment.py 与 RTL 逐拍对齐验证。
module tb_pulse_stretcher_boundary;
  reg clk = 0, rst_n = 0, pulse_in = 0;
  wire pulse_out;
  integer errors;

  pulse_stretcher #(.WIDTH(4)) dut(.clk(clk), .rst_n(rst_n), .pulse_in(pulse_in), .pulse_out(pulse_out));

  always #5 clk = ~clk;

  task check;
    input integer t_id;
    input [255:0] name;
    input [63:0] expected;
    input [63:0] actual;
    begin
      if (actual !== expected) begin
        errors = errors + 1;
        // X/Z 不能直接进 JSON（"actual":x 是非法 JSON）。不确定值显式标注为
        // unknown，保证结构化记录始终可被严格解析器消费。
        if ((^actual) === 1'bx) begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"signal\":\"%0s\",\"expected\":%0d,\"actual\":\"unknown\"}", name, name, expected);
        end else begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"signal\":\"%0s\",\"expected\":%0d,\"actual\":%0d}", name, name, expected, actual);
        end
      end else begin
        $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"%0s\"}", name);
      end
    end
  endtask

  initial begin
    errors = 0;

    // 复位期间输出必须为 0
    rst_n = 0; pulse_in = 0;
    repeat (2) @(posedge clk);
    #1;
    check(0, "reset_output_low", 0, pulse_out);

    rst_n = 1;
    @(posedge clk);
    #1;
    check(1, "idle_output_low", 0, pulse_out);

    // 单拍脉冲：高电平恰好 WIDTH=4 拍，第 5 拍回落
    @(negedge clk); pulse_in = 1;
    @(posedge clk); #1; check(2, "stretch_cycle1_high", 1, pulse_out);
    @(negedge clk); pulse_in = 0;
    @(posedge clk); #1; check(3, "stretch_cycle2_high", 1, pulse_out);
    @(posedge clk); #1; check(4, "stretch_cycle3_high", 1, pulse_out);
    @(posedge clk); #1; check(5, "stretch_cycle4_high", 1, pulse_out);
    @(posedge clk); #1; check(6, "stretch_cycle5_low", 0, pulse_out);

    // 展宽期内再次触发：计数必须被重新装载，展宽被延长而不是被忽略
    @(negedge clk); pulse_in = 1;
    @(posedge clk); #1; check(7, "retrigger_capture_high", 1, pulse_out);
    @(negedge clk); pulse_in = 0;
    @(posedge clk); #1; check(8, "retrigger_mid_high", 1, pulse_out);
    @(negedge clk); pulse_in = 1;   // 展宽中途再来一个脉冲
    @(posedge clk); #1; check(9, "retrigger_reload_high", 1, pulse_out);
    @(negedge clk); pulse_in = 0;
    @(posedge clk); #1; check(10, "retrigger_extended1_high", 1, pulse_out);
    @(posedge clk); #1; check(11, "retrigger_extended2_high", 1, pulse_out);
    @(posedge clk); #1; check(12, "retrigger_extended3_high", 1, pulse_out);
    @(posedge clk); #1; check(13, "retrigger_falls_low", 0, pulse_out);

    // 输入保持 3 拍：高电平 = 3 + (WIDTH-1) = 6 拍，第 7 拍回落
    @(negedge clk); pulse_in = 1;
    @(posedge clk); #1; check(14, "hold_cycle1_high", 1, pulse_out);
    @(posedge clk); #1; check(15, "hold_cycle2_high", 1, pulse_out);
    @(posedge clk); #1; check(16, "hold_cycle3_high", 1, pulse_out);
    @(negedge clk); pulse_in = 0;
    @(posedge clk); #1; check(17, "hold_tail1_high", 1, pulse_out);
    @(posedge clk); #1; check(18, "hold_tail2_high", 1, pulse_out);
    @(posedge clk); #1; check(19, "hold_tail3_high", 1, pulse_out);
    @(posedge clk); #1; check(20, "hold_tail4_low", 0, pulse_out);

    // 展宽期内异步复位：必须立刻拉低，而不是等到下一个时钟沿
    @(negedge clk); pulse_in = 1;
    @(posedge clk); #1; check(21, "before_async_reset_high", 1, pulse_out);
    rst_n = 0;
    #1;
    check(22, "async_reset_pulls_low", 0, pulse_out);

    // 释放复位后不得自行变高，必须等新的脉冲
    // （先把 pulse_in 拉低：否则释放后第一拍会立刻捕获这个脉冲，那是正确行为）
    pulse_in = 0;
    rst_n = 1;
    repeat (3) @(posedge clk);
    #1;
    check(23, "after_reset_stays_low", 0, pulse_out);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_pulse_stretcher_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_pulse_stretcher_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
