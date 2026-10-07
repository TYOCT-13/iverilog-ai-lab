`timescale 1ns / 1ps

////////////////////////////////////English///////////////////////////////////////
// Company:         Erie
// Engineer:        Erie
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
// 版权归属:        Erie
// 开发人员:        Erie
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
	input i_clear,                              // 仅累计许可置位时执行的同步清除
	output [3:0]o_count                         // 最近清除以来接受事件数模十六
);

	//-----------------其他信号-----------------//
	//事件模累计算术
	wire [1:0]wire_priority_select;             // 清除与许可共同决定清除资格
	wire [1:0]wire_increment_select;            // 许可与事件构成两位计数选择码
	wire [4:0]wire_event_sum;                   // 包含溢出位的事件累计中间结果

	//-----------------输出信号-----------------//
	//用户接口
	reg [3:0]cnt_event_o = 4'd0;                // 四位环回事件计数寄存器

	//---------------其他信号连线---------------//
	//其他信号连线
	//事件模累计算术
	assign wire_priority_select = {i_clear, i_enable}; // 两位均为一时允许清除
	assign wire_increment_select = {i_enable, i_event}; // 保留各控制原始四态位值
	assign wire_event_sum = {1'b0, cnt_event_o} + 1'b1; // 显式扩位后保留事件进位

	//---------------输出信号连线---------------//
	//用户接口
	assign o_count = cnt_event_o[3:0];          // 桥接已寄存的模十六计数到输出

	//-------------输出信号处理区域-------------//
	//用户接口
	//复位优先，许可下先清除再累计，其余保持数量
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			cnt_event_o <= 4'd0;                // 异步复位终止当前事件累计区间
		end else begin
			case(wire_priority_select)
				2'b11:begin
					cnt_event_o <= 4'd0;        // 清除匹配后开始新的统计区间
				end
				default:begin
					case(wire_increment_select)
						2'b11:begin
							cnt_event_o <= wire_event_sum[3:0]; // 取低四位实现模十六累计
						end
						default:begin
							cnt_event_o <= cnt_event_o; // 其他控制组合保持当前数量
						end
					endcase
				end
			endcase
		end
	end

endmodule
