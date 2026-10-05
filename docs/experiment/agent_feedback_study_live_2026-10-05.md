# Agent v8：有界端口反馈的八模块完整对照

2026-10-05。432 项登记任务全部走完。本批反馈 Agent 检出 **37/48**，均匀随机 **32/48**，无反馈 **37/48**，人工固定和协议随机分别 **48/48、48/48**。每组 48 项是 16 个不同缺陷各重复三次；这是当前已暴露模块、预算和参考模型下的描述性结果，不证明统计显著、工业泛化或获奖等级。

本版增加真实端口采样的来源绑定摘要、由实际 validator 生成的动作层级提示和独立复位的完整路径说明。目标、正确规格、基线、seed 顺序和周期限制沿用 v7，未根据旧成绩重选。三项修订同时发生，历史差值不能解释成端口反馈的单因素效果。

反馈总计仍为历史 v7 的 37/48，无反馈也为 37/48，未显示整体检出数提高。信用/仲裁反馈由历史 4/12 到本批 8/12，与本批随机 8/12 持平；开发四模块由 22/24 到 20/24，后两已暴露模块由 11/12 到 9/12。预算和服务端采样影响仍在，不能挑单个上升子组替代完整统计。

## 冻结与资源

首请求前工作树干净，冻结源码 `a96933786c17986a739fc2da515db3294d6e8044`。实际登记 131 项输入，结束无变化；Git blob 对照为 `{'exact': 107, 'newline_only': 24}`，无内容差异。原字节快照是复现的字节依据，不能把仅检出提交等同全部原字节门禁。[事前方案](agent_feedback_study_plan_2026-10-05.md)、[登记](agent-feedback-study-live-2026-10-05/preregistration.json)、[执行设置](agent-feedback-study-live-2026-10-05/run_settings.json)、[字节绑定](agent-feedback-study-live-2026-10-05/source_byte_binding.json)分别保留。

源码验收为 1858 通过、2 跳过，mypy 87 文件零问题，运行期间 263 指纹不变；非实现者代理另实跑 121 个非 DUT 检查，不与全仓相加。验收和事前审查后，仅为原始失败日志增加两条 .gitattributes 空白豁免并更新文书，运行源码、规格和计划未再变更。候选审查与最终登记的该属性文件 SHA 区别如实保留。[源码验收](agent_feedback_source_validation_2026-10-05.md)与[事前审查](../review/agent_feedback_prereg_review_2026-10-05.md)不计 API 或 H02。

- 八模块 × 正确及两个缺陷 × 三重复 × 六策略 = 432 项；每策略另有 24 个正确控制。八模块均已在历史 Agent 实验暴露，当前没有新留出或外部盲测。
- 每任务累计刺激上限：FIFO 16、UART 48、SPI 20、握手 8，其余 16；每提案最多 12 向量，累计最多 64 接受向量。single 最多 1 请求，feedback/no_feedback 最多 3 请求和 3 个实际回合，格式及预算拒绝共用上限，理论最多 504 请求。
- 每个实际 episode 独立复位并独立重放正确 RTL；全部输出逐拍 after 比较，AI 不给裁决期望值，复位及参考成本另计。seed 控制本地基线和任务顺序，不锁定服务端采样。
- API 只收到正确规格、接口和允许的计划/状态；不收到 RTL、私有目标/路径/见证或旧结果。六组捕获相同原始证据；no_feedback 隐藏 observation、plan_error 和 latest_decision_error，但自有计划、预算及结果驱动早停仍在，不能称完全盲化。
- 端口摘要最多 12 个确定性端点及等间隔采样，标明省略，保留 X/Z。来源不一致或样本不充分时返回空样本固定原因码；端口事实不等于内部状态、覆盖率或正确性。新增模块功能覆盖仍 unsupported。

## 完整策略结果

|策略|检出/48|三重复（各/16）|不同缺陷并集/16|请求|已报告输入＋输出 tokens|实际刺激周期|
|---|---:|---|---:|---:|---:|---:|
|fixed|48/48|16、16、16|16/16|0|0|1404|
|random|32/48|11、11、10|14/16|0|0|1404|
|protocol_random|48/48|16、16、16|16/16|0|0|1404|
|single|29/48|12、10、7|14/16|70|205,503|888|
|feedback|37/48|11、16、10|16/16|122|426,581|1177|
|no_feedback|37/48|12、14、11|15/16|114|341,065|1179|

所有失败、未执行和部分执行均在完整分母内；没有取最好一次、删除失败行或给失败行另开补齐批次。

|历史分组（当前全为已暴露模块）|每组缺陷分母|fixed|random|protocol_random|single|feedback|no_feedback|
|---|---:|---:|---:|---:|---:|---:|---:|
|development|24|24/24|15/24|24/24|15/24|20/24|22/24|
|previous_internal_modules|12|12/12|8/12|12/12|7/12|8/12|7/12|
|previous_module_set_holdout|12|12/12|9/12|12/12|7/12|9/12|8/12|

这些分层不能重新标为 v8 留出。credit/arb 和 edge/pulse 的历史留出口径只属于旧批次。

|模块 / 缺陷|fixed|random|protocol_random|single|feedback|no_feedback|
|---|---:|---:|---:|---:|---:|---:|
|sync_fifo / fifo_bug_full_off_by_one|3|2|3|2|3|3|
|uart_tx / uart_bug_msb_first|3|2|3|1|3|3|
|spi_master / spi_bug_sclk_polarity|3|3|3|2|3|3|
|handshake_stage / hs_bug_ready_ignores_out_ready|3|2|3|3|3|3|
|credit_guard / mutation_b|3|0|3|3|3|3|
|rotating_arbiter / mutation_b|3|2|3|0|1|0|
|edge_detector / mutation_b|3|3|3|3|3|3|
|pulse_stretcher / mutation_b|3|1|3|2|3|2|
|sync_fifo / fifo_bug_write_when_full|3|0|3|2|3|3|
|uart_tx / uart_bug_busy_never_clears|3|2|3|2|1|3|
|spi_master / spi_bug_done_missing|3|2|3|2|3|3|
|handshake_stage / hs_bug_valid_not_cleared|3|2|3|1|1|1|
|credit_guard / mutation_c|3|3|3|3|3|3|
|rotating_arbiter / mutation_c|3|3|3|1|1|1|
|edge_detector / mutation_c|3|3|3|2|2|2|
|pulse_stretcher / mutation_c|3|2|3|0|1|1|

矩阵每格最多 3，是同一缺陷的重复计数。只有全部子组都支持时才可概括子组表现；整体计数不能掩盖某模块的漏检。

## 正确控制、执行完整性与失败

|策略|登记正确控制|实际执行|实际误报|完整终态|
|---|---:|---:|---:|---|
|fixed|24|24|0|`{'not_detected': 24}`|
|random|24|24|0|`{'not_detected': 24}`|
|protocol_random|24|24|0|`{'not_detected': 24}`|
|single|24|23|0|`{'not_detected': 23, 'request_budget': 1}`|
|feedback|24|24|0|`{'not_detected': 24}`|
|no_feedback|24|24|0|`{'not_detected': 24}`|

414/432 项有实际执行，484 个 episode / 968 个实际及参考侧，证据核验 414/432。严格完整比较资格为 **false**；流程走完不等于每行均有真实仿真。正确控制实际执行 143/144 项，实际误报 0；其余 1 项不能算正确通过。

全任务终态计数：`{'not_detected': 183, 'request_budget': 3, 'detected': 231, 'decision_format_error': 6, 'policy_error': 1, 'token_budget': 8}`。零 DUT 任务共 18 项，逐行身份和原因全部在 [机器回执](agent-feedback-study-live-2026-10-05/receipt.json) 的 unexecuted_tasks；已执行后续失败和资源消耗另见 [严格汇总](agent-feedback-study-live-2026-10-05/strict_summary.json) 与 [完整结果](agent-feedback-study-live-2026-10-05/results.zip)。

## 动作拒绝、预算恢复与端口反馈

实际收费请求的 schema 状态：`{'passed': 287, 'rejected': 18, 'not_reached': 1}`。另有 8 次发送前 TokenBudgetExceeded 事件，未收费，不是模型危险回复；包含这些事件的原轨迹状态计数为 `{'passed': 287, 'rejected': 18, 'not_reached': 9}`。普通格式拒绝 18 次，合法预算拒绝 16 次。另有 2 次既有非预算计划预检错误（reference_plan_invalid、unknown_input_port）；它们不带本次 retry_eligible 标记，所以公开 manifest/receipt 中“其他可补提预检”计数为 0，不代表所有预检均无错误。schema 通过但预算不适配不算格式失败；安全 guard 拒绝保持终止。

|拒绝类型|拒绝次数|有后续合法动作的拒绝|后续实际执行的拒绝|原件保存|
|---|---:|---:|---:|---:|---:|
|decision_format|18|12|12|18|
|plan_budget|16|9|9|16|
|plan_preflight|0|0|0|0|

拒绝表按被拒请求计数，多次拒绝可能指向同一后续 episode；合法 stop 不算实际执行，首个实际回合前的格式补提不能记作第二个仿真回合。

本批预算拒绝后实际执行的被拒请求数为 **9**。脚本及 Icarus 回归只证明机制；真实剩余机会、任务和后续检出须按 [拒绝/恢复索引](agent-feedback-study-live-2026-10-05/trace_manifest.json) 及轨迹审核另行区分。

轨迹审计确认 9 条预算拒绝后的恢复轨迹中 4 项检出（行 205、267、282、410，0 开始），行 282 在第二个实际回合，其余在首个实际回合；包含无反馈策略，不是反馈因果证据。12 条格式拒绝后执行的轨迹中 5 项检出，行 124 在第二实际回合，其余在首回合。两条既有非预算预检错误行 225、359 随后也执行并检出，单独列示，不混入新预算机制的 9/4 计数。

保存的安全原响应 305 份，其中不可解析 JSON 1 份；因 guard 不能保存的原文仅保留已有哈希/长度和原因，不重建。检出所在首个实际回合为 `{'single': {'1': 29}, 'feedback': {'1': 34, '2': 3}, 'no_feedback': {'1': 36, '2': 1}}`。

Agent 实际 episode 端口摘要计数：`{'episodes': 268, 'status.complete': 268, 'returned_samples': 2203, 'omitted_samples': 1041}`。后续实际付费请求的模型 observation 状态：`{'observation_present': 46, 'port.complete': 46}`。no_feedback 实际付费请求共 114 个，三个反馈字段均为空；原始采样仍保存，不能把采样文件存在等同模型已看到。

## 单批预算与完整原件

实际 306 请求，报告用量 **973,149 tokens**，未知预留 0，保守合计 **973,149**，剩余 26,851，上限 1,000,000。已知用量请求 306，未知用量请求 0，闭合 pending 为 0。失败请求计费保留，历史四批闭合账不扣新批，余量不授权另开失败重跑批次。

共享账本按预登记顺序运行，剩余额度不足请求的保守预留时停止发送，即使还有少量未用 tokens。第三重复末段有 8 项 token_budget 终态；整批资源上限没有越过，但晚序任务的实际执行受此限制，严格完整比较资格保持 false，不能据此作公平完整因果优势声明。

- 使用 DeepSeek Flash / 用户指定 4.1f API，chat_completions，thinking disabled，非流式，输出上限 4096，超时 60 秒，无自动传输重试，store=False。不加载本地模型权重。未知用量不能按零，服务商账单未提供，不换算人民币。
- [预算原账](agent-feedback-study-live-2026-10-05/token_budget.json)、[本批预算回执](agent_feedback_study_budget_2026-10-05.json)、[完整原件 ZIP](agent-feedback-study-live-2026-10-05/full_raw_evidence.zip)、[逐文件 SHA/大小](agent-feedback-study-live-2026-10-05/full_raw_manifest.json)、[输入快照](agent-feedback-study-live-2026-10-05/registered_inputs.zip)、[轨迹及原响应 ZIP](agent-feedback-study-live-2026-10-05/traces_and_decisions.zip)均独立保存。

本报告不覆盖 v7 及更早的已绑定结果。历史 v7 的反馈 37/48、随机 32/48、无反馈 37/48 和信用/仲裁反馈 4/12 保持不变；本轮与历史差值只作描述，不据此声称单因素因果。

全量只读代理复核已经完成：[审核文书](../review/agent_feedback_study_review_2026-10-05.md)与原机器记录区分职责。另一代理核对全部 968 执行侧、30,356 输出检查、89,482 个 VCD 端口值、131 输入快照与四个 ZIP；代码作者核对 216 轨迹、306 账本顺序、305 原文哈希/长度及反馈 STATE。无新增 API 或 DUT 仿真，未发现机器证据矛盾。请求 SHA 绑定账本的 canonical sorted JSON，未另存 HTTP wire-order 字节；模型报告用量不等于账单。

源码和代理复核不能替代真人试用或 H02。严格 RTL 样式、异机完整复现、外部 Actions、硬件、真人、视频、账单及正式上传仍需各自真实证据。旧 PDF / PPT / v5 包未由本报告自动更新。
