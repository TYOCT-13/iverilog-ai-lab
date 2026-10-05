# v8 新内部合成模块集合留出实验登记

本轮使用 `valid_data_pipeline` 和 `event_accumulator` 两个新内部合成模块。
Agent 在新模块生成前冻结于 `a96933786c17986a739fc2da515db3294d6e8044`；
模块此前未接受本项目的受控 API 评估。这里的留出是内部合成模块集合留出。
设计、变体和准备验证由本团队制作；不声称外部盲测、独立人审或预训练未见。

## 冻结和执行准入

配置为 `spec/agent_new_holdout_study_1m_v8.json`，资产清单为
`benchmarks/agent_new_holdout_20261005/manifest.json`。准备阶段保持
`freeze_status: UNFROZEN` 和 `manifest_sha256: null`，允许只读机械登记和 dry-run。
只有最终资产、Oracle 适配器、机械测试与来源复核全部完成后，才由主任务将
配置改为 `FROZEN`、填写清单原字节 SHA-256，并把全部改动提交到 Git。

`--execute` 必须同时满足冻结配置、最终清单及其闭合成员集合原字节一致、
v8 源码和提示一致、Git 已提交且工作树干净、全新输出路径，以及显式
`--api-key-file`。全部门禁均先于读取密钥、创建输出或初始化 provider。
不从环境变量读取密钥。清单中的 contract 必须通过完整固定接口及
`reference_sampling_profile` 校验，不能只按模块名称匹配。

执行前只读核对以下五个旧批次的 `results.json`、`token_budget.json`：

- `agent-study-1m-live-20261005`
- `agent-recovery-study-live-20261005`
- `agent-holdout-study-live-20261005`
- `agent-budget-study-live-20261005`
- `agent-feedback-study-live-20261005`

旧账必须有 `finished_at` 且没有 pending 请求。unknown usage 保留其状态、
原 totals、完整 reservation 和原账 SHA，不视为零；旧账不扣本轮额度。
缺少本机私有原账时明确记录 absent 并拒绝执行，不伪造已核验。
旧批次成绩不参与本轮任务、变体、基线或输入选择。本轮也不补跑 v8 的
八个 `token_budget` 失败行。

## 固定范围和策略

两模块各包含正确 RTL、B 和 C 两个固定语义变体；每个目标重复三次，
依次运行 `fixed`、`random`、`protocol_random`、`single`、`feedback`、
`no_feedback` 六策略，共 108 任务。每策略保留 12 缺陷任务分母
（四种不同缺陷各重复三次）和六个正确控制任务。

每任务统一 24 拍累计 stimulus 上限，自动复位和正确 RTL 逐 episode
审计单独计数。每 proposal 最多 12 个向量，累计接受最多 64 个向量。
每个实际 episode 使用全新 DUT 与独立自动复位，不继续前一 episode
状态。时钟固定 `i_clk`、10 ns、posedge；复位为 `i_rstn`、异步低有效、
自动保持两拍。所有输出每拍在 after 时刻采样。

`single` 共用 v8 提示与 schema，最多一次 API request 和一个实际 episode。
`feedback` 与 `no_feedback` 各最多三次共享 request 和三个实际 episode；
格式拒绝、计划预算拒绝和运行后的请求消耗同一限额。`no_feedback` 隐藏
端口观察、覆盖、格式和计划诊断，但保留执行器提前停止和自身剩余额度。
理论上限为 126 请求。各任务/API 失败、未执行和额度不足均保留登记分母。

`fixed` 和 `protocol_random` 基线只用正确规格、显式 contract 和 seed，
不读 RTL、变体标签、私有 witness 或成绩；不因准备验证的检测率重选。
`random` 用 seed 均匀独立采样各业务输入，固定 12 段、每段两拍。
顺序按 seed、目标等级和 case 排列，各组六策略按
`(seed + variant_rank + case_rank) mod 6` 轮转。

## API、预算和证据

运输固定为 `https://api.deepseek.com`、`deepseek-flash`、
`chat_completions`、thinking disabled、nonstream、`store=false`、60 秒超时、
单请求输出 4096 token，自动 transport retry 为零。用户称其为 4.1f API。
完整独立共享额度为输入加输出 1,000,000 token，所有付费拒绝均记账。
沿用 `TokenBudget` 保守 reservation 和 unknown usage 语义，不把缺失 usage
当零，不额外计入 cache-hit/miss。中断也保存 ledger。

API 输入仅为正确规格、接口 contract、允许驱动输入和动作、当前计划、
策略允许的反馈以及剩余额度。不发送 RTL、私有目标/变体、资产路径、
witness、旧成绩或 mutation metadata。

复用 `run_agent_comparison.execute`：每个实际执行 episode 都在正确 RTL
独立重放同一计划；任一正确 RTL alarm 或缺少真实证据令样本无效。
复用 `build_summary` 严格核对真实日志、全部输出采样、固定 contract、
执行来源 SHA 和登记分母。summary 不把准备验证视为 API 结果。

登记动态记录当前 Git `source_revision`，另列 Agent 的原冻结 revision。
冻结全部 `src` Python、执行器依赖、本入口/config/本文、三份新测试、
`.gitattributes` 以及两正式新资产目录的每个原件（正确/变体 RTL、
contract、参考函数、基线、witness、规格和验证证据）。共享执行器在请求前
保存每个原件的原字节副本和 SHA-256，不转换换行。
新输出唯一为 `.iverilog-ai/agent-new-holdout-study-live-20261005`。

机械命令（不读真实 key、不调用 API、不运行 DUT）：

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 scripts/run_agent_new_holdout_study.py
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m pytest -q tests/core/test_agent_new_holdout_study.py
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m mypy scripts/run_agent_new_holdout_study.py
```

最终冻结与提交后，主任务在本机唯一执行完整批次：

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 scripts/run_agent_new_holdout_study.py --execute --api-key-file <本机密钥文件>
```

输出包括 preregistration、registered-inputs 原字节快照、run_settings、
逐任务真实 artifacts、results、previous_batch_accounting、token_budget 和
strict_summary。只有 summary 的真实证据门禁成立才报告可用于冻结比较；
模块留出也不直接推断外部泛化、显著性或因果增益。
