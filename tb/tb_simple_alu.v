`timescale 1ns/1ps
module tb_simple_alu;
    reg [7:0] a,b; // ALU 两个八位输入操作数。
    reg [2:0] op; // 算术、逻辑和移位操作编码。
    wire [7:0] result; // 被测 ALU 的八位结果。
    wire carry,zero; // 进位和零结果标志。
    integer errors; // 累计断言失败数量。
    simple_alu dut(.a(a),.b(b),.op(op),.result(result),.carry(carry),.zero(zero)); // 连接受控激励与被测设计。
    // 任务：检查一个操作的结果并输出机器可读的结构化记录。
    task check; input integer t_id; input [2:0] t_op; input [7:0] t_a,t_b,t_result; input t_carry,t_zero; // 任务参数包含操作、输入、期望结果和标志。
        begin
            op=t_op; a=t_a; b=t_b; #1;
            if(result!==t_result || carry!==t_carry || zero!==t_zero) begin
                errors=errors+1;
                $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"alu_%0d\",\"expected\":%0d,\"actual\":%0d}",t_id,t_result,result);
            end else begin
                $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"alu_%0d\",\"expected\":%0d,\"actual\":%0d}",t_id,t_result,result);
            end
        end
    endtask
    initial begin // 依次执行 ALU 边界和操作覆盖向量。
        errors=0;
        check(1,0,8'hf0,8'h20,8'h10,1,0);
        check(2,0,8'hff,8'h01,8'h00,1,1);
        check(3,1,8'h20,8'h05,8'h1b,1,0);
        check(4,2,8'hf0,8'h0f,0,0,1);
        check(5,3,8'hf0,8'h0f,8'hff,0,0);
        check(6,4,8'haa,8'h55,8'hff,0,0);
        check(7,5,8'h81,0,8'h02,0,0);
        check(8,6,8'h81,0,8'h40,0,0);
        check(9,0,0,0,0,0,1);
        if(errors==0) $display("> INFO: [Verilog] PASS simple_alu");
        else $display("> ERR: [Verilog] FAIL simple_alu errors=%0d",errors);
        $finish;
    end
endmodule
