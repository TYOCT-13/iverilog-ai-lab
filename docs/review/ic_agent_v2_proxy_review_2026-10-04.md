# IC Agent v2 代理复核记录（2026-10-04）

本次代理复核发现两项会造成覆盖假命中或错误成绩的阻断问题；修复后，原反例、新增篡改对照及合法执行对照均得到预期结果，相关定向测试 **81 passed，24.62 s**。当前审查范围内未发现残留阻断。

这是开发过程中的代理技术复核，执行者为 Codex 子代理 `/root/conflict_status`。它**不是真人独立审核，不计入 H02**，也不是竞赛认证。此次 API 请求数为 0，没有读取密钥、调用在线模型、修改历史实验原件或提交 Git。全量回归与正式真实 API 评测在本记录编写时尚未完成，不能从本记录推导其通过或效果提升。

## 1. 范围与版本

审查对象为逐周期采样、功能场景覆盖、Agent 反馈消融、协议预算及比较汇总。重点核对：真实采样点与 VCD 同时间戳末值的差别；缺失、乱序、X/Z、保持输入、参数支持范围；端点断言与逐周期观察的计数；FIFO 净变化为 0 的基线、独立队列规格和单点变体；oracle/coverage 的模型可见性；检出分母、首反例预算、用量与证据绑定。

源码哈希采集时间：**2026-10-04 20:47（UTC+08:00）**。当时 HEAD 为 `d1feb018c1839289c371e6fa6f85ec76f32b4d52`，工作区存在已修改与未跟踪文件。本轮新增采样、覆盖、汇总脚本及测试不都在该 HEAD 中，**不能把此 HEAD 单独称为已复核版本**。下表是当时工作区文件的字节 SHA256；后续冻结提交需另行记录实际提交号。

| 文件 | SHA256 |
|---|---|
| [observations.py](../../src/iverilog_ai/core/observations.py) | `9883628573a7669229a47180dea84591b5b7c7fd7fd2d82dd0d8867019b8e0f3` |
| [functional_coverage.py](../../src/iverilog_ai/core/functional_coverage.py) | `70cd1c00c0e8bc5877fafdb6ba88491d9c5ba2ae16714230aee2a30dfd4bb2fe` |
| [testbench.py](../../src/iverilog_ai/core/testbench.py) | `72da53d44f9a1f2998cc1dfe9d21b1cfd70a29bd46292f4eea2abb78143f468e` |
| [pipeline.py](../../src/iverilog_ai/core/pipeline.py) | `55e8359c2112807b742404822e8bc8538570bda18c751e91b0a876717c29fa6a` |
| [reference_model.py](../../src/iverilog_ai/core/reference_model.py) | `d3b7ab61f9a4fe2ec4ed4551b395193a5c37ebf31e4f01e4e44c73f9f1f1b209` |
| [agent.py](../../src/iverilog_ai/ai/agent.py) | `06bd54f636fed3fb4245e111bd0a08105456569338077107a4d05723ecbc62b6` |
| [run_agent_comparison.py](../../scripts/run_agent_comparison.py) | `b8dbf4bc3a9bac6b9a82fe8f2385ffc21de2d2364a79ccc646bfc17eb5e6b299` |
| [summarize_agent_comparison.py](../../scripts/summarize_agent_comparison.py) | `b6f806d7362216e2af7fcff470454e8d1ce50edadf899b59e2380622c21280d7` |
| [agent_protocols.json](../../spec/agent_protocols.json) | `24c046c9e0e9a11cc04402efd705244d6efc6417a1e8fafe65ed5db1fc449280` |
| [mutation_manifest.json](../../benchmarks/agent_v2/mutation_manifest.json) | `5ca8faef783e5d3a3a30ceed4a137353917c767dd7650966e8e4cdb93b7067eb` |
| [sync_fifo.v](../../rtl/sync_fifo.v) 与 [基线快照](../../benchmarks/agent_v2/sync_fifo_reference.v) | `964cd554041818533ece195f3abcc6979c116c4a3d72106a7fe49c503bd2dadc` |

正向控制的 [preregistration.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/preregistration.json) 保存了执行前更完整的 `code_and_input_sha256`。其中覆盖、pipeline、运行与汇总四个核心文件 SHA 与本表一致。本记录没有为修复前源码另建完整冻结快照；原漏洞证据保存了当时的输出，不应声称只检出上述 HEAD 即可重现旧漏洞。

## 2. 发现 A：采样 packet 没有绑定真实执行

原实现检查 RTL、计划、合约和测试台四项输入 SHA，以及 packet 结构、输入保持语义，但这些输入哈希不能证明 packet 中输出没有被改写，也不能仅凭 packet 自报 `status=complete` 证明进程完成。

实际复现使用正确 FIFO、3 个 idle 周期和真实 Icarus：原结果只命中 `fifo.empty`；只把自己新实验 packet 中一条输出改成 `full=1, empty=0`，输入及四项 provenance 保持不变，分析仍返回 `measured`，并增加 `fifo.full`。原进程对象在内存中替换为 `run=None` 时，旧分析也仍返回 `measured`。前者保存在 [packet_tamper.json](../../.iverilog-ai/agent-v2-proxy-audit-1dda850aa6/packet_tamper.json)，原始执行为 [idle/pipeline_result.json](../../.iverilog-ai/agent-v2-proxy-audit-1dda850aa6/idle/pipeline_result.json)；后者只有当次工具输出，没有另存独立 JSON。实验 packet 测试后恢复原字节，没有改动既有历史实验。

修复由实现代理完成：pipeline 保存 packet 的 SHA256；覆盖分析核验真实 `ProcessResult` 完成、返回码为 0、未超时/截断、具有 stdout，再核验 packet 字节哈希，并用本次进程内存中的 stdout、原计划、合约和四项 SHA 重解析，比较整个 packet。功能断言失败但进程正常完成时，仍允许统计实际观察到的场景。

复核代理使用当前 pipeline 重新执行，没有拿缺少新 SHA 字段的旧 packet 充当修复通过证据。新执行：[capture/run/pipeline_result.json](../../.iverilog-ai/agent-v2-proxy-recheck-9236dde473/capture/run/pipeline_result.json)；结果：[recheck.json](../../.iverilog-ai/agent-v2-proxy-recheck-9236dde473/recheck.json)。

| 对照 | 实测结果 |
|---|---|
| 未修改的 FIFO idle 3 周期 | `measured`，仅 `fifo.empty` |
| 只修改 packet 输出 | `unknown`，`observed_samples_digest_mismatch`，无命中 |
| 同时修改 packet 输出与 metadata SHA | `unknown`，`observed_samples_stdout_mismatch`，无命中 |
| 原 packet 保持完整，执行对象改为 `run=None` | `unknown`，`execution_not_complete`，无命中 |

首次复测脚本调用因新目录中的 `capture` 尚未预建，在允许根路径校验时停止，未执行仿真。随后另建唯一目录并预建该目录后完成上述复测；这个准备错误不计为产品缺陷或通过样本。

## 3. 发现 B：汇总直接信任检出布尔值及可变注册字段

原汇总只按 case、variant、strategy、seed 匹配预注册样本，然后允许结果覆盖注册字段，并直接汇总 `detected`。因此下面这个**有意构造的审计输入**可以得到错误成绩；它不是实际实验结果：

```python
base = {
    "case": "sync_fifo", "variant": "x", "strategy": "feedback", "seed": 0,
    "status": "not_started", "detected": False, "budget_cycles": 160,
}
changed = {**base, "status": "compile_failed", "detected": True, "budget_cycles": 999}
build_summary(
    {"rows": [changed], "finished_at": "2026-10-04T00:00:00Z", "changed_inputs_at_finish": []},
    {"rows": [base]},
)
```

旧输出 [summary_inconsistent.json](../../.iverilog-ai/agent-v2-proxy-audit-1dda850aa6/summary_inconsistent.json) 同时包含 `eligible_for_frozen_comparison=true`、检出 1/1、不可判定 1、预算 999，尽管没有 round 或真实执行证据。

修复后，预注册不可变字段必须相同；正式汇总核验原执行工件哈希、RTL 来源、计划与实际/参考观察，并按 round/reference 判据重算检出及首反例信息。不能只改 `detected` 增加成绩。

复测仍用上述输入，预算 999 被 `immutable preregistration row field mismatch` 拒绝。将预算恢复 160、保留 `compile_failed + detected=true` 后，结果为 `evidence_unknown`、检出 **0/1**、`eligible=false`；分母没有因证据缺失被删掉。结果同样见 [recheck.json](../../.iverilog-ai/agent-v2-proxy-recheck-9236dde473/recheck.json)。

原汇总还遗漏了已保存的“结果可获得时间”。修复后单列该字段，物理失败瞬间的墙钟时间仍为 `null`，不将两者混为一谈。

## 4. 合法执行与篡改对照

为避免修复只会拒绝所有结果，另建 [agent-v2-proxy-summary-e2df558de2](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/)：`profile=v2`，只选 `sync_fifo`、`protocol_random`、seed 0、1 个缺陷，同时包含正确基线。使用本地 Icarus，`request_cap=0`，真实请求数为 0。

| 项目 | 实测结果 |
|---|---|
| 正确基线 | `not_detected`，无误报，`evidence_verified=true` |
| `fifo_bug_full_off_by_one` 单点变体 | `detected`，`evidence_verified=true` |
| 完整合法结果 | `eligible=true`；1 个变体分母，另有 1 个正确基线样本 |
| 首反例 | 零基 cycle 3，累计搜索预算 4 周期 |
| 时间 | 物理失败墙钟 `null`；本次结果可获得时间 0.703 s，不含之后参考审核耗时 |
| 执行记账 | 两个样本合计搜索 320 周期、参考审核 320 周期、960 项输出断言 |
| 只把报告中变体的 `actual.failures` 加 1 | `observation_disagrees_with_result`，`eligible=false`，检出降为 0，真实工件未修改 |

原件：[preregistration.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/preregistration.json)、[run_settings.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/run_settings.json)、[results.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/results.json)；复核结果：[proxy_summary_recheck.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/proxy_summary_recheck.json)。这是汇总完整性的正向控制，不是新增正式检出率评测；不能将这个 1/1 当成 Agent 或 AI 效果成绩。

## 5. 实际测试与其余核查

修复后执行以下定向测试，执行器返回 **81 passed in 24.62s**。使用已安装的 Python 和 Icarus；`--basetemp` 位于仓库外。本次未单独保存 pytest stdout 文件，测试计数与耗时来自当次工具执行记录。

```powershell
# 在项目根目录运行；每次使用仓库外的新目录。
$reviewTemp = Join-Path $env:TEMP ("icarus-proxy-v2-" + [guid]::NewGuid().ToString("N"))
python -m pytest tests/core/test_functional_coverage.py tests/core/test_agent_comparison_summary.py tests/core/test_observed_samples.py tests/core/test_agent_comparison.py tests/ai/test_agent.py::test_real_functional_feedback_ablation_keeps_sampling_and_trace_without_leaks -q --basetemp $reviewTemp
```

该 81 项是本次修复后的定向快照，不与此前已跑的 44 项、8 项重复累加，也不等于全量回归。

| 测试文件 | 记录时 SHA256 |
|---|---|
| [test_observed_samples.py](../../tests/core/test_observed_samples.py) | `c79244944a6b31ccddfdd60a8b635a370617fddc9007e8041f3cd08b8d784471` |
| [test_functional_coverage.py](../../tests/core/test_functional_coverage.py) | `b0a76ca55a917e2651593c6934d33eda78275848c310ac2161f230f4fe467d4c` |
| [test_agent_comparison_summary.py](../../tests/core/test_agent_comparison_summary.py) | `147a8114b9ce4a4a66473ee83b2a80e6fee976f388ce83c30369c9a4c9f0b088` |
| [test_agent_comparison.py](../../tests/core/test_agent_comparison.py) | `95fbfd31e50e786449add78cd67dd328df802edb2dacfdae8cef71f26bcb26bb` |
| [test_agent.py](../../tests/ai/test_agent.py) | `d2087f04b1d21cf76a9bd9d7a0d336a696c40d9aae17b3c95680a2f491cf64a9` |

此外，源码与定向执行核对了以下边界：

- 多周期向量每个激励周期都记录实际端口值，但原功能断言仍在向量端点执行。真实 UART 三种消融第二轮均观察 45 周期、8 项端点断言，两轮累计执行 49 周期；三者首轮提示词相同，无反馈组不暴露 observation，无覆盖组不暴露 coverage，完整执行事实仍落盘。
- 真实 mux 对照在 t=2 ns 的语句采样为 `sel=0, y=17`，同一时刻 VCD 末值已是 `sel=1, y=34`。采样采用执行语句当时值，没有拿 VCD 时间戳末值补猜前一个操作。对应可重复测试为 `test_every_cycle_snapshot_uses_sample_statement_and_preserves_verdict`。
- 缺失、重复、乱序、相同采样时刻、错误宽度、错误来源及截断不能形成完整覆盖；省略输入按照实际保持语义核对。X/Z 的必要条件不计命中；不支持的参数或外部合约不套用内置覆盖配置。
- FIFO 逐拍检查使用独立 `deque` 队列规格，覆盖空满拒绝、同拍接受净 0、指针回绕和复位；两个新变体通过字节级单次替换检查。此前针对采样、功能覆盖、协议清单、参考模型对齐的 44 项执行通过，其中相关文件为 [test_agent_protocol_specs.py](../../tests/core/test_agent_protocol_specs.py)（SHA `0e1eff03fe07b36eab31fc893b3d2330fb3e72df10e33e116c6bb197c1d5906b`）和 [test_reference_model_alignment.py](../../tests/core/test_reference_model_alignment.py)（SHA `bad1b0a430c3e59ed27e9c151973ce29a9ab2ccce777f36d1236f7364c4f33cd`）。这仍是机器规格检查，不是真人独立审核。
- 各策略实际向量数、端点断言密度、累计周期、参考审核成本和 token 并不相同。新旧版本还同时改动 FIFO 基线、规格、预算与采样组织，因此不能把新旧成绩差或组间差直接归因于覆盖反馈；见 [v2 评测计划](../experiment/agent_comparison_v2_plan_2026-10-04.md)。无反馈组仍执行失败即停止，也不应描述成没有任何执行信息的完全盲搜索。

## 6. 原件摘要与未完成项

下列都是本次代理在唯一新目录创建的证据，没有覆盖正式或历史结果。

| 原件 | SHA256 |
|---|---|
| [原 packet 篡改结果](../../.iverilog-ai/agent-v2-proxy-audit-1dda850aa6/packet_tamper.json) | `35d6c9f058e663385d11a49c68b49e41fd2f97bea1093109000d3e6a7333d9e3` |
| [原汇总矛盾构造](../../.iverilog-ai/agent-v2-proxy-audit-1dda850aa6/summary_inconsistent.json) | `941bd0079fd3d7ead2234ae142304c0934749b2680adf5e22a1e98ea2cad6c12` |
| [修复后原反例复测](../../.iverilog-ai/agent-v2-proxy-recheck-9236dde473/recheck.json) | `4cf8a348a07c55cf030e63eb3dad843d241249a12ee3de95bfb7039b58c8de40` |
| [合法对照复核](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/proxy_summary_recheck.json) | `19b1ba4a940ddc1fa7124e896ca6aee563ded026e843883dd37208a249834ab6` |
| [合法对照 results.json](../../.iverilog-ai/agent-v2-proxy-summary-e2df558de2/results.json) | `a67e6c9a44a5cbb1e695d5d8afc05a4516a07a745ed9f1cb35d7b5addde0b499` |

这些 `.iverilog-ai` 本地产物未因写入本记录自动进入 Git 或提交包；移交审核前需另行包含原件并核对哈希。源码记录与本地工件哈希用于发现不一致，不构成数字签名或对恶意重写全部证据的防篡改认证。

尚未由本记录完成：冻结提交后的全量回归、真实 API 的 v2 重复比较、服务商账单核对、独立留出模块评测、真人可用性试用与 H02 独立人工审核。本记录不预填这些项目的通过状态，也不提供成绩提升或获奖保证。
