# 六请求提示澄清诊断：事前方案

日期2026-10-05。先读完短预算三重复原始结果，再选择如下成员；在六个新请求前冻结本文件及执行入口。不是完整新对比、独立留出或原成绩的补考。

## 固定成员与目的

| 原样本 | 模块 / 变体 | seed | 原状态 | 新预算 |
|---|---|---:|---|---:|
| 015 | sync_fifo / fifo_bug_full_off_by_one | 0 | policy_error | 16 |
| 051 | uart_tx / uart_bug_msb_first | 0 | policy_error | 48 |
| 055 | uart_tx / uart_bug_msb_first | 1 | policy_error | 48 |
| 071 | uart_tx / uart_bug_busy_never_clears | 2 | cycle_budget | 48 |
| 099 | spi_master / spi_bug_done_missing | 0 | policy_error | 20 |
| 007 | sync_fifo / reference | 1 | not_detected，正确且有效执行 | 16 |

最后一项是正确FIFO误报检查，不是第六个缺陷。每项最多1请求/1提案/1执行，失败不替换，不自动重试，六请求上限。每个已执行输入同样交给正确RTL审核；保留真实stdout、结构记录、原始提案和全部字节快照。

主观测为六项结构通过率、预算合规和实际执行率；次观测为五个选择缺陷的检出与正确控制的误报。即使五个全检出，也不能改写三重复的API15/24或随机16/24。原结果及其77份输入仍留在原目录。

## 仅澄清本次模型输入

保留原完整规格的接口、复位、接受条件、逐拍串行时序和参考判据，恰好删除每份规格的一段旧长预算说明。新规格前置本次短预算，说明完整回归的场景列表只需选取能容纳的子集；自动初始复位不计激励预算，手动复位计入。不得将UART接受到E40结束和SPI到E16恢复的物理时序缩短。

进一步重申已有decision schema：顶层只有action/reason/vectors，周期合计在内部计算，禁止把vector_count、total_cycles、cycle_sum、cycles_total、cycles加在顶层；向量本身仍必须带cycles。严格extra=forbid不放宽，不清洗模型原始输出后再验收。

模型只接收电路contract、澄清规格及本轮资源state，不收到原失败记录、变体路径或选择理由。fresh rows来自原事前登记，旧rounds/计划/观察不复用。Agent/core、RTL、参考判据、独立复位与逐拍模式不变。

这是选择失败后的诊断，同时改变预算说明、格式强调和随机新提案，不隔离单一因果。seed只标记样本，不控制远程模型随机数。不能将改善直接写成单因素效果、广泛鲁棒性或超过随机。

## 请求与文件边界

[执行入口](../../scripts/run_agent_smoke_diagnostic.py)默认dry-run，零文件写入、零密钥读取、零API。执行固定为DeepSeek Flash、官方HTTPS端点、Chat、thinking disabled、非流式、60秒超时、8192输出tokens，无传输自动重试。

输入写入新目录`.iverilog-ai/agent-smoke-diagnostic-live-20261005-inputs/`，输出写入`.iverilog-ai/agent-smoke-diagnostic-live-20261005/`；任一目录存在即拒绝再次执行。原规格不覆盖，新规格、原源字节、入口、本方案、父结果及[预算账](agent_smoke_api_budget_2026-10-05.json)均登记SHA并在请求前冻结。

现有保守用量354/360，最后六请求预留后达到360；旧1可能在途保持预留。响应usage、失败请求、累计下界和上界分别记新账，实付金额无服务商账单则留空。预算达到上限后停止新API，不能只选成功响应计费或换一套隐含额度。
