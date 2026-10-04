# Agent v2 三次重复实测记录：c7bb280

本轮完成全部252个登记任务、157次真实API请求，未触及335次请求上限。API策略明显低于本地固定与随机基线，主要受动作输出被严格schema拒绝影响。该结果不能支持“Agent提高检出率”或“功能覆盖反馈已带来增益”。全部失败保留，未挑选较好重复作为总成绩。

这是开发集上的机器实验，不是真人试用、独立人工审核、模型训练或独立留出评估。

## 版本与原件

- 源码版本：`c7bb280a1d884db90bd35e89e17142b42b7ca80c`。
- 原始运行目录：[agent-comparison-v2-nonthinking-20261004](../../.iverilog-ai/agent-comparison-v2-nonthinking-20261004/)。
- [预注册](../../.iverilog-ai/agent-comparison-v2-nonthinking-20261004/preregistration.json)、[运行设置](../../.iverilog-ai/agent-comparison-v2-nonthinking-20261004/run_settings.json)、[原始结果](../../.iverilog-ai/agent-comparison-v2-nonthinking-20261004/results.json)、[另存汇总](../../.iverilog-ai/agent-comparison-v2-nonthinking-20261004/summary.json)。汇总未覆盖原件。
- 开始：2026-10-04 13:17:55.721835 UTC；结束：13:30:17.686933 UTC，约741.97秒。北京时间为21:17:55至21:30:17。
- 预注册冻结74项代码与输入；结果的`changed_inputs_at_finish=[]`。该字段为空表示冻结输入未变化，不表示所有模型输出成功。
- 模型`deepseek-flash`，服务商主机`api.deepseek.com`，Chat Completions，显式`thinking_mode=disabled`，`stream=false`，输出上限8192 tokens，请求超时60秒。未取得服务商账单，实付费用未知。
- Agent提示词版本`verification-agent-v3-functional-coverage`；本轮不包含后续v4提示词修改。

统计按[预注册协议](agent_comparison_protocol.md)和[v2计划](agent_comparison_v2_plan_2026-10-04.md)解释。四模块各正确基线加两个缺陷、三次重复、七策略，共252行；缺陷分母为每策略每重复8个，三次合计24个缺陷任务。每策略另有12个正确基线任务，不并入缺陷检出分母。

## 七策略结果

下表分母均保留API拒绝、无执行轮及其他未形成可判定结果的任务。并集只说明三次中至少检出一次的不同缺陷数，不代替平均率。fixed三次使用相同模板，不是三份独立人工测试设计。

| 策略 | 重复0 | 重复1 | 重复2 | 平均检出率 | 三次范围 | 不同缺陷并集 | 未完成或不可判定缺陷任务/24 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed | 7/8 | 7/8 | 7/8 | 87.50% | 87.50%–87.50% | 7/8 | 0 |
| random | 8/8 | 8/8 | 8/8 | 100% | 100%–100% | 8/8 | 0 |
| single | 1/8 | 0/8 | 2/8 | 12.50% | 0%–25% | 3/8 | 21 |
| feedback | 1/8 | 0/8 | 0/8 | 4.17% | 0%–12.50% | 1/8 | 23 |
| no_feedback | 3/8 | 0/8 | 0/8 | 12.50% | 0%–37.50% | 3/8 | 21 |
| protocol_random | 8/8 | 8/8 | 8/8 | 100% | 100%–100% | 8/8 | 0 |
| feedback_no_coverage | 0/8 | 0/8 | 0/8 | 0% | 0%–0% | 0/8 | 24 |

random与protocol_random的100%仅覆盖这8个人工开发集变体，不代表真实IP缺陷检出保证。fixed漏掉本轮`spi_bug_done_missing`，其余三次均相同。协议随机与均匀随机均完成本轮所有登记缺陷的检出，不能据此扩大到未测模块。

## 拒绝、缺失与严格资格

原始252行终态为：76行`detected`、39行`not_detected`、137行`policy_error`；`not_started`和`global_request_budget`均为0。137次模型决策被拒绝，20次通过校验。验证错误类型出现次数为`extra_forbidden`136、`missing`1、`greater_than_equal`1、`too_long`2、`json_invalid`1；一次拒绝可能包含多个错误，类型次数不能当作请求数相加。

这里的`policy_error`是本地动作解析/校验拒绝，不是137次服务商安全拒绝，也不等于137次网络失败。没有通过宽松schema补收不合规输出。

| 策略 | 全部任务数 | policy_error | 完全无执行round | 实际执行round |
|---|---:|---:|---:|---:|
| fixed | 36 | 0 | 0 | 36 |
| random | 36 | 0 | 0 | 36 |
| single | 36 | 33 | 33 | 3 |
| feedback | 36 | 35 | 30 | 6 |
| no_feedback | 36 | 33 | 28 | 9 |
| protocol_random | 36 | 0 | 0 | 36 |
| feedback_no_coverage | 36 | 36 | 34 | 2 |

汇总中`eligible_for_frozen_comparison=false`。具体原因是125行完全没有可核验的仿真round，虽然已记录真实API拒绝和usage。其余127行具有可核验的round证据，合计128个round；有些任务执行有效轮后再遭拒绝，终态仍为`policy_error`。严格资格失败不用于剔除样本：252行、各重复8个缺陷分母和所有已知请求消耗全部保留。本记录描述有限真实结果，不宣称整轮每个任务都具备仿真证据。

已执行并审核的round中，正确目标假警与变体参考重放否决均为0；这不意味着无round的正确基线任务也通过了验证。API策略大量未执行，不能把“没有记录到假警”表述为其完整正确性已验证。

## 请求、周期和检查密度

| 策略 | 请求数 | prompt tokens | completion tokens | total tokens | 搜索周期 | 参考审核周期 | 实际检查数 | 检查/搜索周期 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed | 0 | — | — | — | 10944 | 10944 | 1845 | 0.1686 |
| random | 0 | — | — | — | 10944 | 10944 | 19440 | 1.7763 |
| single | 36 | 54027 | 11095 | 65122 | 120 | 120 | 96 | 0.8000 |
| feedback | 41 | 65596 | 12986 | 78582 | 500 | 500 | 62 | 0.1240 |
| no_feedback | 42 | 64984 | 12212 | 77196 | 423 | 423 | 136 | 0.3215 |
| protocol_random | 0 | — | — | — | 10944 | 10944 | 18450 | 1.6859 |
| feedback_no_coverage | 38 | 57637 | 10682 | 68319 | 99 | 99 | 16 | 0.1616 |

合计157次API请求、289219 total tokens，所有请求均有usage记录，无缺失usage。API上限335是本轮实际冻结设置，不是实付请求数，也不代表必须用尽。服务商缓存字段保留在JSON，不与total tokens重复相加；金额保持未知。

累计周期预算分别为FIFO160、UART512、SPI384、握手160。观察快照不是assertion，未混入检查数。预算相同不代表策略实际花费相同：许多API输出在执行前被拒绝，本轮API组远未消耗完整周期预算。固定、随机和协议随机之间的采样密度也不同；UART/SPI有最多200个向量约束，不能把预算扩大本身解释为AI增益。

## 首反例与功能覆盖消融

首反例预算是此前全部重放周期加当前零基失败周期加一。只统计真实有效检出的任务，不给失败、拒绝或未检出任务虚构首反例值；因此以下条件统计不能单独用于比较总体效率。

| 策略 | 有效检出任务数 | 首反例累计周期：最小/中位/最大 | 结果可获得时间秒：最小/中位/最大 |
|---|---:|---|---|
| fixed | 21 | 4 / 7 / 512 | 0.407 / 1.094 / 3.063 |
| random | 24 | 2 / 15.5 / 93 | 1.344 / 1.969 / 3.171 |
| single | 3 | 6 / 19 / 65 | 2.141 / 3.047 / 3.344 |
| feedback | 1 | 46 / 46 / 46 | 3.594 / 3.594 / 3.594 |
| no_feedback | 3 | 6 / 7 / 50 | 1.891 / 2.187 / 2.343 |
| protocol_random | 24 | 2 / 7.5 / 41 | 1.015 / 1.813 / 3.969 |
| feedback_no_coverage | 0 | 未知/不适用 | 未知/不适用 |

“结果可获得时间”包含生成及仿真等过程，取日志中首个有效失败结果可读取时的相对墙钟时间，不是电路物理失败发生时刻。后者没有精确证据，JSON维持null。

feedback与feedback_no_coverage有24个同模块、同缺陷、同重复编号的对照任务：23对双方均为`policy_error`，1对为feedback检出而无覆盖组`policy_error`。两组分别执行6轮与2轮，均有`measured`功能覆盖快照，但有效可用提案数量不等，模型采样亦独立。不能将1比0视为覆盖反馈因果增益，更不能宣称统计显著。

所有128个实际执行round均记录`measured`功能覆盖。coverage是从真实采样计算的命名事件观察，不是RTL代码覆盖率、形式证明或正确性判据。覆盖汇总与每轮完整快照保留在summary，不把跨轮重复bin次数当成不同事件总数或用户数量。

## 历史隔离与后续边界

本轮不合并`e9b7b8a`旧60行pilot。v2更换完整规格、周期预算、逐周期观察和采样策略，并修复FIFO正确基线/参考模型；两个FIFO变体从修复基线重新施加单点operator。旧FIFO判据和新判据不可拼接，新旧成绩差异不是单因素实验。

`598e6dc`故障预跑保留在独立目录，不作为本轮252行结果的一部分。后续v4精确JSON样例或system角色调整属于不同源码/提示词条件；即使运行一次重复且结果改善，也只能单列联调，不能替代或改写本轮c7版本三次重复。没有独立新模块留出结果，未进行本地模型权重训练。

## SHA256核验表

以下为完整文件字节SHA256，而非截断指纹。逐轮原件和日志哈希另保存在结果中的`evidence_files`；全部74项冻结输入在预注册内逐项列出。

| 原件 | SHA256 |
|---|---|
| preregistration.json | `6fdd06c0f8e4bbdc2d23d91dca275157de85490df64c1ba5629dfb4dea2b2494` |
| run_settings.json | `8a5803ac5f13b0aa2b3414ae45d55b267bd01fb525ef1f1251f35ec6993b5126` |
| results.json | `15cc303d7a7b6f462c5394b4cb5f36606127709d0e71fc65058f0fc1f3251c01` |
| summary.json | `a5950aa095ae6846a7ab60b4fe2f941c066c22793b914cdb9bd6e59b0b4132a2` |
| 冻结runner | `f54d7a9a1006a2323da9143863699e94215b22804c1cf620109da3a4a08633d7` |
| 冻结summary工具 | `b6f806d7362216e2af7fcff470454e8d1ce50edadf899b59e2380622c21280d7` |
| spec/agent_protocols.json | `24c046c9e0e9a11cc04402efd705244d6efc6417a1e8fafe65ed5db1fc449280` |
| v2 mutation_manifest.json | `5ca8faef783e5d3a3a30ceed4a137353917c767dd7650966e8e4cdb93b7067eb` |
| prompt/profile | `9c9faf5d500121d950349b05e3afbc845b4223069b64b8ae871f58e7cda8e80c` |

本文件由参与评测工具实现的机器代理作结果整理，不属于独立真人复核。核验用于检查记录一致性，不构成第三方认证。
