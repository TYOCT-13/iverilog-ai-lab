`timescale 1ns/1ps

module tb_simple_alu;
  reg [7:0] a;
  reg [7:0] b;
  reg [2:0] op;
  wire [7:0] result;
  wire [0:0] carry;
  wire [0:0] zero;
  integer failures;
  integer checks;
  integer cycle;

  simple_alu dut_i (.a(a), .b(b), .op(op), .result(result), .carry(carry), .zero(zero));

  initial begin
    $dumpfile("waveform.vcd");
    $dumpvars(0, tb_simple_alu);
  end

  initial begin
    failures = 0;
    checks = 0;
    cycle = 0;
    a = 8'b0;
    b = 8'b0;
    op = 3'b0;
    a = 8'b11111111;
    b = 8'b00000001;
    op = 3'b000;
    #1;
    checks = checks + 1;
    if (result !== 8'b00000000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, result);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, result);
    end
    checks = checks + 1;
    if (carry !== 1'b1) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, carry);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, carry);
    end
    checks = checks + 1;
    if (zero !== 1'b1) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, zero);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"add_boundary\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, zero);
    end
    cycle = cycle + 1;
    a = 8'b11110000;
    b = 8'b00001111;
    op = 3'b010;
    #1;
    checks = checks + 1;
    if (result !== 8'b00000000) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, result);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000000\",\"actual\":\"%b\"}", cycle, result);
    end
    checks = checks + 1;
    if (carry !== 1'b0) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, carry);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, carry);
    end
    checks = checks + 1;
    if (zero !== 1'b1) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, zero);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"and_mask\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"1\",\"actual\":\"%b\"}", cycle, zero);
    end
    cycle = cycle + 1;
    a = 8'b00000011;
    b = 8'b00000000;
    op = 3'b101;
    #1;
    checks = checks + 1;
    if (result !== 8'b00000110) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000110\",\"actual\":\"%b\"}", cycle, result);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"result\",\"expected\":\"00000110\",\"actual\":\"%b\"}", cycle, result);
    end
    checks = checks + 1;
    if (carry !== 1'b0) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, carry);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"carry\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, carry);
    end
    checks = checks + 1;
    if (zero !== 1'b0) begin
      failures = failures + 1;
      $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, zero);
    end else begin
      $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"left_shift\",\"cycle\":%0d,\"signal\":\"zero\",\"expected\":\"0\",\"actual\":\"%b\"}", cycle, zero);
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
