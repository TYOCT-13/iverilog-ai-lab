# IC Agent v4 API 接线与留证代理复核（2026-10-04）

本次发现并复现了两种活动凭据检查绕过：重复 JSON 键丢弃前值，以及重序列化把凭据中的引号/反斜线再次转义。实现代理修复后，在冻结提交 `28be1edc8b84067912e2034567a8e8a5803b8184` 上重新执行，三组模拟凭据反例均被拒绝，未归档、未形成已验证动作、未执行计划。当前核验范围未发现残留阻断。

执行者为 Codex 子代理 `/root/conflict_status`。这是代理技术复核，**不是 H02 真人独立审核**。所有网络响应来自 HTTP stub，使用明确虚构的凭据；本代理真实 API 请求数为 **0**，没有读取真人凭据、修改源码或提交 Git。父任务的真实 v4 smoke 和全量回归另行执行，不是本记录的通过依据。

## 1. 冻结版本与核验范围

最终核验时间：**2026-10-04 22:15（UTC+08:00）**。HEAD 为上述 `28be1ed`；以下文件在复测后逐字节匹配该提交的 Git blob，相关路径没有未提交修改。本记录及其他任务的文档可以尚未提交，不能据此声称整个工作区完全干净。

| 文件 | SHA256 |
|---|---|
| [agent.py](../../src/iverilog_ai/ai/agent.py) | `80d77a699a1fe4683c24cba1b96deff3497fe242adfde31264e29a29807cd742` |
| [provider.py](../../src/iverilog_ai/ai/provider.py) | `caf55116017e962743e03223ff978b13e69ba71b41e11113d16648e8e9763478` |
| [test_agent_decision_v4.py](../../tests/ai/test_agent_decision_v4.py) | `98f4418d19bba5343ca48ac5fda8e3c5f84ad47c852fe0a60cb145357b477b90` |
| [export_agent_trajectories.py](../../scripts/export_agent_trajectories.py) | `60949d44bf8866e53abc67abf94d9b5c72ed5255afb5667f66b53d106aecc1d5` |
| [test_agent_export.py](../../tests/core/test_agent_export.py) | `ba0fc7aa436faf89a7b7afb81b50f17db608b8eb8b65e8f740972391e24eea8c` |

核验范围：真实构造的 HTTP Request body 中 system/user 角色；旧 `generate(prompt)` 兼容；请求与 usage 记账；拒绝额外 `type` 的 schema；不可信决策正文归档的凭据、完成状态、大小及路径边界；prompt/wire 消息摘要；旧 v3 轨迹与 v4 导出的版本隔离。不重新评定历史 API 成绩，不验证新模型效果，不把 HTTP stub 称为在线服务。

中间提交 `31ecee345e9b5ce7120f3e0bdb2b954b6e01c593` 尚未包含此次凭据守门修复，不能登记为最终通过版本。原始反例记录未独立保存当时完整源码快照；最终复测文件明确保存了最终 HEAD 与源码 SHA。

## 2. 原始发现

### 2.1 重复键隐藏 Unicode 转义的活动凭据

模拟凭据为 `synthetic-v4-test-key-only`。返回正文使用两个解码后相同的 `reason` 键：

```json
{"action":"stop","reason":"\u0073ynthetic-v4-test-key-only","reason":"safe","vectors":[]}
```

原守门先查 raw 中的完整凭据，再 `json.loads` 后检查重序列化文本。前一检查被 Unicode 转义避开，后一检查因普通解析丢弃前一个重复键值而漏检。真实 Agent 调用 HTTP stub 后返回 `model_stopped`，并将含转义模拟凭据的原文写入归档。

原证据：[duplicate_key_probe.json](../../.iverilog-ai/v4-proxy-audit-05961407c1/duplicate_key_probe.json)。其中 `raw_guard_allows=true`、`archived=true`、`unicode_escaped_synthetic_key_in_artifact=true`。目录内原轨迹及归档仅含模拟数据，不可纳入真实 API 实验或训练数据。

### 2.2 解码后重新序列化仍可能隐藏引号或反斜线

另以包含引号、反斜线的模拟活动凭据直接检查守门函数：解码后的 `reason` 与凭据相同，但 `json.dumps` 会再次转义这些字符，导致 `secret in serialized_json` 仍为假，原守门返回允许。该原始探针结果仅在工具输出中，没有另存独立 JSON。它是对通用 Provider 凭据边界的检查，不声称实际 DeepSeek 凭据含这些字符。

修复采用 `object_pairs_hook` 拒绝任意层次的重复解码键，并直接递归检查解码后的字符串、对象键和值、列表元素；不再靠重序列化文本检查。初始轨迹与 typed observation 的同类检查也改用该字符串遍历。失败诊断只保存固定码 `duplicate_json_key` 或 `credential_in_response`，不保存错误正文或秘密片段。

## 3. 冻结后的独立复测

在唯一新目录 [v4-proxy-frozen-4c120b99c1](../../.iverilog-ai/v4-proxy-frozen-4c120b99c1/) 使用当前冻结源码、真实 Provider 请求构造和 HTTP stub 逐项执行。汇总原件为 [frozen_v4_recheck.json](../../.iverilog-ai/v4-proxy-frozen-4c120b99c1/frozen_v4_recheck.json)，各 case 子目录保留原轨迹。

| 输入 | 实际停止/校验结果 | 原文归档 | 已验证动作 / 计划执行 |
|---|---|---|---|
| 重复键覆盖 Unicode 转义模拟凭据 | `policy_error` / `duplicate_json_key` | 无 | 无 / 0 |
| 引号模拟凭据出现在解码字符串 | `policy_error` / `credential_in_response` | 无 | 无 / 0 |
| 反斜线模拟凭据出现在解码字符串 | `policy_error` / `credential_in_response` | 无 | 无 / 0 |
| 完整 JSON 但含额外 `type="json_object"` | `policy_error` / `extra_forbidden` | 有，字节与响应一致 | 无 / 0 |
| 合法 `stop` | `model_stopped`，动作通过校验 | 有，字节与响应一致 | 有 / 0，符合 stop 行为 |

五个 case 各捕获 1 次 stub HTTP 调用，Provider 请求计数各为 1；模拟 usage 均保留 prompt 7、completion 11，包括拒绝的响应。它们不是实际 token 消耗或账单。三种凭据反例的解码后轨迹也不包含活动模拟凭据。

每个请求实际 body 的角色均为 `system`、`user`：system 是固定规则，user 是状态 JSON。轨迹 `messages_sha256` 与实际 body 消息数组的规范 JSON 摘要一致；`prompt_sha256` 与组合文本预览一致。两个摘要描述不同表示，不互相替代，也不是包含 HTTP 头和全部请求参数的整包摘要。

## 4. 定向测试与兼容边界

冻结后执行下面两份测试文件：**48 passed，1 skipped，0.65 s**。跳过项为 Windows 创建目录符号链接失败，错误 1314；没有把它记为通过。此前 36 passed / 1 skipped 的初稿测试不与本次计数累加。pytest 数字来自工具执行输出，未另存 stdout 日志文件。

```powershell
# 项目根目录；每次使用仓库外的新临时目录。
$reviewTemp = Join-Path $env:TEMP ("icarus-v4-proxy-" + [guid]::NewGuid().ToString("N"))
python -X utf8 -m pytest tests/ai/test_agent_decision_v4.py tests/core/test_agent_export.py -q --basetemp $reviewTemp
```

已核验的具体边界：

- Chat 实际发送两条 `messages`；Responses 实际发送两条文本 `input` 消息。旧 `generate(prompt)` 仍保持单 user 消息或文本 input。非法角色、未类型化消息、空文本在 transport 前拒绝。这里只验证构造，不证明所有远程网关接受这种结构。
- 两条消息经过同一请求计数、thinking 配置、输出上限与有界回退路径；模拟首请求断连、第二次流式成功时，实际尝试与计数都是 2，角色保持不变。流式 usage 缺失仍是未知，不能按零费用解释。
- v4 提示词 literal 示例能通过真实 schema；顶层额外 `type` 仍 `extra_forbidden`。没有删除非法字段、修补模型输出或新增模型重试来伪造有效决策。
- 仅 JSON 可解析、无重复键、服务报告 `stop`、不超过 64000 字符/256000 UTF-8 字节、通过活动凭据检查的正文可归档。截断、超大、不可解析或结束状态未知的输出不保存原文。归档以固定相对路径独占新建，不覆盖已存在文件。
- 归档对象是 Provider 提取的最终决策文本的 UTF-8 字节，不是原始 HTTP 响应整包、头部或隐藏推理全文。`trusted=false` 和 `record_kind=untrusted_model_decision` 保存在轨迹元数据中；归档文件本身保留原文。
- 原文归档路径与 metadata 不进入下一轮 observation、oracle 或覆盖判据；归档文件不被重新读取执行。只有原正常 schema、输入、预算等校验通过后提取的动作能形成测试计划。合法 JSON 但 schema 不合法的正文可供诊断保存，却不能执行。
- 对缺少结束遥测的旧调用，归档要求与原有动作校验是两个边界：本改动没有把所有未知结束状态一概改成禁止动作，也没有把“未归档”冒充“完整响应”。现有 SSE 没有可靠 stop 遥测时，不宣称取得完整可归档正文。

准备阶段另用 Windows 目录 junction 指向本次 run 外的私有对照目录，实测 `SafePathError` 拒绝且目标目录无文件：[junction_probe.json](../../.iverilog-ai/v4-proxy-junction-03218113a4/junction_probe.json)。这是 junction 路径逃逸对照，不能替代因权限被跳过的目录 symlink 测试，也不构成并发文件系统攻击的完整证明。

## 5. v3/v4 导出隔离与残余限制

独立合成对照 [export_isolation_probe.json](../../.iverilog-ai/v4-proxy-export-f10cba3001/export_isolation_probe.json) 使用两份可通过导出筛选的 v4 fixture 和一份完整 v3 fixture：v3 被记为 `non_api_or_unknown_version`；归档 metadata 中独有的诊断 marker 未进入导出 messages。所有输入都是明确标注的合成样本，不能作为真实 API 或训练效果证据。

v4 轨迹版本为 `verification-agent-v4-typed-decisions`；导出器要求当前版本、API 记录类别、已验证动作与执行记账，输出仍是 `pending` 人工筛选候选。它不自动把新归档中的被拒绝响应当成正向训练样本。导出器不是密码学真实性验证器：此次没有证明任意外来轨迹均不可伪造，也没有核验服务商账单或训练数据质量。

活动凭据检查仅覆盖当前 Provider key 的原文及 JSON 解码字符串；不保证发现其他秘密、编码后再拼接的秘密或所有隐写形式。未对远程服务的真实完成行为、模型格式成功率、RTL 检出收益作保证。目录 symlink 权限场景仍未实际执行；完整回归、真实 v4 smoke/重复实验和真人 H02 结果必须分别登记。

## 6. 原件校验

| 原件 | SHA256 |
|---|---|
| [原重复键反例](../../.iverilog-ai/v4-proxy-audit-05961407c1/duplicate_key_probe.json) | `8623d5d6dd74098fe00a4856c14b967ba46a64ac3a539fa36c1512f37b1a2a93` |
| [最终冻结复测](../../.iverilog-ai/v4-proxy-frozen-4c120b99c1/frozen_v4_recheck.json) | `6938a1219ba8c2be8fdf1b3b3ef97e6584079b3b413e9914b346e73ab243593c` |
| [导出隔离合成对照](../../.iverilog-ai/v4-proxy-export-f10cba3001/export_isolation_probe.json) | `f6955a8097c99e2fa7774852b32f24528631fba9b5e84bc97068514c2a22c429` |
| [junction 路径对照](../../.iverilog-ai/v4-proxy-junction-03218113a4/junction_probe.json) | `0adf3b14df8bda0252108e47087119078d6494ba307f7ab47f9a2dce7ed1b76d` |

这些唯一 `.iverilog-ai` 目录只承载本次代理模拟复核，不覆盖历史原件；它们未因文档链接自动进入 Git 或发布包。原始反例中的所有凭据均为模拟值。移交复核时应保留上述说明与原件哈希，避免被误计为真实 API 请求、正式检出成绩或真人审核。
