# 同轮数、同单次刺激预算：历史数据重汇总

这是对已完成实验的**事后共同 seed 子集分析**，不是新实验，也不是预注册验证。没有重新调用模型或运行仿真。
对 random、ai（MockProvider）、online_ai 一律选择 seed 0–4，各 5 轮；选择规则是共同连续前缀，没有按检出率挑轮次。
相同 seed 编号只是历史轮次对齐，不表示在线模型与随机策略使用相同随机源或生成同样激励。原有 10 轮在线记录完整保留。

fixed 是已记录的一轮确定性人工激励参照，不能说成实跑了 5 轮，也不参与‘5 轮总刺激预算相同’的比较。

## 结果

| 策略 | 实际轮数 | 累计检出 | 单轮平均 | 单轮范围 | 不可判定变体行 | 参考告警失效变体（去重） |
|---|---:|---:|---:|---:|---:|---:|
| 人工固定（单轮参照） | 1 | 57/67（85.1%） | 85.1% | 85.1%–85.1% | 0 | 0 |
| 随机 | 5 | 57/67（85.1%） | 78.2% | 74.6%–83.6% | 0 | 0 |
| Mock 回放随机计划 | 5 | 57/67（85.1%） | 78.2% | 74.6%–83.6% | 0 | 0 |
| 在线 deepseek-flash | 5 | 61/67（91.0%） | 83.9% | 79.1%–86.6% | 0 | 0 |

在所选共同子集中，在线模型累计检出 61/67，随机为 57/67，净多 4 个；单轮平均分别为 83.9%、78.2%。
人工固定单轮参照为 85.1%；在线模型单轮平均低于该参照。样本仅覆盖这些内置案例和 5 个历史轮次，不能推广为 AI 普遍优于人工，也没有进行显著性或独立留出集检验。

## 计分与预算核对

- 分母从 manifest 的参与案例中固定提取；缺失、生成失败、编译失败、超时、无可比检查等按现有 `strategy_scoring.summarize` 记为不可判定且仍留在分母。
- 同一（案例，seed）的参考 RTL 出现功能告警时，相关变体行的检出作废。变体的 `passed_with_warnings` 可表示真实功能差异，不能一律当作执行失败。
- 本次所选记录的不可判定变体行总数为 0；参考告警失效行总数为 0。表格末列按（案例，变体）去重，JSON 同时保留失效行数与告警计划数。
- 共核对 1280 条执行记录的 `total_cycles == budget_cycles`；缺失变体记录 0，未执行记录 0。
- 三种 5 轮策略逐案例的单次、累计周期预算相同。Mock 与随机计划哈希一致：True；Mock 回放不是独立的模型能力证据。

| 案例 | 每次周期预算 | 三种 5 轮策略的每变体累计周期 |
|---|---:|---:|
| debounce | 32 | 160 |
| edge_detector | 20 | 100 |
| handshake_stage | 24 | 120 |
| johnson_counter | 24 | 120 |
| mod10_counter | 24 | 120 |
| pulse_stretcher | 32 | 160 |
| pwm | 32 | 160 |
| sequence_101_overlap | 24 | 120 |
| spi_master | 64 | 320 |
| sync_fifo | 40 | 200 |
| sync_reset | 20 | 100 |
| traffic_light_emergency | 24 | 120 |
| uart_tx | 40 | 200 |

## 在线请求记录

所选子集共有 65 个计划请求，只有 63 个含 provider usage，另有 2 个没有 usage。按 `request_id` 去重，不能把同一请求在多个变体上的记录重复相加。

已记录 prompt tokens：**119,262**；completion tokens：**470,098**；total tokens：**589,360**。
其中 reasoning tokens 为 **367,668**，是 completion 的子集，不再额外相加。cache hit/miss 分别为 90,624/28,638。
这些数值仅汇总保存下来的 usage，不是完整账单、付费 HTTP 调用数量或实付费用；没有 usage 不等于零费用。

缺少 usage 的计划请求：

- `online_ai-pwm-3`
- `online_ai-spi_master-3`

## 复现与文件

在仓库根目录执行（仅读取本地文件，不联网）：

```powershell
python scripts/summarize_matched_budget.py --rounds 5 --output-dir docs/experiment/matched-budget-2026-10-04
```

也可用随本报告保存的精简输入快照复核到其他目录：

```powershell
python scripts/summarize_matched_budget.py --source docs/experiment/matched-budget-2026-10-04/selected_runs.json --rounds 5 --output-dir .iverilog-ai/matched-budget-replay
```

- `summary.json`：完整汇总、逐 seed 检出列表、参考失效/失败统计、预算审计、缺少 usage 的请求及输入 SHA-256。
- `selected_runs.json`：仅保留计分、预算、请求去重所需的原始字段；不含 API 密钥、原始提示或本机仿真路径。它是可独立复核的派生产物，不能代替原始完整实验。
- 原始输入 `.iverilog-ai/strategy-online-flash/strategy_matrix.json` 保持不变；其中未选中的历史记录不能删除或并入本子集统计。

原始在线历史为 **10 轮**，累计 **63/67**、单轮均值 **83.4%**；不可判定变体行 **8**，其中参考告警失效行 **5**。与本报告 5 轮子集是不同统计口径，不能互换。
