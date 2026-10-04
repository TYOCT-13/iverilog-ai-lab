# 首轮 Agent pilot 主动停止记录（2026-10-04）

性质：接线失败开发记录，不是有效的完整能力对照试验。由代理只读核对本机原始 JSON，不是真人试用或独立人工复核。原始目录为 `.iverilog-ai/agent-comparison-live-20261004/`，所有 60 条预注册样本保留，未删除失败或覆盖结果。

## 为什么停止

首轮冻结代码为 `0de10a0`。实验 runner 未显式传入 `wire_api`，沿用 Provider 的 `responses` 默认值，与此前真实联调使用的 `chat_completions` 不同。主代理发现接线配置不一致后主动终止进程，`operator_stop.json` 记录停止时间为 2026-10-04 06:44:37.7478548 UTC，即北京时间 14:44:37.7478548。

已知事实是收到的输出发生截断或 JSON 校验失败。没有保存可重放的原始响应正文，不能断言协议不一致就是所有错误的唯一原因，也不能推测服务商返回了什么具体文本。服务端截断标志、JSON 解析错误和预算设置可能涉及不同问题；后续成功不能反向改写本轮记录。

## 原始结果核对

| 项目 | 原始记录值 | 解读 |
|---|---:|---|
| 预注册样本 | 60 | 全部保留 |
| `results.json.requests_attempted` | 7 | 最后一次保存的样本汇总请求数，不是保证完整的账单数 |
| 8 个轨迹的 `requests_attempted` 合计 | 7 | 与汇总一致；末个轨迹尚未更新传输计数 |
| 有 usage 的响应 | 7 | 每份均为第一条决策，没有重复累计参考回放 |
| 输入 tokens 合计 | 3,528 | 可知用量 |
| 输出 tokens 合计 | 47,905 | 可知用量 |
| 总 tokens 合计 | 51,433 | 仅上述 7 份响应，不含未知在途调用用量 |
| API 生成的实际仿真轮数 | 0 | 本轮在线决策均未形成执行证据 |

费用没有服务商账单，保持未知；不能把 token 数直接当实付金额，也不能将未知请求费用记为零。

逐轨迹情况：

| 样本 | 已落盘请求数 | 决策状态/停止原因 | 已知 total_tokens |
|---|---:|---|---:|
| sample-002 | 1 | rejected / output_truncated | 8,696 |
| sample-003 | 1 | rejected / policy_error，json_invalid | 8,594 |
| sample-004 | 1 | rejected / output_truncated | 8,696 |
| sample-007 | 1 | rejected / output_truncated | 8,696 |
| sample-008 | 1 | rejected / policy_error，json_invalid | 7,569 |
| sample-009 | 1 | rejected / policy_error，json_invalid | 5,066 |
| sample-012 | 1 | rejected / policy_error，json_invalid | 4,116 |
| sample-013 | 0 | requested；轨迹默认 interrupted，未结束保存 | 未知 |

sample-013 在强制停止时已有 `requested` 决策，但轨迹仍为请求前的计数 0、耗时 0，未写入返回结果。由此不能证明第 8 次尝试未发出，也不能单凭该文件证明服务端已收到并计费。确定已有记录的是 7 次完成并有用量的响应；还存在一个可能已在途的调用，其发送、完成和计费状态无法从本地记录完全确认。预算与费用报告需单列这项不确定性。

## 状态与分母

`results.json` 中 60 行的状态如下：

| 状态 | 数量 |
|---|---:|
| not_detected | 4 |
| detected | 2 |
| output_truncated | 3 |
| policy_error | 4 |
| not_started | 47 |

其中 detected/not_detected 来自已执行的本地固定/随机基线，不是 API Agent 成绩。`not_started` 包括 sample-013 这个已有请求前轨迹的样本，因此不能解释为 47 项均完全没有发生任何活动。最终完成时间及 `changed_inputs_at_finish` 未保存，不能写成整轮正常完成或冻结一致性验收通过。

每策略仍有 8 个预注册缺陷样本。不得删除失败与未完成后重新计算一个更高的“成功率”；也不得把已完成的局部基线与下一轮在线结果拼成一次实验。这一轮单列为开发失败记录，不进入后续新 pilot 的有效检出统计。

## 原始文件完整性

只读检查时获得的 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `results.json` | `12ddc895b3d930a915fdc3d4d9daa93ab09165f701d1454451866d89f38f4bdd` |
| `preregistration.json` | `16a2c00752e0355c19311338a1135644aa9f1ace95c9be675fd4363f8eb72b9e` |
| `operator_stop.json` | `d86e4a4a22a2a2a7989d7317231631a414027d9329e8a46a83e04c264f7994f9` |

这些原件位于 Git 忽略目录；对外提交时应另行收录脱敏原件。哈希固定的是现有文件内容，不是服务端账单证明。

## 修正与后续轮次

根代理已修改 runner，显式选择 `chat_completions`，增加 `--wire-api` 参数和运行设置记录，以便核对实际配置。新一轮使用新目录和新的冻结版本，不覆盖首轮。本文不填写新轮成绩；其结果须另行检查完整清单、配置哈希、输入变化标记、实际消耗、参考回放和所有失败后报告。

## 同时核对的机器功能验收

独立于本轮 API pilot，另对 `.iverilog-ai/machine-acceptance-20261004/` 做了只读完整性核对：SHA 清单登记的 **285 个文件全部存在且 SHA-256 匹配**。清单自身哈希为 `9a925eb2afc7920e16a0a569157f83d633ee9e122d5eef2c5866f2e3e74d1a8e`，与[机器验收记录](../trial/machine_acceptance_2026-10-04.md)一致。

JUnit 记录为 22 测试、0 失败、0 错误、0 跳过，37.934 秒；metadata 中 T12 退出码为 2、0。取证运行器重定向工件目录并记录真实 CLI 返回值，未见替换为预设成功结果。这些材料支持“选定的机器功能检查通过”，不支持真人完成率、真人满意度、真实浏览器触摸/下载测试或 API 模型效果。

另有复现边界：metadata 和 285 文件清单未冻结被测 `src`、测试、UI 源码的完整哈希或运行 commit。文件一致性不能单独证明某个后续最终提交已获得相同验收；只能作为本机当时工作区执行的产物记录。正式冻结版本仍需按对应范围验证。此次核对没有修改机器验收原件或将其包装为独立人工审核。
