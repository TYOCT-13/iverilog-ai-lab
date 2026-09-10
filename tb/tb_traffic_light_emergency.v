`timescale 1ns/1ps

module tb_traffic_light_emergency;
    reg clk = 0; // 5 ns 时钟用于状态机采样。
    reg rst_n = 1; // 低有效异步复位，先保持释放以产生可观测下降沿。
    reg emergency = 0; // 紧急模式输入，覆盖正常状态输出。
    wire [1:0] main_light; // 主路灯编码：红=0、黄=1、绿=2。
    wire [1:0] side_light; // 支路灯编码：红=0、黄=1、绿=2。
    integer errors; // 本测试台累计的失败检查数量。
    integer cycle_count; // 采样上升沿的单调周期编号。
    integer test_id; // 当前结构化结果的测试编号。
    reg [1:0] expected_main; // 当前检查期望的主路灯编码。
    reg [1:0] expected_side; // 当前检查期望的支路灯编码。

    // 实例化被测设计，但不改写其源文件。
    traffic_light_emergency dut ( // 连接交通灯状态机实例。
        .clk(clk), // 连接测试台时钟。
        .rst_n(rst_n), // 连接低有效异步复位。
        .emergency(emergency), // 连接紧急模式控制。
        .main_light(main_light), // 连接主路灯输出。
        .side_light(side_light) // 连接支路灯输出。
    );

    // 生成连续运行的仿真时钟。
    always #5 clk = ~clk;
    // 记录结构化结果使用的稳定周期编号。
    always @(posedge clk) cycle_count = cycle_count + 1;

    // 按规格依次执行复位、紧急模式和正常状态循环场景。
    initial begin
        errors = 0;
        cycle_count = 0;

        #2;
        rst_n = 0;
        @(negedge clk);
        #1;
        test_id = 1;
        expected_main = 2;
        expected_side = 0;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end

        rst_n = 1;
        emergency = 1;
        #1;
        test_id = 2;
        expected_main = 1;
        expected_side = 0;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end
        @(negedge clk);
        #1;
        test_id = 3;
        expected_main = 1;
        expected_side = 0;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end

        emergency = 0;
        @(negedge clk);
        #1;
        test_id = 4;
        expected_main = 0;
        expected_side = 2;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end
        @(negedge clk);
        #1;
        test_id = 5;
        expected_main = 0;
        expected_side = 1;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end
        @(negedge clk);
        #1;
        test_id = 6;
        expected_main = 2;
        expected_side = 0;
        if (main_light !== expected_main || side_light !== expected_side) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"lights_%0d\",\"cycle\":%0d,\"signal\":\"main_light\",\"expected\":%0d,\"actual\":%0d,\"message\":\"traffic light mismatch; side expected=%0d actual=%0d\"}", test_id, cycle_count, expected_main, main_light, expected_side, side_light);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"lights_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end

        if (errors == 0)
            $display("> INFO: [Verilog] PASS traffic_light_emergency");
        else
            $display("> ERR: [Verilog] FAIL traffic_light_emergency errors=%0d", errors);
        $finish; // 结束本次确定性回归。
    end
endmodule
