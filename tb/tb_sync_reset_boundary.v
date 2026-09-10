`timescale 1ns/1ps
// sync_reset 边界测试：复位同步器级数、极性、释放延迟、重新拉低可立即生效。
module tb_sync_reset_boundary;
  reg clk = 0, ext_rst_n = 1;
  wire rst_n;
  integer errors;

  sync_reset dut (.clk(clk), .ext_rst_n(ext_rst_n), .rst_n(rst_n));

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

    // ext_rst_n 拉低后，同步复位输出必须为低（异步置位路径）
    ext_rst_n = 1; #1;
    ext_rst_n = 0;
    #1;
    check(0, "assert_pulls_low", 0, rst_n);

    // 释放后第一个时钟沿：第二级仍未被第一级灌入 1，输出必须仍为低
    ext_rst_n = 1;
    @(posedge clk);
    #1;
    check(1, "release_first_edge_still_low", 0, rst_n);

    // 第二个时钟沿：两级同步完成，输出必须为高
    @(posedge clk);
    #1;
    check(2, "release_second_edge_high", 1, rst_n);

    // 保持高
    repeat (3) @(posedge clk);
    #1;
    check(3, "stays_high", 1, rst_n);

    // 重新拉低必须立即生效（异步）
    ext_rst_n = 0;
    #1;
    check(4, "reassert_immediate_low", 0, rst_n);

    // 再次释放，行为必须可重复
    ext_rst_n = 1;
    @(posedge clk);
    #1;
    check(5, "second_release_first_edge", 0, rst_n);
    @(posedge clk);
    #1;
    check(6, "second_release_second_edge", 1, rst_n);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_sync_reset_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_sync_reset_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
