# ICARUS 答辩讲稿 v3

建议用 7–9 分钟讲述主线，追问时展开证据定位。下列每页正文进入 PPTX 演讲者备注。材料匿名，不填写机构、成员、署名、签字或队号。数据冻结于材料事实源，答辩材料制作没有追加 API、读取凭据或重新运行 DUT。

## 01 ICARUS

ICARUS 是面向数字 IP 的验证智能体。它让第三方模型 API 根据正确规格和完整接口合约建议测试输入，由本地受控执行器生成测试台，使用真实 Icarus 仿真，再由独立于模型建议的判据解释结果。作品的可评估贡献是把测试规划、执行权限、预算和原件留存接成一个受控闭环。我们没有训练或微调基础模型，也没有提供本地模型权重。用户请求的模型名称是 4.1f，服务返回的模型标识为 deepseek-flash。接下来分别说明架构、新模块实验、真实失败和证据边界。

证据定位：docs/competition/ic/v3/material_data.json 的 api、uses_third_party_api_only、trained_or_finetuned_weights。新实验源码为 20400fa7dca0c9804a96b1eb9842956782a9e81f，核心 Agent/helper/System 先冻结于 a96933786c17986a739fc2da515db3294d6e8044。

## 02 数字 IP 的验证需求

需求来自本项目的实际合约、执行日志和失败记录分析，没有虚构用户访谈、效率百分比或真人计时。以两项新合约为例，valid/data 流水线需要检验两级延迟、flush 优先级及 invalid 时输出归零；事件累计器需要检验使能条件、四位模 16 回绕和 clear 不受 enable 限制。一个能编译运行的输入序列仍可能遗漏这些边界。工具面向数字电路学习者、小型 IP 开发者和技术复核人员，提供可以回指输入、采样点和输出差异的记录。

证据定位：spec/agent_new_holdout_20261005/valid_data_pipeline_spec.md、event_accumulator_spec.md。旧 FIFO 及 UART 规格改进见 docs/experiment/protocol_oracle_improvements_2026-10-04.md。适用范围只覆盖已审计的合约与参数，不能扩展到任意 SoC 或物理签核。

## 03 API 规划与仿真裁决

图中各阶段均为可编辑原生对象。模型只收到正确规格、完整接口合约、允许驱动的输入、自己的计划、剩余预算及允许的执行反馈。它不能修改目标 RTL、判据、执行命令或受支持设计的期望值，私有变体 RTL、目标标签、路径和 witness 不进入请求。执行器先做动作格式、输入权限和预算检查，再实际仿真。每个实际 episode 具有独立 DUT 实例和自动复位，随后在正确 RTL 上独立重放同一计划并比较每个 after-edge 采样的全部输出。新接口包含 i_clk 和异步低有效 i_rstn，周期 10ns，自动复位 2 拍。

证据定位：src/iverilog_ai/ai/agent.py、src/iverilog_ai/core/pipeline.py、scripts/run_agent_new_holdout_study.py。逐请求 canonical body SHA、消息 SHA 与原件绑定见 docs/review/agent-new-holdout-study-review-2026-10-05/trace-audit.json。账本保留的是 canonical JSON SHA，原始 HTTP wire-order body 字节未单独存档。

## 04 新内部模块集合留出

这一批登记 2 个新模块，每个模块包含正确、B、C 三个目标，采用 3 次重复和 6 种策略，合计 108 任务。每种策略有 4 个不同缺陷乘 3 次重复，即 12 个缺陷任务，另有 6 个正确任务。新模块成员与此前五个受控 API 批次不重叠，Agent、helper 和 System 在新模块生成前已经冻结。设计、变体和实验仍来自同一团队，因此这里称内部模块集合留出。没有独立时间戳证明选型早于旧 v8 成绩，也没有外部盲测或预训练未见证明。不能把内部成员不重叠扩大解释为外部独立评估。

证据定位：docs/experiment/agent_new_holdout_study_plan_2026-10-05.md、spec/agent_new_holdout_study_1m_v8.json、benchmarks/agent_new_holdout_20261005/manifest.json。三项核心冻结 SHA 和原字节快照由新实验审计核对。所有 108 项均已真实执行。

## 05 共享请求与执行预算

新批使用独立的 1,000,000 input+output token 上限，不扣历史用量，也不用于补齐旧失败行。实际 87 次收费请求，输入 301,910、输出 37,714，合计 339,624 reported tokens，unknown 和 pending 均为零。这个数字是服务方报告的 token 用量，不是货币账单。单次 API 至多 1 请求和 1 实际 episode；反馈与无反馈各至多 3 个共享请求和 3 个实际 episode。格式错误和周期预算拒绝后的补提均是收费新请求，仍共用原任务上限。每个任务累计刺激拍至多 24，每次提案至多 12 向量，累计接受至多 64。独立自动复位和正确 RTL 重放成本单列。传输配置为 thinking disabled、非流式、4096 输出上限、60 秒超时和零自动重试。

证据定位：docs/experiment/agent_new_holdout_study_budget_2026-10-05.json、新公开 token_budget.json、preregistration.json、run_settings.json。理论请求上限 126 不是实际请求数。剩余预算不授权追加独立补批，store=False 是客户端配置而非第三方数据保留行为的证明。

## 06 新108任务的六策略检出

条形图直接使用原生图表和嵌入式 literal workbook，分母统一为每策略 12 个登记缺陷任务。固定测试 12、均匀随机 10、协议随机 8、单次 API 8、反馈 Agent 11、无反馈 10。固定测试最好。反馈比均匀随机和无反馈各多 1 项，但只有 4 个不同缺陷和 3 次重复，预算、提案及早停行为也不同，因此不能声称因果、显著性或普适工业收益。全部 36 个正确任务实际执行且没有误报。strict=true 只表示内部完整证据资格满足，并不表示全部动作成功，第 108 行仍以终态格式失败留在完整分母。

证据定位：docs/experiment/agent-new-holdout-study-live-2026-10-05/strict_summary.json、receipt.json。每策略 repeated detections 分别为固定 4/4/4、均匀随机 4/3/3、协议随机 4/2/2、单次 API 2/2/4、反馈 4/4/3、无反馈 3/3/4。不同重复不视为不同独立缺陷。首次实际检出 episode：单次 API 首轮 8；反馈首轮 6、第二轮 5；无反馈首轮 8、第二轮 1、第三轮 1。后续 episode 实际找到反例说明闭环有可观察行为，不能据此证明反馈因果。

## 07 实际端口事实与无反馈对照

80 个 Agent 实际 episode 都保存了完整端口反馈文档。原始有限采样共有 826 点，helper 返回 701 点、省略 125 点。每份最多 12 个端点及等间隔样本，省略和 X/Z 语义保留，实际这批没有 X/Z。这是有限绑定端口流的 complete，不能表示所有设计行为完整覆盖。保存反馈文档和真正发送给模型的反馈 STATE 要分开：只有反馈策略的 20 个后续已发送 STATE 带端口事实，合计返回 180 点、省略 12 点。无反馈的 31 个已发送 STATE 中 observation、plan_error、latest_decision_error 全为 None，但其中 12 个仍保留自己的 current_plan 和减少后的预算，执行器也仍早停。两个新模块的功能覆盖状态是 unsupported/unknown，不补造命名 bins。24 个命名 bins 只属于旧四个配置。

证据定位：trace-audit.json 的 paid_model_state_port_facts 和 helper 重建计数，新 receipt.json 的 port_observation_episodes。helper 绑定 RTL、plan、contract、TB、采样包、stdout 与执行结果，端口投影不含期望值和私有路径。X/Z 的保留机制由既有审计验证，本轮材料没有重新执行测试。

## 08 付费拒绝与真实执行

所有 87 个原 API 响应都保存，其中 86 个可解析 JSON、1 个不可解析；不隐藏 paid failure。85 个响应通过 schema、2 个格式拒绝。5 个预算拒绝属于 schema 通过的子集，不能加到 85 和 2 之上形成 92 请求。预算拒绝花费 23,991 tokens，其中 2 个任务后续真正执行，1 个后续检出。格式拒绝花费 9,274 tokens，其中 1 个任务后续执行 2 个 episode，没有后续检出。legacy preflight 有标与无标均为零，不能只数 retry_eligible 就宣称其它拒绝为零。

第 108 行，即 zero-based index 107，对应 event_accumulator、mutation_c、反馈策略、seed 2。请求 1 实际执行 14 拍且没有检出，请求 2 因剩余刺激预算拒绝，请求 3 格式拒绝后达到原 3 请求上限，终态为 decision_format_error。它有 1 个实际 episode、证据核验有效，仍作为未检出失败保留在分母。拒绝后的执行和检出只作描述，不构成反馈的因果收益。

证据定位：trace-audit.json 的 all_paid_rejection_events、explicit_error_classification、traces[sample=107]；原轨迹 sample-107/agent/agent_trajectory.json 与原响应在公开 traces_and_decisions.zip 和 full_raw_evidence.zip 中。

## 09 原件绑定与机器审计

证据链从冻结输入快照开始，绑定 458 项登记输入，实际保存 4,359 个 raw 文件。公开 full_raw_manifest 与 ZIP 使用原字节，未把格式失败改写成成功。压缩 raw archive 为 7,027,646 字节，未压缩原文件总量 64,589,914 字节，两者口径不同。Git 绑定 446 项 exact、12 项只存在换行差异，因此原始登记快照仍为权威，不能声称干净 checkout 每字节相同。

两类审计身份要分开。核心审计由非实现者代理完成 2,192 个机器检查，包括 1,923 加 269；这仍不是真人独立人审。轨迹审计由实验 entry 代码作者检查 54 条轨迹和 87 次请求，明确非独立于入口作者、非 H02。核心输出重算 6,214 项、VCD 端口值核对 27,434 项；这些数字分别表示有限机器证据，不等于真人评测人数。所有机器审计都没有追加 API 或 DUT。

证据定位：docs/review/agent-new-holdout-study-review-2026-10-05/core-audit.json、trace-audit.json、receipt.json；新 full_raw_manifest.json、registered_inputs_manifest.json、source_byte_binding.json。source_checksums.json 保存本材料实际引用原件及 authoring source 的 SHA。

## 10 旧v8的开发与复用集合

旧 v8 批次登记 432 任务、414 实际执行，18 个没有 DUT episode。每策略缺陷分母为 48，检出依次为 48、32、48、29、37、37；306 请求、973,149 tokens。144 个正确任务中 143 实际执行，没有实际误报，1 个未执行，所以不能写成 144/144 都通过。strict=false 表示该批完整证据资格不满足，未执行和其它失败仍保留。旧表与新 108 的模块集合、缺陷分母和预算不同，不合并为一个总检出率，也不画同一增益趋势。新 1M 批预算独立，不补跑旧 token_budget 失败行。

证据定位：docs/experiment/agent-feedback-study-live-2026-10-05/receipt.json、strict_summary.json、docs/experiment/agent_feedback_study_live_2026-10-05.md。旧源码冻结为 a96933786c17986a739fc2da515db3294d6e8044。本页保持旧批身份与真实失败，不代表新模块的旧版本成绩。

## 11 判据独立性的规格案例

这一页说明为什么判据不能只依赖模型的自述。FIFO 旧 RTL 与旧 reference model 曾共享计数错误。独立 deque 规格检查发现中间占用时同时接受读写，占用量应净零改变。第 5 拍读 25、写 99 后，队列从 [25,66] 变为 [66,99]，占用量仍为 2。第 7 拍首次出现 full 端口差异，旧实现为 0、队列应为 1、修复后为 1。同一 76 拍、228 次输出比较，差异从 66 变为 0。

右侧是同字节冻结的外部历史候选集合，24 个候选包含 15 个人工变体、3 个正确基线、3 个等价改写和 3 个编译失败控制。补全人工 UART TX 计时 SPEC 后，15 个人工变体的检出从 13/15 变为 15/15。正确和等价控制没有误报，编译控制单列。它来自同作者的两个仓库，有限流程，不是独立外部盲测，更不是 AI 成绩或 AI 自动发现缺陷的证明。此页所有历史数字只说明规格独立性和受支持判据修复。

证据定位：docs/experiment/protocol_oracle_improvements_2026-10-04.md，旧 FIFO before/after evidence.json 与 external/replay-20261004-protocol-v2/evidence.json 的原 SHA 随本材料绑定。没有新增 DUT 重放。

## 12 证据边界与交付

现有机器工程记录为 2,033 通过、2 跳过、0 失败，mypy 88 源文件零错，535 个冻结指纹无变化。这是工程回归记录，不是 AI 效果或真人验收。范围限于已审计合约与参数、有限刺激拍和有限输出采样。新模块属于同团队合成集合，没有外部盲测、预训练未见、因果或普适收益证明。硬件验证、异机 Actions、真人试用和独立人工 H02 原件尚未提供；12 项严格 RTL 样式残项和 WaveDrom 3.6.1 缺失仍披露，不能填假想通过。真人和 H02 是内部证据完善项，官方规则未将它们列为硬门槛。

投递材料按官方要求组织：技术方案 PDF 不超过 10MB，答辩交 PDF，佐证合并为一份 PDF，视频可选为 3–5 分钟 MP4、不超过 300MB，截止 2026 年 10 月 15 日 20:00。本答辩 PDF 为图像式导出，编辑请使用 PPTX。最终目标是让每个数字、失败与限制都有可定位原件，后续扩展必须用新的预登记实验说明。

官方来源：material_data.json 的 rules，核验日期 2026-10-05。通知 https://www.aicomp.cn/notice/4756.html ，规则和技术报告大纲的完整官方 URL 保存在该事实源并写入此页备注。最终投递文件名按真实队号-赛题名称-作品名称-材料名称组织，目前未提供真实队号，所以保留内部 v3 文件名而不填虚构编号。工程来源：docs/experiment/agent_new_holdout_source_validation_2026-10-05.md。当前未在 Microsoft PowerPoint/LibreOffice/Google Slides 打开验证，不能将 artifact-tool 预览等同于 Native Office 验收。

