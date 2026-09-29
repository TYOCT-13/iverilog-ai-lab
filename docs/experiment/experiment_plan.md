# 三策略公平比较实验协议

本文件是**执行前的协议**，不是结果汇总。协议在跑正式实验之前冻结；如果跑了之后又改口径，
必须把新结果另存，并在报告里说明改了哪一条。

## 目标与策略

比较固定（人工预先写好的向量）、随机（受控种子产生的向量）和 AI（provider 生成、经 `TestPlan` 校验的向量）
三种策略在**同一案例、同一刺激预算、同一观察点集合、同一独立期望值来源**下的效果。
AI 不得修改 RTL、绕过 schema 或直接执行命令。

Mock provider 只用于流程回归（它回放的是随机策略的期望值），**不构成模型能力证据**。

## 控制变量

固定 Icarus/iverilog 版本、OS、Python 版本、RTL commit、testbench 生成器、超时、最大输出与编译参数；
随机策略记录 seed；AI 策略记录 provider/model、端点、提示词指纹与原始计划哈希。
密钥不进任何产物。

### 刺激预算（先按规格定，再看结果）

每个案例的总刺激周期 `T` 写在 `src/iverilog_ai/core/strategy_scoring.py` 的 `CASE_BUDGETS` 里，
**连同理由**（例如 UART 必须覆盖起始位 + 8 数据位 + 停止位，因此 T=40 周期而不是一个统一的小常数）。
同案例的所有策略使用同一个 `T`；不同案例之间 `T` 可以不同。

生成出来的计划一律按 `T` **归一化**后再执行：

- 超出 `T`：从尾部整条截断，跨越边界的最后一条按剩余周期缩短——前面的输入时序语义不变；
- 不足 `T`：按**末态保持**补齐（复制最后一条的输入并延长其周期），不引入新的输入变化；
- **原始计划与归一化计划都留档**（`plan_raw.json` / `plan_normalized.json`），两者哈希都写进行记录。

这条曾经不成立：旧实现里 fixed/random/ai/online 各自跑 4/12/12/18 个向量，
而报告把它当作"同预算比较"。判据是**实际总周期**（`total_cycles`），不是向量条数。

### 期望值来源

三组都用同一份**独立**期望值：内置案例由 `reference_model` 复算并作为权威预言机覆盖；
AI 自己写的期望值只用于"期望值准确性"这一项诊断，不进入检出判定。
不在参考模型覆盖范围内的设计（`AUTHORITATIVE` 之外）**不臆造**权威期望值：没有可用判据时记证据不足。

## 计分口径

1. **分母预先固定**：来自 `benchmarks/manifest.json` 登记的 (案例, 缺陷变体) 组合，
   与"实际跑出了哪些行"无关。某个案例跑了 10 轮，分母仍然只算一次 (案例, 变体)。
2. **不可判定一律按未检出计入**：计划生成失败、计划非法、编译失败、超时、执行失败、
   零可比较检查项，以及**预定轮次里缺失的记录**，都在 `undecidable_by_reason` 里留原因，
   并保留在分母里。`0/0` 记 `n/a`，不写 `0.0%`。
3. **参考告警作废该轮**：某一轮的**参考设计**自己出现功能不一致（硬失败或期望值不一致）时，
   该轮计划对变体的告警不算有效检出（`plans_excluded_by_reference_alarm`）。
   作废的粒度是 (案例, 轮次)，不是整轮。
4. **单轮与累计并集分开报**：`detection_rate`（累计并集）与
   `detection_rate_single_round_{mean,min,max}` 并排给出。同一案例的多个变体不是彼此独立的大样本，
   不做显著性宣传。
5. **同一刺激预算 ≠ 同一端到端成本**：生成时间、重试次数与费用单列，不参与检出率。

## 运行流程

1. 先运行干净 RTL（参考设计），再对每个已登记缺陷变体运行三组策略；
   **参考设计不干净的那一轮，其变体结果不参与有效检出**。
2. 每次只通过 `IcarusExecutor` / `VerificationPipeline` 执行，保留 `SimulationResult`、
   stdout/stderr、输入 SHA-256、testbench、归一化计划与报告。
3. 由独立规则解析结构化记录；检出判定只看**结构化功能失败**（`records`），
   模型自带的额外断言不参与（它们会改变检查强度，因此只作为诊断字段保留）。
4. 报告样本数、单轮均值与范围，注明工具失败、不可判定与作废的轮次。

## 数据表（每行一次运行）

| strategy | case | variant | seed | budget_cycles | vectors | total_cycles | check_count | plan_raw_sha256 | plan_sha256 | prompt_sha256 | model | attempts | usage | generation_ms | compile_ms | sim_ms | records_pass | failures | defects_found | status | undecidable_reason | artifact_paths |
|---|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|

（历史矩阵只有其中一部分字段；缺字段的旧文件按 `None` 读取，不当作通过。）

## 已执行基线

`scripts/run_strategy_experiment.py` 的离线基线在协议改造后重新跑过一遍，产物另存：

- 目录：`.iverilog-ai/strategy-budget-check/`（`--seeds 1`，不含在线模型）
- 分母 67（清单登记的案例 × 缺陷变体，两个纯组合案例因无时钟被跳过）
- fixed 57/67 = 85.1%；random 55/67 = 82.1%；ai（MockProvider）55/67 = 82.1%
- 三组在同一案例上的**实际总周期完全一致**（见 `strategy_matrix.json` 的 `total_cycles`）

历史实验（改造前）保留在 `.iverilog-ai/strategy-experiment-final/`、`.iverilog-ai/model-compare-r10-*/` 等目录，
**只读，不覆盖**。它们的口径与本文不同（预算不统一、分母由行集合决定），因此新旧数字不可混用。

## 不伪造结果规则

空记录、损坏标记、编译失败、超时、缺失工件必须标成 `inconclusive` 或对应的失败状态，
不得记为通过或缺陷已发现。未运行的单元留空；不得估算时间或补写反例。
任何 AI 摘要都不能覆盖 `SimulationResult`。Icarus 为非官方扩展后端，
结论只适用于声明的版本与规格范围；实验不上传密钥、不自动提交 PR。
