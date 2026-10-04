# 决策格式 v4：独立消息与被拒绝响应的诊断证据

日期：2026-10-04。本轮先在 `.iverilog-ai/v4-prepared/` 隔离准备；主代理确认 c7bb280 正式 252 行评测完成、源码完整性检查通过后，才应用改动。代码、提示词与实验版本分别登记，旧实验原件保留。

## 改造依据

一次真实单请求诊断保存在 `.iverilog-ai/decision-format-diagnostic-20261004/`。它明确排除在能力评分外，使用 `thinking_mode=disabled`，返回 `finish_reason=stop`，usage 为 prompt 1584、completion 443、total 2027。返回正文具有顶层 `type/action/reason/vectors`，其中 `type="json_object"`。实际 `AgentDecision` 校验报 `extra_forbidden`，位置为 `type`；完整响应 SHA 为 `c9a2a235624d711716b27293f3436440b4a826ce4118109224d08c66221d820d`。

这证实该次失败包含“把传输配置复制进决策”的结构错误，不是长度截断。它不能证明所有旧实验失败都具有同一字段，也不能用单次诊断推算总体修复收益。

另一个已查明的输入问题是：v3 虽有名为 SYSTEM_PROMPT 的 Python 常量，实际 Chat body 只有一个 user 消息，系统规则与状态拼在一起。`decision_messages()` 原用于导出候选对话，并未被在线 Agent 发送。v4 将真实 API 调用改为两条明确消息。DeepSeek 官方 Chat 支持 system/user 角色；Responses 的 input message 也接受文本 content 与这两种角色。[Chat 文档](https://api-docs.deepseek.com/api/create-chat-completion/)、[Responses 文档](https://api-docs.deepseek.com/api/create-response/)

## 最小改动

provider 增加不可变的 `ProviderMessage(role, content)` 与 `generate_messages(messages)`，新路径只接受 system/user 文本消息；Chat 发送 messages 数组，Responses 发送 input 消息数组。它与旧 `generate(prompt)` 共用传输、请求计数、输出长度配置、thinking_mode 与有界流式回退。旧方法仍发送原先的单 user 消息或 Responses 文本 input，不猜测第三方协议。

Agent 对真实 `OpenAICompatibleProvider` 使用独立 system/user 消息：system 为规则，user 为规范化状态 JSON。其他 Provider 继续使用旧字符串接口。provider 在实际 HTTP 请求尝试处计算 wire messages/input 的 canonical JSON SHA256；Agent 每条决策保存 `message_format` 与 `messages_sha256`。旧 `prompt_sha256` 是组合文本预览的摘要，不能拿它冒充新 wire 消息摘要。

新提示词版本为 `verification-agent-v4-typed-decisions`。SYSTEM_PROMPT 加入可直接通过当前 AgentDecision/TestVector 校验的 append/stop JSON literal，并明确 response_format、type、json_object、role 等是接口或消息元数据，不能复制到决策。append 示例使用 `{}` 输入表示保持已有电平，避免示例端口与实际合约不一致。模型应按真实合约生成激励，样例没有新增正确性假设。

schema 保持 `extra="forbid"`，不删除非法 type、不修补输出、不回填失败决策；没有新增模型重试。模型仍只能追加激励或停止，判据、参考实现、观察与覆盖由原执行器决定。

## 完整响应的受控保存

满足下列条件的决策正文原字节，保存为 `untrusted_decisions/decision-NNN.json`，供错误诊断和将来的失败轨迹筛选：

- 最多 64000 字符、256000 UTF-8 字节，服务报告结束为 `stop`。
- JSON 可解析，每个对象内的解码键必须唯一，包括嵌套对象。活动 provider key 不出现在 raw，也不出现在递归遍历的已解码字符串键/值中；不通过重新 JSON 序列化来检查。这样能拒绝 `\u` 转义以及带 quote/backslash 的活动密钥。
- 路径完全由程序生成并受本次 output_dir 的 SafePathPolicy 限制；目录链接被拒绝，目标文件必须新建，以 exclusive open 写入，不覆盖已有文件。

每条决策保存工件相对路径、原字节 SHA256、字节数、`record_kind="untrusted_model_decision"`、`trusted=false`、结束状态与凭据检查范围。合法 JSON 但 schema 不合法的响应也能保留；后续 schema 校验仍然拒绝执行，usage 与失败代码照常记录。

该产物不进入 observation 或下一次模型状态，不作为缺陷、正确性或覆盖的裁决，也不自动当作正向 SFT 样本。现有训练候选导出器依旧要求决策通过校验并具有真实执行结果。

应用后的独立代理复核发现初版的重复键漏洞：第一个 reason 包含 Unicode 转义的活动模拟 key，后一个 reason 为 safe；普通 json.loads 丢弃前值，导致归档包含被遗漏的模拟凭据，并接受最后一个值。原复现保留于 `.iverilog-ai/v4-proxy-audit-05961407c1/duplicate_key_probe.json`，只使用模拟 key，没有真实 API 请求。修复使用 object_pairs_hook 在丢弃值之前检查每个解码键，重复键直接抛出静态错误并停止 Agent，绝不归档或执行；这个错误不能当作普通 JSON 解析失败吞掉。重复 action/reason、Unicode 等价键、嵌套字段或输入键均采用同一拒绝规则。

独立复核还发现模拟活动 key 含 quote/backslash 时，重新序列化会再次转义字符，从而漏掉明文子串。现版直接检查全部已解码字符串键/值，并在初始状态与 typed observation 的既有守门处复用同一窄检查。输入含活动 key 时零请求拒绝；观察含活动 key 时不记录该轮。决策只保留静态 `duplicate_json_key` 或 `credential_in_response` 错误码，不保存模型原文、密钥或异常详情；这仍不保证检测其他秘密或任意编码方式。

这里的凭据检查只覆盖活动 key 的原文及 JSON 解码，不保证发现其他秘密或所有编码方式。无法解析的 JSON、长度截断、超大正文、结束状态未知均不保存原文。现有 SSE 路径没有可靠的完成标记遥测，因此仅返回文本而没有 stop 标记时不宣称获得完整可归档响应；旧调用的判定不因此放宽。

## 兼容与实验边界

新路径适合本次已验证的官方 Chat API。第三方网关可能拒绝多个角色，必须明确报告失败，不能偷偷拼回 user 消息后算同一版本成功。普通 planner/review 的 generate(prompt) 仍保持原接口。覆写 OpenAICompatibleProvider.generate 的自定义子类若要改变 Agent 输出，需要适配新的 generate_messages；任意自定义 Provider 的旧方法不受此切换影响。

提示词变更后，现有导出器会拒绝 v3 轨迹，避免按新 SYSTEM_PROMPT 重建旧对话。这是版本边界，不是丢弃旧实验；旧 c7bb280 的三重复完整结果必须按原版本报告。v4 在新目录预登记策略、重复次数、请求上限、源码/输入/提示词 SHA，不能与 c7 的同名策略均值拼接，也不能选择多个版本的最佳行。

此改动改进 API 任务格式和诊断证据，不训练权重。新模式能否提高结构有效率、实际协议场景或缺陷检出率，仍要由另外登记的真实实验回答。

## 隔离验证

草稿导入器只替换当前 Python 进程中的 provider/agent 模块，读取现有回归测试；它不会应用补丁，外部网络 transport 被禁止，只允许本机测试服务器。

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 .iverilog-ai/v4-prepared/run_prepared_tests.py
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m mypy .iverilog-ai/v4-prepared/tree/src/iverilog_ai/ai/provider.py .iverilog-ai/v4-prepared/tree/src/iverilog_ai/ai/agent.py --cache-dir .iverilog-ai/v4-prepared/mypy-cache
```

覆盖真实 body 中的角色、canonical SHA、旧单消息兼容、模式字段与回退预算、literal 样例 schema、非法 type 的原文归档及拒绝执行、Unicode 转义密钥、截断/超大/不可解析/未知结束不归档、文件不覆盖、工件不进入反馈。目录符号链接测试在 Windows 缺少创建权限时明确跳过，不能记为已验证。

隔离结果：142 项通过、1 项因 Windows 1314 缺少目录符号链接权限而跳过，8.37 秒；provider/agent 两文件 mypy 通过，原两份源码 SHA 未变，JUnit 保存于草稿目录。应用前核对 baseline.json 中原源码 SHA，应用后记录新 SHA。隔离测试通过不代替应用到正式源码后的回归与独立复核。

正式源码的验证命令：

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m pytest -q tests/ai/test_agent_decision_v4.py tests/ai/test_provider_thinking_mode.py tests/ai/test_agent.py tests/ai/test_planner.py tests/ai/test_streaming_provider.py tests/ai/test_api_handoff.py tests/core/test_agent_export.py
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m mypy src/iverilog_ai/ai/provider.py src/iverilog_ai/ai/agent.py
```

应用后正常导入路径的结果：142 项通过、1 项因同一 Windows 权限限制跳过，7.94 秒；两份实际源码 mypy 通过，diff whitespace 检查无错误。JUnit 保存于 `.iverilog-ai/v4-prepared/applied-tests.xml`。本代理不调用真实 API，正式实验由主代理另外冻结并执行。

独立复核后的凭据边界修复回归：154 项通过、1 项因相同 Windows 符号链接权限限制跳过，8.66 秒；实际 provider/agent 的 mypy 通过，diff whitespace 检查通过。新增检查包含重复 action/reason、Unicode 等价键、顶层与嵌套重复隐藏值、quote/backslash 的解码字符串值与键，以及初始状态零请求拒绝、typed observation 不落盘。JUnit 另存于 `.iverilog-ai/v4-prepared/credential-guard-tests.xml`；原重复键复现与此前测试收据保留。
