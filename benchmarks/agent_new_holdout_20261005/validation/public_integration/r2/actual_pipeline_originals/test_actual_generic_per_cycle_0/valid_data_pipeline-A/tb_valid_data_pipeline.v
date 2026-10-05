`timescale 1ns/1ps

module tb_valid_data_pipeline;
  reg [0:0] i_clk;
  reg [0:0] i_rstn;
  reg [0:0] i_flush;
  reg [0:0] i_valid;
  reg [7:0] i_data;
  wire [0:0] o_valid;
  wire [7:0] o_data;
  integer failures;
  integer checks;
  integer cycle;

  valid_data_pipeline dut_i (.i_clk(i_clk), .i_rstn(i_rstn), .i_flush(i_flush), .i_valid(i_valid), .i_data(i_data), .o_valid(o_valid), .o_data(o_data));

  initial i_clk = 1'b0;
  always #5 i_clk = ~i_clk;

  initial begin
    failures = 0;
    checks = 0;
    cycle = 0;
    i_clk = 1'b0;
    i_rstn = 1'b0;
    i_flush = 1'b0;
    i_valid = 1'b0;
    i_data = 8'b0;
    i_rstn = 1'b0;
    @( posedge i_clk );
    @( posedge i_clk );
    #1;
    i_rstn = 1'b1;
    #1;
    i_valid = 1'b1;
    i_data = 8'b10100101;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_valid !== 1'b0) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"accept\",\"cycle\":%0d,\"signal\":\"o_valid\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, o_valid);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"accept\",\"cycle\":%0d,\"signal\":\"o_valid\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, o_valid);
    end
    checks = checks + 1;
    if (o_data !== 8'b00000000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"accept\",\"cycle\":%0d,\"signal\":\"o_data\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, o_data);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"accept\",\"cycle\":%0d,\"signal\":\"o_data\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, o_data);
    end
    $display("IVERILOG_AI_OBSERVATION {\"cycle\":%0d,\"time_ns\":%.3f,\"test_id\":\"accept\",\"sample_phase\":\"after\",\"inputs\":{\"i_clk\":\"%b\",\"i_rstn\":\"%b\",\"i_flush\":\"%b\",\"i_valid\":\"%b\",\"i_data\":\"%b\"},\"outputs\":{\"o_valid\":\"%b\",\"o_data\":\"%b\"}}", cycle, $realtime, i_clk, i_rstn, i_flush, i_valid, i_data, o_valid, o_data);
    cycle = cycle + 1;
    i_valid = 1'b0;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_valid !== 1'b1) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"next\",\"cycle\":%0d,\"signal\":\"o_valid\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, o_valid);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"next\",\"cycle\":%0d,\"signal\":\"o_valid\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, o_valid);
    end
    checks = checks + 1;
    if (o_data !== 8'b10100101) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"next\",\"cycle\":%0d,\"signal\":\"o_data\",\"expected\":\"10100101\",\"actual\":\"%b\"}", cycle, o_data);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"next\",\"cycle\":%0d,\"signal\":\"o_data\",\"expected\":\"10100101\",\"actual\":\"%b\"}", cycle, o_data);
    end
    $display("IVERILOG_AI_OBSERVATION {\"cycle\":%0d,\"time_ns\":%.3f,\"test_id\":\"next\",\"sample_phase\":\"after\",\"inputs\":{\"i_clk\":\"%b\",\"i_rstn\":\"%b\",\"i_flush\":\"%b\",\"i_valid\":\"%b\",\"i_data\":\"%b\"},\"outputs\":{\"o_valid\":\"%b\",\"o_data\":\"%b\"}}", cycle, $realtime, i_clk, i_rstn, i_flush, i_valid, i_data, o_valid, o_data);
    cycle = cycle + 1;
    $display("IVERILOG_AI_SUMMARY {\"checks\":%0d,\"failures\":%0d,\"cycles\":%0d}", checks, failures, cycle);
    if (failures == 0) begin
      $finish(0);
    end else begin
      $finish(1);
    end
  end
endmodule
