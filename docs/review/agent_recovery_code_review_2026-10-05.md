# Agent 格式拒绝恢复：只读代码复核

日期：2026-10-05。复核发现一处明确非正常结束状态仍能触发格式重试的问题，修复后已用原反例及合法动作控制复测通过；当前限定范围内未发现剩余阻断项。这是**代理代码复核，不是H02真人审核，也不是新实验成绩审核**。

本次没有调用真实API、读取实际凭据、执行真实DUT或修改生产代码。HTTP全部由本地函数替身接管，凭据均为合成字符串；执行计数检查使用内存pipeline替身。仅新增本报告及[机器回执](agent-recovery-code-review-2026-10-05/receipt.json)。小样轨迹和选定pytest日志留在私有临时目录，不作为真实API或电路证据。

## 绑定版本

复核对象是 [agent.py](../../src/iverilog_ai/ai/agent.py) 的普通JSON/schema拒绝重试、原始回复归档、诊断隔离和预算终态。最终实际检查的工作字节SHA256：

`b3eca75bab345ef2b9d5d2ebd0280f9811bd37532fb979d2f8c5a4ac220ce5fe`

提示版本为 `verification-agent-v6-bounded-format-recovery`。复核时HEAD为 `10ebefe7848812ce57c4d50ed7ee5b6e51db4eb6`，agent修改尚未包含在该提交中，因此不将此HEAD称为已包含修复的冻结版本。源码、schema、provider及所用测试文件的SHA与长度均登记在机器回执；完整回归、类型检查及最终提交冻结由根代理另行登记。

根代理完成回归后，仅删除专项测试文件末尾一个多余换行。机器回执保留实际测试时的原SHA；[测试原字节副本](agent-recovery-code-review-2026-10-05/reviewed_test_bytes.zip)可以核对该SHA。最终测试文件SHA为`21ed61d24293349dd862f498cfdba4f7b2e5a4f71e225a1ea216c1d74ea23bfe`，生产Agent字节未因此变化。

## 发现、修复与原例复判

**RECOVERY-01：非正常服务端结束状态被误当普通格式错误重试。**

初版源码SHA为 `0bb11da1c01faab972a3bdf84c39e30acca6779dd6f761d7e683e0496830e75c`。通过HTTP替身返回以下content，并分别设置 `finish_reason=content_filter` 或 `tool_calls`：

```json
{"action":"stop","reason":"safe","vectors":[],"type":"json_object"}
```

原实现只提前处理 `length`。两例均将首回复标记为可重试schema错误，消费第2次请求，随后收到正常stop而结束为 `model_stopped`。这两例被记录为实际发现，初次36例矩阵不能表述为“全部无问题”。

修复在解析/归档/schema之前检查明确的非stop结束状态，返回固定代码 `non_decision_finish`。最终重放两例均为：1次请求、`policy_error`、`retry_eligible=false`、归档blocked、0轮执行、0周期。另用合法stop与合法append分别配合这两种finish，共4个控制例，确认不是只对额外type字段生效。

`length`仍结束为 `output_truncated`；`None`保留旧provider兼容，不把完成状态未知的回复归档为已完成原文。

## 实际执行的检查

| 检查 | 最终结果 | 范围 |
|---|---|---|
| HTTP替身矩阵 | 40例通过，49个模拟HTTP请求 | 普通格式恢复、合成凭据、重复键、转义、大小、结束状态、usage |
| 内存计数案例 | 9例通过 | 请求、轮次、append重放、周期、错误生命周期与终态 |
| state标记检查 | 4种反馈/覆盖组合通过 | observation、判据、失败、覆盖、plan_error、decision_error |
| 选定pytest项目 | 9通过、1跳过 | 归档碰撞、可信诊断、命令/判据/向量限制、时间预算、UTF-8原字节 |

这些检查分别记录，不与实现代理报告的测试数相加，也不称为全仓回归。pytest的basetemp在仓库外，关闭缓存插件；跳过项是Windows创建目录符号链接缺少权限（1314），不能据此声称本机已实际验证该链接场景。

最终HTTP矩阵保留了合法控制：可检查的尾逗号、缺外层右括号、缺值及尾随文字原文会作为 `.txt` 惰性保存；schema不合法但JSON可解析的回复保存为 `.json`。原UTF-8字节、长度、SHA一致，格式错误本身不执行，剩余额度内的后续合法动作才被接受。

12个合成凭据案例覆盖原文、Unicode转义、嵌套值、对象键，以及包含引号和反斜线的凭据；均立即停止且不归档。4个重复解码键案例、6个未完成/不可检查转义或字符串案例也均不可重试。超长、截断及矛盾usage不降级为普通schema恢复。

## 请求、周期与终态

| 内存案例 | 请求 | 执行轮次 | 激励周期 | 终态 |
|---|---:|---:|---:|---|
| single=1，格式错误 | 1 | 0 | 0 | decision_format_error |
| 错误后合法2拍 | 2 | 1 | 2 | round_budget |
| 连续3次错误 | 3 | 0 | 0 | decision_format_error |
| append：2拍→错误→追加1拍 | 3 | 2 | 5 | request_budget |
| 错误后传输异常 | 2 | 0 | 0 | policy_error |
| 错误后length截断 | 2 | 0 | 0 | output_truncated |
| 预检错误→格式错误→合法，无反馈 | 3 | 1 | 1 | round_budget |
| 错误后超周期提案 | 2 | 0 | 0 | cycle_budget |
| 已执行2拍后格式请求耗尽 | 2 | 1 | 2 | decision_format_error |

schema拒绝不增加round、accepted_vectors或stimulus cycles，不替换已接受的plan；usage和实际请求数经finally保存后再检查共享上限。append案例实际执行2拍加重放后的3拍，累计5拍。single上限1不会私自追加纠正请求；时间额度耗尽也会在下一请求前停止。

schema通过清除 `latest_decision_error`，计划预检通过清除 `latest_plan_error`。已有有效执行后发生格式耗尽仍保留先前证据，不冒充普通成功或普通未检出。

## 可信诊断、无反馈与归档边界

诊断只包含固定解析代码、白名单字段/合同端口名、受限下标和固定提示；未知字段转为 `unknown_field`。合成恶意字段名、错误消息标记和原回复内容没有进入下一请求。schema仍拒绝命令字段、模型自定义期望及超过12个向量；不会清洗坏动作后静默执行。

无反馈时 `observation`、`plan_error`、`latest_decision_error`均为空，即便启用功能覆盖也不会显示这些字段。归档原文及其路径/metadata不进入反馈、判据或执行。无反馈仍保留执行器早停及流程/剩余额度信息，本检查不据此宣称单因素反馈隔离或反馈因果收益。

原回复只作为 `trusted:false` 诊断保存，完成状态必须为stop；采用固定文件名、新文件排他创建和输出路径校验。现有 `.json`及新 `.txt`碰撞测试均确认不覆盖原文件。无法完整检查的字符串/转义故意阻断，因此不能承诺每次拒绝都有完整原文。

凭据守门的范围是当前活动key的原文和JSON解码字符串，不是任意编码、拆分字符串或所有秘密的通用扫描器。此次检查没有真实服务端响应，也不证明格式失败率、检出率或用户收益改善；新批次结果需要另行审核，旧实验和缺失原文不会因此被补造。
