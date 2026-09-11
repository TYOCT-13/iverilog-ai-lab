# 真实在线模型实验记录

记录日期：2026-09-10
服务商与端点：DeepSeek 官方接口 `https://api.deepseek.com`
模型：`deepseek-flash`
请求形状：`chat_completions`，`stream=auto`，`max_retries=1`
重复次数：每案例 1 次（`--online-repeats 1`）
案例集合：11 个（`benchmarks/manifest.json` 的 categories 减去纯组合逻辑案例）
完成任务：256/256，不可判定 0

> 本记录不含 API Key、原始提示词或模型响应正文。凭据只经环境变量传入。

---

## 一、四策略对照结果

同一组案例、同一套显式 DUT 合约、同一个 `VerificationPipeline`，四个策略的差别只在
**测试计划从哪来**：

| 策略 | 模型请求 | 请求级合法率 | 参考误报(硬失败) | 参考设计期望值不一致 | 缺陷总数 | 缺陷检出 | 检出率 | 平均生成 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed（人工固定向量） | 10 | 100% | 0 | 0 | 54 | 35 | 64.8% | — |
| random（随机激励） | 10 | 100% | 0 | 0 | 54 | 30 | 55.6% | — |
| ai（离线 MockProvider） | 10 | 100% | 0 | 0 | 54 | 30 | 55.6% | 4.8 ms |
| **online_ai（deepseek-flash）** | 10 | **100%** | **0** | **2** | 54 | **45** | **83.3%** | **37.2 s** |

### 关键读法

1. **模型没有被"猜错期望值"污染结论**：所有策略的参考误报（硬失败）都是 0。
   缺陷检出与误报用同一套结构化失败反例判定，因此这组数字可以直接比较。
2. **真实模型的检出率(83.3%)明显高于随机(55.6%)与离线 Mock(55.6%)**，
   也高于人工固定向量(64.8%)。这说明模型确实在有方向地构造能触发缺陷的输入，
   而不是在"猜哪个 RTL 有 bug"。
3. **AI 自己写的期望值只有 75.5% 与独立参考模型一致**。也就是说，如果让 AI
   同时负责"设计测试"和"判定对错"，大约四分之一的检查会建立在错误期望值上。
   这正是本项目把参考模型设为权威预言机、把 AI 期望值偏差单列为诊断指标的原因。
4. **参考设计上的 2 条期望值不一致**（`uart_tx` 8 条、`pwm` 5 条 warn 记录）
   经逐条核查，全部是 AI 对边沿采样相位与计数器边界的判断错误，不是工具缺陷，
   也不是参考模型错误——这两个案例目前不在权威预言机范围内（见第四节）。
5. **平均生成耗时 37.2 s**，明显长于固定/随机/离线策略（毫秒级）。
   在线实验必须把生成耗时与仿真耗时分开统计，否则会把模型延迟误读成工具变慢。

## 二、token 使用量

逐次记录保存了服务商返回的 usage（`strategy_matrix.json` 的 `runs[].usage`）。
本次 10 次计划请求的合计：

| 项 | 数值 |
|---|---:|
| prompt tokens | 15,179 |
| completion tokens | 98,025 |
| total tokens | **113,204** |

> **口径更正（2026-09-12）**：本节早先给出的是 `97,124 / 542,183 / 639,307`。那是
> **按行累加 usage** 得到的：一次计划请求的计划被同一案例的多个变体复用，每个变体行
> 都带着同一份 usage，于是总量被放大约 5.6 倍。按 `request_id` 去重后如上表所示，
> 单请求均值约 **11.3k** tokens。结论与量级判断不变，绝对数字此前偏高。
> 已同步修正 `scripts/compare_models.py` 的汇总口径并加了回归用例。

其中 completion 主要来自推理 token（样例：单次请求 3475 completion tokens 中
2242 为 reasoning tokens）。

**费用估算（仅供参考）**：本次未接入价格表，因此不给出金额。如需在报告中写出成本，
应显式标注价格来源与日期，并按"每次计划"和"每个检出缺陷"两个口径分别计算。
`strategy_report.md` 不包含费用字段，避免用未核实的单价推断结论。

## 三、可复现命令

```powershell
$env:IVERILOG_AI_API_KEY = "<临时密钥>"
python scripts/run_strategy_experiment.py `
  --project-root . `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe `
  --seeds 1 `
  --online `
  --online-endpoint https://api.deepseek.com `
  --online-model deepseek-flash `
  --online-repeats 1 `
  --online-stream auto
```

产物：

- `.iverilog-ai/online-real-flash/strategy_matrix.json`（逐次机器可读记录）
- `.iverilog-ai/online-real-flash/strategy_report.md`（人类可读汇总）

## 四、本次实验暴露并已修复的三个问题

为了让这次实验能跑通，修掉了三个真实缺陷（都已提交并有测试覆盖）：

1. **模型生成的断言字段不合规**：模型给出 `signal_equals` 之类的模板名但字段名
   不符合受控模板（例如自己发明字段）。修复方式是让提示词显式列出每个模板允许的
   字段集合，并把实验的 `max_retries` 从 0 提到 1，允许模型在收到严格 Schema 的
   拒绝原因后自我纠正一次（只重试一次，避免放大成多次请求与多份费用）。
2. **参考模型时序与 RTL 不一致**：`sync_fifo` 的 `rd_data`/`empty`/`full` 有三条
   语义此前写错，会把"参考设计通过"改写成"参考设计失败"。已逐拍对齐并加入权威
   预言机，同时新增 `tests/core/test_reference_model_alignment.py` 作为"对齐一个、
   加入一个"的可执行门禁。
3. **权威预言机的适用范围**：只有逐拍对齐过的设计才允许覆盖 AI 期望值；
   `uart_tx`、`spi_master`、`handshake_stage`、`debounce`、`pwm`、`sync_reset`
   目前仍只用于诊断，这些案例回退为 AI 期望值并在 oracle 记录中标注
   `expectation_source="ai_generated"`。本次 `uart_tx`/`pwm` 的 2 条不一致就落在
   这个范围内，属于诊断信息，不影响裁决。

## 五、尚未完成

- **每个模型至少 10 次固定重复**：本次每案例只跑了 1 次（控制额度消耗）。
  要写出均值与标准差，需要把 `--online-repeats` 提到 10 并预留足额额度。
- **2～3 个模型的公平对比**：本次只评测了 `deepseek-flash`。
  该端点还提供 `deepseek-v4-pro`，接入方式只需换 `--online-model`。
- **费用估算字段**：需要在实验中增加价格配置并注明价格来源与日期。
- **未检出缺陷清单公开**：本次 `online_ai` 在 54 个缺陷中检出 45 个，剩余 9 个如下表。
  按要求公开，不做隐去。

### 本次 online_ai 未检出的 9 个缺陷

| 案例 | 缺陷 | 未检出的原因 |
|---|---|---|
| `spi_master` | `spi_bug_sclk_polarity` | AI 计划未驱动 `start` 或不检查 `sclk` 周期数，时钟不翻转这一差异没有被观测到 |
| `spi_master` | `spi_bug_done_missing` | AI 计划未在传输结束后检查 `done` 脉冲 |
| `spi_master` | `spi_bug_extra_bit` | AI 计划未统计一次传输的 `sclk` 上升沿个数（多发一位不可见） |
| `handshake_stage` | `hs_bug_data_captured_always` | AI 计划未构造「`in_valid=0` 但数据变化」的场景，无法暴露数据被无条件捕获 |
| `debounce` | `deb_bug_reset_state` | AI 计划未声明复位后的期望输出，复位初值错误不可见 |
| `mod10_counter` | `mod10_bug_async` | 该缺陷的差异只在**复位前的上电初值**，需要 `sample_before_reset`；AI 计划未启用 |
| `mod10_counter` | `mod10_bug_enable_sticky` | AI 计划未构造「使能撤销后再次使能」的序列 |
| `sequence_101_overlap` | `seq_bug_late` | 该缺陷只在被检测序列的**同一拍**体现，AI 计划的采样相位未命中 |
| `traffic_light_emergency` | `traffic_bug_emergency_output` | 该缺陷只在**时钟边沿之间**改变输入才可观测（生成式 testbench 的已知边界） |

这 9 项的共同点是：**AI 计划都没有把对应缺陷的触发条件写进测试意图**。这是"AI 测试规划"
的真实能力边界，而不是判定错误——它们全部由人工固定向量或手写边界 testbench 检出
（固定矩阵 70/70）。要提升这一指标，方向是给规则包补充协议级触发清单，
而不是放宽判定标准。

