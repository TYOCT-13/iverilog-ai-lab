`timescale 1ns/1ps
// edge_detector 功能测试：复位、上升沿单周期脉冲、保持期间不重复触发、下降沿不产生脉冲。
//
// 复位期间 signal_in 保持为高：这样"复位漏清历史寄存器"的缺陷会在复位释放后的
// 第一个时钟沿暴露为不确定值，而不是被此后的 signal_in=0 掩盖掉。
module tb_edge_detector;
  reg clk = 0;
  reg rst_n = 1;
  reg signal_in = 1;
  wire rising;

  integer errors;
  integer cycle_count;

  edge_detector dut (.clk(clk), .rst_n(rst_n), .signal_in(signal_in), .rising(rising));

  always #5 clk = ~clk;
  always @(posedge clk) cycle_count = cycle_count + 1;

  task check;
    input [255:0] name;
    input [63:0] expected;
    input [63:0] actual;
    begin
      if (actual !== expected) begin
        errors = errors + 1;
        // 历史寄存器未被复位时 rising 可能是 X；X/Z 不能直接进 JSON
        // （"actual":x 是非法 JSON），因此显式标注为 unknown。
        if ((^actual) === 1'bx) begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"rising\",\"expected\":%0d,\"actual\":\"unknown\"}", name, cycle_count, expected);
        end else begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"rising\",\"expected\":%0d,\"actual\":%0d}", name, cycle_count, expected, actual);
        end
      end else begin
        $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"%0s\",\"cycle\":%0d}", name, cycle_count);
      end
    end
  endtask

  // 推进一个采样周期：时钟低电平期间激励已稳定，沿之后 #1 采样。
  task tick;
    begin
      @(negedge clk);
      #1;
    end
  endtask

  initial begin
    errors = 0;
    cycle_count = 0;

    // 复位：signal_in 已经为高，rising 仍必须被异步清 0。
    #2;
    rst_n = 0;
    #1;
    check("reset_clears_rising", 0, rising);

    // 复位释放后的第一个采样周期必须出现脉冲（历史寄存器已被清 0）。
    rst_n = 1;
    tick;
    check("first_rise_after_reset", 1, rising);

    // 输入持续为高时只能有一个周期的脉冲。
    tick;
    check("pulse_is_single_cycle", 0, rising);

    // 下降沿不产生脉冲。
    signal_in = 0;
    tick;
    check("no_pulse_on_falling", 0, rising);
    tick;
    check("low_level_no_pulse", 0, rising);

    // 第二次上升沿必须再次产生单周期脉冲。
    signal_in = 1;
    tick;
    check("second_rise", 1, rising);
    tick;
    check("second_pulse_single_cycle", 0, rising);

    // 高电平期间异步复位：rising 立即回到 0。
    rst_n = 0;
    #1;
    check("reset_during_high", 0, rising);
    rst_n = 1;
    signal_in = 0;
    tick;
    check("post_reset_low", 0, rising);

    if (errors == 0)
      $display("> INFO: [Verilog] PASS edge_detector");
    else
      $display("> ERR: [Verilog] FAIL edge_detector errors=%0d", errors);
    $finish; // 结束本次确定性回归。
  end
endmodule
