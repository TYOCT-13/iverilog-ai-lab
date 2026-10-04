# 提示澄清后的六请求诊断

六个真实API请求全部通过原严格schema及周期预算检查，均实际执行：五个选择缺陷任务检出 **4/5**，一个正确FIFO控制无误报。仍有一个UART漏检；不能据此宣称全面解决或超过随机。原完整三重复成绩仍为API **15/24**、随机 **16/24**。

## 范围与记录

[事前固定方案](agent_smoke_diagnostic_plan_2026-10-05.md)、[预登记](agent-smoke-diagnostic-2026-10-05/preregistration.json)、[设置](agent-smoke-diagnostic-2026-10-05/run_settings.json)、[六项真实计划与用量](agent-smoke-diagnostic-2026-10-05/rows.json)、[回执](agent-smoke-diagnostic-2026-10-05/receipt.json)。完整原件在`.iverilog-ai/agent-smoke-diagnostic-live-20261005/`。入口与方案在新请求前提交为`bdc9e20`；Agent/core仍为`4d8eafb`。

成员是上一轮五个没有执行的任务，加一个曾有效执行的正确FIFO控制，故是**事后选择、事前固定成员**的诊断。五任务含四个不同缺陷，UART msb_first重复两次；检出4/5任务、3/4不同缺陷。seed0/1/2的分母3/1/1不平衡，不将共享摘要器计算的重复均值当成新三重复对照。新提案从自动复位开始，不复用旧输入或失败观察；API不接收变体名称或选择原因。

每份原规格恰好删除一段旧长预算说明，前置本次短预算与“完整场景列表只取可容纳子集”；另重申顶层只含action/reason/vectors。公开[四份新规格](agent-smoke-diagnostic-2026-10-05/specs/)；E40/E16等电路时序、严格extra=forbid与参考判据保留，没有清洗输出或放宽通过门槛。

## 所有诊断结果

| 原任务 | 模块 / 变体 / seed | 实际激励 / 上限 | 状态 |
|---|---|---:|---|
| 015 | sync_fifo / fifo_bug_full_off_by_one / seed0 | 4/16 | detected |
| 051 | uart_tx / uart_bug_msb_first / seed0 | 46/48 | detected |
| 055 | uart_tx / uart_bug_msb_first / seed1 | 42/48 | detected |
| 071 | uart_tx / uart_bug_busy_never_clears / seed2 | 5/48 | not_detected |
| 099 | spi_master / spi_bug_done_missing / seed0 | 18/20 | detected |
| 007 | sync_fifo / reference / seed1 | 7/16 | not_detected |

6/6原动作validated，6/6实际执行，共122激励周期；正确参考审核再执行122周期。12份DUT/参考执行侧可核验，85份登记原字节均已冻结，源变化为空。共享摘要器的资格字段为true，表示本诊断的证据完整；**不会把事后选样诊断变成完整公平比较**。

漏检的UART busy_never_clears只用了5拍：先3拍start=0、data_in=0，再2拍start=0、data_in=255，完全未请求发送。实测功能场景仅uart.idle命中，request/busy/frame_start/complete_frame缺失。这是缺少有效发送场景的漏检，不是电路正确或判据失效的证据。剩余周期并未被充分使用；下版应在协议场景缺失时明确提示补测需求。

结构和预算合规从原五次未执行变为本次可执行，是局部稳定性的积极观察。但预算提示、格式强调及远程随机新提案一起变化，且样本由失败挑选，不能把4/5写成单因素提升、泛化或新主指标。没有对照组新跑，未验证后续反馈的增益。原[短预算三重复报告](agent_smoke_live_2026-10-05.md)及其15/24不改。

## 预算与复核

本次13833已报告tokens，6请求全部有usage，没有重试或弃掉失败请求。[新预算账](agent_smoke_diagnostic_api_budget_2026-10-05.json)：已知359响应，旧1可能在途继续预留，保守360/360，剩0，累计857957tokens；没有服务商账单，实付留空。在此预算下停止新的API调用。

[只读子代理复核](../review/agent_smoke_diagnostic_review_2026-10-05.md)单独保存，不算真人试用、人审H02或异机验证。新增入口测试见[日志回执](agent-smoke-validation-2026-10-05/receipt.json)：24项通过，增加父结果SHA绑定后5项复测通过；不相加作全仓数量。

本轮做完的是提示澄清与六项诊断。仍需在完整新对照中验证协议场景质量与稳定性，再增加独立留出；这两项未被本诊断替代。
