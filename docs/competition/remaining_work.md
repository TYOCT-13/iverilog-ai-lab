# Icarus 智测未完成项与实验推进记录

更新日期：2026-09-09

本文记录改进方案中尚未完成的能力，并作为后续实现的验收依据。当前优先推进真实在线模型实验；API 密钥只通过环境变量传入，不写入代码、日志或报告。

## 一、尚未完成的功能

### 0. 本轮已解决（原「技术问题」清单）

- **权威预言机**：内置案例的期望值改由参考模型独立复算并覆盖 AI 数值，AI 期望值
  偏差单列为诊断指标。修复前在线实验出现「参考误报 25/40」，根因是 AI 猜错期望值
  被同时计入误报与检出；修复后参考误报与期望值不一致双双归零。
- **多周期向量期望值语义**：`expected` 只在该向量末周期检查，不再逐周期比对终值。
- **复位前初值观测**：新增 `sample_before_reset` 与 contract 端口 `initial` 字段，
  覆盖「上电初值不符合规格」这类此前不可观测的缺陷。
- **本地调试模型服务**：`iverilog_ai.ai.debug_server`，OpenAI 兼容、仅监听回环地址、
  不联网、无需 API Key，使在线代码路径可离线回归。
- **流式网关兼容**：provider 新增 `stream="auto"`，对只接受 SSE 的网关自动回退。
- **缺陷基准扩展**：12 个案例 / 70 个缺陷，固定矩阵 70/70 检出、参考误报 0、不可判定 0。

### 1. 实验可信度

- 缺陷基准已扩展到 50 个；当前固定矩阵实跑检出 50/50、参考误报 0、不可判定 0。下一步目标是继续提升缺陷类型多样性并向 50 个以上扩展新的协议和时序错误。
- 尚未完成 2～3 个真实在线模型的稳定对比实验。
- 尚未完成每个模型至少 10 次固定重复实验。
- 已形成统一 JSON/Markdown 实验报告，包含请求级合法率、生成延迟、仿真耗时、缺陷检出率和不可判定原因。
- token 使用量和费用估算尚未在逐次记录及汇总中体现。
- 还需公开未检出缺陷和失败请求，避免只展示最好结果。

### 2. 自定义 RTL 通用性

- ANSI/non-ANSI 端口解析仍属于常见语法子集。
- 复杂参数化位宽、共享方向声明和更多 SystemVerilog 类型尚未完整支持。
- include/宏/参数依赖尚未提供完整的用户确认界面。
- 自定义 RTL 的期望值证据等级（规格、人工、AI）尚未在报告中单独展示。

阶段 2 已完成首版：FIFO、UART、SPI、Valid/Ready 握手、按键去抖、PWM、多路选择器和同步复位均有 Python reference model，并纳入一致性检查；FIFO/ UART/ SPI/ 去抖/ PWM 的关键参数已进入 contract，并用于 testbench 实例化和模型计算。更完整的协议边界测试仍在后续完善。

阶段 3 已完成首版：新增 RTL 静态质量审查器和 `review_rtl.py` 命令行入口，输出质量评分、error/warn/info、规则 ID、行号、源码哈希和修复建议；网页支持内置/自定义 RTL 审查和报告下载。后续仍可增加更完整的 AST/CDC/位宽分析。

阶段 4 已完成首版：新增无第三方依赖 VCD 解析、信号列表、时间范围和变化统计；流水线、报告和网页均可展示 VCD 自动分析结果，仍需后续增加失败周期自动关联和标准/自定义 RTL 波形差异检测。

### 3. AI 诊断与修复闭环

- 已有失败解释、候选修复和临时副本验证，但尚未形成统一的自动闭环报告。
- 失败指纹、诊断假设、补充测试计划和前后结果尚未统一关联持久化。
- AI 调用次数、预算和费用上限尚未在网页中可视化。
- 候选修复最终应用仍需人工操作，尚未提供明确的人工确认工作流。

## 二、真实在线模型实验实现状态

`scripts/run_strategy_experiment.py` 现已增加 `online_ai` 策略：

- 每个案例默认重复 10 次，可通过 `--online-repeats` 调整；
- endpoint、model 和 API key 由命令行参数/环境变量提供；
- 每次请求记录 `plan_valid`、生成耗时、计划哈希、模型 usage（若服务商返回）；
- 在线请求失败记录为 `inconclusive`，不会伪造仿真结果；
- 汇总增加 `plan_valid_rate`、`mean_generation_ms`、参考误报率和缺陷检出率；
- API key 不进入 JSON 记录。
- 在线计划生成时会把当前案例的 DUT contract 作为受控上下文传给模型，避免将 `enable` 等真实端口猜成 `en`；单个变体的 testbench/仿真异常会记录为 `inconclusive` 并继续后续实验。
- 缺陷统计已按结构化失败反例计数，不再要求总体状态必须为 `failed`；这是因为当前功能不匹配按既定规则显示为 `passed_with_warnings`，但仍应计为缺陷检出。

示例（PowerShell）：

```powershell
$env:IVERILOG_AI_API_KEY = "<临时密钥>"
python scripts/run_strategy_experiment.py `
  --project-root . `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe `
  --online `
  --online-endpoint https://api.deepseek.com `
  --online-model deepseek-v4-flash `
  --online-repeats 10
```

输出文件：

- `.iverilog-ai/strategy-experiment/strategy_matrix.json`
- `.iverilog-ai/strategy-experiment/strategy_report.md`（面向评审和复盘的 Markdown 汇总）

其中 `runs` 保存逐次结果，`summary.online_ai` 保存汇总指标。服务商未返回 usage 时，该字段为 `null`，不能据此推断费用。

Markdown 报告会自动记录开始/结束时间、总耗时、完成任务数、请求级合法率、参考误报、缺陷检出率、平均生成延迟和不可判定错误；报告不包含 API Key、原始提示词或模型响应正文。

## 三、后续验收顺序

1. 用真实 API 完成至少一个模型的 4 案例 × 10 重复实验。
2. 增加模型价格配置和费用估算字段，并在报告中标注价格来源和日期。
3. 接入第二个真实模型，生成公平比较表。
4. 已完成缺陷基准扩展至 50 个；后续继续增加协议和时序类缺陷。
5. 完成自定义 RTL 复杂语法和证据等级标记。
6. 完成诊断/修复闭环持久化和人工确认界面。

## 四、限制

- 在线实验可能受限于服务商限流、额度和网络稳定性；失败请求必须保留为失败或 inconclusive。
- Icarus 仿真通过仅代表当前 testbench 和仿真证据通过，不代表综合、时序或 FPGA 上板通过。
