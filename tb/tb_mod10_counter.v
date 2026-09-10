`timescale 1ns/1ps

module tb_mod10_counter;
    reg clk = 0; // 5 ns 时钟用于激励上升沿状态更新。
    reg rst_n = 1; // 低有效异步复位，先保持释放以产生可观测下降沿。
    reg enable = 0; // 计数使能输入，用于验证暂停与恢复。
    wire [3:0] count; // 被测模十计数器的四位输出。
    integer errors; // 本测试台累计的失败检查数量。
    integer cycle_count; // 采样上升沿的单调周期编号。
    integer test_id; // 当前结构化结果的测试编号。
    reg [3:0] expected_count; // 当前采样点的期望计数值。

    // 实例化被测设计，但不改写其源文件。
    mod10_counter dut ( // 连接模十计数器实例。
        .clk(clk), // 连接测试台时钟。
        .rst_n(rst_n), // 连接低有效异步复位。
        .enable(enable), // 连接计数使能。
        .count(count) // 连接计数输出。
    );

    // 生成连续运行的仿真时钟。
    always #5 clk = ~clk;
    // 记录结构化结果使用的稳定周期编号。
    always @(posedge clk) cycle_count = cycle_count + 1;

    // 按规格依次执行复位、暂停、连续计数和回绕场景。
    initial begin
        errors = 0;
        cycle_count = 0;

        // 在零时刻之后断言异步复位，确保复位边沿可被被测模块观察。
        #2;
        rst_n = 0;
        #1;
        if (count !== 4'd0) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"reset\",\"signal\":\"count\",\"expected\":0,\"actual\":%0d,\"message\":\"reset did not clear counter\"}", count);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"reset\"}");
        end

        rst_n = 1;
        enable = 1;
        // 连续使能时，前两个周期应递增。
        for (test_id = 1; test_id <= 2; test_id = test_id + 1) begin
            expected_count = test_id[3:0];
            @(negedge clk);
            #1;
            if (count !== expected_count) begin
                $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"count_%0d\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":%0d,\"actual\":%0d,\"message\":\"counter mismatch\"}", test_id, cycle_count, expected_count, count);
                errors = errors + 1;
            end else begin
                $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"count_%0d\",\"cycle\":%0d}", test_id, cycle_count);
            end
        end

        enable = 0;
        // 关闭使能时，计数值应在两个周期内保持不变。
        for (test_id = 3; test_id <= 4; test_id = test_id + 1) begin
            expected_count = 4'd2;
            @(negedge clk);
            #1;
            if (count !== expected_count) begin
                $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"count_%0d\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":%0d,\"actual\":%0d,\"message\":\"counter mismatch\"}", test_id, cycle_count, expected_count, count);
                errors = errors + 1;
            end else begin
                $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"count_%0d\",\"cycle\":%0d}", test_id, cycle_count);
            end
        end

        enable = 1;
        // 恢复使能后，验证递增至九以及九到零的回绕。
        for (test_id = 5; test_id <= 11; test_id = test_id + 1) begin
            expected_count = test_id - 2;
            @(negedge clk);
            #1;
            if (count !== expected_count) begin
                $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"count_%0d\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":%0d,\"actual\":%0d,\"message\":\"counter mismatch\"}", test_id, cycle_count, expected_count, count);
                errors = errors + 1;
            end else begin
                $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"count_%0d\",\"cycle\":%0d}", test_id, cycle_count);
            end
        end
        test_id = 12;
        expected_count = 4'd0;
        @(negedge clk);
        #1;
        if (count !== expected_count) begin
            $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"count_%0d\",\"cycle\":%0d,\"signal\":\"count\",\"expected\":%0d,\"actual\":%0d,\"message\":\"counter mismatch\"}", test_id, cycle_count, expected_count, count);
            errors = errors + 1;
        end else begin
            $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"count_%0d\",\"cycle\":%0d}", test_id, cycle_count);
        end

        if (errors == 0)
            $display("> INFO: [Verilog] PASS mod10_counter");
        else
            $display("> ERR: [Verilog] FAIL mod10_counter errors=%0d", errors);
        $finish; // 结束本次确定性回归。
    end
endmodule
