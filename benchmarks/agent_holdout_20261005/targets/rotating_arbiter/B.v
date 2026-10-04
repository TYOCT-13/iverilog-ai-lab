`timescale 1ns / 1ps
// Company       : ICARUS project
// Engineer      : Automated generation
// Create Date   : 2026-10-05
// Design Name   : Registered rotating priority arbiter
// Module Name   : rotating_arbiter
// Description   : Four requesters with a rotating starting position
// Simulations   : Local Icarus Verilog
// Referrences   : spec/agent_holdout_20261005/rotating_arbiter_spec.md
// Dependencies  : None
// 版权归属       : ICARUS 项目
// 开发人员       : 自动生成
// 创建日期       : 2026-10-05
// 设计名称       : 寄存轮转优先仲裁
// 模块名称       : rotating_arbiter
// 模块说明       : 四个请求者的循环优先级选择
// 仿真工程       : 本地 Icarus Verilog
// 参考资料       : spec/agent_holdout_20261005/rotating_arbiter_spec.md
// 依赖文件       : 无

module rotating_arbiter
(
	//---------------全局信号---------------//
	input clk,                                // 仲裁结果寄存的上升沿时钟
	input rst_n,                              // 优先起点和结果的异步低复位

	//---------------用户接口---------------//
	input [3:0] request,                      // 四个请求位置的有效位
	input advance,                            // 允许下一拍改变优先起点
	output [3:0] grant                        // 本拍选中的独热请求
);

//--------------寄存信号区域--------------//
// 优先起点是跨拍保存的仲裁状态
reg [1:0] reg_pointer;                       // 当前扫描顺序的首个位置

//--------------编码信号区域--------------//
// 选择编码与独热译码共享同一优先级判断
reg [1:0] enc_selected;                      // 当前组合判定的请求编号
reg [3:0] dec_grant;                         // 将选中编号转为独热许可
reg flag_selected;                          // 区分有效选择与空请求

//--------------输出信号区域--------------//
// 寄存输出使本拍选择不受后续输入改变
reg [3:0] grant_o;                           // 保持最新时钟边沿的仲裁结果

//--------------输出赋值区域--------------//
assign grant = grant_o;                      // 将已寄存许可连接到接口

//--------------组合处理区域--------------//
// 从旧起点按四种静态次序寻找第一个请求
always@(*)begin
	enc_selected = 2'd0;                    // 空请求的编码占位值
	dec_grant = 4'b0000;                    // 未选中时所有许可撤销
	flag_selected = 1'b0;                   // 默认没有可服务的请求
	case(reg_pointer)
		2'd0:begin
			if(request[0])begin
				enc_selected = 2'd0;
				dec_grant = 4'b0001;
				flag_selected = 1'b1;
			end else if(request[1])begin
				enc_selected = 2'd1;
				dec_grant = 4'b0010;
				flag_selected = 1'b1;
			end else if(request[2])begin
				enc_selected = 2'd2;
				dec_grant = 4'b0100;
				flag_selected = 1'b1;
			end else if(request[3])begin
				enc_selected = 2'd3;
				dec_grant = 4'b1000;
				flag_selected = 1'b1;
			end else begin
				flag_selected = 1'b0;
			end
		end
		2'd1:begin
			if(request[1])begin
				enc_selected = 2'd1;
				dec_grant = 4'b0010;
				flag_selected = 1'b1;
			end else if(request[2])begin
				enc_selected = 2'd2;
				dec_grant = 4'b0100;
				flag_selected = 1'b1;
			end else if(request[3])begin
				enc_selected = 2'd3;
				dec_grant = 4'b1000;
				flag_selected = 1'b1;
			end else if(request[0])begin
				enc_selected = 2'd0;
				dec_grant = 4'b0001;
				flag_selected = 1'b1;
			end else begin
				flag_selected = 1'b0;
			end
		end
		2'd2:begin
			if(request[2])begin
				enc_selected = 2'd2;
				dec_grant = 4'b0100;
				flag_selected = 1'b1;
			end else if(request[3])begin
				enc_selected = 2'd3;
				dec_grant = 4'b1000;
				flag_selected = 1'b1;
			end else if(request[0])begin
				enc_selected = 2'd0;
				dec_grant = 4'b0001;
				flag_selected = 1'b1;
			end else if(request[1])begin
				enc_selected = 2'd1;
				dec_grant = 4'b0010;
				flag_selected = 1'b1;
			end else begin
				flag_selected = 1'b0;
			end
		end
		default:begin
			if(request[3])begin
				enc_selected = 2'd3;
				dec_grant = 4'b1000;
				flag_selected = 1'b1;
			end else if(request[0])begin
				enc_selected = 2'd0;
				dec_grant = 4'b0001;
				flag_selected = 1'b1;
			end else if(request[1])begin
				enc_selected = 2'd1;
				dec_grant = 4'b0010;
				flag_selected = 1'b1;
			end else if(request[2])begin
				enc_selected = 2'd2;
				dec_grant = 4'b0100;
				flag_selected = 1'b1;
			end else begin
				flag_selected = 1'b0;
			end
		end
	endcase
end

//--------------主任务区域----------------//
// 指针仅在已选中且允许推进时用于下一拍
always@(posedge clk or negedge rst_n)begin
	if(rst_n == 1'b0)begin
		reg_pointer <= 2'd0;                 // 复位从请求位置零开始
	end else if(flag_selected)begin
		reg_pointer <= enc_selected + 2'd1;  // 下拍从本次选中位置之后开始
	end else begin
		reg_pointer <= reg_pointer;          // 禁止推进或空请求时保留起点
	end
end

//--------------输出处理区域--------------//
// 本拍输出取旧起点决定的组合许可
always@(posedge clk or negedge rst_n)begin
	if(rst_n == 1'b0)begin
		grant_o <= 4'b0000;                  // 复位撤销所有请求许可
	end else begin
		grant_o <= dec_grant;                // 时钟边沿保存本次仲裁结果
	end
end

endmodule
