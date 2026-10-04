# 主指标清单（指标 — 来源 — 版本 — 时间 — 适用范围）

本文件回答一个问题：**报告里出现的每个数字，能不能追到一条原始记录？**

规则（路线图的 P0-A）：

- 一个数字只属于一种口径。**新旧口径不混用**，不同口径的数字不放在同一张表里比较。
- 来源必须落到**文件路径 + 生成时间**；能给出复现命令的给出命令。
- **测试"收集/运行"的数量不写成"通过"的数量**，失败与跳过分别列。
- 追不到记录的，写"未复核"或"无记录"，不估算、不外推。

初次核对：2026-09-29，HEAD `2b9594f`。本次口径修订：2026-10-05；保留原始实验文件，
最新v5生产实现为 `4d8eafb`，完整回归1170/2，296项指纹无变；两测试文件随后格式修改与45项复测另列。v5逐拍/独立补测为1重复60任务；旧c7三重复、28be1ed烟测与e9b7b8a pilot分别归档，不能互换。当前正式v2 PDF仍属于28be1ed。

---

## 1. 缺陷检出（内置基准，手写测试台）

| 指标 | 数值 | 口径 / 它到底测的是什么 | 来源文件 | 生成时间 | 复现命令 |
|---|---|---|---|---|---|
| 缺陷检出 | **83/83，0 误报，0 不可判定** | **手写测试台**跑参考实现与全部缺陷变体；矩阵里的 `strategy` 字段是 `fixed`。**与 AI/LLM 无关** | `.iverilog-ai/benchmark-matrix/matrix.json`（`summary`） | 2026-09-14 01:09 UTC | `python scripts/run_benchmark_matrix.py` |
| 参考实现全过 | 15/15 | 同一矩阵里的参考设计 | 同上 | 同上 | 同上 |
| 变体可综合 | 98/98 | Yosys 综合，不是行为正确性 | `.iverilog-ai/synthesis-matrix/synth-matrix.json` | 2026-09-14 01:09 UTC | `python scripts/run_synthesis_matrix.py` |
| 离线路径全过 | 15/15 | 不需要密钥的 plan→tb→Icarus 链路 | `.iverilog-ai/pipeline-matrix/pipeline-matrix.json` | 2026-09-14 01:09 UTC | `python scripts/run_pipeline_matrix.py` |

**适用范围**：这些数字说明"在这 15 个案例、83 个变体、这套手写测试台下，参考实现通过且变体被检出"。
**不能**用来支撑"AI 能检出缺陷"，也**不能**外推到其它设计或其它测试台。

## 2. 离线消融（三组实测与一项并集推导）

| 组 | 检出 | 口径 / 它到底测的是什么 | 来源 | 时间 |
|---|---|---|---|---|
| A `handwritten-tb` | **83/83** | 手写测试台的检出上限（对照组） | `.iverilog-ai/ablation-matrix/matrix.json` | 2026-09-20 14:50 UTC |
| B `ai-plan-plain` | **0/83** | **离线规则规划器**生成的计划，**没有独立期望值** → 只有激励与波形，零可比较检查项 | 同上 | 同上 |
| C `ai-plan-oracle` | **76/83** | 同样的离线计划 + **参考模型复算的期望值** | 同上 | 同上 |
| A ∪ C | **83/83** | 并集，**不是第四次实测**（是 A 与 C 的合并，规划器独立贡献 0 条） | 同上（由上面三行算出） | 同上 |

复现：`python scripts/run_ablation_matrix.py`。

**口径提醒（旧文档写法需要按这三条改）**：

- `83/83` 是**手写测试台**的结果，不是 AI 的结果。
- `0/83` 的含义是"**没有期望值、零可比较检查项**"，不是"AI 完全无能"；换成有期望值的计划就是 76/83。
- `76/83` 是**离线规则规划器**（本地确定性规则）的结果，**不是真实 LLM**。
- B/C 保持计划相同，仅改变期望值来源；A/C 同时涉及手写测试台与规则生成路径的差异。
  该实验说明独立期望值在当前执行链中的作用，不能证明 LLM 的增益，也不是四档实测。

## 3. 预算对齐实验（每计划同预算，分开披露轮数）

口径见 `docs/experiment/experiment_plan.md`：预算按案例预先确定、各策略共用；执行前归一化；
分母来自清单；不可判定按未检出计入；参考设计自己乱报时作废该 (案例,轮次) 的检出。
**相同的每计划刺激预算不等于相同的多轮累计预算。** 原始 fixed 实跑 1 轮，random/Mock 各 5 轮，
online_ai 为 10 轮（seed 0–9）。不把不同轮数的累计并集当作同总预算比较。

| 轮次 | 策略 | 分母 | 检出 | 累计并集检出率 | 单轮平均 | 不可判定 | 来源 | 时间 |
|---|---|---:|---:|---:|---:|---:|---|---|
| 1 轮 | fixed | 67 | 57 | 85.1% | 85.1% | 0 | `.iverilog-ai/strategy-budget-check2/strategy_matrix.json` | 2026-09-29 14:38 UTC |
| 1 轮 | random | 67 | 55 | 82.1% | 82.1% | 0 | 同上 | 同上 |
| 1 轮 | ai（MockProvider） | 67 | 55 | 82.1% | 82.1% | 0 | 同上 | 同上 |
| 1 轮 | fixed | 67 | 57 | 85.1% | 85.1% | 0 | `.iverilog-ai/strategy-fair-5rounds/strategy_matrix.json` | 2026-09-29 15:05 UTC |
| 5 轮 | random | 67 | 57 | 85.1% | 78.2%（74.6%–83.6%） | 0 | 同上 | 同上 |
| 5 轮 | ai（MockProvider） | 67 | 57 | 85.1% | 78.2%（74.6%–83.6%） | 0 | 同上 | 同上 |
| 10 轮 | **online_ai（deepseek-flash）** | 67 | **63** | **94.0%** | **83.4%（73.1%–89.6%）** | **8 条变体 runs** | `.iverilog-ai/strategy-online-flash/strategy_matrix.json` | 2026-10-01 10:41–11:57 UTC |

- 1 轮那次 `code_revision = 22b864a…`、`working_tree_dirty = true`（当时改动未提交，因此**仅凭 commit 不能复现这一轮**）。
- 离线文件 `code_revision = 2b9594f8…`、`working_tree_dirty = false`；
  880 条 runs = fixed 80（1 轮）+ random 400（5 轮）+ Mock 400（5 轮）；不可判定 0、参考告警作废 0。
- 在线文件 `code_revision = 47ed59b9…`、`working_tree_dirty = false`；1,680 条 runs 包括上述
  880 条基线和 **800 条 online_ai runs（10 轮）**，不能全算成在线任务。在线组 13 案例 × 10 轮
  = **130 次计划请求**；文件耗时 75.2 分钟。不可判定为 **8 条变体 runs**（`reference_false_alarm` 5 + `no_records` 3）；
  后 3 条因计划校验失败未产生比较记录，不是已执行计划的零检查项结论。
  其中参考告警计划为 2 个；`plans_excluded_by_reference_alarm = 5` 是去重后的 (case, variant) 数，
  本次恰好与参考告警导致的失效 run 数相同，不能将它解释成 5 个计划。
- 离线结果表明：**随机与 AI(Mock) 的累计并集在 5 轮后追平固定向量单轮（都是 57/67）**，
  但**单轮**平均只有 78.2%、波动区间 74.6%–83.6%——「并集好看」不等于「每轮都行」。
- **适用范围**：开发集（内置 13 个有时钟的案例；2 个纯组合案例不参与）。
  `ai` 组用的是 MockProvider，它**回放随机策略的计划**，因此这一组**不是模型能力证据**。

**原始结果的结论边界**：在线十轮并集 63/67（94.0%）不能直接证明它在同总预算下优于五轮随机或
单轮固定向量。在线单轮平均 **83.4% < 人工固定向量 85.1%**；不能笼统写“优于人工”或“替代人工测试设计”。

### 3.1 seed 0–4 事后子集（2026-10-04 重算，无新增模型请求）

从同一份 `.iverilog-ai/strategy-online-flash/strategy_matrix.json` 选取 online/random/Mock 的连续
seed 0–4，各为 5 轮；fixed 保留其原始 seed 0 单轮作参照。原始十轮记录不覆盖。
这是**事后描述性分析**，不是预注册或独立留出评测。

| 策略 | 轮数 / runs / 计划请求 | 并集检出 | 单轮均值 | 单轮范围 | 不可判定 / 参考失效 runs |
|---|---|---:|---:|---|---:|
| fixed | 1 / 80 / 13 | 57/67 = 85.0746% | 85.0746% | 85.0746%–85.0746% | 0 / 0 |
| random | 5 / 400 / 65 | 57/67 = 85.0746% | 78.2090% | 74.6269%–83.5821% | 0 / 0 |
| MockProvider | 5 / 400 / 65 | 57/67 = 85.0746% | 78.2090% | 74.6269%–83.5821% | 0 / 0 |
| online_ai（deepseek-flash） | 5 / 400 / 65 | **61/67 = 91.0448%** | **83.8806%** | **79.1045%–86.5672%** | **0 / 0** |

来源：`docs/experiment/matched-budget-2026-10-04/README.md`、`summary.json`、`selected_runs.json`；
重算命令：`python scripts/summarize_matched_budget.py`。相同五轮与每计划预算下，在线相对随机累计
净多检出 4 条，单轮均值高约 5.7 个百分点；**83.9% 仍低于 fixed 的 85.1%**。
fixed 实际只执行一次，不能用在线五轮并集宣称同总预算下胜过人工。

### 3.2 token 用量与费用估算（不可写成实付费用）

| 范围 | 计划请求 | 保存 usage 的去重请求 | prompt tokens | completion tokens | 其中 reasoning | 总 tokens |
|---|---:|---:|---:|---:|---:|---:|
| 原始在线 10 轮 | 130 | 128 | 242,146 | 1,000,332 | 787,217 | 1,242,478 |
| 在线 seed 0–4 子集 | 65 | 63 | 119,262 | 470,098 | 367,668 | 589,360 |

以上是保存的 API usage 按 `request_id` 去重之和，不是供应商账单。未保存 usage 的请求不能直接视为免费。
原始十轮按当时记录的标价估算：高峰 cache-miss 情景约 **$1.273**，非高峰约 **$0.637**；
实际费用仍需账单、缓存命中与调用时段核对，不能写成“费用实测”或挪作五轮子集成本。
同一请求的 usage 会重复挂在多个变体行上，不能按行累计。

### 3.3 API Agent 五策略 pilot（冻结 `e9b7b8a`，2026-10-04）

来源：[完整报告](agent_comparison_live_2026-10-04.md)、[持久摘要](agent-comparison-chat-2026-10-04/summary.json)；原始目录 `.iverilog-ai/agent-comparison-live-chat-v2/`。北京时间 14:54:42–15:11:32。4 模块，每模块清单首 2 个已有缺陷及正确基线，5 策略，开发集单次重复，**60 行、8 个独立缺陷**。预注册与设置在请求前冻结并关联 SHA256；固定分母包含失败和不可判定。

| 策略 | 检出/8 | 缺陷未检出 | 缺陷不可判定 | 请求 | 正确基线假警 | 变体参考回放否决 |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 5/8 | 3 | 0 | 0 | 0 | 0 |
| random | 5/8 | 3 | 0 | 0 | 0 | 0 |
| single | 2/8 | 1 | 5 | 12 | 1 | 2 |
| feedback | 4/8 | 4 | 0 | 19 | 1 | 0 |
| no_feedback | 2/8 | 3 | 3 | 21 | 0 | 0 |

- 实际 **52/84 请求、234,536 tokens**：prompt 32,429、completion 202,107；52 请求均有 usage，按 sample:decision 去重，重复 ID 为 0。费用未取到账单，不能称实付金额。
- **36 份 Agent 轨迹、122 份 pipeline 证据**逐项复核。搜索 1,606 周期＋参考审核 1,606 周期，实际检查项 2,904＋参考检查项 2,904。审核是额外执行，不反馈给搜索 Agent。
- 正确基线假警 **2 个样本**与变体参考回放否决 **2 个样本**分别列示，不合并成含糊的误报率。全样本保留 **6 个 output_truncated、5 个 policy_error**；失败日志条数不作为独立缺陷数。
- 反馈 4/8 **未胜固定/随机 5/8**。4 对 2 只是单次开发集观察，不能强因果归因为反馈机制；采样密度、检查项与提前停止情况不同，相同周期上限不等于相同覆盖。
- 发现反例就停止，没有修改 RTL 或失败驱动修复，没有独立留出集、真人试用或独立人工审核。

**首次中断开发记录单列**：`.iverilog-ai/agent-comparison-live-20261004/` 因隐式 Responses 协议与已验证接口不一致而中止。落盘 **7 次已知请求、51,433 已知 tokens**，另有 **1 次可能在途请求**没有最终 usage；没有 finished_at，47 行 not_started。未知消耗不按零处理，不与本轮 52 请求或成绩拼接。

**新护栏不改旧分数**：核心保护提交 `1c1e0dc` 对内置顺序逻辑的 before 相位不提供权威 oracle，Agent 因不足独立证据停止；遗漏输入按真实 testbench 保持上一值。后续 `867b8bd` 只修 PDF 排版；冻结 `e9b7b8a` pilot 未按新护栏重跑，分数和假警原样保留，不能称为修复后新成绩。

### 3.4 外部有限规格与真实 API（分别计量）

| 范围 | 实测 | 来源与边界 |
|---|---|---|
| 冻结开发重放 | **24 输入**＝3 基线＋15 历史人工变体＋3 等价改写＋3 编译失败；差分 15 different、6 identical、3 inconclusive | `.iverilog-ai/external/replay-20261004-ic-final/evidence.json`；[说明](external_agent_readiness.md)，不是独立留出或上游真实缺陷 |
| 有限 SPEC_TB | 三基线分别 11/10/28 检查、零失败；变体检出 **13/15** | UART TX 的 prescale_off_by_one 与 busy_never_clears 未检出；差分 different 不能冒充规格判定 |
| UART RX 实际 API | **1 请求、2 轮、782 双侧周期、5,661 tokens**；23→27 向量；有效输出比较 547→628、差异 0 | [记录](external_agent_live_2026-10-04.md)、[摘要](external-agent-live-2026-10-04/summary.json)；候选和基线同字节，只证明追加执行接通 |

外部证据为 `qualified_baseline_differential`，不冒充 reference_model；断言 checks/failures 为 0，输出比较数另列。历史位序变体无网络重放中，原固定计划本来就能发现同一差异，不能把功劳归给新增向量。外部 1 请求不并入内置 52 请求；24 输入也不同于适配器的 24 项自动化测试。

### 3.5 v2 七策略三次重复（c7bb280，v3提示词）

[完整记录](agent_comparison_v2_live_2026-10-04.md)与[小型持久回执](agent-comparison-v2-2026-10-04/receipt.json)，原始完整目录 `.iverilog-ai/agent-comparison-v2-nonthinking-20261004/`。252登记任务，4模块共8个开发集缺陷，七策略各3次；每策略缺陷分母24任务，正确基线另列。规格、预算、采样、FIFO基线及两个单点变体均与旧pilot不同。

| 策略 | 三次每次检出/8 | 平均检出率 | 请求 |
|---|---|---:|---:|
| fixed | 7 / 7 / 7 | 87.50% | 0 |
| random | 8 / 8 / 8 | 100% | 0 |
| single | 1 / 0 / 2 | 12.50% | 36 |
| feedback | 1 / 0 / 0 | 4.17% | 41 |
| no_feedback | 3 / 0 / 0 | 12.50% | 42 |
| protocol_random | 8 / 8 / 8 | 100% | 0 |
| feedback_no_coverage | 0 / 0 / 0 | 0% | 38 |

157请求、289219 tokens，usage无缺失；137动作被本地严格schema拒绝、20通过。125行无可核仿真round，严格资格false；252行和全部缺陷分母保留。冻结输入变化为空。API未胜本地基线，不支持覆盖增益。100%仅指8个已知开发变体。参考假警/审核否决0仅适用于真正执行并审核的轮，不把无round的正确输入视为通过。

### 3.6 v4 接线烟测（28be1ed，独立版本）

[完整记录](agent_comparison_v4_smoke_2026-10-04.md)与[持久回执](agent-comparison-v4-smoke-2026-10-04/receipt.json)，原始完整目录 `.iverilog-ai/agent-comparison-v4-smoke-20261004/`。同七策略与8缺陷，预登记1重复、84行，最多120请求。实际system/user消息和新JSON样例属于同时改动，不能与c7三次均值拼成同版实验或择优替代。

| 策略 | 检出/8 |
|---|---:|
| fixed | 7/8 |
| random | 8/8 |
| single | 2/8 |
| feedback | 6/8 |
| no_feedback | 7/8 |
| protocol_random | 8/8 |
| feedback_no_coverage | 5/8 |

94/94模型决策通过结构校验，94请求、201710 tokens，全部usage有记录；43 detected、40 not_detected、1 execution_error。执行失败是正确UART基线任务，0round，因此严格资格仍false；全部分母保留。参考假警/审核否决0不能抹去这项失败。反馈6/8低于无反馈7/8与随机8/8，不能宣传反馈或功能场景的普遍增益。结构通过不等于提出了有效新场景或电路完全正确。未训练权重、未作新模块留出、真人参与数0。

### 3.7 协议与应用控制（零API，不计AI成绩）

| 指标 | 实测 | 记录与范围 |
|---|---|---|
| FIFO独立队列 | 同76周期/228输出比较：旧基线66差异→修复基线0；两新单点控制56/46差异 | [判据修正](protocol_oracle_improvements_2026-10-04.md)；独立deque规格及真实Icarus，默认DEPTH=4，不外推参数 |
| 外部有限SPEC | 同24冻结输入：15已知变体13/15→15/15；3基线/3等价无误报，3编译失败不可判定 | 同记录；人工补位持续时间/busy期限，非Agent新发现；差分仍15/6/3 |
| 内置功能场景 | 四类默认参数合约24项命名事件 | [功能场景](functional_coverage_2026-10-04.md)；实际端口观察，不是代码覆盖率、形式证明或AI成效 |
| UART离线应用 | 三输入各512周期/338检查；正确0差异、MSB变体48、busy变体136 | [应用重放](../demo/ic_agent_v2_walkthrough.md)、[回执](application-uart-v2-2026-10-04/receipt.json)；协议随机0API，2个已知变体 |
| 包内反例复放 | 338比较/48差异、failed_checks、0API | `.iverilog-ai/application-uart-v2-20261004/portable-failure/replay-5f322e4e068b/`；重放退出0为完整执行，不表示设计通过 |

### 3.8 v4前累计API预算（历史，不是账单）

[预算账](ic_agent_v4_api_budget_2026-10-04.json)：预跑24个已保存响应加1可能在途按25预留；正式157、诊断1、v4烟测94。已知276响应/663939已报告tokens，保守277请求≤本轮360上限，实付费用null。预跑、诊断不并入能力统计；更早pilot和历史模型调用不属于本轮预算。候选轨迹不是已训练模型，结构失败数据不自动作正样本。

### 3.9 v5逐拍与独立补测（4d8eafb，1次重复）

[完整事实记录](agent_comparison_v5_live_2026-10-05.md)、[带SHA摘录](agent-comparison-v5-live-2026-10-05/receipt.json)、[60行摘要](agent-comparison-v5-live-2026-10-05/rows.json)；完整原件 `.iverilog-ai/agent-comparison-v5-live-20261005/`。评测profile v3、提示词 `verification-agent-v5-independent-episodes`；五策略、四模块默认参数、8个已知开发缺陷，60任务，每策略8缺陷及4正确基线。所有策略共同改为逐拍检查，API每轮复位独立运行；不是旧v3提示词或独立留出。

| 策略 | 检出/8 | 请求 | 报告tokens | 全12任务激励周期 | 实际输出检查 | 任务耗时累计/秒 |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 8/8 | 0 | 无API | 3648 | 10560 | 22.030 |
| random | 8/8 | 0 | 无API | 3648 | 10560 | 24.876 |
| protocol_random | 8/8 | 0 | 无API | 3648 | 10560 | 23.641 |
| feedback | 8/8 | 20 | 51179 | 595 | 1626 | 40.096 |
| no_feedback | 7/8 | 21 | 50072 | 627 | 1751 | 46.437 |

41请求全部有usage、101251 tokens；40结构通过、1拒绝。无反馈正确FIFO第二提案extra_forbidden，2请求/1执行轮/15周期，最终policy_error；无反馈握手valid未清零变体3请求仍漏检，保留完整分母。已执行正确基线误报0，全部60任务证据回读通过，74/74冻结字节验证，严格资格true、输入变化空。该资格不意味着所有动作成功。

8个反馈检出均在首请求，无法据此证明失败反馈或覆盖场景的因果增益。首反例累计激励周期中位数反馈8、随机18.5；逐缺陷仅3更早/1同/4更晚。两种策略实际计划长度、停止行为和API开销不同，不能用595对3648单独宣称公平的速度提升；反馈含模型/网络的任务总耗时仍更长。没有逐检查首反例的可靠墙钟计时，没有paired model RNG、多次重复、新模块留出或本轮覆盖消融。

### 3.10 v5累计预算与零API诊断

[新增预算账](ic_agent_v5_api_budget_2026-10-05.json)保持旧账不动：旧已知276响应加新41为317，旧可能在途1继续预留，保守318/360，剩42；已报告累计765190 tokens，实付费用null。

[旧输入重放](agent_v5_optimization_2026-10-05.md)只诊断采样方式：同86周期UART计划端点8检查/0差异、逐拍172检查/16差异；同26周期SPI计划端点16检查/0差异、逐拍104检查/25差异。25是输出失败记录数，不是25个不同周期。两例各模式真实端口轨迹相同、正确基线无误报；已知旧输入的事后重查不计新在线模型成绩。

## 4. 在线模型实验（历史，探索性口径）

来源：`.iverilog-ai/model-compare-r10-*`（2026-09-11 生成，`deepseek-flash` / `deepseek-v4-pro`）。

| 策略 | 分母 | 检出 | 检出率 |
|---|---:|---:|---:|
| fixed | 67 | 56 | 83.6% |
| random | 67 | 51 | 76.1% |
| ai（MockProvider） | 67 | 51 | 76.1% |
| online_ai（真实模型） | 67 | 65 | 97.0% |

**这些数字属于旧口径**（行集合推导分母、`compile_failed` 不计入不可判定、参考设计告警不作废检出、
预算未统一），因此：

- 只能作为**探索性结果**引用，**不得**与本轮新口径的数字并列比较；
- 其中的 `inconclusive` 字段为 `None`（旧 schema 没有这一项）；
- 原始文件只读保留，不覆盖、不改写。

## 5. 工程与质量指标（每次都要连着命令与版本一起写）

| 指标 | 数值 | 来源 / 复现 | 时间 | 备注 |
|---|---|---|---|---|
| 历史全仓自动化测试 | **914 passed / 1 skipped / 0 failed，227.34 秒** | `.iverilog-ai/ic-validation-pdf-final-20261004/pytest.log`、`pytest.xml`、`metadata.json`；持久记录 `docs/experiment/ic_validation_2026-10-04.md` §6 / `ic-validation-pdf-final-2026-10-04/` | 2026-10-04，源码 `867b8bd564c881954c98cc18813884a4074d1ed5`，148 个源码/配置指纹 | 含采样保护及 PDF 混排/列表修复；mypy 72、未可达扫描163、BOM0；1 跳过为推荐断言表为空，不是模型成绩 |
| 当前v5全仓自动化测试 | **1170 passed / 2 skipped / 0 failed / 0 errors，245.01秒** | [冻结验收](ic_agent_v5_validation_2026-10-05.md)、`docs/experiment/ic-agent-v5-validation-2026-10-05/validation.json`及JUnit/日志 | 2026-10-05，生产实现 `4d8eafb`，296源码/测试/配置指纹 | mypy76源码0错、未可达200文件0、BOM0；两测试尾空行后续变化与45项复测单列；不声称最终全部测试字节与清单相同 |
| 当前v5浏览器工作流 | **三尺寸0横溢出；UART58/58；非默认补测/采样设置与结果切页保持；0API** | `docs/experiment/ic-agent-v5-validation-2026-10-05/browser/results.json` | 2026-10-05，重启冻结源码服务 | 手机为视口模拟，r1/r2自动化失败保留；同会话rerun保持不是进程重启保持；非真人或真实浏览器API请求 |
| 历史v4全仓自动化测试 | **1073 passed / 2 skipped / 0 failed，187.031秒** | [冻结验收](ic_agent_v4_validation_2026-10-04.md)、`docs/experiment/ic-agent-v4-validation-2026-10-04/validation.json`及JUnit/日志 | 2026-10-04，源码 `28be1ed`，291源码/配置指纹 | mypy76源码0错误、未可达187文件0、BOM0；空断言表/Win1314 symlink跳过；浏览器r3另列，历史日志不覆盖 |
| 历史v4浏览器工作流 | **三尺寸0横溢出；UART58/58；切页结果保留；0API** | `docs/experiment/ic-agent-v4-validation-2026-10-04/browser/results.json` | 2026-10-04，冻结源码新服务 | 手机为视口模拟；r1/r2失败保留；不称真人、在线API或实体手机测试 |
| 采样保护版回归 | **914 passed / 1 skipped / 0 failed，211.47 秒** | `.iverilog-ai/ic-validation-sampling-guard-20261004/pytest.log`；持久 `ic-validation-2026-10-04/` | 2026-10-04，源码 `1c1e0dc5b30a65a83673951cc495b1a7b700511c`，148 个源码/配置指纹 | 后续只改 PDF 渲染代码，不重新计算 API pilot 成绩；该日志保留，不能累加 |
| 专项机器验收 | **22 passed / 0 skipped / 0 failed，285 个工件指纹一致** | `docs/trial/machine_acceptance_2026-10-04.md`，`.iverilog-ai/machine-acceptance-20261004/` | 2026-10-04 | 3 UI＋19 CLI，T12 缺失工具退出 2→正常恢复退出 0；不是真人试用 |
| 自动化测试与类型检查（历史快照） | **768 passed / 1 skipped / 0 failed；mypy 64 文件 0 error** | `docs/experiment/local_validation_2026-10-04.md` 及其附带日志 | 2026-10-04，基线 `2ef75da` + 当轮修改 | 当时 PDF 同步后的全量快照，不是当前结果，不累加 |
| 中间回归（历史快照） | **910 passed / 1 skipped，197.00 秒** | `.iverilog-ai/ic-validation-final-20261004/pytest.log` | 2026-10-04 | before 门控前中间源码，已由当前 914/1 替代 |
| 更早失败回归（历史保留） | **909 passed / 1 failed / 1 skipped，222.74 秒** | `.iverilog-ai/ic-validation-exact-snapshot-20261004/pytest.log` | 2026-10-04 | output_dir 边界测试失败；不能将该日志误引为 910 全过，也不替换当前 914/1 |
| 自动化测试（历史快照） | **720 passed / 1 skipped** | `python -m pytest -q` | 2026-10-01（HEAD `84943ad`） | 不是当前回归结果；另有更早的 700 passed / 1 skipped。历史干净 venv 为 675 passed / 3 skipped / 0 failed。当前见上方 914/1 行 |
| 类型门禁 | mypy 61 文件 0 error | `python -m mypy` | 2026-10-01 | |
| 死代码 | 121 文件 0 处 | `python scripts/check_dead_code.py` | 2026-10-01 | |
| 编码门禁 | 0 问题 | `python scripts/strip_bom.py --check` | 2026-10-01 | |
| 基准矩阵（2026-10-01 代码复跑） | 参考设计 15 个**误报 0**；缺陷变体 83 个 **83/83 检出**；不可判定 0 | `python scripts/run_benchmark_matrix.py --output-dir .iverilog-ai/matrix-final` | 2026-10-01 | 每案例的 `result.json` 原样保留；矩阵为速度默认不 dump 波形 |
| 证据包可复核性（历史快照） | 8 文件 / 11.1 KB；**6 条记录 sha256 逐条重算一致**；zip 完整性 OK | `python .dsh-tmp/verify_pack_final.py G:\iai-evidence-pack-final` | 2026-10-01 | 本轮未重新生成；历史重新哈希结论不等于当前代码的完整可复现性 |
| 本轮c7/v4冻结交接包 | **127,448,982字节；10,331 ZIP条目，10,330项文件SHA全匹配；4源码归档；注册280/281精确匹配** | `docs/competition/ic/evidence_pack_v4_2026-10-04.md`与JSON | 2026-10-04，材料c5e9171；生产28be1ed | 1早期计划MD未恢复，2旧provider换行恢复明记；已知负例junction链接明确排除；CRC/SHA是字节检查，非人审或异机 |
| 当前v5限定证据包 | **48,306,453字节；3,282 ZIP条目，3,281文件SHA/CRC通过；74/74输入字节冻结** | `docs/competition/ic/evidence_pack_v5_2026-10-05.md`与JSON | 2026-10-05，生产4d8eafb | 包括本轮60任务/41请求、允许目录的失败与截图；不替代旧c7/v4或其缺项；包后回执独立存放 |
| 当前v5包外反例重放 | **108输出比较/16失败；failed_checks；0API；结构化stdout与原run一致** | `docs/experiment/ic-agent-v5-pack-replay-2026-10-05/receipt.json`及完整stdout/stderr | 2026-10-05，从新ZIP解至仓库外独立Temp目录 | 同机已有Python/Icarus，不导入项目模块；过程退出0不是DUT通过；首次辅助脚本文件计数错误在执行前停止，另存 |
| 当前v5包后代理核查 | **3,281项SHA/CRC、74快照、60行/150执行侧、41请求和预算一致** | `docs/review/ic_v5_pack_review_2026-10-05.md`及`docs/review/ic-v5-pack-review-2026-10-05/receipt.json` | 2026-10-05，独立子代理只读核查 | 仅3.55e-15耗时浮点尾差，无实质冲突；复核既有离线日志，不重跑仿真/凭据扫描/历史远程响应，不是H02或异机 |
| 本轮包后反例重放 | **338比较/48失败；failed_checks；0API；过程退出0** | `docs/experiment/ic-agent-v4-pack-replay-2026-10-04/receipt.json`及stdout/stderr | 2026-10-04，新目录解包后运行真实replay.py | 同机既有Python/Icarus，无项目模块导入；初次辅助脚本ZIP根路径错误另存，不当模型或DUT失败 |
| 包内源码离线抽检 | **0 API 请求；547 输出比较 / 0 差异；退出 0** | `docs/experiment/ic-pack-smoke-2026-10-04/smoke.json`、stdout/stderr | 2026-10-04 | 外层ZIP提取源码和冻结UART RX，显式导入提取后的src；使用本机已有依赖/Icarus；首个辅助脚本字段KeyError另记，不计入应用失败或模型成绩 |
| 静态规则 | 44 条（error 4 / warn 27 / info 13） | `iverilog_ai.core.static_review.RULE_REGISTRY` | 2026-09-29 实测 | 规则的**条数不是效果**：噪声率另有指标 |
| 参考模型覆盖 | 15 个设计 | `iverilog_ai.core.reference_model.AUTHORITATIVE` | 2026-09-29 实测 | 只有这些设计能自动提供独立期望值；其余必须人工合约 |
| 提交体检 | 1 error（`CITATION.cff` 仍写 `example.invalid`） | `python scripts/check_submission.py --repo .` | 2026-09-29 | **已知未修**：仓库公开后填真实地址 |

## 6. 逐项资源与成果链接

| 项 | 状态 |
|---|---|
| 仓库公开地址 | **未确定**（`CITATION.cff` 仍是占位 `example.invalid`，也是提交体检里唯一的 error） |
| GitHub Action 外部调用验证 | **未做**（需要一个调用方仓库才能真跑） |
| 外部模块（第三方 RTL）验证 | 3模块24输入：新人工SPEC15/15，旧13/15保留；差分15/6/3。UART RX旧1请求联调见3.4，新判据见3.7；不计AI增益 |
| 真人试用记录 | **无记录**（任务卡与汇总工具已就绪；机器 22 项验收不替代真人） |
| 演示视频 | **未录**（脚本已就绪：`docs/demo/demo_script.md`） |
| 提交文案（名称/简介） | **已备**（`docs/competition/submission_cover_text.md`，2026-10-04 实测 242 字） |
| 原开源赛道证据包 | **2026-10-01 历史生成与核验，本轮未覆盖**（`G:\iai-evidence-pack-final[.zip]`） |
| 本轮c7/v4本地证据包 | **已生成、字节校验及同机反例重放**（`.iverilog-ai/ic-agent-v4-evidence-20261004.zip`）；280/281注册字节匹配，1项缺失明记；异机、真人及正式提交未完成 |
| 当前v5本地证据包 | **已生成、字节校验及仓库外反例重放**（`.iverilog-ai/ic-agent-v5-evidence-20261005.zip`）；74/74新输入齐全，不改写旧缺项；异机、真人与正式提交未完成 |
| 历史 IC 本地证据包 | **已生成与代理审计**（`.iverilog-ai/ic-evidence-pack-20261004.zip`）；旧包内源码同机抽检通过；不含本轮c7/v4原件，异机与正式提交未完成 |

其中未确定、未做、无记录与仅有历史证据的项目，不写成当前已完成；机器验收不能补写真人完成状态。

## 7. 维护规则

1. 新数字进报告之前，先在本文件登记一行；没有来源文件的一律不写进报告。
2. 口径变了（例如这次的固定分母改造），**新结果另存新目录**，旧目录只读；
   报告里引用旧数字时必须带上"旧口径"标注。
3. 任何"通过/检出"类结论都要能回答两个问题：**在哪套口径下**、**对哪些输入**。
