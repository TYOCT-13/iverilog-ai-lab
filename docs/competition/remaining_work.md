# 未完成项与推进记录（持续更新）

更新日期：2026-09-12

本文记录**当前仍然开放**的项，以及已经关闭的项（保留原因，便于评审核对）。
API 密钥只通过环境变量传入，不写入代码、日志或报告。

## 一、当前仍然开放的项

### 1. 实验规模

| 项 | 现状 | 说明 |
|---|---|---|
| 真实模型 | **2 个**（`deepseek-flash` / `deepseek-v4-pro`）已跑完同口径对比 | 见 `docs/experiment/model_comparison_2026-09-11.md` |
| 每模型重复次数 | `deepseek-flash` **已完成 10 次重复**（当前 13 案例 / 67 缺陷口径） | `docs/experiment/online_model_r10_2026-09-12.md`；检出 65/67 = 97.0%，参考误报 0 |
| `deepseek-v4-pro` 的 10 次重复 | **仍在运行**（同口径、同重复次数，完成后出对比文档） | 运行器按案例增量落盘，中断不丢已花 token 的结果 |
| 在**当前**基准上重跑在线实验 | `deepseek-flash` 已完成；`deepseek-v4-pro` 进行中 | 上表两行即为此项 |
| 极端参数下的模型行为 | 未做 | 例如超长上下文、非英文目标描述 |

> 在线实验要花真实 token。**不跑就不会在材料里写"已完成"**——宁可写"当前规模与限制"。

### 2. 自定义 RTL 的语法覆盖

- ANSI/non-ANSI 端口解析仍是常见语法子集；复杂参数化位宽、共享方向声明、
  更多 SystemVerilog 类型尚未完整支持。
- 宏定义与 include 目录：命令行（`--define` / `--include-dir`）与网页均已支持，
  但**没有**"依赖关系可视化/自动推导"。
- 自定义 RTL 的期望值证据等级已在报告与网页展示（三态：参考模型 / AI 生成 / 未给出）。

### 3. 诊断与修复闭环

- 已有失败解释、候选修复、临时副本验证（`repair_compare`）与网页入口；
- **尚未**做成统一的闭环报告：失败指纹 → 诊断假设 → 补充测试计划 → 前后结果
  还没有持久化关联；
- 候选修复的应用仍需人工确认，没有独立的确认工作流界面；
- 网页尚未可视化 AI 调用次数与费用上限（定价表已具备，未核验的价格保持 `null`）。

### 4. 需要真人参与的事

- `docs/trial/` 的试用材料就绪，但**还没有真人试用记录**（结果页保持"待收集"）。
- 上游贡献材料（`docs/competition/upstream_contribution.md`）已备好两份 Issue 草稿，
  **尚未提交**——需要维护者账号，提交与回复都要如实记录。

### 5. 明确不做（设计边界，不是欠账）

时序签核、布局布线/比特流、上板验证、代码覆盖率（语句/分支/翻转）、形式化等价证明。
理由与替代证据见 `docs/project_overview.md` 的「项目边界」与 `docs/layered_evidence.md`。

## 二、已关闭的项（保留原因）

| 项 | 结论 | 证据 |
|---|---|---|
| 权威预言机（期望值由参考模型复算并覆盖 AI 数字） | 已完成；AI 期望值偏差单列为诊断指标 | `docs/reference_model_alignment.md` |
| 多周期向量的期望值语义 | 只在该向量末周期检查终值 | `tests/core/` 回归用例 |
| 复位前初值观测 | `sample_before_reset` + contract 端口 `initial` | 同上 |
| 离线调试接口 | 已提供；并已用**离线 AI 路径矩阵**证明 15 个案例逐个跑通 | `scripts/run_pipeline_matrix.py` |
| 流式网关兼容 | `stream="auto"` 三层有界回退 | `docs/experiment/online_model_experiment_2026-09-10.md` |
| 缺陷基准扩展 | 15 案例 / **83** 缺陷，固定矩阵 83/83 检出、0 误报、0 不可判定 | `benchmarks/manifest.json` |
| 2～3 个真实模型对比 | 已完成 2 个（同口径、含可比性检查） | `docs/experiment/model_comparison_2026-09-11.md` |
| token 用量与费用估算 | 逐次记录 usage；价格表未核验时留 `null`，绝不填 0 | `data/model_pricing.json`、`docs/experiment/` |
| 公开未检出缺陷与失败请求 | 首轮实验公开了 9 个未检出缺陷及原因 | `docs/experiment/online_model_experiment_2026-09-10.md` |
| 静态质量审查器 | 44 条规则，每条配正反例与噪声校准记录 | `docs/static_rules.md` |
| VCD 自动分析 | 语义结论、相位检查、失败时间窗、双波形差异、信号活动覆盖率 | `docs/vcd_analysis.md`、`docs/coverage.md` |
| 分层证据 | 仿真/综合/时序/比特流/上板五层显式状态；98 个变体全部可综合 | `docs/layered_evidence.md` |
| 行为级对比 | `compare-rtl` + 网页；语义等价重写判为一致 | `docs/behavior_compare.md` |
| 工程门禁 | 全量测试、基准矩阵、综合矩阵、离线路径矩阵、未可达代码检查、编码卫生、mypy | `.github/workflows/ci.yml` |

## 三、限制（评审须知）

- 在线实验受服务商限流、额度与网络稳定性影响；失败请求保留为失败或 inconclusive，
  不伪造结果。
- 离线路径矩阵证明的是**流水线**在每个案例上都能跑通；其计划来自仓库自带的
  确定性规则，**不代表任何真实模型的能力**。
- Icarus 仿真通过只代表当前 testbench 与仿真证据通过，不代表综合、时序或上板通过。
