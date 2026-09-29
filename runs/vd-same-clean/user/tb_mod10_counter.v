`timescale 1ns/1ps

module tb_mod10_counter;
  reg [0:0] clk;
  reg [0:0] rst_n;
  reg [0:0] enable;
  wire [3:0] count;
  integer failures;
  integer checks;
  integer cycle;

  mod10_counter dut_i (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));

  initial begin
    $dumpfile("waveform.vcd");
    $dumpvars(0, tb_mod10_counter);
  end

  initial clk = 1'b0;
  always #5 clk = ~clk;

  initial begin
    failures = 0;
    checks = 0;
    cycle = 0;
    clk = 1'b0;
    rst_n = 1'b0;
    enable = 1'b0;
    rst_n = 1'b0;
    @( posedge clk );
    @( posedge clk );
    #1;
    rst_n = 1'b1;
    #1;
    rst_n = 1'b0;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_reset\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_reset\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_01\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_01\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0010) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_02\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_02\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0011) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_03\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_03\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0011) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_04\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_04\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0100) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_05\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_05\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0101) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_06\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_06\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0110) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_07\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_07\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0110) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_08\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_08\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0111) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_09\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0111\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_09\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0111\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_10\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_10\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_11\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_11\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_12\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_12\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_13\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_13\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_14\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_14\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0010) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_15\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_15\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0010) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_16\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_16\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0011) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_17\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_17\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0100) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_18\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_18\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0101) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_19\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_19\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0101) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_20\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_20\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0101\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0110) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_21\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_21\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0110\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0111) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_22\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0111\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_22\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0111\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_23\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_23\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b0;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_24\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_24\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_edge_01\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_edge_01\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b0;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_edge_02\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_edge_02\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b1001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_edge_03\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_edge_03\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"1001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    cycle = cycle + 1;
    rst_n = 1'b1;
    enable = 1'b1;
    @( posedge clk );
    #1;
    checks = checks + 1;
    if (count !== 4'b0001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"debug_edge_04\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"debug_edge_04\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, count);
    end
    cycle = cycle + 1;
    $display("IVERILOG_AI_SUMMARY {\"checks\":%0d,\"failures\":%0d,\"cycles\":%0d}", checks, failures, cycle);
    if (failures == 0) begin
      $finish(0);
    end else begin
      $finish(1);
    end
  end
endmodule
