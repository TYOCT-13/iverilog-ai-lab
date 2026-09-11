# 在线模型实验（10 次重复，当前基准）

运行日期：2026-09-12
模型：`deepseek-flash`（DeepSeek 官方兼容接口）
基准口径：**13 个案例 / 67 个缺陷变体**（`benchmarks/manifest.json` 去掉两个纯组合逻辑案例
`simple_alu`、`mux4`——它们的合约没有时钟，向量式 testbench 不适用，运行器会显式跳过并给出原因）
重复次数：**每个案例 10 次计划请求**（共 130 次）
输出目录：`.iverilog-ai/model-compare-r10-deepseek-flash/`
在线模型状态：`deepseek-v4-pro` 的同口径实验**已完成**（64/67 = 95.5%、计划合法率 100%），
两模型对比见 `docs/experiment/model_comparison_2026-09-12.md`。

---

## 一、实验设计（可比性）

| 维度 | 设置 |
|---|---|
| 案例集合 | 13 个（同一份 `manifest.json` 派生，不由脚本另抄一份） |
| 缺陷分母 | 67（逐案例分母取自清单，不从运行记录反推） |
| 重复次数 | 每案例 10 次；两种被测策略共享同一批案例与重复次数 |
| DUT 合约 | 完全相同（`examples/<case>_contract.json`） |
| 上下文口径 | 完全相同：同一份规则包 + 实测开源约定片段 |
| 判决口径 | 完全相同：Icarus + 结构化断言；内置案例的期望值由参考模型复算并覆盖 AI 数字 |
| 凭据 | 只从环境变量读取；不写入代码、日志或结果文件 |

四个策略的含义：`fixed`（人工固定向量）、`random`（按种子随机激励）、
`ai`（离线 MockProvider，**不代表任何真实模型能力**）、`online_ai`（真实在线模型）。

---

## 二、结果

### 2.1 四策略对比（同一批 67 个缺陷、同一批参考设计）

| 策略 | 计划合法率 | 缺陷检出 | 检出率 | 参考误报 | 期望值不一致 | 不可判定 | 平均生成 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 固定向量（人工） | 100% | 56/67 | 83.6% | 0 | 0 | 0 | — |
| 随机激励 | 100% | 51/67 | 76.1% | 0 | 0 | 0 | — |
| 离线 MockProvider | 100% | 51/67 | 76.1% | 0 | 0 | 0 | 0.0s |
| **在线模型 `deepseek-flash`** | **96.2%** | **65/67** | **97.0%** | **0** | 4 | 5 | 35.3s |

（"检出"按"该缺陷是否至少被检出一次"计；`online_ai` 的参考误报按 125 次参考运行统计。）

三点值得注意：

1. **参考设计零误报**：65/67 检出的同时，**125 次参考设计运行**（130 次请求中有 5 次计划被
   拒绝，其变体行记为不可判定，不产生参考运行）**没有任何一次出现硬失败**——检出率不是靠乱报换来的。
   4 次参考运行出现的是"AI 期望值与参考模型不一致"的**诊断**记录（warn 级），不影响判决。
2. **在线模型明显强于离线基线**：+20.9 个百分点（97.0% vs 76.1%）。离线策略是确定性规则，
   不具备推理能力，这个差距衡量的是"真实模型相对规则生成器的增量"。
3. **不可判定 5 次**：全部是计划被严格校验拒绝（见 2.3），运行器记录为 `inconclusive`，
   **不伪造仿真结果**，也不把它们算成检出或漏检。

### 2.2 逐案例检出（`online_ai`）

| 案例 | 缺陷数 | 检出 | 未检出 |
|---|---:|---:|---|
| sequence_101_overlap | 13 | 13 | — |
| mod10_counter | 12 | 11 | `mod10_bug_async` |
| traffic_light_emergency | 11 | 11 | — |
| johnson_counter | 4 | 4 | — |
| edge_detector | 4 | 4 | — |
| sync_reset | 4 | 3 | `srst_bug_sync_assert_only` |
| debounce | 3 | 3 | — |
| handshake_stage | 3 | 3 | — |
| spi_master | 3 | 3 | — |
| sync_fifo | 3 | 3 | — |
| pulse_stretcher | 3 | 3 | — |
| pwm | 2 | 2 | — |
| uart_tx | 2 | 2 | — |

### 2.3 未检出缺陷（2 个，逐条原因）

| 缺陷 | 触发条件 | 为什么没检出 | 基准矩阵里能否检出 |
|---|---|---|---|
| `srst_bug_sync_assert_only` | `ext_rst_n` 在**两个时钟沿之间**拉低 | AI 生成的激励都是"沿前施加、沿后采样"，检查点落在采样沿上，看不到断言延迟 | **能**（手写边界 testbench 在 `ext_rst_n` 拉低后 1ns 就采样） |
| `mod10_bug_async` | 只能在**复位前**观测（`sample_before_reset`） | 该次生成的计划没有声明复位前期望值 | **能**（边界 testbench 显式观测复位前初值） |

**结论**：这 2 个漏检都不是"模型能力不足"，而是**激励相位/观测点设计**问题——
恰好印证了固定向量策略的价值（人工设计的边界激励能覆盖 AI 想不到的采样时刻）。

### 2.4 计划失败的 5 次请求（3.8%）

5 次请求（`traffic_light_emergency-8`、`sync_fifo-2`、`sync_reset-3`、`sync_reset-8`、
`pulse_stretcher-6`）**两次尝试都被严格校验拒绝**，同一个根因：

```
assertions[0] contains unsupported field(s): signal
input: [{'kind': 'signal_implies', ...}]
```

模型给 `signal_implies` 模板多写了一个 `signal` 字段，而该模板只接受
`when_signal` / `then_signal`（提示词里已逐条列出允许字段）。这属于**受控拒绝生效**：
宁可不跑，也不接受一份语义不明的计划。可改进项（未在本轮改动，以免改变实验口径）：
在提示词里对 `signal_implies` 额外强调"不得包含 `signal` 字段"。

### 2.5 token 与耗时

| 项 | 数值 |
|---|---:|
| 计划请求 | 130（123 次服务商返回 usage；5 次计划被严格校验拒绝；2 次返回了合法计划但未带 usage） |
| prompt tokens | 223,011 |
| completion tokens | 1,006,160（其中大部分是推理 token） |
| total tokens | **1,229,171** |
| 单请求均值 | ≈ 10.0k tokens |
| 生成耗时 | 中位 29.4s / 平均 35.3s / 最慢 157.8s |

> 口径说明：token 按 **`request_id` 去重**后累加。一次计划请求的计划会被同一案例的
> 参考设计与全部缺陷复用，若按"行"累加会把总量放大到变体数倍（本机实测 6–13 倍），
> 早期文档就踩过这个坑，见 `docs/experiment/model_comparison_2026-09-11.md` 的口径更正。
> **金额不给**：`data/model_pricing.json` 的价格未核验，按项目规则不给金额（`null` 不等于 0）。

一个实测细节（样例请求）：prompt 1,782 tokens 中 **1,536 命中缓存**，completion 5,124 中
**3,503 是推理 token**。也就是说成本主要由推理长度决定，而推理长度与"要不要设计断言"
高度相关——这正是 2.4 里那类失败值得优化提示词的原因。

---

## 三、可复现命令

```powershell
$env:IVERILOG_AI_API_KEY = "<临时密钥>"      # 只经环境变量传入，不写入仓库
$env:MODEL = "deepseek-flash"; $env:REPEATS = "10"
python .dsh-tmp/run_online_r10.py            # 或在 CI 之外直接调用：
python scripts/run_strategy_experiment.py `
  --project-root . --output-dir .iverilog-ai/model-compare-r10-deepseek-flash `
  --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe `
  --seeds 1 --online --online-endpoint https://api.deepseek.com `
  --online-model deepseek-flash --online-api-key-env IVERILOG_AI_API_KEY `
  --online-repeats 10 --online-stream auto
```

生成的表格（机械汇总，不含结论）：`scripts/compare_models.py <各模型目录> --output ...`；
该脚本会拒绝把"未跑完（`partial=true`）""案例集合不同""重复次数不同"的记录放进同一张表。

---

## 四、与上一轮（2 次重复、12 案例 / 62 缺陷）的差异

| 维度 | 2026-09-11 | 本轮 |
|---|---|---|
| 案例 / 缺陷 | 12 / 62 | **13 / 67**（新增脉冲展宽器） |
| 每案例重复 | 6 | **10** |
| 检出 | 58/62 = 93.5% | **65/67 = 97.0%** |
| 计划合法率 | 95.8% | 96.2% |
| 参考误报 | 0 | 0 |

两轮**不可直接比较**：案例集合与重复次数都变了。可以说的只有：在更严的基准（多一个
案例类型、多 5 个缺陷、重复次数更多）上，检出率没有下降。

---

## 五、限制（如实说明）

- 本文件只覆盖 `deepseek-flash` 一个模型；`deepseek-v4-pro` 的同口径结果见
  `docs/experiment/model_comparison_2026-09-12.md`。
- 两个纯组合逻辑案例（`simple_alu`、`mux4`）不参与：它们的合约无时钟，向量式 testbench
  不适用，运行器**显式跳过并给出原因**，不静默缩小分母。
- 离线策略的计划由仓库自带的确定性规则生成，**不代表任何真实模型能力**。
- "检出"指该缺陷在固定激励下产生结构化失败记录；这不等于该设计已被完整验证。
- 演示视频、技术报告正文等材料不在本文件范围内。
