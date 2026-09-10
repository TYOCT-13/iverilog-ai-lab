`timescale 1ns/1ps
// uart_tx 边界测试：起始位极性、LSB 先发位序、停止位、busy 生命周期。
module tb_uart_tx_boundary;
  localparam CLKS_PER_BIT = 2;
  reg clk = 0, rst_n = 0, start = 0;
  reg [7:0] data_in = 8'h00;
  wire tx, busy;
  integer errors;
  integer i;
  reg seen_start, seen_stop, seen_stop_late, rx_bit;
  reg [7:0] rx_shift;
  reg [3:0] rx_count;

  uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut (
    .clk(clk), .rst_n(rst_n), .start(start), .data_in(data_in), .tx(tx), .busy(busy)
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
        // X/Z 不能直接进 JSON（"actual":x 是非法 JSON）。这里把不确定值
        // 显式标注为 unknown，保证结构化记录始终可被严格解析器消费。
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

  // 在稳定点采样 tx（往前推进若干时钟沿后取值）。
  // Verilog 函数不能包含延时，因此这里用 task + output 实现。
  task sample_tx;
    input integer edges;
    output value;
    begin
      repeat (edges) @(posedge clk);
      #1;
      value = tx;
    end
  endtask

  initial begin
    errors = 0;
    seen_start = 0; seen_stop = 0; rx_shift = 0; rx_count = 0;

    // 复位：tx 空闲为高，busy 为 0
    rst_n = 1; #2;
    rst_n = 0;
    @(posedge clk);
    #1;
    check(0, "reset_tx_idle_high", 1, tx);
    check(1, "reset_busy_low", 0, busy);
    rst_n = 1;
    @(negedge clk);

    // 启动一帧，数据 8'hA5 = 1010_0101，LSB 先发
    data_in = 8'hA5;
    start = 1;
    @(negedge clk);
    start = 0;
    @(posedge clk);
    #1;
    check(2, "busy_after_start", 1, busy);
    check(3, "start_bit_low", 0, tx);

    // 逐位采样：第 k 位应为 data_in[k]
    for (i = 0; i < 8; i = i + 1) begin
      sample_tx(CLKS_PER_BIT, rx_bit);
      rx_shift[i] = rx_bit;
    end
    check(4, "received_byte_lsb_first", 8'hA5, rx_shift);

    // 停止位判据：数据位走完后、busy 释放前，tx 必须保持高电平。
    // 停止位被拉低的缺陷会让其中某一拍变成 0，因此连续采两拍再与 1 比较，
    // 比只采一拍更稳健（只采一拍可能刚好落在参考与缺陷都相同的相位上）。
    sample_tx(1, seen_stop);
    check(5, "stop_bit_high", 1, seen_stop);
    sample_tx(1, seen_stop_late);
    check(8, "stop_bit_high_late", 1, seen_stop_late);
    repeat (CLKS_PER_BIT * 3) @(posedge clk);
    #1;
    check(6, "busy_released_after_frame", 0, busy);
    check(7, "tx_idle_after_frame", 1, tx);

    // 第二帧使用位序互补的数据，进一步锁定位序
    data_in = 8'h3C;
    start = 1;
    @(negedge clk);
    @(negedge clk);
    start = 0;
    @(posedge clk);
    #1;
    check(8, "start_bit_low_2", 0, tx);
    rx_shift = 0;
    for (i = 0; i < 8; i = i + 1) begin
      sample_tx(CLKS_PER_BIT, rx_bit);
      rx_shift[i] = rx_bit;
    end
    check(9, "received_byte_2", 8'h3C, rx_shift);

    if (errors == 0) begin
      $display("> INFO: [Verilog] PASS tb_uart_tx_boundary");
      $finish(0);
    end else begin
      $display("> ERR: [Verilog] FAIL tb_uart_tx_boundary errors=%0d", errors);
      $finish(1);
    end
  end
endmodule
