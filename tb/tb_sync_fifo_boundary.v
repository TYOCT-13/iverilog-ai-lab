`timescale 1ns/1ps
// sync_fifo 边界测试：写满、满时写、空读、顺序、指针回绕。
// 每个可观测检查输出一行 IVERILOG_AI_RESULT 结构化记录。
module tb_sync_fifo_boundary;
  localparam DEPTH = 4;
  reg clk = 0, rst_n = 0, wr_en = 0, rd_en = 0;
  reg [7:0] wr_data = 0;
  wire [7:0] rd_data;
  wire full, empty;
  integer errors;
  integer i;

  // 测试平台自持的行为模型，用于生成独立期望序列（不读取 DUT 内部信号）。
  reg [7:0] expect_mem [0:DEPTH-1];
  integer wr_model = 0, rd_model = 0, count_model = 0;
  reg [7:0] expect_data;

  sync_fifo #(.DATA_WIDTH(8), .DEPTH(DEPTH)) dut (
    .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data),
    .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty)
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

  task do_write;
    input [7:0] value;
    begin
      @(negedge clk);
      wr_data = value;
      wr_en = 1;
      expect_mem[wr_model] = value;
      wr_model = (wr_model + 1) % DEPTH;
      count_model = count_model + 1;
      @(negedge clk);
      wr_en = 0;
      #1;
    end
  endtask

  task do_read;
    output [7:0] value;
    begin
      @(negedge clk);
      rd_en = 1;
      expect_data = expect_mem[rd_model];
      rd_model = (rd_model + 1) % DEPTH;
      count_model = count_model - 1;
      @(negedge clk);
      rd_en = 0;
      #1;
      value = rd_data;
    end
  endtask

  initial begin
    errors = 0;
    wr_model = 0; rd_model = 0; count_model = 0;

    // 复位：empty 为高，且读数据必须被清零
    rst_n = 1; #2;
    rst_n = 0;
    @(posedge clk);
    #1;
    check(0, "reset_empty", 1, empty);
    check(14, "reset_rd_data_zero", 0, rd_data);
    rst_n = 1;
    @(negedge clk);
    #1;

    // 写满 4 个：写满后 full 必须为 1
    do_write(8'hA5);
    @(negedge clk); #1;
    check(1, "count1_not_full", 0, full);
    do_write(8'h5A);
    do_write(8'hC3);
    do_write(8'h3C);
    @(negedge clk); #1;
    check(2, "full_after_4_writes", 1, full);
    check(3, "not_empty_when_full", 0, empty);

    // 满时继续写必须被丢弃：FIFO 内容与指针都不得改变。
    // 先记录当前最旧的一个数据，再试图越界写入，随后读回验证顺序未被打乱。
    do_write(8'hEE);
    @(negedge clk); #1;
    check(15, "still_full_after_overflow_write", 1, full);

    // 读第一个：内容必须按写入顺序返回
    do_read(expect_data);
    check(4, "read_order_1", 8'hA5, expect_data);
    check(5, "full_cleared_after_read", 0, full);
    check(6, "empty_cleared_when_count3", 0, empty);

    // 指针回绕：再写 1 个（写到槽位 0），然后再读 3 个验证顺序
    do_write(8'h69);
    @(negedge clk); #1;
    check(7, "full_after_wrap_write", 1, full);
    do_read(expect_data);
    check(8, "read_order_2", 8'h5A, expect_data);
    do_read(expect_data);
    check(9, "read_order_3", 8'hC3, expect_data);
    do_read(expect_data);
    check(10, "read_order_4", 8'h3C, expect_data);
    do_read(expect_data);
    check(11, "read_order_5_wrapped", 8'h69, expect_data);

    // 读空后 empty 必须为 1
    @(negedge clk); #1;
    check(12, "empty_after_drain", 1, empty);
    check(13, "not_full_after_drain", 0, full);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_sync_fifo_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_sync_fifo_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
