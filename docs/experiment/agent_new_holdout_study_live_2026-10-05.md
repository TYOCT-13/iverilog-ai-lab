# 冻结 Agent v8：两个新内部模块的完整 API 留出

2026-10-05。108 项全部登记任务结束。反馈 Agent **11/12**，均匀随机 **10/12**，无反馈 **10/12**。每个分母是四个不同缺陷各重复三次，所有失败和未执行仍保留。这里只描述这个固定内部集合，不证明统计显著、工业泛化或获奖等级。

Agent、端口摘要 helper 和 SYSTEM_PROMPT 在新模块生成前冻结于 a969337。新增的是两级有效数据流水与许可事件模16累计器，以及独立正确参考适配；未改 Agent、训练模型或运行本地模型权重。模块集合与五个早期受控 API 批次互斥，但设计和缺陷都由本团队制作，不是外部盲测、独立作者缺陷、预训练未见、真人试用或 H02。没有独立时间戳证明选型早于 v8 历史结果，不作该更强声明。

实际运行源码 `20400fa7dca0c9804a96b1eb9842956782a9e81f`；458 项输入原字节快照结束无变，Git 对照 `{'exact': 446, 'newline_only': 12}`，原字节快照仍为字节依据。[方案](agent_new_holdout_study_plan_2026-10-05.md)、[登记](agent-new-holdout-study-live-2026-10-05/preregistration.json)、[字节绑定](agent-new-holdout-study-live-2026-10-05/source_byte_binding.json)和[预算](agent_new_holdout_study_budget_2026-10-05.json)分别保留。

完整源码验收 2033 通过、2 跳过，mypy88文件零问题，535 项指纹不变；首轮10个旧路径/探针失败原件保留。非实现者代理另194项非DUT控制流与8项不同封装检查通过，共202；原审计器首轮钩子错误也保留。这些与全仓检查重叠，不相加。[源码验收](agent_new_holdout_source_validation_2026-10-05.md)、[事前复核](../review/agent_new_holdout_prereg_review_2026-10-05.md)不是API成绩或人审。

首次启动被生产跟踪门禁拦截：140份原始仿真日志/结果受通用runs/忽略规则过滤，未纳入第一次Git提交。该次0 API、0密钥读取、0 DUT且未创建输出；只明确跟踪已登记原件后提交新实际执行源码，Agent/全部登记字节及108任务范围不变。[原拒绝回执](agent-new-holdout-validation-2026-10-05/admission_attempts/r1/receipt.json)保留，不视为一次新API批次，也没有擦掉失败。

两模块×正确/B/C×三重复×六策略=108。每策略12缺陷任务、6正确控制；每任务统一24累计刺激拍，自动复位/正确侧审计另外统计。每提案≤12向量，累计接受≤64；single最多1请求，feedback/no_feedback最多3共享格式、预算拒绝和实际episode请求，理论126请求。各episode独立复位，全真实输出每拍after检查，期望由独立参考产生。种子控制本地基线和顺序，不锁定服务端采样。

API只接收正确规格、接口、自有计划/预算和允许的反馈；不接收RTL、私有变体/路径/见证或旧成绩。fixed与protocol_random只读正确规格/contract/seed；random为12独立均匀输入段各2拍。no_feedback隐藏observation、plan_error、latest_decision_error，仍有自有预算及执行器早停，不能称完全盲化。新增功能覆盖仍unsupported/unknown，未增加专属bins或提示。

|策略|检出/12|重复（各/4）|不同缺陷并集/4|请求|已报告输入＋输出tokens|实际刺激拍|
|---|---:|---|---:|---:|---:|---:|
|fixed|12/12|4、4、4|4/4|0|0|432|
|random|10/12|4、3、3|4/4|0|0|432|
|protocol_random|8/12|4、2、2|4/4|0|0|432|
|single|8/12|2、2、4|4/4|18|61529|236|
|feedback|11/12|4、4、3|4/4|38|166073|300|
|no_feedback|10/12|3、3、4|4/4|31|112022|290|

|模块/中性变体|fixed|random|protocol_random|single|feedback|no_feedback|
|---|---:|---:|---:|---:|---:|---:|
|valid_data_pipeline/mutation_b|3|3|3|3|3|3|
|event_accumulator/mutation_b|3|3|1|3|3|3|
|valid_data_pipeline/mutation_c|3|3|3|1|3|3|
|event_accumulator/mutation_c|3|1|1|1|2|1|

每格最多3，是同一个缺陷的重复。不能把12重复任务当12不同缺陷，也不能挑最好一次替代完整统计。

|策略|登记正确控制|实际执行|实际误报|终态|
|---|---:|---:|---:|---|
|fixed|6|6|0|{'not_detected': 6}|
|random|6|6|0|{'not_detected': 6}|
|protocol_random|6|6|0|{'not_detected': 6}|
|single|6|6|0|{'not_detected': 6}|
|feedback|6|6|0|{'not_detected': 6}|
|no_feedback|6|6|0|{'not_detected': 6}|

实际执行 108/108 任务、134 episode、268 实际/正确侧；零DUT任务 0。严格完整比较资格为 **true**，表示全部登记任务的实际执行证据满足这套冻结汇总门禁，不表示每次模型动作都成功。反馈组仍有一项终态 `decision_format_error`：此前已有真实执行，最后请求格式被拒且共享请求额度耗尽，按未检出保留在 12 项分母。原失败没有删除，也没有补开失败专用批次。

收费请求 87/126；已报告tokens 339624，未知保守预留 0，合计 339624/1000000，剩余 660376。unknown请求 0、pending0。历史五账先闭合且不扣新额，不把cache hit/miss额外相加，不把模型usage当货币账单。

付费动作状态 `{'passed': 85, 'rejected': 2}`；未发送共享cap事件 0。普通格式拒绝 2、计划预算拒绝 5，标记retry_eligible的其他preflight 0。另未标记的legacy计划拒绝 0，不能把标记计数为0解释成所有preflight为0。原响应状态 `{'saved': 87}`；可保存原文与guard阻断的hash-only情况分别如实保留，不补造原文。

轨迹全量核查确认87份响应原文均保存：86份可解析JSON、1份不可解析；安全阻断、缺失回复或轨迹均0。5次计划预算拒绝消耗23991 tokens，之后2个不同任务各执行1个实际episode，其中1个检出；2次格式拒绝消耗9274 tokens，之后1个任务执行2个episode，未检出。另一格式拒绝为第108行（从0开始index107，event_accumulator/mutation_c/feedback/seed2）：共3请求，此前实际执行1轮14刺激拍，最后请求因额外顶层字段被拒，未检出且证据有效。拒绝后执行只是观察到的过程，不把事件数当新任务或反馈因果收益。

端口摘要采集 `{'episodes': 80, 'status.complete': 80, 'returned_samples': 701, 'omitted_samples': 125}`，实际送入收费模型STATE的观察 `{'observation_present': 20, 'port.complete': 20}`。每次最多12确定性端点/等间隔样本，明确省略，保留X/Z，来源冲突即返回inconclusive。采集的全部端口事实不等于送进API的全部采样；证据不携带期望值或私有路径。

80份摘要来自826个有限原样本，18份有省略，本次真实X/Z为0。真正送入模型的是20个反馈STATE中的180返回样本、12省略样本；single18个STATE无观察，no_feedback31个STATE的observation/plan_error/latest_decision_error均None。后者仍有12个STATE保留自有计划和减少后的预算，以及执行器早停；不能称所有信息完全盲化。新两模块的功能覆盖均unsupported/unknown，端口摘要complete不是覆盖率或设计正确的证明。

[完整回执](agent-new-holdout-study-live-2026-10-05/receipt.json)、[原始全包](agent-new-holdout-study-live-2026-10-05/full_raw_evidence.zip)、[全部SHA](agent-new-holdout-study-live-2026-10-05/full_raw_manifest.json)、[轨迹索引](agent-new-holdout-study-live-2026-10-05/trace_manifest.json)保留原字节。[结果机器审查](../review/agent_new_holdout_study_review_2026-10-05.md)由非实现者核心审计与entry作者轨迹审计分别记录，不能称真人/H02。请求SHA为canonical sorted JSON，不冒充网络线上原始字节顺序。

两份结果审计均已封存。非实现者完成2192个不同非DUT机械检查（1923主体＋269不同命令/观察绑定），重算6214个输出值，核对27434个VCD端口值、4244个双侧刺激采样与536自动复位拍，以及4ZIP的全部成员、4359原始文件SHA；未发现原件或统计矛盾。轨迹作者核对54条轨迹、87请求与所有原响应。它们与2033个pytest测试分开，不能相加为测试数；重算复用冻结参考和helper，不冒充外部规格认证。首次及补充审计器失败、过早修正说明、351份工具/日志/各次原件均在[审计封装回执](../review/agent-new-holdout-study-review-2026-10-05/receipt.json)与ZIP中保留，所有API/DUT原件未改。

无反馈差值只作该集合描述，服务端采样没有配对固定。反馈比均匀随机和无反馈各高一项，固定基线仍以12/12最高；这些结果不足以证明反馈的因果收益。旧八模块v8的37/48和历史v7结果均不改写，不混合不同集合的分母。

严格RTL样式仍12项未过，WaveDrom依赖缺失；无新Vivado/硬件、UI截图、异机干净克隆、外部Actions或真人/H02。旧正式v2 PDF/PPT尚未同步本轮，不能直接引用成同一版本。

第一次证据打包因Windows长路径触发Git `revision:path`读取失败，已生成的14份部分产物、当时打包工具和失败回执均原样保留。失败文本曾由工具返回，但没有单独的原始stdout字节文件，未事后重建。只修复打包工具为按blob ID读取，再生成完整公开包；没有改原始实验或新增API/DUT。[打包尝试保留回执](agent-new-holdout-validation-2026-10-05/publication_attempts/preservation_receipt.json)记录两次工具及完整产物SHA。
