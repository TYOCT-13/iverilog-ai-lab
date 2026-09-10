`timescale 1ns/1ps

module tb_johnson_counter;
    reg clk = 0; // 5 ns 时钟用于激励上升沿状态更新。
    reg rst_n = 1; // 低有效异步复位，先保持释放以产生可观测下降沿。
    reg enable = 0; // 移位使能输入，用于验证暂停与恢复。
    wire [3:0] q; // 被测约翰逊计数器的四位输出。
    integer errors; // 本测试台累计的失败检查数量。
    integer cycle_count; // 采样上升沿的单调周期编号。

    // 实例化被测设计，但不改写其源文件。
    johnson_counter dut ( // 连接约翰逊计数器实例。
        .clk(clk), // 连接测试台时钟。
        .rst_n(rst_n), // 连接低有效异步复位。
        .enable(enable), // 连接移位使能。
        .q(q) // 连接四位输出。
    );

    // 生成连续运行的仿真时钟。
    always #5 clk = ~clk;
    // 记录结构化结果使用的稳定周期编号。
    always @(posedge clk) cycle_count = cycle_count + 1;

    // 统一的结构化检查：期望值与实际值都是四位输出 q。
    task check;
        input [255:0] name;
        input [3:0] expected;
        input [3:0] actual;
        begin
            if (actual !== expected) begin
                errors = errors + 1;
                // X/Z 不能直接进 JSON（"actual":x 是非法 JSON），显式标注为 unknown。
                if ((^actual) === 1'bx) begin
                    $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"q\",\"expected\":%0d,\"actual\":\"unknown\",\"message\":\"johnson counter mismatch\"}", name, cycle_count, expected);
                end else begin
                    $display("IVERILOG_AI_RESULT {\"ok\":false,\"test_id\":\"%0s\",\"cycle\":%0d,\"signal\":\"q\",\"expected\":%0d,\"actual\":%0d,\"message\":\"johnson counter mismatch\"}", name, cycle_count, expected, actual);
                end
            end else begin
                $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"%0s\",\"cycle\":%0d}", name, cycle_count);
            end
        end
    endtask

    // 推进一个采样周期：在时钟低电平期间保持激励，沿之后采样。
    task tick;
        begin
            @(negedge clk);
            #1;
        end
    endtask

    // 按规格依次执行复位、自启动、完整 8 状态循环、暂停/恢复和序列中途复位。
    initial begin
        errors = 0;
        cycle_count = 0;

        // 在零时刻之后断言异步复位，确保复位边沿可被被测模块观察。
        #2;
        rst_n = 0;
        #1;
        check("reset_zero", 4'd0, q);

        // 自启动：0000 不是吸收态，使能后第一拍必须变成 0001。
        rst_n = 1;
        enable = 1;
        tick;
        check("self_start_1", 4'd1, q);
        tick;
        check("shift_2", 4'd3, q);
        tick;
        check("shift_3", 4'd7, q);
        tick;
        check("shift_4_all_ones", 4'd15, q);
        tick;
        check("shift_5", 4'd14, q);
        tick;
        check("shift_6", 4'd12, q);
        tick;
        check("shift_7", 4'd8, q);

        // 序列中途异步复位：不等待时钟沿，且与 enable 无关。
        rst_n = 0;
        #1;
        check("reset_mid_sequence", 4'd0, q);

        // 复位释放后必须能再次自启动（第二次进入 8 状态循环）。
        rst_n = 1;
        enable = 1;
        tick;
        check("restart_1", 4'd1, q);
        tick;
        check("restart_2", 4'd3, q);

        // 关闭使能：计数值必须保持，而不是继续移位。
        enable = 0;
        tick;
        check("hold_1", 4'd3, q);
        tick;
        check("hold_2", 4'd3, q);

        // 恢复使能后从暂停点继续。
        enable = 1;
        tick;
        check("resume_1", 4'd7, q);

        if (errors == 0)
            $display("> INFO: [Verilog] PASS johnson_counter");
        else
            $display("> ERR: [Verilog] FAIL johnson_counter errors=%0d", errors);
        $finish; // 结束本次确定性回归。
    end
endmodule
