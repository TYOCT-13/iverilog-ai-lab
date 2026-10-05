`timescale 1ns/1ps

module tb_event_accumulator;
  reg [0:0] i_clk;
  reg [0:0] i_rstn;
  reg [0:0] i_enable;
  reg [0:0] i_event;
  reg [0:0] i_clear;
  wire [3:0] o_count;
  integer failures;
  integer checks;
  integer cycle;

  event_accumulator dut_i (.i_clk(i_clk), .i_rstn(i_rstn), .i_enable(i_enable), .i_event(i_event), .i_clear(i_clear), .o_count(o_count));

  initial i_clk = 1'b0;
  always #5 i_clk = ~i_clk;

  initial begin
    failures = 0;
    checks = 0;
    cycle = 0;
    i_clk = 1'b0;
    i_rstn = 1'b0;
    i_enable = 1'b0;
    i_event = 1'b0;
    i_clear = 1'b0;
    i_rstn = 1'b0;
    @( posedge i_clk );
    @( posedge i_clk );
    #1;
    i_rstn = 1'b1;
    #1;
    i_enable = 1'b1;
    i_event = 1'b1;
    i_clear = 1'b0;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_count !== 4'b0001) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, o_count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0001\",\"actual\":\"%b\"}", cycle, o_count);
    end
    cycle = cycle + 1;
    i_enable = 1'b1;
    i_event = 1'b1;
    i_clear = 1'b0;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_count !== 4'b0010) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, o_count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0010\",\"actual\":\"%b\"}", cycle, o_count);
    end
    cycle = cycle + 1;
    i_enable = 1'b1;
    i_event = 1'b1;
    i_clear = 1'b0;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_count !== 4'b0011) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, o_count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0011\",\"actual\":\"%b\"}", cycle, o_count);
    end
    cycle = cycle + 1;
    i_enable = 1'b1;
    i_event = 1'b1;
    i_clear = 1'b0;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_count !== 4'b0100) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, o_count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"normal\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0100\",\"actual\":\"%b\"}", cycle, o_count);
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
