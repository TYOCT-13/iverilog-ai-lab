# Agent v7：八模块完整预算恢复对照

2026-10-05。本批432项登记任务全部走完，反馈 Agent 检出 **37/48**，均匀随机 **32/48**，固定/协议随机分别 **48/48、48/48**。这是本批固定模块和资源下的描述性结果，不据此宣称统计显著、工业泛化或省奖等级。

本版增加合法但超剩余周期/向量预算提案的有界补提；拒绝不执行、不裁剪、不占接受向量，原响应和费用保留。提示词与旧四模块基准分段同时变化，因此旧版差值不能解释为单因素效果。

总计反馈与无反馈均为37/48，低于两种人工基线。信用/仲裁子组的反馈4/12、无反馈6/12仍低于随机8/12；后两模块集合留出中反馈11/12、随机9/12。表现随模块变化，不能概括成全部子组优于随机。本批三次预算拒绝均出现在原请求额度末尾，**没有观察到预算拒绝后再执行或检出的真实恢复案例**；已有stub与Icarus回归证明机制可执行，真实收益尚未证实。

## 冻结、资源和范围

- 首请求前工作树干净，冻结源码 `b9f7a6ed57b215208b790c3be32980862267aa49`；[事前方案](agent_budget_study_plan_2026-10-05.md)、[登记](agent-budget-study-live-2026-10-05/preregistration.json)、[设置](agent-budget-study-live-2026-10-05/run_settings.json)及[事前代理审查](../review/agent_budget_prereg_review_2026-10-05.md)单独保存。
- 127项实际输入原字节快照全部匹配，结束无变化。与Git blob对照：{'exact': 103, 'newline_only': 24}，内容差异0。[字节绑定](agent-budget-study-live-2026-10-05/source_byte_binding.json)保留每项双SHA；登记快照是原字节依据，不能宣称只检出Git提交即可满足全部字节门禁。
- Agent SHA `b17db6882dc43899713c641f7134b820df606f31e02cd6d0ec037aac057189cb`，system SHA `1e0b5c481a2e1184d8abcc8006a56e4e93170c36cb0b1c79e7c9a6f57e9aede5`；执行中未调整方案。
- 八模块×正确/B/C目标×三重复×六策略=432任务。每策略48缺陷任务来自16个不同缺陷重复三次，另24正确控制。seed不是模型随机数锁定，不能当作配对服务采样。
- 每任务FIFO16/UART48/SPI20/握手8/其余16累计刺激周期；所有策略每提案最多12向量、累计最多64接受向量。single至多1请求，feedback/no_feedback至多3共享请求和3实际回合，格式与预算拒绝共用请求限额，理论504请求。
- 每次实际episode独立复位，全部输出逐拍after检查；正确RTL逐episode独立重放。复位与参考审计成本另列。AI expected不裁决结果。random采用最多12段均匀独立业务输入，固定与协议随机仅按正确规格构造输入，不读取目标/变体/见证/成绩。
- API仅收到正确规格、接口与允许状态，不接收RTL/路径/私有标签/见证/旧结果。no_feedback隐藏观察、功能覆盖和格式/计划错误；自己的计划、预算和执行器结果驱动早停仍存在，不是完全盲化。未为新模块添加定制覆盖提示，unsupported/unknown不算覆盖证据。
- 开发四模块与信用/仲裁两模块已有API暴露。边沿检测/脉冲展宽是旧离线基准，以往26份受控Agent成员文件未含这两类，仅列模块集合留出；不是v7冻结后新设计、外部盲测、独立缺陷作者或模型预训练未见。

## 完整策略结果

|策略|检出/48|三重复（各/16）|不同缺陷并集/16|请求|输入＋输出tokens|实际刺激周期|
|---|---:|---|---:|---:|---:|---:|
|fixed|48/48|16、16、16|16/16|0|0|1404|
|random|32/48|11、11、10|14/16|0|0|1404|
|protocol_random|48/48|16、16、16|16/16|0|0|1404|
|single|34/48|11、13、10|14/16|72|174,163|871|
|feedback|37/48|11、14、12|14/16|138|356,240|1175|
|no_feedback|37/48|12、13、12|15/16|124|302,813|1088|

每个注册失败/未执行/部分执行任务均保留在对应分母，正确控制不混入缺陷检出率。没有挑选最好一次或给失败行单独重跑。

|子组|每组缺陷分母|fixed|random|protocol_random|single|feedback|no_feedback|
|---|---:|---:|---:|---:|---:|---:|---:|
|development|24|24/24|15/24|24/24|22/24|22/24|21/24|
|prior_internal_holdout|12|12/12|8/12|12/12|3/12|4/12|6/12|
|module_set_holdout|12|12/12|9/12|12/12|9/12|11/12|10/12|

后两模块子组不能与前六混作新的独立泛化集合；内部重复手工缺陷只支持上述范围。

|模块及缺陷|fixed|random|protocol_random|single|feedback|no_feedback|
|---|---:|---:|---:|---:|---:|---:|
|sync_fifo / fifo_bug_full_off_by_one|3|2|3|3|3|3|
|uart_tx / uart_bug_msb_first|3|2|3|2|3|3|
|spi_master / spi_bug_sclk_polarity|3|3|3|3|3|2|
|handshake_stage / hs_bug_ready_ignores_out_ready|3|2|3|3|3|3|
|credit_guard / mutation_b|3|0|3|1|0|2|
|rotating_arbiter / mutation_b|3|2|3|0|0|0|
|edge_detector / mutation_b|3|3|3|2|3|3|
|pulse_stretcher / mutation_b|3|1|3|3|3|3|
|sync_fifo / fifo_bug_write_when_full|3|0|3|3|3|3|
|uart_tx / uart_bug_busy_never_clears|3|2|3|3|2|2|
|spi_master / spi_bug_done_missing|3|2|3|2|2|2|
|handshake_stage / hs_bug_valid_not_cleared|3|2|3|3|3|3|
|credit_guard / mutation_c|3|3|3|0|2|2|
|rotating_arbiter / mutation_c|3|3|3|2|2|2|
|edge_detector / mutation_c|3|3|3|3|3|3|
|pulse_stretcher / mutation_c|3|2|3|1|2|1|

矩阵每格最多3，表示同一缺陷的三次重复，不是三个独立缺陷。

## 正确控制、执行完整性与失败

|策略|登记正确控制|实际执行|误报|状态|
|---|---:|---:|---:|---|
|fixed|24|24|0|{'not_detected': 24}|
|random|24|24|0|{'not_detected': 24}|
|protocol_random|24|24|0|{'not_detected': 24}|
|single|24|21|0|{'not_detected': 21, 'decision_format_error': 2, 'request_budget': 1}|
|feedback|24|24|0|{'not_detected': 21, 'policy_error': 1, 'decision_format_error': 2}|
|no_feedback|24|23|0|{'not_detected': 19, 'policy_error': 2, 'decision_format_error': 3}|

共 **423/432** 任务有实际episode，**507** episode / **1014** 实际＋参考执行侧。证据核验 **423/432**；严格完整比较 eligibility 为 **false**。严格字段不等于检出率，也不能把流程走完称每行都有真实仿真。

正确控制实际执行140/144项，0误报；其余4项未执行，不算正确通过。实际与参考各7,346刺激周期、14,957逐输出检查，合计29,914检查，不包含复位。另一代理核对全部1,014侧stdout/计划/逐拍记录和VCD，88,126端口采样值一致，同时间歧义0。完整原件ZIP包含14,876文件、原始214,317,663字节；ZIP为22,239,237字节，SHA `d2d7df662de9633044946a51063c03a1364f2c0b69315dcb65eba8f784f72269`。

|未执行行（0开始）|模块/目标/策略/seed|状态|stop|请求|费用tokens|
|---|---|---|---|---:|---:|
|13|spi_master/reference/single/0|decision_format_error|decision_format_error|1|2980|
|62|spi_master/spi_bug_sclk_polarity/no_feedback/0|policy_error|policy_error|1|2605|
|76|credit_guard/mutation_b/single/0|request_budget|request_budget|1|2230|
|86|edge_detector/mutation_b/single/0|decision_format_error|decision_format_error|1|1965|
|156|spi_master/reference/single/1|decision_format_error|decision_format_error|1|2643|
|172|credit_guard/reference/single/1|request_budget|request_budget|1|2212|
|332|pulse_stretcher/reference/no_feedback/2|policy_error|policy_error|1|2115|
|347|uart_tx/uart_bug_msb_first/single/2|decision_format_error|decision_format_error|1|2661|
|399|spi_master/spi_bug_done_missing/single/2|decision_format_error|decision_format_error|1|2948|

完整状态计数：{'not_detected': 179, 'decision_format_error': 11, 'policy_error': 4, 'detected': 236, 'request_budget': 2}。已执行行中的后续格式/预算/安全失败也保留，不把部分执行后一项未执行提案当作已完成的功能漏检。每行细节见原始results.zip与strict_summary。

## 预算补提与原响应

schema状态 {'passed': 300, 'rejected': 30, 'not_reached': 4}；普通格式拒绝 30 次，预算拒绝 3 次，其他计划预检拒绝 0 次。三者分开计数；schema通过但预算不适配不记成格式失败。安全原响应保存 330 项，其中不可解析JSON原文 0 项；未保存原文不重造。

|拒绝类型|拒绝数|有后续合法动作的拒绝|后续实际执行的拒绝|拒绝原件保存|
|---|---:|---:|---:|---:|
|decision_format|30|18|18|30|
|plan_budget|3|0|0|3|
|plan_preflight|0|0|0|0|

此表按被拒请求计数；多次拒绝可指向同一后续episode，不能把计数当不同恢复任务数。后续合法stop不计仿真执行。恢复后的检出也不自动证明功能反馈因果优势。

轨迹工具核对全部216条Agent轨迹、334实际请求与账本顺序、请求body SHA及用量。schema通过的300个动作中，291个append实际执行，3个预算拒绝、3个stop、3个已接受提案重复均不执行。17条轨迹在付费格式拒绝后实际执行，其中6项检出（行61、92、98、200、348、400），全部在首个实际episode，后两项包含无反馈策略，不解释为后续仿真反馈的贡献。

330份原响应均为可解析JSON；本批未发生普通json_invalid，故没有真实API的不可解析JSON文本补提证据。另4份原文因安全guard只保留哈希/元数据：2项uninspectable_json_strings、2项duplicate_json_key，均finish=stop且fatal，没有补提，不是输出截断。原文未被重建或伪装保存。代码作者的[轨迹机器审计](../review/agent-budget-study-review-2026-10-05/trace-audit.json)与其他代理的核心证据审计分开披露，不计独立人审。

|有预算拒绝任务（0开始）|模块/目标/策略/seed|拒绝次数|后续执行|最终检出|总请求|总实际周期|
|---|---|---:|---|---|---:|---:|
|9|uart_tx/reference/feedback/0|1|False|False|3|42|
|76|credit_guard/mutation_b/single/0|1|False|False|1|0|
|172|credit_guard/reference/single/1|1|False|False|1|0|

检出发生的第一个实际DUT回合：{'single': {'1': 34}, 'feedback': {'1': 33, '3': 2, '2': 2}, 'no_feedback': {'1': 35, '2': 2}}。请求序号与实际回合不同；在首次真实执行前的付费补提不能记为第二仿真回合。

## 费用与完整原件

本完整批次实际 **334** 请求，输入＋输出 **833,216 tokens**，未知预留 **0**，保守合计 **833,216**，剩余 **166,784**，未超过单一1,000,000限额。所有失败响应包含在账本。历史账不扣入本批，余量不授权另开失败重跑批次。

- [预算原账](agent-budget-study-live-2026-10-05/token_budget.json)与[预算回执](agent_budget_study_budget_2026-10-05.json)；输出4096、thinking disabled、非流式、超时60秒、自动传输重试0，DeepSeek Flash / 用户指定4.1f。服务商账单未提供，不把tokens写成人民币。
- [完整原件ZIP](agent-budget-study-live-2026-10-05/full_raw_evidence.zip)包含全部实际/参考执行侧、计划/stdout/stderr/VCD和冻结输入，不只是轨迹；[完整manifest](agent-budget-study-live-2026-10-05/full_raw_manifest.json)逐项给SHA/大小。原件ZIP及各摘要的校验见[机器回执](agent-budget-study-live-2026-10-05/receipt.json)。
- [轨迹/原响应ZIP](agent-budget-study-live-2026-10-05/traces_and_decisions.zip)、[拒绝/恢复索引](agent-budget-study-live-2026-10-05/trace_manifest.json)、[结果ZIP](agent-budget-study-live-2026-10-05/results.zip)、[严格汇总](agent-budget-study-live-2026-10-05/strict_summary.json)全部保留完整分母。
- 全量1716/2和登记补漏后34项定向、mypy85的区别见[源码验收](agent_budget_source_validation_2026-10-05.md)，不是冻结后重新运行全套。严格RTL样式未通过，实际语义与样式门禁分别披露。

[结果代理复核](../review/agent_budget_study_review_2026-10-05.md)保存原机器核查，核心证据由另一代理核对，轨迹由补提代码作者工具核对，不等于真人试用、外部独立人审或H02。异机完整复现、外部Actions、真人、视频、账单与正式报名上传仍需真实证据。旧PDF/PPT/v5包未由本报告自动更新；本报告不覆盖v6及更早实验。
