# 两类新内部合成模块留出资产

本目录提供 `valid_data_pipeline`（两级有效数据流水）和 `event_accumulator`（许可事件模16累计器）。Agent/helper/system提示词已冻结；本新cohort首次API前固定两模块及全部四处单点语义突变，不宣称有独立时间戳证明早于v8结果形成；这是团队内部合成资产，同一团队制作缺陷，不能称外部盲测、独立作者缺陷、真人试用或人审。

正确规格位于 `spec/agent_new_holdout_20261005/`。合同固定为无参数、10ns 上升沿、`i_rstn` 异步低有效、起始复位2拍；全部输出 after 逐拍采样。每任务所有独立复位 episode 共用24刺激拍，每提案≤12输入段，Agent累计接受64向量是额外安全上限。省略输入在本 episode 内保持，不跨 episode 保持电路状态。

`manifest.json` 显式绑定正确来源、固定合同、正确规格及 A/B/C 中性目录源 SHA。A为正确参考，B/C仅机器审核映射。`private_metadata/` 不作为任何 API 输入。`baseline_factory(case, strategy, seed, contract, cycles)` 只读正确规格和显式合同，支持 fixed/random/protocol_random、cycles=24；均匀随机为12个独立输入段各2拍。所有 expected为空，不读取目标RTL、突变元数据、见证或成绩。

私有首次功能验收：4748短任务、21124刺激拍、24260输出检查，对正确RTL零差异；6目标均真实Icarus Verilog-2001编译/运行成功。4处语义变体均有真实私有见证，同时保留不触发的正常控制任务。修改注释、排版和显式算术截断后r2完整重复通过。基线18个计划（两模块×三策略×seed0/1/2）432拍648输出检查通过；40项纯接口/预算/确定性/错误合约检查通过。以上是离线机械证据，未形成任何新增Agent成绩。

在新增权威参考集之前，新state adapter已直接对照r2全部24260真实输出样本，且最后注释排版修正与r2非注释token等价。正式generic pipeline集成及完整合同负例的最终结果另见 `validation/public_integration_receipt.json`，仅在实际完成后生成。

样式首失败101项、第二轮35项、第三轮12项均保留。r3八类矩阵：compile/ast/comment/profile通过；readability与naming未通过，余项是强组合逻辑锥预算9项和输出桥接`count_o`默认规范与cnt_命名要求冲突3项。未为过门禁增加延迟或改变功能。testbench/toolchain在该静态门禁未请求，不代表已验证全部工具链；另有真实Icarus机械执行证据。WaveDrom3.6.1依赖缺失，注册write-spec首轮端口role不足rc2、补正后实际renderer缺失rc1均保留；未安装依赖、未生成或声称验收SVG，无Vivado综合/实现结果。RTL头部规范中设计PDF/Vivado路径仅样式元数据，非生成或执行证明。

先前未暴露核查仅覆盖已公开完成批次的preregistration成员和标准rtl模块名。列表与SHA在 `prior_module_membership.json`；不证明模型预训练未见相关电路或所有非正式讨论都不存在。当前运行批次的局部成绩未读取。旧Agent、提示词、历史报告及原始实验结果未改。
