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
    i_enable = 1'b0;
    i_event = 1'b1;
    @( posedge i_clk );
    #1;
    checks = checks + 1;
    if (o_count !== 4'b0000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"paused\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, o_count);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"paused\",\"cycle\":%0d,\"signal\":\"o_count\",\"expected\":\"0000\",\"actual\":\"%b\"}", cycle, o_count);
    end
    $display("IVERILOG_AI_OBSERVATION {\"cycle\":%0d,\"time_ns\":%.3f,\"test_id\":\"paused\",\"sample_phase\":\"after\",\"inputs\":{\"i_clk\":\"%b\",\"i_rstn\":\"%b\",\"i_enable\":\"%b\",\"i_event\":\"%b\",\"i_clear\":\"%b\"},\"outputs\":{\"o_count\":\"%b\"}}", cycle, $realtime, i_clk, i_rstn, i_enable, i_event, i_clear, o_count);
    cycle = cycle + 1;
    $display("IVERILOG_AI_SUMMARY {\"checks\":%0d,\"failures\":%0d,\"cycles\":%0d}", checks, failures, cycle);
    if (failures == 0) begin
      $finish(0);
    end else begin
      $finish(1);
    end
  end
endmodule
