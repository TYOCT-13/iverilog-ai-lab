# 外部 RTL 的 API Agent：限定输出差分

2026-10-04。执行与检查来自 Codex 自动化，不是真人试用，也不是独立人工审核。

## 证据与范围

入口 `scripts/run_external_verification_agent.py`。适配器复用项目的有界 Agent 循环、严格 API 动作校验与真实 Icarus 流水线。基线先通过已有手写 SPEC_TB 的有限规格检查，再以 `qualified_baseline_differential` 证据比较输入相同的两次仿真。模型只追加激励，不能改基线、合约或判据。

这不是内置 reference_model，`checks` 和 `failures` 保持 0；另列 `compared_samples`、`differences`。发现差异的标签是 `behavior_difference`，不称“功能反例”。无差异也不是完整功能正确或形式等价证明。输入来自已经分析过的开发重放集，没有独立留出含义。

限定输出：

| 模块 | 已有规格测试支持的比较输出 | 约束 |
|---|---|---|
| uart_rx | m_axis_tdata、m_axis_tvalid、frame_error、busy | valid 为 0 时不比较 payload；未测 overrun_error 不纳入 |
| uart_tx | txd、busy | s_axis_tready 未有直接规格断言，不纳入 |
| priority_encoder | output_valid、output_encoded、output_unencoded | valid 为 0 时不比较未规定的编码值 |

采样点来自生成测试台 `cycle` 计数器实际递增的 VCD 时刻，每次递增紧接测试台采样语句。两侧必须拥有相同采样周期和时间，样本数必须匹配计划周期数；只读顶层合约输出，忽略 DUT 内部寄存器。未知 X/Z、缺失信号、缺失样本、编译/运行失败或输入哈希变化都不能得到一致结论。

历史外部 uart_tx 与内置案例同名。适配器必须显式关闭流水线的内置参考模型映射，避免错误套用不相干的模型；不可通过改输出标签隐藏这类冲突。

## 本地运行

先按 `external_agent_readiness.md` 冻结三个源文件。新输出目录不得存在。

```powershell
python scripts/run_external_verification_agent.py --manifest .iverilog-ai/external/frozen-20261004-ic/manifest.json --candidate .iverilog-ai/external/uart_rx_check/uart_rx_baseline.v --module uart_rx --output-dir .iverilog-ai/external-agent/new-offline --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe
```

默认只执行真实本地资格检查和单轮差分，不调用 API。`--execute` 才运行 API Agent；需显式给出 `--endpoint`、`--model`，凭据由 `--api-key-file` 或环境变量 `IVERILOG_AI_API_KEY` 提供。使用 Chat Completions 协议，不写入凭据。开始于已有的固定激励计划，后续轮次才请求 API 追加输入。

默认最多 3 轮、2 次请求、累计 1200 个双侧激励周期。每轮旧计划重新执行，候选和基线各计一次，因此 UART RX 固定计划 182 周期消耗 364 个预算周期。资格检查是额外的固定准备步骤，单独记录，不计进 Agent 激励周期；复位开销也不包含在刺激周期中。API 上限不是金额封顶。

## 产物与验证

`qualification/` 保留冻结基线、候选、输入清单、SPEC_TB、编译与仿真日志、`qualification.json`。每轮保留候选与基线的真实 pipeline_result、波形、`baseline_samples.json` / `candidate_samples.json` 和 `external_observation.json`。Agent 轨迹仍使用主循环的逐轮落盘和请求预算机制。

在接口联调中，真实 Icarus 对历史 UART RX 位序变体记录了 cycle 80、836 ns 时 m_axis_tdata=150 与 105 的差异；比较了 547 个有效输出样本。该运行没有调用 API，也没有创建新变体。

实际服务商 API 联调由主任务统一执行。本适配器开发使用真实 Icarus 和明确 mock 的网络测试，不把 mock 结果作为真实模型成绩。现有 SPEC_TB 的覆盖局限不会因 Agent 接入而消失，尤其 UART TX 的历史两个变体曾被规格测试台漏检。


离线验收：`tests/core/test_external_agent.py` 20 项通过，适配脚本 mypy 通过。覆盖三模块基线、已有等价改写、真实位序差异、编译失败、仅内部字段变化、采样不足/XZ、冻结源和资格哈希变化；两项 mock HTTP 配合真实 Icarus 验证了共用 Agent 的追加激励与双侧预算。364 周期预算时没有 API 请求，1200 周期预算时 1 次 mock 请求、2 轮执行实际消耗 732 个双侧激励周期。

可保留的本轮独立离线 CLI 证据：`.iverilog-ai/external-agent/uart-rx-bit-order-typed-offline/offline-round/external_observation.json`。这是机器执行的真实仿真结果，不是实际服务商调用记录。
