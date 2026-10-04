# 六请求提示澄清诊断：只读代理复核

日期：2026-10-05。诊断入口及方案提交：`bdc9e20a0d4d1fe6c79d5f3c125d866338d43d5b`；原 Agent/core 版本仍为 `4d8eafb`。

**新六项的原字节、执行证据与公开统计一致，未发现新增不一致。** 六次提案全部通过既有严格 schema 和预算校验并执行；检出 4/5 个选择的缺陷任务，即 3/4 个不同缺陷，一个正确 FIFO 控制无误报。仍有 UART 漏检。本次不改写原正式比较的 API 15/24、均匀随机 16/24，也不证明单因素因果或超过随机。

[机器回执](agent-smoke-diagnostic-review-2026-10-05/receipt.json)保存逐项 SHA、85 份快照检查、六行及 12 执行侧、提示规格规范化、用量与公开材料绑定。本轮只读核验，未调用 API、读取真人凭据或重跑仿真；只新建本复核及其回执，没有修改原实验、旧复核或生产源码。这是代理复核，不计真人试用、H02 或异机复现。

## 成员、快照与真实执行

成员按[诊断方案](../experiment/agent_smoke_diagnostic_plan_2026-10-05.md)为父实验 sample 015、051、055、071、099 五个未执行任务，加 sample 007 正确 FIFO seed 1 控制。新登记行均从 `not_started / requests=0 / rounds=[]` 开始；旧计划、旧观察与失败记录未复用。父结果的登记 SHA 与原件匹配。

核对[新原始结果](../../.iverilog-ai/agent-smoke-diagnostic-live-20261005/results.json)及[严格摘要](../../.iverilog-ai/agent-smoke-diagnostic-live-20261005/summary.json)：

- 登记、results、summary 六成员及预算一致，每任务最多一次请求、一次目标执行，额外正确 RTL 审核单独计数。
- 85 份登记输入的集合、安全相对路径、尺寸、SHA、原字节副本及当前源文件全部一致；包含原/新规格、诊断入口、方案、父结果与预算账。登记、设置、结果、摘要之间的 SHA 引用正确，`changed_inputs_at_finish=[]`。
- 六个目标执行和六个参考审核共 12 份 pipeline 记录，计划、合同、执行 RTL/测试台、逐拍期望、stdout、结果及失败列表的绑定一致。由实际结构化记录重算检出与首次检出周期，结果与摘要相符；无正确参考审核告警。
- 所有目标执行合计 122 激励周期、291 次输出比较，正确参考审核另执行 122 周期。共享摘要的 `eligible_for_frozen_comparison=true` 表示这些记录完整，不会把事后选样诊断变成无偏的完整对照实验。

| 父 sample | 模块 / 变体 / seed | 实际刺激 / 上限 | 状态 | 首次检出搜索周期 |
| --- | --- | ---: | --- | ---: |
| 015 | FIFO / `fifo_bug_full_off_by_one` / 0 | 4/16 | detected | 3 |
| 051 | UART / `uart_bug_msb_first` / 0 | 46/48 | detected | 8 |
| 055 | UART / `uart_bug_msb_first` / 1 | 42/48 | detected | 5 |
| 071 | UART / `uart_bug_busy_never_clears` / 2 | 5/48 | not_detected | — |
| 099 | SPI / `spi_bug_done_missing` / 0 | 18/20 | detected | 16 |
| 007 | FIFO / reference / 1 | 7/16 | not_detected，无误报 | — |

五个缺陷任务中包含同一 UART 位序缺陷的两次提案，所以不同缺陷只有四个。seed 0/1/2 的缺陷任务数为 3/1/1，不平衡；不将共享摘要器计算的重复均值当作新三重复对照。

## 实际模型输入

从冻结诊断脚本的 AST 提取旧预算前缀与新前置说明，逐字重建规范化规格。四份规格分别仅删除原 FIFO 第 35 行、UART 第 33 行、SPI 第 32 行、握手第 32 行的一段旧预算文字；其余正文保留，UART E40 与 SPI E16 等电路时序没有缩短。重建结果与冻结生成规格、实际输入文件及[公开规格副本](../experiment/agent-smoke-diagnostic-2026-10-05/specs/)原字节相同。

六个真实 `decisions[0].state.specification` 与对应规范化规格一致；结构化短预算仍为 16/48/20，对应各自模块。全部 `max_requests=max_rounds=1`，`independent / per_cycle`，首态 `current_plan / observation / plan_error` 均为 null。辅助代理还将非规格 state 字段与合同、通用目标及新 episode 初态逐字段重建比对：未发现变体路径、父失败记录或选择理由被加入模型输入。

统一前缀提醒顶层仅含 `action/reason/vectors`，没有修改 `extra=forbid` 或清洗模型输出后验收。六份未受信任的原始提案尺寸、SHA 与轨迹引用一致，实际均只有这三个顶层字段，均为 `validated` 且执行第 1 轮。原始提案只作为模型输出留证，不作为参考判据。

## 保留的 UART 漏检

[sample-003 的实际计划](../../.iverilog-ai/agent-smoke-diagnostic-live-20261005/sample-003/agent/round-01/testplan.json)先保持 3 拍 `start=0, data_in=0`，再保持 2 拍 `start=0, data_in=255`。5 份真实观察均为 `start=0, busy=0, tx=1`；本次根本没有请求发送。

轨迹功能场景记录只有 `uart.idle` observed，`uart.request`、`uart.busy`、`uart.frame_start`、`uart.busy_request_attempt`、`uart.complete_frame` 均 missing。观察包 SHA 为 `a7f884736326795b2f8152d5b0a14e08023645cdabd85f908af39403abfa6631`，与轨迹覆盖证据绑定一致。因此该漏检是本次计划没有构造有效发送场景，不能据此称电路正确或参考判据失效。格式与预算合规不等于计划具有足够的验证价值。

## 公开材料与预算绑定

公开六行的成员、实际计划、覆盖计数、状态、首次检出周期及 usage 与原件逐字段一致；公开回执的策略统计与原 summary 完全相同，preregistration/settings 副本逐字节相同。绑定的是父代理最后统一 LF 后的文档字节：

| 材料 | SHA-256 |
| --- | --- |
| [正式短预算报告](../experiment/agent_smoke_live_2026-10-05.md) | `5abd8dd708b2bcd1d31a233968c55f6232c218eb022dbbd6d13995f7c562ac7e` |
| [六请求诊断报告](../experiment/agent_smoke_diagnostic_2026-10-05.md) | `9b775d65c95ac76661a3ccf85df361cf8e7e5c0d2f69b317fb664f5f0b756b3d` |
| [新预算账](../experiment/agent_smoke_diagnostic_api_budget_2026-10-05.json) | `42da5004074b06d5e892bd4343a22be4e17195dcae3cae831abb0d5c9fd1c035` |
| [公开诊断回执](../experiment/agent-smoke-diagnostic-2026-10-05/receipt.json) | `d73f9ff0524307fee55127e3145c352cdf1f458d9eaff425db139e947f763f03` |
| 原始诊断 results | `bd3046d68cb30b7fa35ffa2d118150bdfc95ee04571634c3a452a1ac87226c22` |

六请求全部有 usage，合计 13,833 tokens。前账及新原始结果的 SHA 引用匹配；353＋6＝**359** 个已知响应，354＋6＝**360** 个保守预留请求，844,124＋13,833＝**857,957** 个已报告 tokens，剩余 **0**。历史 1 个可能在途请求继续预留；没有服务商账单，实付金额仍为空。该账的统计范围沿用前账，不是账户全部历史费用。

公开报告保留了原 15/24 对 16/24、5 任务/4 不同缺陷的区分、空闲 UART 漏检及事后选样限制。预算说明、格式强调与随机新提案同时改变，缺少单因素对照；本诊断没有新跑随机基线，也没有验证后续反馈增益。确认记录完整与提案可执行，不能替代完整新对照、独立留出、真人试用或 H02。
