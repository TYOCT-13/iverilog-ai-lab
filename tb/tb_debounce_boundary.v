`timescale 1ns/1ps
// debounce 边界测试：复位状态、短抖动抑制、稳定后跟随、门限计数与释放。
module tb_debounce_boundary;
  localparam COUNT_MAX = 3;

  reg clk = 0, rst_n = 0, key_in = 1;
  wire key_state;

  integer errors;

  debounce #(.COUNT_MAX(COUNT_MAX)) dut (
    .clk(clk), .rst_n(rst_n), .key_in(key_in), .key_state(key_state)
  );

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

    // 复位：稳定状态为释放（1）
    rst_n = 1; #2;
    rst_n = 0;
    @(posedge clk);
    #1;
    check(0, "reset_state_released", 1, key_state);
    rst_n = 1;
    @(negedge clk);

    // 短抖动（2 拍）不足以改变输出：门限为 COUNT_MAX=3
    key_in = 0;
    repeat (2) @(posedge clk);
    #1;
    check(1, "glitch_rejected_before_threshold", 1, key_state);

    // 稳定按下 COUNT_MAX 拍后输出跟随
    @(posedge clk);
    #1;
    check(2, "stable_press_follows", 0, key_state);

    // 保持按下时输出保持
    repeat (3) @(posedge clk);
    #1;
    check(3, "state_held_while_pressed", 0, key_state);

    // 释放侧同样需要稳定 COUNT_MAX 拍
    key_in = 1;
    @(posedge clk);
    #1;
    check(4, "release_glitch_rejected", 0, key_state);
    repeat (2) @(posedge clk);
    #1;
    check(5, "stable_release_follows", 1, key_state);

    // 计数必须在输入回到采样值时清零：短暂抖动后不应累积到门限
    key_in = 1;
    repeat (2) @(posedge clk);
    key_in = 0;
    @(posedge clk);
    #1;
    key_in = 1;
    @(posedge clk);
    #1;
    key_in = 0;
    repeat (2) @(posedge clk);
    #1;
    check(6, "counter_reset_on_match", 1, key_state);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_debounce_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_debounce_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
