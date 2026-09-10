`timescale 1ns/1ps
// handshake_stage 边界测试：valid/ready 依赖、数据保持、重复传输、复位状态。
module tb_handshake_stage_boundary;
  localparam WIDTH = 8;

  reg clk = 0, rst_n = 0, in_valid = 0, out_ready = 0;
  reg [WIDTH-1:0] in_data = 0;
  wire in_ready, out_valid;
  wire [WIDTH-1:0] out_data;

  integer errors;

  handshake_stage #(.WIDTH(WIDTH)) dut (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
    .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data)
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

    // 复位：输出无效、数据清零、输入侧就绪
    rst_n = 1; #2;
    rst_n = 0;
    @(posedge clk);
    #1;
    check(0, "reset_out_valid_low", 0, out_valid);
    check(1, "reset_out_data_zero", 0, out_data);
    rst_n = 1;
    @(negedge clk);
    #1;
    check(2, "ready_when_idle", 1, in_ready);

    // 握手：下游不就绪时输入被接收、输出保持、数据保持
    out_ready = 0;
    in_data = 8'h3C;
    in_valid = 1;
    @(posedge clk);
    #1;
    check(3, "out_valid_after_accept", 1, out_valid);
    check(4, "out_data_after_accept", 8'h3C, out_data);
    check(5, "ready_low_while_blocked", 0, in_ready);

    // 数据保持：输入撤掉后输出数据不得改变
    in_valid = 0;
    in_data = 8'hFF;
    repeat (3) @(posedge clk);
    #1;
    check(6, "data_held_when_stalled", 8'h3C, out_data);
    check(7, "out_valid_held_when_stalled", 1, out_valid);

    // 消费：下游就绪后输出必须撤销
    out_ready = 1;
    @(posedge clk);
    #1;
    check(8, "out_valid_cleared_after_consume", 0, out_valid);
    check(9, "ready_high_after_consume", 1, in_ready);

    // 无输入时不得凭空产生有效输出，也不得把无效输入的数据写进输出寄存器。
    // out_ready=1 使 in_ready 为高，构成"允许接收、但没有有效数据"的场景：
    // 此时 out_data 必须保持为上一次真正被接收的值，不得跟随 in_data 变化。
    in_valid = 0;
    out_ready = 1;
    in_data = 8'hEE;
    repeat (3) @(posedge clk);
    #1;
    check(10, "no_spurious_valid", 0, out_valid);
    check(11, "data_held_when_no_valid", 8'h3C, out_data);

    // 重新发起一次握手，确认模块可重复使用且数据通路仍然正确。
    in_data = 8'h77;
    in_valid = 1;
    out_ready = 0;
    @(posedge clk);
    #1;
    check(12, "rehandshake_valid", 1, out_valid);
    check(13, "rehandshake_data", 8'h77, out_data);
    in_valid = 0;
    out_ready = 1;
    repeat (2) @(posedge clk);
    #1;
    check(14, "rehandshake_consumed", 0, out_valid);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_handshake_stage_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_handshake_stage_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
