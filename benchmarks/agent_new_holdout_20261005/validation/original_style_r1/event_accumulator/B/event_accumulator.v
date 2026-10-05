`timescale 1ns / 1ps

////////////////////////////////////English///////////////////////////////////////
// Company:         ICARUS AI Lab
// Engineer:        ICARUS
//
// Create Date:     2026/10/05 12:00:00
// Design Name:     event_accumulator
// Module Name:     event_accumulator
// Description:     description/event_accumulator_Design.pdf
// Simulations:     testbench/vivado/2021.1/event_accumulator
//
// Referrences:     None
//
// Dependencies:    None
//
// Version:         V1.0
// Revision Date:   2026/10/05 12:00:00
// History:
// Time             Version     Revised by        Contents
// 2026/10/05       V1.0        ICARUS            Create file.
///////////////////////////////////Chinese////////////////////////////////////////
// 版权归属:        ICARUS AI Lab
// 开发人员:        ICARUS
//
// 创建日期:        2026年10月05日
// 设计名称:        event_accumulator
// 模块名称:        event_accumulator
// 模块说明:        Description/event_accumulator_Design.pdf
// 仿真工程:        TestBench/Vivado/2021.1/event_accumulator
//
// 参考资料:        None
//
// 依赖文件:        None
//
// 当前版本:        V1.0
// 修订日期:        2026年10月05日
// 修订历史:
// 时间             版本        修订人            修订内容
// 2026年10月05日   V1.0        ICARUS            创建文件

module event_accumulator
(
	//-----------------全局信号-----------------//
	input i_clk,                                // 事件控制采样时钟
	input i_rstn,                               // 异步归零低有效复位

	//-----------------用户接口-----------------//
	input i_enable,                             // 当前事件累计许可
	input i_event,                              // 当拍事件存在标记
	input i_clear,                              // 不受累计许可限制的同步清除
	output [3:0]o_count                        // 最近清除以来接受事件数模十六
);

	//-----------------输出信号-----------------//
	//累计计数结果
	reg [3:0]count_o = 4'd0;                    // 四位环回事件计数寄存器

	//---------------输出信号连线---------------//
	//事件数量接口
	assign o_count = count_o;                  // 桥接已寄存的模十六计数到输出

	//-------------输出信号处理区域-------------//
	//计数状态更新
	//复位与清除优先，许可事件累计，其余保持数量
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			count_o <= 4'd0;
		end else if(i_clear)begin
			count_o <= 4'd0;
		end else if(i_event)begin
			count_o <= count_o + 4'd1;
		end else begin
			count_o <= count_o;
		end
	end

endmodule
