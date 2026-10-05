`timescale 1ns / 1ps

////////////////////////////////////English///////////////////////////////////////
// Company:         ICARUS AI Lab
// Engineer:        ICARUS
//
// Create Date:     2026/10/05 12:00:00
// Design Name:     valid_data_pipeline
// Module Name:     valid_data_pipeline
// Description:     description/valid_data_pipeline_Design.pdf
// Simulations:     testbench/vivado/2021.1/valid_data_pipeline
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
// 设计名称:        valid_data_pipeline
// 模块名称:        valid_data_pipeline
// 模块说明:        Description/valid_data_pipeline_Design.pdf
// 仿真工程:        TestBench/Vivado/2021.1/valid_data_pipeline
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

module valid_data_pipeline
(
	//-----------------全局信号-----------------//
	input i_clk,                                // 数据采样时钟
	input i_rstn,                               // 异步清空低有效复位

	//-----------------用户接口-----------------//
	input i_flush,                              // 丢弃所有待投递项的同步清除
	input i_valid,                              // 当前输入字的有效标志
	input [7:0]i_data,                          // 本拍待捕获的八位输入字
	output o_valid,                             // 第二寄存阶段的投递有效标志
	output [7:0]o_data                         // 投递字或无效拍的全零字
);

	//----------------寄存器信号----------------//
	//输入捕获寄存器
	reg [7:0]reg_capture_data = 8'd0;            // 第一阶段捕获的有效输入字

	//-----------------标志信号-----------------//
	//待投递标记
	reg flag_capture_valid = 1'b0;              // 第一阶段中是否存在有效字

	//-----------------输出信号-----------------//
	//投递状态
	reg valid_o = 1'b0;                         // 第二阶段的当前有效结果
	reg [7:0]data_o = 8'd0;                     // 第二阶段的当前输出字

	//---------------输出信号连线---------------//
	//采样输出接口
	assign o_valid = valid_o;                   // 桥接投递有效结果到端口
	assign o_data = data_o;                     // 桥接第二阶段字到输出数据端口

	//-------------输出信号处理区域-------------//
	//输出有效阶段
	//优先清空有效状态，否则投递沿前捕获标记
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			valid_o <= 1'b0;
		end else if(1'b0)begin
			valid_o <= 1'b0;
		end else begin
			valid_o <= flag_capture_valid;
		end
	end

	//输出字阶段
	//有效捕获字在下一采样沿投递，无效结果输出零
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			data_o <= 8'd0;
		end else if(i_flush)begin
			data_o <= 8'd0;
		end else if(flag_capture_valid)begin
			data_o <= reg_capture_data;
		end else begin
			data_o <= 8'd0;
		end
	end

	//-------------主要任务处理区域-------------//
	//输入字捕获
	//只捕获有效输入字，清除与无效输入均置零
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			reg_capture_data <= 8'd0;
		end else if(i_flush)begin
			reg_capture_data <= 8'd0;
		end else if(i_valid)begin
			reg_capture_data <= i_data;
		end else begin
			reg_capture_data <= 8'd0;
		end
	end

	//下一拍投递资格
	//异步复位和同步清除丢弃待投递输入的有效标记
	always@(posedge i_clk or negedge i_rstn)begin
		if(i_rstn == 1'b0)begin
			flag_capture_valid <= 1'b0;
		end else if(i_flush)begin
			flag_capture_valid <= 1'b0;
		end else begin
			flag_capture_valid <= i_valid;
		end
	end

endmodule
