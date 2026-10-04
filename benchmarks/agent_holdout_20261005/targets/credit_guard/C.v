`timescale 1ns / 1ps
// Company       : ICARUS project
// Engineer      : Automated generation
// Create Date   : 2026-10-05
// Design Name   : Saturating credit counter
// Module Name   : credit_guard
// Description   : Single-clock credit acquisition and release_req
// Simulations   : Local Icarus Verilog
// Referrences   : spec/agent_holdout_20261005/credit_guard_spec.md
// Dependencies  : None
// 版权归属       : ICARUS 项目
// 开发人员       : 自动生成
// 创建日期       : 2026-10-05
// 设计名称       : 饱和信用计数
// 模块名称       : credit_guard
// 模块说明       : 信用获取与归还的单时钟状态更新
// 仿真工程       : 本地 Icarus Verilog
// 参考资料       : spec/agent_holdout_20261005/credit_guard_spec.md
// 依赖文件       : 无

module credit_guard
(
	//---------------全局信号---------------//
	input clk,                                // 信用状态更新的上升沿时钟
	input rst_n,                              // 异步低有效复位输入

	//---------------用户接口---------------//
	input acquire,                            // 获取一个信用的请求
	input release_req,                            // 归还一个信用的请求
	output [2:0] credits                      // 当前可用信用数量
);

//--------------输出信号区域--------------//
// 信用寄存器由复位和业务事件共同控制
reg [2:0] credits_o;                         // 提供接口读数的信用状态

//--------------输出赋值区域--------------//
assign credits = credits_o;                  // 将寄存计数连接到外部端口

//--------------主任务区域----------------//
// 上升沿处理事件，异步复位恢复初始额度
always@(posedge clk or negedge rst_n)begin
	if(rst_n == 1'b0)begin
		credits_o <= 3'd3;                   // 恢复三个可用信用
	end else if(acquire)begin
		if(credits_o != 3'd0)begin
			credits_o <= credits_o - 3'd1;   // 获取成功后扣除额度
		end else begin
			credits_o <= credits_o;          // 空额度保留原状态
		end
	end else if(release_req && !acquire)begin
		if(credits_o != 3'd7)begin
			credits_o <= credits_o + 3'd1;   // 归还成功后增加额度
		end else begin
			credits_o <= credits_o;          // 上界限制下保持计数
		end
	end else begin
		credits_o <= credits_o;              // 中性事件不改变信用
	end
end

endmodule
