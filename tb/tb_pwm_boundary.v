`timescale 1ns/1ps
// pwm 边界测试：0% 占空比恒低、满占空比近全高、中间占空比按比例翻转、极性正确。
//
// 参考实现语义：pwm_out 取的是"当前计数器值 < duty"，且计数器与输出在同一个
// 时钟沿更新，因此输出比计数器晚一拍生效。断言按这个语义设定。
module tb_pwm_boundary;
  localparam WIDTH = 8;

  reg clk = 0, rst_n = 0;
  reg [WIDTH-1:0] duty = 0;
  wire pwm_out;

  integer errors;
  integer high_count;
  integer k;

  pwm #(.WIDTH(WIDTH)) dut (.clk(clk), .rst_n(rst_n), .duty(duty), .pwm_out(pwm_out));

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

  // 在连续 clocks 个时钟沿统计 pwm_out 为高的次数。
  task count_high;
    input integer clocks;
    output integer observed;
    begin
      integer n;
      observed = 0;
      for (n = 0; n < clocks; n = n + 1) begin
        @(posedge clk);
        #1;
        if (pwm_out === 1'b1) observed = observed + 1;
      end
    end
  endtask

  initial begin
    errors = 0;

    // 复位：输出为低
    rst_n = 1; #2;
    rst_n = 0;
    @(posedge clk);
    #1;
    check(0, "reset_out_low", 0, pwm_out);
    rst_n = 1;
    @(negedge clk);

    // duty=0：输出必须恒低（计数器 < 0 永不成立）
    duty = 0;
    count_high(32, high_count);
    check(1, "duty_zero_all_low", 0, high_count);

    // duty=255：256 拍周期里只有计数器=255 的那一拍为低
    duty = 255;
    count_high(256, high_count);
    check(2, "duty_full_high_255_of_256", 255, high_count);

    // duty=128：256 拍周期里正好一半为高
    duty = 128;
    count_high(256, high_count);
    check(3, "duty_half_exactly_128", 128, high_count);

    // duty=1：256 拍周期里只有 1 拍为高
    duty = 1;
    count_high(256, high_count);
    check(4, "duty_one_exactly_1", 1, high_count);

    // duty=64：四分之一
    duty = 64;
    count_high(256, high_count);
    check(5, "duty_quarter_exactly_64", 64, high_count);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_pwm_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_pwm_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
