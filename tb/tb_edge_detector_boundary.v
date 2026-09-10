`timescale 1ns/1ps
// edge_detector 边界测试：复位期间输入已为高、脉冲宽度恰好一拍、连续边沿、
// 高电平期间复位、下降沿不产生脉冲。
//
// 参考实现语义：低有效异步复位把历史寄存器和 rising 同时清 0；每拍
// rising = signal_in & ~signal_d，signal_d 记录上一拍的 signal_in，
// 因此一个上升沿只对应一个周期的脉冲。断言按这个语义设定。
module tb_edge_detector_boundary;
  reg clk = 0, rst_n = 1;
  reg signal_in = 1;
  wire rising;

  integer errors;
  integer cycle_count;
  integer pulses;

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

  // 在连续 clocks 个时钟沿统计 rising 为高的次数（X 不计入）。
  task count_pulses;
    input integer clocks;
    output integer observed;
    begin
      integer n;
      observed = 0;
      for (n = 0; n < clocks; n = n + 1) begin
        tick;
        if (rising === 1'b1) observed = observed + 1;
      end
    end
  endtask

  initial begin
    errors = 0;
    cycle_count = 0;

    // 复位边界：复位期间 signal_in 已经为高，历史寄存器必须被清 0，
    // 否则复位释放后的第一个时钟沿得不到确定的脉冲。
    rst_n = 1; #2;
    rst_n = 0; #1;
    check("reset_clears_rising_while_high", 0, rising);
    rst_n = 1;
    tick;
    check("first_edge_after_reset", 1, rising);
    tick;
    check("no_retrigger_while_high", 0, rising);

    // 低电平边界：输入持续为低不产生脉冲。
    signal_in = 0;
    count_pulses(4, pulses);
    check("pulse_count_while_low_is_0", 0, pulses);

    // 脉冲宽度边界：从低电平拉起后保持高 6 拍，整个窗口只能有 1 个脉冲
    // （窗口必须包含那个上升沿，否则统计不到任何脉冲）。
    signal_in = 1;
    count_pulses(6, pulses);
    check("pulse_count_while_high_is_1", 1, pulses);

    // 连续边沿边界：每个上升沿各产生一个脉冲，中间保持电平不产生。
    signal_in = 0;
    tick;
    check("edge_a_fall", 0, rising);
    signal_in = 1;
    tick;
    check("edge_a_rise", 1, rising);
    signal_in = 0;
    tick;
    check("edge_b_fall", 0, rising);
    signal_in = 1;
    tick;
    check("edge_b_rise", 1, rising);
    tick;
    check("edge_b_hold", 0, rising);

    // 高电平期间异步复位：rising 立即清 0；复位释放后输入仍为高，
    // 因为历史寄存器被清 0，第一个时钟沿重新产生一次脉冲。
    rst_n = 0; #1;
    check("reset_during_high", 0, rising);
    rst_n = 1;
    tick;
    check("pulse_after_reset_release", 1, rising);
    tick;
    check("no_retrigger_after_release", 0, rising);

    // 下降沿边界：1 → 0 不产生脉冲。
    signal_in = 0;
    count_pulses(2, pulses);
    check("falling_edge_no_pulse", 0, pulses);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_edge_detector_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_edge_detector_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
