# 既有模块的 Agent 集合留出资产

这里固定 `edge_detector` 和 `pulse_stretcher` 两个已有离线基准模块。只读核查了此前受控 Agent 实验的 26 份成员文件，两模块均未出现在那些模块集合中。这不表示模型预训练未见、设计从未测试、外部盲测或独立作者新缺陷。资产准备与 Agent v7 修改并行，不声称在 v7 冻结后创建。

`manifest.json` 按旧 `benchmarks/manifest.json` 顺序各选前两个缺陷，全部纳入，不按新结果筛选。每模块 A 是正确 RTL、B/C 是原有人工变体的逐字节复制；合约也逐字节复制。原变体的注释保留，因此模型只可读取新 `spec_path` 的正确功能规格与显式合约，不能读取目标源码、manifest 私有标签、witness、成员审核或校验结果。

两个任务都采用默认合约、10 ns 上升沿、异步低有效复位两拍、每个 episode 独立复位、全部输出逐拍 `after`。所有实际 episode 共用 16 刺激拍，每次提案最多 12 向量、累计接受最多 64 向量，最多三个共享请求轮次，进一步服从运行时剩余额度。`pulse_stretcher` 固定 WIDTH=4：触发拍计入四拍窗口，窗口内每个高输入样本都会重新触发，最后一个高输入样本后仍有三拍高输出。

入口是 `baselines.py:baseline_factory(case, strategy, seed, contract, cycles)`。仅支持 fixed、random、protocol_random 和已资格认定的默认合约、16 拍。它只读取正确公开规格；fixed/protocol_random 由正常采样变化、保持、完整窗口及重触发构成。random 采用十二段，前四段各两拍、后八段各一拍，仅随机业务输入并保持 `rst_n=1`。所有计划空 expected、after、最多十二向量，不读取目标、标签或成绩。

离线验证使用独立转换真值表和最近触发时间窗口，交叉核对原 core 参考模型及实际 Icarus。最终 81 项通过、三个辅助文件 mypy 零错误；28 次 pipeline 仿真共 330 拍/检查，加两次直接异步复位仿真，合计 30 次真实编译/执行，全部返回 0。四个已登记 witness 均真实检出，正确对照无失败。512 个八拍二值序列的穷举是 Python 双语义校验，不是额外 Icarus 执行。

首轮 77 通过、4 失败保留：新增测试把缺陷检出的运行状态错误要求为 `failed`。真实记录是 `status=passed_with_warnings`、`verdict=failed_checks`、每变体一条功能失败；输出已匹配登记反例。仅修新测试与报告读取，未改 oracle、RTL、Agent 或 runner。补测四项及最终完整测试另存，不覆盖首轮。

原字节 RTL 不符合 readable-verilog-generator 的严格样式规则。其八类门禁及原失败报告另有记录；静态 formatter 解析/样式失败与实际 Icarus 成功分别列出，不声称严格 RTL 样式交付通过。未运行综合或远程工具链。

来源、SHA、首轮失败、最终测试和实际工件索引见 `validation_receipt.json`；`audit/style_gate_summary.json` 列出八类样式矩阵。全部为本地离线资产校验，0 API、未读密钥、未安装依赖、未提交 Git；不含真人试用、独立人审或 Agent 效能成绩。
