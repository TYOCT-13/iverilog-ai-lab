`timescale 1ns/1ps
// mux4 边界测试：四个选择值各选对通道、数据变化立即跟随、选择线来回切换。
module tb_mux4_boundary;
  localparam WIDTH = 8;

  reg [WIDTH-1:0] d0 = 8'h10;
  reg [WIDTH-1:0] d1 = 8'h20;
  reg [WIDTH-1:0] d2 = 8'h30;
  reg [WIDTH-1:0] d3 = 8'h40;
  reg [1:0] sel = 0;
  wire [WIDTH-1:0] y;

  integer errors;

  mux4 #(.WIDTH(WIDTH)) dut (.d0(d0), .d1(d1), .d2(d2), .d3(d3), .sel(sel), .y(y));

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
    // mux4 用 always @(*) 实现：时刻 0 的初值不构成"输入变化"，输出会停在 X。
    // 因此先显式驱动一次输入并让时间推进，组合输出才会求值。
    d0 = 8'h10; d1 = 8'h20; d2 = 8'h30; d3 = 8'h40;
    sel = 2'd0;
    #1;
    // 再切一次选择线，确保 always @(*) 已被至少一个事件触发过。
    sel = 2'd1; #1;
    sel = 2'd0; #1;

    // 四个取值互不相同，任何选择错误都会暴露
    sel = 2'd0; #1;
    check(0, "sel0_picks_d0", 8'h10, y);
    sel = 2'd1; #1;
    check(1, "sel1_picks_d1", 8'h20, y);
    sel = 2'd2; #1;
    check(2, "sel2_picks_d2", 8'h30, y);
    sel = 2'd3; #1;
    check(3, "sel3_picks_d3", 8'h40, y);

    // 数据变化必须在组合路径上立即跟随
    d1 = 8'hA5;
    sel = 2'd1; #1;
    check(4, "data_change_follows", 8'hA5, y);
    d2 = 8'h5A;
    sel = 2'd2; #1;
    check(5, "data_change_follows_2", 8'h5A, y);

    // 选择线切回 0 必须回到 d0
    sel = 2'd0; #1;
    check(6, "sel_back_to_d0", 8'h10, y);

    // 四个通道取互不相同且非原值的编码，防止靠通道间巧合蒙对
    d0 = 8'h01; d1 = 8'h02; d2 = 8'h04; d3 = 8'h08; #1;
    sel = 2'd3; #1;
    check(7, "sel3_distinct_values", 8'h08, y);
    sel = 2'd2; #1;
    check(8, "sel2_distinct_values", 8'h04, y);
    sel = 2'd1; #1;
    check(9, "sel1_distinct_values", 8'h02, y);
    sel = 2'd0; #1;
    check(10, "sel0_distinct_values", 8'h01, y);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_mux4_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_mux4_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
