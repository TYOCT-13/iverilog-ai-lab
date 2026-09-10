`timescale 1ns/1ps
// johnson_counter 边界测试：异步复位（含全 1 状态复位）、0000 自启动、8 拍周期、
// 使能暂停/恢复、暂停期间不复位则必须保持。
//
// 参考实现语义：低有效异步复位立即把 q 清 0；使能时每拍左移并反馈最高位的反相，
// 因此 0000 不是吸收态，序列为 0000 → 0001 → 0011 → 0111 → 1111 → 1110 → 1100
// → 1000 → 0000（8 个状态）。断言按这个语义设定。
module tb_johnson_counter_boundary;
  reg clk = 0, rst_n = 1;
  reg enable = 0;
  wire [3:0] q;

  integer errors;
  integer cycle_count;
  integer k;
  integer first_zero;

  johnson_counter dut (.clk(clk), .rst_n(rst_n), .enable(enable), .q(q));

  always #5 clk = ~clk;
  always @(posedge clk) cycle_count = cycle_count + 1;

  task check;
    input [255:0] name;
    input [63:0] expected;
    input [63:0] actual;
    begin
      if (actual !== expected) begin
        errors = errors + 1;
        // X/Z 不能直接进 JSON（"actual":x 是非法 JSON）。不确定值显式标注为
        // unknown，保证结构化记录始终可被严格解析器消费。
        if ((^actual) === 1'bx) begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"q\",\"expected\":%0d,\"actual\":\"unknown\"}", name, cycle_count, expected);
        end else begin
          $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"q\",\"expected\":%0d,\"actual\":%0d}", name, cycle_count, expected, actual);
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

    // 复位边界：异步复位不需要时钟沿，且与 enable 无关。
    rst_n = 1; #2;
    rst_n = 0; #1;
    check("async_reset_clears", 0, q);

    // 自启动 + 周期边界：从 0000 出发，连续使能 8 拍必须第一次回到 0000。
    rst_n = 1;
    enable = 1;
    first_zero = 0;
    for (k = 1; k <= 8; k = k + 1) begin
      tick;
      if (q === 4'd0 && first_zero == 0) first_zero = k;
      if (k == 4) check("all_ones_at_4th_shift", 15, q);
      if (k == 5) check("all_ones_shifts_to_1110", 14, q);
    end
    check("first_return_to_zero_at_8", 8, first_zero);
    check("period_is_eight_cycles", 0, q);

    // 全 1 状态下异步复位：必须立即回到 0000（不等待时钟沿）。
    tick; // 0001
    tick; // 0011
    tick; // 0111
    tick; // 1111
    check("reached_all_ones", 15, q);
    rst_n = 0; #1;
    check("async_reset_from_all_ones", 0, q);
    rst_n = 1;
    tick;
    check("self_start_after_reset", 1, q);

    // 使能暂停边界：序列中途关闭使能必须保持，恢复后从暂停点继续。
    tick; // 0011
    tick; // 0111
    check("before_hold", 7, q);
    enable = 0;
    tick;
    check("hold_1", 7, q);
    tick;
    check("hold_2", 7, q);
    tick;
    check("hold_3", 7, q);
    enable = 1;
    tick;
    check("resume_after_hold", 15, q);

    // 关闭使能且当前为 0000：必须一直保持 0000，不得自发移位。
    rst_n = 0; #1;
    check("reset_before_disabled_hold", 0, q);
    rst_n = 1;
    enable = 0;
    tick;
    tick;
    tick;
    check("no_shift_when_disabled", 0, q);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_johnson_counter_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_johnson_counter_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
