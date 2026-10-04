# 外部 RTL 冻结重放与 Agent 接入边界

日期：2026-10-04。执行者：Codex 机器检查。**不属于真人试用或独立人工复核，不预设成绩。**

冻结重放阶段已修复：抓取对象与检查对象不对应、检查工具路径硬编码、固定目录覆盖旧产物、规格测试没有完整结束标志时仍可能显示“全过”。该阶段未修改 RTL、未生成新缺陷、未使用付费 API。随后已完成外部 API Agent 接入和一次真实服务商请求，见下文；历史报告与原始目录保留。

## 可复现入口

在项目根目录运行，两个输出目录都必须不存在；工具路径替换为实际安装路径：

```powershell
python scripts/fetch_external_modules.py --local-root . --output-dir .iverilog-ai/external/new-frozen-inputs
python scripts/check_external_module.py --manifest .iverilog-ai/external/new-frozen-inputs/manifest.json --output-dir .iverilog-ai/external/new-replay --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe
```

第一条按历史源码 SHA256 验证后复制输入，第二条默认只验证三个基线。没有缓存时使用 `--fetch` 代替 `--local-root .`；网络获取结果也必须匹配冻结 SHA256，远端 master 变化时失败而非悄悄接受新版本。本轮实际验证的是离线复制路径，未验证网络下载路径。UART 历史 ref 是 master，不能补写一个未经证明的 commit；priority_encoder 使用已有完整 commit。

重放历史变体时，给第二条追加 `--existing-cases .iverilog-ai/external/uart_rx_check`。只复制已有文件并记录候选 SHA256；不会运行字符串替换生成新变体。新环境需要另外取得这一历史候选目录，`--fetch` 仅获取上游基线，不制造或下载本项目历史变体。缺少历史候选时报错。

三个模块是 uart_rx、uart_tx、priority_encoder。UART 与规则开发来源同作者，并且这些案例已在开发中分析过；priority_encoder 已用于规则开发。**全部标为开发重放集，不是独立留出集。**

## 本轮实际记录

- 冻结输入：`.iverilog-ai/external/frozen-20261004-ic/manifest.json`。
- 完整日志重放：`.iverilog-ai/external/replay-20261004-ic-final/evidence.json`。
- 此前本轮第一次重放也保留于 `replay-20261004-ic/`，没有覆盖。
- Icarus 实跑 24 个输入：3 基线、15 个历史人工变体、3 个历史等价改写、3 个历史编译失败输入。
- 差分状态：15 `different`、6 `identical`、3 `inconclusive`。
- 基线规格检查：UART RX 11 项、UART TX 10 项、优先编码器 28 项，均零失败。
- 规格测试台检出 13/15 个历史人工变体；UART TX 的 `mut_prescale_off_by_one` 与 `mut_busy_never_clears` 仍未被规格测试台检出。保留这一局限，不能用差分结果冒充规格判定。
- 夹具回归 29 项通过，覆盖输入哈希篡改、目录逃逸、拒绝覆盖、明确 CLI 参数、规格仿真缺失结束标志/非零退出等。两个脚本通过 mypy。

此处“检出”仅描述给定人工变体和已执行检查；不是发现了 15 个上游真实缺陷，也不是通用检出率。差分的 `identical` 只说明给定激励下没有观测到差异，不是形式等价证明。

## 产物接口

`manifest.json` / `inputs_manifest.json`：`schema_version=external-inputs-v1`，`modules` 以模块名索引；每项含 repository、ref、path、url、sha256、local、spdx、acquisition、independent_holdout。`local` 相对于清单目录，读取时拒绝越界并核验全部输入哈希。

`evidence.json`：`record_kind=machine_replay`、`independent_holdout=false`；`input_manifest` 给出冻结输入；`tools` 保存实际工具版本输出；`artifact_sha256` 保存本次产物相对路径及内容哈希。`rows` 每项含 module、variant、candidate（相对于证据目录）、candidate_sha256、result。每例完整编译/仿真/差分日志分别保存在 `*_compile.log`、`*_simulation.log`、`*_diff.log`，不成功编译时没有仿真日志。

`result.spec_complete` 表示真实仿真正常退出且含正检查数的完整 SPEC_SUMMARY；与 `failures` 一起阅读。检查失败也是有效的执行结果。`diff_status` 为 identical/different/inconclusive，细节位于 `diff_<module>_<variant>/verify_diff.json`。

## API Agent 接入现状（已实施）

外部适配器 `scripts/run_external_verification_agent.py` 已复用有界 Agent 循环及 typed observation 接口，使用 `qualified_baseline_differential`，不冒充 reference_model，也不将输出比较样本数称为断言数。实现与命令见[外部 API Agent 使用说明](external_api_agent.md)。

已实施的约束：

1. 冻结并核验基线/候选哈希，真实执行已有 SPEC_TB；仅在正常退出、正检查数且零失败时授予有限测试范围内的资格。
2. 同一累计激励计划分别执行基线和候选，两侧周期均计入预算；API 只能追加输入，不能改变基线、合约或判据。
3. 只比较既有资格检查支持的合约输出。生成测试台在实际采样语句同点加入只读日志，记录即时输出；严格校验补丁锚点并保存原测试台、插桩测试台及源码哈希。旧 VCD 时间戳最终值方案有采样歧义，已停用并保留错误取证，见[代理交叉检查](../review/external_agent_cross_review_2026-10-04.md)。
4. 断言 checks/failures 保持 0，单列 compared_samples/differences；编译错误、空采样、X/Z、采样点不齐或输入哈希变化不能得到一致结论。发现差异停止为 behavior_difference，不称功能反例。
5. 外部流水线显式关闭内置参考模型映射，避免外部 uart_tx 与内置同名案例混用判据；训练候选导出仍不把这种差分证据混入 reference_model 样本。

真实 UART RX 联调已经完成：**1 次 deepseek-flash / Chat Completions 请求、两轮 23→27 向量、每侧 182→209 周期、累计 782 双侧周期、547→628 个有效输出比较、0 差异**，因 round_budget 停止。实际 usage 为 5661 tokens，没有账单金额。该次使用修复后的即时快照；候选与基线内容相同，所以它验证的是接线与追加执行，不是通用准确率。

详见[真实联调记录](external_agent_live_2026-10-04.md)及[公开摘要与工件指纹](external-agent-live-2026-10-04/summary.json)。保存后的最终 API 计划另做 0 API 历史位序变体重放，但原固定计划本来就能暴露同一差异，不能归因于新增 4 个向量。

基线资格依赖已有有限规格检查，不是额外建立了一套独立完整规格，更不是独立人工认可。UART TX 两个历史变体的规格漏检仍然保留。三模块属于已开发使用的重放集；这些运行没有补齐真人试用、独立人工复核或独立留出评估。

版本 `1c1e0dc` 新增的内置 before 相位保守门控针对 reference_model 路径；外部 typed observer 使用真实测试台同点快照，其 before/after 捕获口径没有因此改为预测值。
