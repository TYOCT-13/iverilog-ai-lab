# 外部 UART RX API Agent 真实联调（2026-10-04）

本次真实使用 DeepSeek Flash（模型 ID `deepseek-flash`），Chat Completions，非流式。由主任务统一发起 **1 次 API 请求**，运行两轮真实 Icarus；本记录作者随后核查原始轨迹、即时快照、日志与哈希，并完成 0 API 的历史变体离线重放。

这是代理参与的工程联调与机器证据检查，**不是真人试用、独立人工审核或独立留出评估**。本记录作者也是外部适配器实现者，存在实现者关系。未预设“理想成绩”。

## 真实运行事实

北京时间 2026-10-04 15:13:29–15:13:47，轨迹耗时 17.688 秒。候选与通过既有 SPEC_TB 资格检查的基线是相同冻结 UART RX 字节；资格检查 11 项、0 失败，不能当作完整功能证明。

| 轮次 | 计划向量 | 每侧实际采样点 / 激励周期 | 两侧周期 | 有效输出比较 | 差异 |
|---|---:|---:|---:|---:|---:|
| 1：已有固定计划 | 23 | 182 | 364 | 547 | 0 |
| 2：API 追加后 | 27 | 209 | 418 | 628 | 0 |
| 累计执行 | — | 候选 391、基线 391 | **782** | 重跑旧计划，不能当成互不重复覆盖 | 0 |

停止原因是 `round_budget`：达到两轮上限，而不是模型证明设计正确。证据类型 `qualified_baseline_differential`，两轮 verdict 均为 `no_observed_difference`；断言 checks/failures 都保持 0，样本比较数另列，没有冒充内置 reference_model。

请求预算：最多 1 请求、2 轮、8192 输出 token、1200 双侧激励周期。服务商返回 usage：prompt 2118、completion 3543、total **5661 tokens**；没有账单金额，不能把 token 数称为人民币成本。复位开销和预先 SPEC_TB 资格检查不在激励周期数中。

## API 实际追加了什么

4 个向量均为 after 相位，共 27 个候选周期：

| 条件 | 周期 |
|---|---:|
| RX 空闲高、ready=0、prescale=1 | 6 |
| ready=0 时 RX 拉低短脉冲 | 3 |
| ready=0 时 RX 回到空闲高 | 12 |
| RX 空闲高、ready=1、prescale=65535 | 6 |

这证明 API 能读取已有计划/观测并追加可执行激励。新增条件涉及 ready 拉低、短低脉冲和 prescale 极值，但这里没有完成极大 prescale 下的一整帧，也不能凭 idle 阶段 ready=0 就声称完整反压协议已覆盖。正样本与自身比较为零差异是接线与运行一致性证据，不是准确率证明。

## 原始证据核查

原始目录：`.iverilog-ai/external-agent/uart-rx-live-one-request-20261004/`；轨迹为 `agent/agent_trajectory.json`。

本次读取并验证：

- 资格记录的 SHA256 与每轮 observation 引用一致；冻结 candidate/baseline 内容哈希一致。
- 两侧真实编译/运行均返回 0，内置参考模型映射确为 disabled。
- 从原始 run_stdout 重新解析即时采样日志，与保存的 baseline_samples/candidate_samples 逐项一致；重新比较得出 547/628 和 0 差异。
- 原测试台及插桩测试台哈希与 snapshot_instrumentation 元数据一致。
- 共登记 28 个核查工件指纹，使用项目相对路径，不发布凭据或服务商密钥文件。

公开摘要与指纹：`docs/experiment/external-agent-live-2026-10-04/summary.json`。它不是原始工件归档，干净 Git 克隆不自带 `.iverilog-ai/` 中的完整波形和源码副本。

## 已保存计划的离线历史变体重放（0 API）

另开 `.iverilog-ai/external-agent/uart-rx-live-plan-bitorder-offline-20261004/`，没有修改候选源码，没有新增缺陷，使用已有 `uart_rx_mut_bit_order.v`：

| 计划 | 比较样本 | 差异 |
|---|---:|---|
| 原固定 23 向量 / 182 周期 | 547 | cycle 80、836 ns，m_axis_tdata：基线 150，候选 105 |
| API 扩展 27 向量 / 209 周期 | 628 | 同一处差异，未增加新差异 |

**原固定计划本来就能暴露该变体，因此不能把此差异归功于新增 4 个向量，不能声称 API 独立发现了缺陷。**此次离线重放只证明最终计划仍能保留原有差分能力。它没有发送任何新的 API 请求。

## 验收边界

外部适配器的 24 项离线测试见 `external_api_agent.md`，不与本次 live 混算为模型成绩。早期 VCD 最终时间戳采样方法存在歧义，见 `external_agent_cross_review_2026-10-04.md`；本次真实联调使用修复后的即时快照，不引用旧采样结果冒充本次证据。

当前已证明 API—追加计划—真实双侧仿真—限定输出差分—轨迹保存这条链可执行。尚未证明相对固定/随机策略提高了缺陷检出率，也没有新增真人反馈或人工独立复核结论。
