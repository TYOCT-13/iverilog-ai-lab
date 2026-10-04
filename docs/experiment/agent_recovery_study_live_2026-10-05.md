# Agent 普通格式恢复：完整六组 API 实测

日期：2026-10-05。新批次已完成216登记任务，使用138次真实API、378,204输入加输出tokens。固定/均匀随机/协议随机/single/feedback/no_feedback分别检出21/16/21/20/23/22个缺陷任务，每组分母24。反馈组本次计数高于随机、单次调用和无反馈，但全部23次检出均发生在首次实际仿真；不能由此证明仿真反馈产生增益、统计显著或新模块泛化。

普通格式拒绝后，有4项任务恢复到真实执行，其中3项检出缺陷、1项正确参考无误报。另1项只恢复为合法stop。仍有4项完全未执行，严格完整证据资格为false。所有登记成员、失败和未知状态都保留，没有挑选成功条目替换旧成绩。

## 版本与事前条件

源冻结提交：`9c3bd3c0cf9caa0fb95e6bbdee6147ae447e58cc`。生产Agent提示版本：`verification-agent-v6-bounded-format-recovery`；Agent原字节SHA：`b3eca75bab345ef2b9d5d2ebd0280f9811bd37532fb979d2f8c5a4ac220ce5fe`。

[事前方案](agent_recovery_study_plan_2026-10-05.md)、[配置](../../spec/agent_recovery_study_1m.json)、[执行入口](../../scripts/run_agent_recovery_study.py)在真实请求前提交。沿用[上一完整批次](agent_study_1m_live_2026-10-05.md)的216任务、四份规格原字节、成员顺序、三个重复、每组24缺陷加12正确任务，周期上限仍为FIFO16/UART48/SPI20/握手8。每次episode独立自动复位，after逐拍检查，合约、RTL、参考模型与基线生成方法一致。仍为8个公开开发缺陷的三次重复，没有独立留出。

新干预包括普通schema/可安全检查的JSON错误在剩余请求内补提、可信格式诊断、拒绝原文留存，以及system prompt的两句格式纠正说明。父入口和预算脚本补全类型声明；共享汇总器单列未解决的格式终态。这是整体配置比较，提示词与恢复机制同时变化；模型随机性没有配对seed，不作单因素因果推断。

单次策略最多1请求；feedback和no_feedback最多3请求。拒绝动作不执行、不计仿真轮次或周期，新请求仍付费用量。12向量、额外字段禁止、模型expected禁止及既有schema保持不变。重复键、凭据回显、无法可靠检查的字符串、异常usage、明确非stop服务终态、路径及传输错误不降级为普通格式重试。

## 完整结果与上一批对照

| 策略 | 本轮检出/24 | 三重复检出，各/8 | 跨重复并集/8 | 请求 | 输入加输出tokens | 实际激励周期 | 上一批检出/24 |
|---|---:|---|---:|---:|---:|---:|---:|
| fixed | 21 | 7 / 7 / 7 | 7 | 0 | 0 | 828 | 21 |
| random | 16 | 5 / 5 / 6 | 7 | 0 | 0 | 828 | 16 |
| protocol_random | 21 | 7 / 7 / 7 | 7 | 0 | 0 | 828 | 21 |
| single | 20 | 6 / 8 / 6 | 8 | 36 | 95,612 | 621 | 21 |
| feedback | 23 | 8 / 7 / 8 | 8 | 51 | 145,050 | 688 | 18 |
| no_feedback | 22 | 7 / 7 / 8 | 8 | 51 | 137,542 | 687 | 22 |

并集8/8不替换每组24的主分母。API组可以提交短计划或提前停止，基线补齐同一周期上限，因此实际资源并不相同。反馈组较上一批多5个检出任务，single少1个，无反馈相同；只能报告这两轮的观察差异。

single20次、feedback23次都在首次实际仿真检出。feedback中21项用1请求，2项用2请求；row71先是既有计划预检拒绝，row174先是schema拒绝，两者都没有先执行DUT。row71不能计入本轮新增格式恢复。因此“首仿真轮”不能写成“首请求”。no_feedback有21次首仿真轮检出，另row66握手valid未清除、repeat0在第2次实际仿真检出，累计8个刺激周期；该组仍存在执行器早停的残余信息。

反馈组唯一未检出缺陷任务为FIFO写满仍写入、repeat1：三个实际episode都没有形成有效反例，累计14周期，上限16。它是有效执行后的漏检，不能和格式拒绝合并，也不补成理想结果。

## 格式恢复的实际证据

138请求中125个输出通过严格schema；13个被拒绝，包含10个普通schema拒绝和3个重复键安全拒绝。本轮普通拒绝均为`schema_invalid`，没有实际`json_invalid`。动作接纳率未被用作成绩替代：上一批136/145，本批125/138，不能声称输出格式失败率下降。

10次普通格式拒绝都保留原UTF-8 `.json`字节、SHA、长度及`trusted:false`；其中5次后续输出通过schema，4次真的执行，另一次为合法stop。它们不是5次新仿真，也不是5个新增缺陷。

| 登记行 | 策略、样本 | 拒绝后动作 | 实际执行 | 结论 |
|---|---|---|---|---|
| 86 | no_feedback，正确SPI，repeat1 | stop | 没有新增执行 | 此前已有正常仿真；只恢复为合法回复 |
| 156 | feedback，正确SPI，repeat2 | append_vectors | 20周期 | 参考正确，无误报 |
| 174 | feedback，UART位序缺陷，repeat2 | append_vectors | 43周期 | 首次实际仿真检出 |
| 180 | no_feedback，SPI时钟极性缺陷，repeat2 | append_vectors | 18周期 | 首次实际仿真检出 |
| 198 | no_feedback，UART busy不清除，repeat2 | append_vectors | 44周期 | 首次实际仿真检出 |

其余5次格式拒绝分别为row31/75/81/146/207；row31/207是single=1，row75/146已经用完3次请求，row81的下一回复触发重复键拒绝。10次普通拒绝消耗28,277 tokens，所有13次拒绝合计36,320，均已包含在378,204内。

3次重复键拒绝不保存原文，只留下固定错误码、回复SHA及长度。外部复核可核验这些留证状态，不能从不存在的原文独立确认具体重复键。无法安全检查的回复同样故意不落原文，不承诺“所有失败都有完整响应”。

新增畸形JSON `.txt`原文归档在本批未触发；其证据来自合成HTTP及实际Icarus测试，不能写成本批在线观察。上一批row126缺失的响应仍缺失，不追补或猜测原文。

## 失败、正确参考与证据资格

| 登记行 | 样本、策略、重复 | 终态 | 已执行轮次 |
|---|---|---|---:|
| 9 | 正确UART，feedback，0 | policy_error：重复键 | 0 |
| 31 | UART位序缺陷，single，0 | decision_format_error | 0 |
| 56 | UART busy不清除，no_feedback，0 | cycle_budget：提案超上限 | 0 |
| 75 | 正确FIFO，feedback，1 | decision_format_error | 2 |
| 81 | 正确UART，no_feedback，1 | policy_error：重复键 | 1 |
| 143 | 握手valid未清除，no_feedback，1 | policy_error：重复键 | 1 |
| 146 | 正确FIFO，feedback，2 | decision_format_error | 2 |
| 207 | SPI done缺失，single，2 | decision_format_error | 0 |

完全未执行是row9/31/56/207，共4项，其中3个缺陷、1个正确参考；并非“4个格式错误”。8个异常终态中有4项保留此前有效仿真，格式耗尽不被汇总为普通未检出。三组API的全部失败仍留在各24缺陷任务分母。

实际执行212/216任务，229个审计episode、458个真实执行侧。全部实际执行的正确目标和各轮参考审计未出现误报；各组正确任务实际执行数分别为12/12/12/12/11/12，反馈组正确UART的一项未执行。反馈组另有2个正确任务在有效仿真后格式耗尽，无反馈组另有1个正确任务在有效仿真后重复键终止，因此不能写“正确任务全部成功”。

89份登记输入原字节快照与SHA全部一致，`changed_inputs_at_finish=[]`。严格汇总`eligible_for_frozen_comparison=false`，原因为4项没有可审计的真实仿真轮次。快照一致只证明本次输入稳定，不补足这些执行缺项，也不等于H02人审通过。

## 用量与执行条件

[本轮预算账](agent_recovery_study_budget_2026-10-05.json)与[原始共享账本](agent-recovery-study-live-2026-10-05/token_budget.json)：输入348,617、输出29,587，合计378,204；138次用量已知，未知预留0，剩余621,796。缓存命中257,664加未命中90,953等于输入，未重复计入总用量。没有服务商货币账单，不估算实际费用。

所有API组使用同一1,000,000-token预算，仅计本完整批次，历史用量不扣新轮。理论请求上限252、每请求输出4096、thinking disabled、非流式、60秒，无自动传输重试；格式补提是重新计费的新请求。最大实际输出462 tokens，累计已用加下一请求预留的峰值404,165，未触及守门或输出上限。总墙钟393.015秒。

预算预留是工程保守界，不宣称准确tokenizer或计费保证。没有因剩余额度另开重复批次、选择最好结果或绕过本轮上限。

## 工程检查与只读复核

[全仓检查原件](agent-recovery-validation-2026-10-05/receipt.json)记录最终1,307通过、2跳过、0失败；mypy对src/ui/scripts的82个源文件0错误，检查前后源SHA一致。跳过项是本机目录符号链接权限1314、当前为空的推荐断言表。测试调用真实API为0，不与历史1,170或本轮定向测试相加。

初次全仓r1为1,304通过、3失败、2跳过，原因是根代理误把pytest临时目录放在仓库内，影响仓库外路径断言，并把测试故意生成的坏编码/语法文件送入仓库扫描。原日志、XML和样本保留；r2改用仓库外新目录，通过检查，未放宽生产代码或原断言。专项测试末尾仅清理一个额外换行，测试时原字节另存，未为该纯空白变化重新执行整套测试。

[代码复核](../review/agent_recovery_code_review_2026-10-05.md)发现并推动修复了content_filter/tool_calls错误重试问题，原反例和合法动作控制已复测。它是代理代码复核，不是人审、真实API或新成绩审核。

本批[结果只读复核](../review/agent_recovery_study_review_2026-10-05.md)单独核对实际stdout、判据、89快照、138请求、格式恢复、账本和公开原件；审核范围与机器回执以其报告为准。复核不会再请求API、执行DUT或替真人签名。

## 原件与复现范围

[机器回执](agent-recovery-study-live-2026-10-05/receipt.json)、[严格汇总](agent-recovery-study-live-2026-10-05/strict_summary.json)、[完整结果ZIP](agent-recovery-study-live-2026-10-05/results.zip)、[登记](agent-recovery-study-live-2026-10-05/preregistration.json)、[执行设置](agent-recovery-study-live-2026-10-05/run_settings.json)、[89输入原字节ZIP](agent-recovery-study-live-2026-10-05/registered_inputs.zip)、[轨迹及安全留存回复ZIP](agent-recovery-study-live-2026-10-05/traces_and_decisions.zip)、[轨迹/响应/恢复清单](agent-recovery-study-live-2026-10-05/trace_manifest.json)分别保存本批证据与SHA。

完整本地执行原件在`.iverilog-ai/agent-recovery-study-live-20261005/`。公开副本有全部结果、API轨迹、135份安全留存回复和冻结输入，未复制全部458侧仿真日志；不能把这个紧凑目录称为完整异机运行包。ZIP解包或重放不计新增API请求和新增独立实验。

入口默认dry-run，不读取密钥、创建实验目录或调用API。执行命令为`python scripts/run_agent_recovery_study.py --execute --api-key-file <本机凭据路径>`；本轮固定输出目录已存在，入口会拒绝覆盖重跑。后续新实验须先另定范围、输出路径及预算，不删除旧目录腾出“重跑”。

## 下一步

优先做独立新模块留出，再检查格式可靠性和合法但超周期的提案处理。当前反馈组23/24值得继续验证，但23次都在首次实际仿真，尚没有仿真反馈追加检出的证据。no_feedback隐藏观察、覆盖、plan_error及格式诊断，仍存在结果驱动早停与剩余额度的残余信号。

真人试用、独立H02、完整异机复现、远程开源发布、外部Actions、视频和正式提交依然需要真实执行。旧技术方案PDF、答辩和旧ZIP不因本次实测自动更新。本项目仍使用API优化验证流程与收集轨迹，没有自行运行开源模型或完成权重微调。
