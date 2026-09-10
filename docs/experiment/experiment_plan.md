# 三策略公平比较实验协议

## 目标与策略

比较固定（人工预先写好的向量）、随机（受控种子产生的向量）和 AI（provider 生成、经 `TestPlan` 校验的向量）三种策略在相同案例、预算和 testbench 观察点上的效果。AI 不得修改 RTL、绕过 schema 或直接执行命令。

## 控制变量

固定 Icarus/iverilog 版本、OS、Python 版本、RTL commit、testbench、超时、最大输出、编译参数和 run 资源；随机策略记录 seed，AI 策略记录 provider/model、prompt 版本和原始计划哈希。每策略使用相同的 wall-clock 或向量预算，至少重复 5 个 seed（AI 若非确定则记录每次响应）。

## 运行流程

1. 先运行干净 RTL，再对每个已登记缺陷变体运行三策略。
2. 每次只通过 `IcarusExecutor` 执行，保留 `SimulationResult`、stdout/stderr、输入 SHA-256 和报告。
3. 由独立规则解析结构化记录，统计发现的缺陷；人工复核边界样本。
4. 报告样本数、均值/标准差、置信区间（如适用），注明工具失败与 inconclusive。

## 数据表（每行一次运行）

| strategy | case | rtl_revision | seed/request_id | budget_s | vectors | compile_ms | sim_ms | records_pass | failures | defects_found | status | artifact_path |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| fixed/random/ai | traffic_light_emergency |  |  |  |  |  |  |  |  |  |  |  |

## 已执行基线

脚本 `scripts/run_strategy_experiment.py` 已按上述流程完成 5 个 seed 的离线基线：

- fixed：20 次运行（4 个参考 + 16 个缺陷），计划合法率 100%，参考误报 0，检出 16/16。
- random：100 次运行（5 个 seed），计划合法率 100%，参考误报 0，检出 13/16。
- ai：100 次运行（5 个 seed，`MockProvider`），计划合法率 100%，参考误报 0，检出 13/16。
- 三种策略均使用相同的 `VerificationPipeline`、Icarus/vvp、超时和结构化结果协议；
  完整行级证据见 `.iverilog-ai/strategy-experiment-final/strategy_matrix.json`。

## 不伪造结果规则

空记录、损坏标记、编译失败、超时、缺失工件必须标为 `inconclusive`/对应失败状态，不得记为通过或缺陷已发现。未运行的单元留空；不得估算时间或补写反例。任何 AI 摘要都不能覆盖 `SimulationResult`。Icarus 为非官方扩展后端，结果仅适用于声明的版本与规格范围；实验不上传密钥、不自动提交 PR。
