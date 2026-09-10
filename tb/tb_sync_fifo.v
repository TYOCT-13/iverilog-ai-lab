`timescale 1ns/1ps
module tb_sync_fifo;
 reg clk=0,rst_n=0,wr_en=0,rd_en=0; reg [7:0] wr_data=0; wire [7:0] rd_data; wire full,empty;
 sync_fifo #(.DATA_WIDTH(8),.DEPTH(4)) dut(clk,rst_n,wr_en,wr_data,rd_en,rd_data,full,empty); always #5 clk=~clk;
 task rec; input ok; input [127:0] id; begin $display("IVERILOG_AI_RESULT {\"ok\":%s,\"test_id\":\"%s\"}",ok?"true":"false",id); end endtask
 initial begin rst_n=1; #2; rst_n=0; #2; if(empty) rec(1,"reset_empty"); else rec(0,"reset_empty"); rst_n=1; @(negedge clk); wr_data=8'hA5;wr_en=1; @(negedge clk); wr_en=0; if(empty) rec(0,"write_nonempty"); else rec(1,"write_nonempty"); @(negedge clk); rd_en=1; @(negedge clk); rd_en=0; #1; if(rd_data!==8'hA5) $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"read_data\",\"signal\":\"rd_data\",\"expected\":165,\"actual\":%0d}",rd_data); else rec(1,"read_data"); $finish; end
endmodule
