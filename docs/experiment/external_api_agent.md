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

采样来自生成测试台实际采样语句后的只读 `$display` 快照，位于 `cycle` 递增与下一组输入赋值之前。补丁要求锚点数量等于计划周期数、每个锚点的前行必须是原始结果输出语句；结构变化即拒绝运行，不静默替换。每侧保留未插桩测试台、实际编译测试台及 generator/adapter/测试台 SHA256。两侧必须拥有相同采样周期和时间，样本数必须匹配计划周期数；只读限定合约输出，忽略 DUT 内部寄存器。未知 X/Z、缺失信号、缺失样本、编译/运行失败或输入哈希变化都不能得到一致结论。

旧版使用 cycle 变化所在 VCD 时间戳最终值，现已停用：组合逻辑下一输入可能在同一时间戳更新输出，不能代表采样语句瞬间。本轮真实取证发现 priority_encoder 16 个点中 4 个不一致。原始错误证据保留在 `.iverilog-ai/external-agent/sampling-cross-review-20261004/`。

历史外部 uart_tx 与内置案例同名。适配器必须显式关闭流水线的内置参考模型映射，避免错误套用不相干的模型；不可通过改输出标签隐藏这类冲突。

## 本地运行

先按[冻结输入与重放说明](external_agent_readiness.md)冻结三个源文件。新输出目录不得存在。

```powershell
python scripts/run_external_verification_agent.py --manifest .iverilog-ai/external/frozen-20261004-ic/manifest.json --candidate .iverilog-ai/external/uart_rx_check/uart_rx_baseline.v --module uart_rx --output-dir .iverilog-ai/external-agent/new-offline --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe
```

默认只执行真实本地资格检查和单轮差分，不调用 API。`--execute` 才运行 API Agent；需显式给出 `--endpoint`、`--model`，凭据由 `--api-key-file` 或环境变量 `IVERILOG_AI_API_KEY` 提供。使用 Chat Completions 协议，不写入凭据。开始于已有的固定激励计划，后续轮次才请求 API 追加输入。

默认最多 3 轮、2 次请求、累计 1200 个双侧激励周期。每轮旧计划重新执行，候选和基线各计一次，因此 UART RX 固定计划 182 周期消耗 364 个预算周期。资格检查是额外的固定准备步骤，单独记录，不计进 Agent 激励周期；复位开销也不包含在刺激周期中。API 上限不是金额封顶。

## 产物与验证

`qualification/` 保留冻结基线、候选、输入清单、SPEC_TB、编译与仿真日志、`qualification.json`。每轮保留候选与基线的真实 pipeline_result、波形、`baseline_samples.json` / `candidate_samples.json` 和 `external_observation.json`。Agent 轨迹仍使用主循环的逐轮落盘和请求预算机制。

早期接口联调的“547 样本、cycle 80”记录来自旧 VCD 时间戳法，存在采样歧义，不能独立支撑精确采样主张。修复后另在全新目录用即时快照真实重放该历史 UART RX 变体，重新观察到 cycle 80、836 ns 的 m_axis_tdata=150 与 105、547 个有效输出比较。新旧产物均保留，不用新结果覆盖旧证据。两次均未调用 API、未创建新变体。

实际服务商 API 联调已由主任务统一完成，见[真实联调记录](external_agent_live_2026-10-04.md)及[公开摘要](external-agent-live-2026-10-04/summary.json)：1 次 deepseek-flash / Chat Completions 请求、2 轮、输出上限 8192 tokens、双侧周期上限 1200；实际 usage 5661 tokens，累计执行 782 双侧周期。计划从 23 向量/182 周期扩展到 27 向量/209 周期，有效输出比较从 547 增至 628，两轮均无差异，达到 round_budget 停止。这组真实值与下方 mock 测试的 732 周期必须区分。

真实联调使用相同冻结字节的候选与基线，证明链路可运行，不证明模型提高了检出率。最终计划在已有位序变体上的 0 API 重放仍发现同一差异，但原固定计划也能发现，不能将功劳归给新增向量。已有 SPEC_TB 只是有限规格检查，不因接入 Agent 成为独立完整规格；UART TX 两个历史变体的规格漏检仍保留。真实请求、mock 网络回归都不能替代真人试用或独立人工复核。


历史初版离线检查曾有 20 项通过，但未覆盖同时间戳后续输入变化，不能作为修复后验收。修复后 `tests/core/test_external_agent.py` **24 项通过**，适配脚本 mypy 通过。新增连续组合输入在 before/after 两种相位的逐点规格检查、UART before 第一采样时刻 28 ns 检查，以及补丁锚点变动即拒绝的测试。覆盖三模块基线、已有等价改写、真实位序差异、编译失败、仅内部字段变化、采样不足/XZ、冻结源和资格哈希变化；两项 mock HTTP 配合真实 Icarus 验证了共用 Agent 的追加激励与双侧预算。364 周期预算时没有 API 请求，1200 周期预算时 1 次 mock 请求、2 轮执行实际消耗 732 个双侧激励周期。

修复后独立离线 CLI 证据：`.iverilog-ai/external-agent/uart-rx-bit-order-exact-snapshot-offline/offline-round/external_observation.json`。旧 `uart-rx-bit-order-typed-offline` 目录保留为历史含采样歧义的记录。这些都是机器仿真结果，不是实际服务商调用记录。


采样歧义的发现与修复过程见[代理交叉检查](../review/external_agent_cross_review_2026-10-04.md)。版本 `1c1e0dc` 对内置 reference_model 的 before 相位采用保守门控；外部适配器已关闭该模型映射，并通过 typed observer 使用真实测试台同点快照，因此不受该内置预测限制影响，也不将其误报为外部功能正确性。
