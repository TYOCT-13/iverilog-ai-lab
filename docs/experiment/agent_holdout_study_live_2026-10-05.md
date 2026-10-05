# 冻结后新模块：六组真实 API 对照

日期：2026-10-05。完整批次已结束，原件已封存；本报告不替换任何历史实验。

本批反馈 Agent 检出 **10/12** 个登记缺陷任务，均匀随机 **8/12**，固定向量和协议随机均为 **12/12**。这是两个新增内部合成模块上的观察：补充了开发模块之外的测试，但反馈组仍低于两种人工基线，不能据此宣称统计显著、反馈因果优势或工业设计普遍泛化。

## 冻结与输入边界

- 本批源码提交：`c07756fb74da69aa81dccff25a706947f7cee6bd`，请求前工作树干净；[事前方案](agent_holdout_study_plan_2026-10-05.md)、[机器登记](agent-holdout-study-live-2026-10-05/preregistration.json)、[运行设置](agent-holdout-study-live-2026-10-05/run_settings.json) 与 [事前代理审查](../review/agent_holdout_prereg_review_2026-10-05.md) 均有原字节记录。
- 两模块 `credit_guard`、`rotating_arbiter` 在 v6 Agent 算法冻结之后建立，与此前 FIFO/UART/SPI/握手模块互斥。每模块有一个正确目标和两个人工单点缺陷，全部进入登记，没有根据 API 成绩筛选。
- Agent 文件 SHA 为 `b3eca75bab345ef2b9d5d2ebd0280f9811bd37532fb979d2f8c5a4ac220ce5fe`，system 提示 SHA 为 `8b5f844143e9c85052eee2398cf2f13c4840e3fc86e589ca9c48fc4304c7cb03`，与冻结时相同；没有为取得新成绩修改算法或提示。新增的是合同、规格、参考判据、基线适配和评测入口。
- 模型收到完整正确规格、合同、预算和允许的执行反馈。目标与正确参考 RTL 源码、路径、SHA、缺陷标签及人工 witness 不进入模型请求；本地执行器读取 RTL 供仿真与证据绑定。模型预训练是否见过类似算法未知。
- 留出级别是**冻结后内部作者创建的合成新模块**。`independent_holdout=true` 表示模块集合互斥，不表示外部作者独立盲测；`external_independent_holdout=false`。不计真人试用或 H02。
- 功能覆盖分析器未增加新模块定制提示；本批返回 `unsupported`，不是完整覆盖率，也不将空覆盖信息算作检出。

执行使用的是登记并保存的 86 项工作目录原字节。与上述提交的 Git blob 对照，74 项逐字节一致，12 个历史文件仅 CRLF/LF 换行不同；86 项均与登记 SHA、运行快照及结束时工作目录一致，无内容差异。路径和双 SHA 另见结果复核回执。**提交标识不能替代原字节快照**；不能宣称仅检出该提交即可满足全部字节门禁，不为消除换行差异修改已绑定输入或成绩。

## 相同预算与判据

六策略 × 两模块 × 正确/B/C 三目标 × 三重复（seed 0/1/2），共 **108 登记任务**。每组有 **12 缺陷任务＋6 正确控制**；12 个任务来自 **4 个不同缺陷重复三次**，不是 12 个独立缺陷。

每任务最多累计 16 激励周期，每实际 episode 独立复位，逐拍 after 检查全部输出。每提案至多 12 向量；沿用 Agent 累计接受向量上限 64。single 最多一请求/一轮，feedback 与 no_feedback 最多三请求/三轮。初始复位和正确参考审核周期另计，未混入 16 拍刺激预算。

fixed 和 protocol_random 只按正确规格生成输入，不读取目标、变体、witness 或仿真结果；各计划恰好 16 拍。random 使用合同数据输入均匀采样的 12 段，前四段各两拍、后八段各一拍，段内保持输入。这与旧四模块每拍重新随机的基线不同，**不合并两批随机检出率**。API 未用满周期的短提案不人为补齐；有相同预算上限，不代表相同实际刺激或覆盖密度。

Python 判据和正确 RTL 分别表达规格语义。每个实际执行的计划都在正确 RTL 上重放，以逐拍输出和原始 stdout 复核；AI 提供的期望值不裁决结果。成功检出必须具备真实编译、执行、正确参考无告警及可追溯输出不一致。

## 完整结果

| 策略 | 检出/12 | seed 0/1/2（各/4） | 不同缺陷并集/4 | 请求 | 输入＋输出 tokens | 实际激励周期 |
|---|---:|---|---:|---:|---:|---:|
| fixed | 12/12 | 4、4、4 | 4/4 | 0 | 0 | 288 |
| random | 8/12 | 3、3、2 | 3/4 | 0 | 0 | 288 |
| protocol_random | 12/12 | 4、4、4 | 4/4 | 0 | 0 | 288 |
| single | 5/12 | 1、1、3 | 3/4 | 18 | 38,044 | 110 |
| feedback | 10/12 | 4、3、3 | 4/4 | 32 | 73,133 | 213 |
| no_feedback | 9/12 | 3、3、3 | 4/4 | 36 | 79,210 | 232 |

周期列包括每组全部登记目标的实际刺激；正确参考另各重放同样周期。六组共 1,419 实际刺激周期及 1,419 正确参考审核周期，不含复位。不能用周期总数或 API 网络耗时差直接宣称速度优势。

| 缺陷（每项三重复） | fixed | random | protocol_random | single | feedback | no_feedback |
|---|---:|---:|---:|---:|---:|---:|
| credit_guard B：空额度申请回绕 | 3 | 0 | 3 | 0 | 2 | 2 |
| rotating_arbiter B：advance=0 仍推进指针 | 3 | 2 | 3 | 1 | 2 | 1 |
| credit_guard C：同时申请释放错误扣减 | 3 | 3 | 3 | 3 | 3 | 3 |
| rotating_arbiter C：指针未移到被选请求下一位 | 3 | 3 | 3 | 1 | 3 | 3 |

36 个正确控制任务全部实际执行，观测误报为 0；每个实际计划的正确参考审核也无否决。有限测试的无告警不等于电路被证明正确。

反馈组七次在首实际仿真轮检出，三次在第二轮检出：row 31（仲裁 C、seed 0）为 4＋4 拍，row 85（额度 B、seed 2）为 4＋4 拍，row 107（仲裁 C、seed 2）为 6＋4 拍，三项首轮均无不一致，第二轮均出现一个不一致。无反馈组则有五次首轮、四次第二轮检出。row 下标从 0 起。

后续轮次确有新检出，但 no_feedback 也发生同类现象。API 随机数未配对；no_feedback 隐藏 DUT 观察、计划错误和格式诊断，执行器早停及剩余预算仍含流程信号。本批反馈组比无反馈多一项、比随机多两项，不能单凭这些计数或第二轮检出归因于仿真反馈。

## 失败、格式恢复与严格资格

108 行全部保留，**107 任务实际执行，136 episode／272 执行侧**；107 行执行证据通过核验，86 个冻结输入原字节匹配，结束时源码变化为空。共享严格汇总的 `eligible_for_frozen_comparison=false`，未因较好的检出计数改成 true。

- **row 14**：额度 B、single、seed 0。合法 schema 提案含七向量、总计 18 拍，超过登记的 16 拍，执行前停止；零 DUT 执行、零刺激周期，付费请求仍计账，失败仍计入缺陷任务分母。这是全批唯一未执行任务。
- **row 50**：额度 B、feedback、seed 1。首轮真实执行七拍未检出；第二请求的合法 schema 提案为 11 拍，超过剩余九拍，`stop_reason=cycle_budget`，没有执行第二提案。该请求的 2,439 tokens 已计账。行已有首轮执行证据，最终 `status=not_detected`，不是另一项全未执行；不能把反馈组这次未检出说成全部提案执行后的功能漏检。
- **row 51**：额度 B、no_feedback、seed 1。前两轮真实执行 12 拍而未检出，第三请求含重复 JSON 键，被安全策略 fatal 拒绝；仍计未检出，不能当作全部动作成功。受限归档保留 hash/长度/诊断，原文未保存；不能补造原文或降低重复键保护。
- **row 75**：正确额度目标、no_feedback、seed 2。第二请求含额外字段 `unknown_field`，普通 `schema_invalid` 可在原请求上限内补提，原始 JSON 已安全留存；第三请求恢复合法动作并真实执行。拒绝请求增加 tokens 和请求数，不消耗 DUT 刺激周期。该恢复属于正确控制，**不是额外缺陷检出**，no_feedback 请求不含格式诊断。

86 次模型响应中 84 次通过动作 schema、两次被拒绝；其中一个普通格式拒绝实际恢复，一个重复键安全拒绝不可重试。留存 **85 份受控响应原件**，包括普通拒绝原文；另一次只留安全元数据。本批未观察到 `json_invalid`，不能用它证明 malformed `.txt` 在线恢复已发生；相关能力只有既有测试证据。

## API 预算

[独立预算账](agent_holdout_study_budget_2026-10-05.json) 与 [原始守门账](agent-holdout-study-live-2026-10-05/token_budget.json) 记录 **86 真实请求，172,545 输入＋17,842 输出＝190,387 tokens**。完整批次共享 1,000,000 上限，剩 809,613；86 请求 usage 全部已知，最终未知预留为 0，没有超限。

使用已配置的服务商 Flash API，thinking disabled、nonstream、每响应输出上限 4,096、超时 60 秒、无自动网络重试。普通格式补提是新的付费请求。历史用量不扣本批，旧 360 累计请求限制不是当前规则，余额本身不代表另开批次的登记。未训练权重、未运行本地模型；没有服务商实际账单，不填实付金额。

原始执行时间 UTC 2026-10-04 23:51:37 至 23:54:23（北京时间 2026-10-05 07:51:37 至 07:54:23），整批约 165.70 秒。它包括模型/网络、本地仿真及参考审核，不是逐检查首反例墙钟耗时。

## 工程检查与可复核原件

[本批源码验收](agent-holdout-validation-2026-10-05/receipt.json)：**1,570 passed、2 skipped、0 failed**，mypy **83 源文件 0 错误**；346 个源码/测试/资产指纹在检查前后不变。两项跳过是 Windows 目录符号链接权限不足；不能计作通过。定向检查与旧 1,307/2、1,170/2 全仓结果不相加。此记录不是干净克隆或外部 Actions 验证。

[新资产与原始验证](../../benchmarks/agent_holdout_20261005/README.md) 另有实际 Icarus 编译/运行及 2,296 条输出观测。首次端口名 `release` 导致的编译失败原件仍保留，修正为 `release_req` 后成功原件单独保存；均发生在真实 API 之前。

附加 `readable-verilog-generator` 严格风格链路**未通过**：两模块的 ast/readability/naming 失败，缺少指定 WaveDrom renderer 等依赖，未生成声称已渲染的 SVG。技能静态解析的 compile 标签不当作真实编译证明。本项目的真实 Icarus 语义验证另列，不称综合、时序或板级验证通过。

- [公开机器回执](agent-holdout-study-live-2026-10-05/receipt.json) 绑定 13 项产物；[严格汇总](agent-holdout-study-live-2026-10-05/strict_summary.json) 含全部 108 行及逐拍审核信息。
- [完整原始 results](agent-holdout-study-live-2026-10-05/results.zip)、[86 项冻结输入](agent-holdout-study-live-2026-10-05/registered_inputs.zip)、[轨迹与安全响应](agent-holdout-study-live-2026-10-05/traces_and_decisions.zip)、[拒绝与恢复清单](agent-holdout-study-live-2026-10-05/trace_manifest.json) 均为原字节副本。
- [全部原件 ZIP](agent-holdout-study-live-2026-10-05/full_raw_evidence.zip)（5,674,412 字节）与 [逐文件 SHA/大小清单](agent-holdout-study-live-2026-10-05/full_raw_manifest.json) 包含结束时私有实验目录的 **4,039 文件、46,400,791 原始字节**，包括 272 侧的编译/运行 stdout、stderr、测试台、执行结果、波形及冻结输入。保留安全拒绝时原本缺失的正文状态，不声称 86 份完整响应。
- 私有原件继续位于 `.iverilog-ai/agent-holdout-study-live-20261005/`。保存全部文件不等于已验证异机完整复现；原件包含本机路径和工具信息。

本地只读重算可将输出写到全新文件；不请求 API、不覆盖原 summary：

```powershell
python scripts/summarize_agent_comparison.py .iverilog-ai/agent-holdout-study-live-20261005/results.json --output .tmp-codex/holdout-summary-new.json
```

评测入口 [run_agent_holdout_study.py](../../scripts/run_agent_holdout_study.py) 默认仅干运行；`--execute` 要求已提交干净源码及全新固定目录。现有批次已存在，应读取原件，不能删除目录刷分或改写登记结果。

结果只读代理复核另见 [复核报告](../review/agent_holdout_study_review_2026-10-05.md) 与 [机器回执](../review/agent-holdout-study-review-2026-10-05/receipt.json)，不计真人或 H02。真人试用、独立人审、外部盲测、完整异机复现、实际视频和正式 PDF/PPT 的版本同步仍需相应真实证据；旧 v5 ZIP 与旧提交稿不自动获得本批结果。
