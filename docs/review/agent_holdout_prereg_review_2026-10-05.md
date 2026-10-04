# 新模块留出事前代理审查（2026-10-05）

本次结论：最终候选的任务登记、刺激预算、模型可见信息和两类逐拍判据未发现尚未修正的阻断问题。审查中发现的向量预算表述冲突，以及自定义基线缺少执行前上限检查，均已在真实 API 请求前修正并复核。此结论只允许进入后续冻结与实际评测流程，不是评测成绩、全仓验收通过、外部认证或 H02 真人独立审查。

审查对象是 [事前方案](../experiment/agent_holdout_study_plan_2026-10-05.md)、[新入口](../../scripts/run_agent_holdout_study.py)、[模块资产](../../benchmarks/agent_holdout_20261005/README.md)及其接入判据。审查代理没有修改生产源码、旧实验或旧复核报告，没有读取真实凭据，没有发出真实 API 请求。只运行了获授权的本地定向测试、Icarus 对照和截断网络的 HTTP stub。

## 冻结与字节边界

既有 Agent 来源为 `f664d85c9204ffacb64c54feeb9e6dd13c87a34a`；Agent v6 文件 SHA256 为 `b3eca75bab345ef2b9d5d2ebd0280f9811bd37532fb979d2f8c5a4ac220ce5fe`，SYSTEM_PROMPT SHA256 为 `8b5f844143e9c85052eee2398cf2f13c4840e3fc86e589ca9c48fc4304c7cb03`。二者与登记配置一致，没有为新模块改变 Agent 算法或系统提示词。

本报告绑定的是资产作者及入口作者停止写入后的 **49 个候选文件原字节**，完整路径、大小和 SHA 见 [机器回执](agent-holdout-prereg-review-2026-10-05/receipt.json)。新留出源码提交在本报告写入时尚未创建，因此不把既有提交号冒充包含新模块的提交。当前部分资产有 CRLF；审查保留这些字节，没有做换行归一化。

| 关键文件 | SHA256 |
|---|---|
| `benchmarks/agent_holdout_20261005/manifest.json` | `9bc16e190ed4c9fa295bf0b692cd85bbe5c6015ca5cfd808d7b70c4df7974a44` |
| `benchmarks/agent_holdout_20261005/validation_receipt.json` | `73b2b8931692348295db60061f8e358b8c73e0e4652e5656cecfdbc569ca8a6c` |
| `docs/experiment/agent_holdout_study_plan_2026-10-05.md` | `79b22d63331d87bb498f8e494336b3670f3ed444acf8557fcc565a501c9ddc97` |
| `scripts/run_agent_comparison.py` | `1296186752f5fd91fbc24bb055219386a8cf6d212b8944f0e9efc6ea4c8325d4` |
| `scripts/run_agent_holdout_study.py` | `cb01b01c9c1865811993fde74a9736845ed7862cae03f49edb89bd4af6763079` |
| `scripts/summarize_agent_comparison.py` | `c184667043131fcfe1ed7934c2152ff2471004137c0f421e2d2c952d21c57d5b` |
| `src/iverilog_ai/core/reference_model.py` | `561eaf956a660ac6f3cfb4b28ba04561e63cebef2cf8eac2089b5d3e76287219` |

## 发现与修复

1. **向量预算口径冲突。** 初审时两份实际模型规格写“最多 200 个向量”，同时计划要求每提案最多 12 个。进一步核对发现执行入口没有覆盖 AgentLimits.max_vectors，实际默认累计接受上限是 64，也不是 200。最终规格、manifest、配置及方案明确为每任务累计 16 刺激周期、每提案最多 12 向量、累计接受最多 64 向量。通用 TestPlan 的 200 上限若作为内部结构限制保留，须与本批实际 Agent 上限分开；16 拍上限在本批先于累计 64 向量触发。修正文案没有改变冻结 Agent 或四个变体语义。
2. **自定义基线接入保护不足。** 初版 execute 直接执行 baseline_factory 的返回计划。现有 18 个冻结基线本身全部合规，但接口不能独立拒绝超额工厂。最终 execute 在 DUT 前检查 TestPlan 类型、模块名、登记向量上限及累计周期；17 拍、13 向量及错误模块的三个反例均停为 execution_error，实际 pipeline 调用为零，任务行仍保留。旧入口没有登记新向量上限时保留既有默认兼容。
3. **旧固定案例路径已解耦。** 新入口显式登记 contract_path/reference_rtl/目标 RTL；execute 在创建输出及初始化 provider 前验证其登记与安全路径。参考重放和摘要均使用同一登记映射，不再把新资产强行归入旧四案例路径。接口资源校验失败会在整批开始前终止，不产生可选择的部分成绩。

首次资产 `release` 保留字编译错误仍由资产回执登记，修正为 `release_req` 后的记录另存。该失败没有被当作通过。本代理没有重放初版错误；只读确认其回执保留状态与原件引用。

## 任务、预算与模型信息

冻结集合是 2 模块 × 3 目标 × 3 次重复 × 6 策略，共 **108 个唯一任务**。每策略 18 个任务，包括 **12 个缺陷任务和 6 个正确控制**；12 是四个不同缺陷各重复三次，不能解释为 12 个独立缺陷。六策略为 fixed、random、protocol_random、single、feedback、no_feedback，均保留注册分母。

所有任务累计刺激上限为 16 拍，逐拍 after 检查输出；每实际 episode 从独立自动复位开始。single 最多 1 请求/1 轮，其余两种 API 策略最多 3 请求/3 轮，理论请求总数为 18 × (1+3+3) = **126**。所有实际 provider 共享同一 1,000,000 token 账本，4096 输出上限，拒绝与失败也计账；旧批次用量不扣本批。此处核对接线和冻结配置，不声称已经产生新的真实用量。

纯内存重算的 18 个基线（2 模块 × 3 基线 × 3 seed）均恰好 16 拍、每计划不超过 12 向量、after 采样、期望字段为空且确定性相同。各 seed 向量数：

| 模块 | fixed | random | protocol_random |
|---|---|---|---|
| credit_guard | 6 / 6 / 6 | 12 / 12 / 12 | 4 / 4 / 4 |
| rotating_arbiter | 10 / 10 / 10 | 12 / 12 / 12 | 10 / 10 / 11 |

fixed/protocol_random 合并相邻相同输入，未改变展开后的 16 拍序列。random 按合同数据输入位宽均匀产生 12 个独立段，前四段各 2 拍，其余各 1 拍。因此它不是旧四模块“每拍独立重新采样”的同一个随机条件，不能直接合并两批分数。Agent 仍可能用较少周期或更短提案；预算是共同上限，不保证每组实际使用相同拍数或请求数。

最终 HTTP stub 检查覆盖两模块、A/B/C 三目标、反馈/无反馈两模式，共 12 场景、36 次模拟传输。先运行一次内存 pipeline，再给坏 JSON，最后 stop，以检验已有观察和格式诊断后的消息。网络连接被显式拒绝；内存 pipeline 不是 DUT 证据。真实 typed 消息为 system/user，同模块三目标各轮 state 相同，没有目标路径、RTL 源码/SHA、变体标签、manifest 或人工 witness；current_plan 没有参考输出 expected 值。模型收到的是规格、合同、预算和该策略允许的反馈。

no_feedback 的 observation、plan_error、latest_decision_error 始终为 null，参考答案没有借这些字段回传。执行器仍根据仿真结果早停，剩余预算和流程状态也保留；因此不把它描述为完全无信息的因果控制。新模块功能覆盖分析器返回 unsupported/unknown，没有新增覆盖命中或定制覆盖提示。修复前相同 12 场景的另 36 次模拟请求原件也保留，两轮共 72 次 **模拟** 传输，真实 API 为 0。

## 判据、变体与实际本地验证

credit_guard 的 Python 判据按饱和算术及同时保持更新，独立资产语义使用事件差值夹紧，RTL 用条件分支。rotating_arbiter 的集成判据先从旧指针循环选择，再决定下一拍指针；资产语义用模距离最小值，RTL 用四套显式优先级。已核对异步低复位、输出寄存、单点选择、空请求保持及环回。错误端口/位宽/参数/时钟或复位合同不获得权威判据；X/Z、非法输入及 before 采样也被拒绝。

A 与正确参考 RTL 字节一致；每个 B/C 均是 manifest 唯一锚点的一次替换，其余字节相同。四个手工触发序列的真实 Icarus 输出如下；这些是离线判据审查，不是 Agent 提案或成绩：

| 变体 | 刺激拍数 | 正确输出 | 变体输出 |
|---|---:|---|---|
| credit_guard mutation_b | 4 | 2, 1, 0, 0 | 2, 1, 0, 7 |
| credit_guard mutation_c | 1 | 3 | 2 |
| rotating_arbiter mutation_b | 2 | 1, 1 | 1, 2 |
| rotating_arbiter mutation_c | 2 | 1, 2 | 1, 1 |

本代理实际执行的检查分为两次：

- 40 项定向 pytest 通过（1.98 秒）：唯一替换 SHA、完整状态/输入转换、四个 witness、错误合同、X/Z、before 拒绝，以及真实逐拍 pipeline 原件绑定。其中真实 Icarus 为 10 次资产运行、690 条逐拍观测，另有 2 次 pipeline 运行、26 项检查。
- 修复后 9 项复核通过（1.71 秒）：最终预算/可见范围、SHA、固定语义控制，以及三个基线执行前拒绝反例；这一轮不执行 DUT。

两轮有 SHA 检查重复，不把 40+9 说成 49 个独立测试；也不与其他代理或全仓测试数字相加。pytest basetemp 位于仓库外。12 次真实 Icarus 的 56 个原始文件另有逐字节 ZIP 副本，SHA `0cd444c6dd8eae679a0941d8e0f16b2a1bb5b5cca3b75291cecaeb38da24cf4d`。日志、命令、原件索引、最终 HTTP stub 及候选字节清单均由机器回执绑定，私有根目录为 `.iverilog-ai/holdout-prereg-review-20261005-bfe9e11ea9/`。初次辅助汇总脚本误读 pipeline JSON 顶层 status，发生 KeyError 后改读 simulation.status；未改实验记录或重跑 DUT，该辅助错误也在回执注明。

## 保留的限制

这是 Agent 冻结后由内部作者构造的两类合成新模块，不是外部盲测，也没有真人参与；模型预训练是否见过类似算法未知。正确模型的完整有限状态/输入转换审查不能替代任意工业 RTL、综合、时序或硬件验证。四个已知单点变体、三个重复和非配对模型随机数不足以预设统计胜利或反馈因果。本报告不新增 H02 记录。

使用 [readable-verilog-generator 技能](C:/Users/TYOCT/.codex/skills/readable-verilog-generator/SKILL.md) 的只读 analyze 路由；资产已有严格门禁保持未通过，未把本代理的本地 Icarus 通过当作技能门禁通过：

| 技能公开门禁 | 两个模块当前状态 |
|---|---|
| compile | passed（技能静态解析） |
| ast | failed |
| readability | failed |
| comment | passed |
| naming | failed |
| profile | passed |
| testbench | not_requested（技能报告；本次项目测试另列） |
| toolchain | not_requested（技能报告；本地 Icarus 另列） |

credit_guard 为 36 errors/0 strict warnings，rotating_arbiter 为 115 errors/1 strict warning。WaveDrom 规定渲染器及部分技能依赖缺失，不声称 SVG 渲染、完整技能链路、综合、时序收敛或硬件验证通过。最终源码提交、全仓验收及真实 108 任务评测均由根代理另行留证；本报告不预写其通过或成绩。
