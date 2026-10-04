# 外部 RTL 冻结重放与 Agent 接入边界

日期：2026-10-04。执行者：Codex 机器检查。**不属于真人试用或独立人工复核，不预设成绩。**

本轮已修复：抓取对象与检查对象不对应、检查工具路径硬编码、固定目录覆盖旧产物、规格测试没有完整结束标志时仍可能显示“全过”。未修改 RTL、未生成新缺陷、未使用付费 API。历史报告与历史原始目录保留。

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

## 接入 API Agent 的下一步接口方案（尚未实现）

当前 `ai/agent.py` 接受 `VerificationPipeline` 的 reference_model 判据；外部模块没有对应内置参考模型。现有 verify-diff 是另一类证据，**不能把它伪装成 reference_model 或将波形样本数冒充断言数**。

建议增加显式 ExternalVerificationRunner，输入为：已冻结且哈希核验的基线、候选、合约、累计激励计划、已完成的基线规格资格检查、输出目录和工具/时间预算。它应：

1. 先执行并保存基线规格测试，要求正常退出、检查数大于零、失败数为零；将资格仅限定为这些已执行规格检查。
2. 每轮将同一份激励送入冻结基线和候选，预算计入两次仿真；禁止 API 修改参考实现、合约判据或已有检查。
3. 差分仅使用合约中输出端口及明确采样时刻。当前原始差分含内部信号，内部实现变化不应自动成为功能差异。
4. 返回显式证据类型 `qualified_baseline_differential`，包括 baseline/candidate/contract/plan 哈希、两次仿真状态、实际比较的输出/样本、差异样本和资格记录。运行失败、空观测或 X/Z 不可判定情况需保持 inconclusive。
5. Agent 可据此追加输入；终止标签为 behavior_difference 或预算结束。只有另有规格判据确认时才能称 functional_counterexample。
6. 轨迹导出按证据类型分开处理，不混进目前只接收 reference_model 的训练候选；三模块本轮轨迹不能称独立留出评估。

这项 Runner 与 Agent 的类型化证据接口仍需要实现和测试；本轮完成的是可复现外部输入、真实重放与产物契约，并未声称外部 UART 已接入 API Agent。
