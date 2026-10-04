# DeepSeek 思考模式：配置故障预跑与修复

日期：2026-10-04。此记录说明 API 请求配置与一次中断预跑，不能用来报告完整评测成绩，也不是模型权重训练结果。

## 已保存的执行事实

预跑原件位于 `.iverilog-ai/agent-comparison-v2-live-20261004/`，启动代码提交为 `598e6dcf11fef60497ac12c26642b375bc1810a9`。登记了 252 行评测，使用 `api.deepseek.com` 的 `deepseek-flash`、Chat Completions、`max_output_tokens=8192`、非流式请求；当时 provider 没有发送 `thinking` 字段。`reasoning_effort=None` 也不等于显式关闭思考，而且原 Chat 请求构造没有将这个配置发送到服务。

首轮 single 的提示词约 3776 字符，服务 usage 记录输入 1608 tokens，规格约 1666 字符，最多允许新增 12 个向量，尚无执行反馈。已保存轨迹提供以下诊断证据：

| 轨迹与请求 | 返回正文长度 | completion tokens | 结束与处理 |
|---|---:|---:|---|
| `sample-002` single 首次请求 | 未保存有效正文长度 | 8192 | `length`，拒绝执行，没有仿真轮次 |
| `sample-003` feedback 第一次请求 | 665 字符，4 个向量 | 5319 | `stop`，通过结构校验后执行 |
| `sample-003` feedback 第三次请求 | 705 字符，4 个向量 | 7661 | `stop`，通过结构校验后执行 |
| `sample-004` no_feedback 第二次请求 | 909 字符 | 3979 | `stop`，`extra_forbidden`，拒绝执行 |

`sample-009`、`sample-016` 的 single 也出现 `length` 与 8192 completion tokens。短正文同时伴随数千 completion tokens，提示词也没有接近大上下文边界，因此“计划序列本身太长”不足以解释这些现象。思考消耗输出预算是主要待验证解释；不能把所有失败归为这个原因。

当日官方文档说明默认启用思考，Chat 请求可用 `thinking.type` 显式设置 `enabled` 或 `disabled`，思考正文与回答正文分开返回。[DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)

旧轨迹只保留标量 usage，没有保存 `completion_tokens_details.reasoning_tokens`，也没有保存原始 reasoning 正文或被拒绝响应的完整 JSON。因此，我们没有直接测出某次请求的思考 token 数，也不能断定截断具体发生在哪个字段。`length` 与有效 JSON 不完整必须继续作为失败处理。`extra_forbidden` 是另一类输出结构错误：JSON object 格式不保证满足本项目的 `AgentDecision` schema，现有原件不足以定位多余字段。[DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)

主代理已中断这次预跑，原文件不追溯修改。原 `results.json` 的 `finished_at` 与 `changed_inputs` 尚为 null，全局保存计数停在 22；逐轨迹核对另有 24 个带 usage 的响应及 1 个可能在途而没有 usage 的请求。22 不是可信的最终请求总数，预算预留 25 次也不是已证实的 25 次账单。停止说明与完整性收据另存。本次不形成正式能力数字。

## 最小接口变更

`OpenAICompatibleProvider` 新增可选参数：

```python
thinking_mode: Literal["enabled", "disabled"] | None = None
```

- `None`：不发送 `thinking`，不猜测服务默认值；保留旧调用方式。
- Chat Completions 的 `enabled` / `disabled`：实际 HTTP body 添加 `{"thinking": {"type": "enabled"}}` 或 `{"thinking": {"type": "disabled"}}`。
- Responses 的非 None 值：在发请求前明确抛出 `ValueError`；本项目不把 Chat 扩展自动翻译到另一协议。Responses 使用独立的 `reasoning.effort`，原有 None 行为保留。[DeepSeek Responses 文档](https://api-docs.deepseek.com/api/create-response/)
- 其他值立即拒绝。即使调用方在初始化后修改 `wire_api`，也不能将这个字段误发到 Responses。

provider 层不依据主机名、模型名或 endpoint 自动开启或关闭思考。其他 Chat 服务只有调用方明确选择时才发送该扩展；本地 body 测试不证明第三方服务支持或遵守它。主界面新增「思考模式」控件，「自动」仅对官方 `api.deepseek.com` 的 `deepseek-flash` 明确选择关闭，其他地址和模型遵循服务默认；用户可以改为服务默认、开启或关闭。Responses 控件停用，不发送该 Chat 字段。评测 runner 通过 `--thinking-mode` 显式接入，正式运行必须记录所选模式。

Agent 轨迹与 provider 诊断记录 `thinking_mode`。轨迹另记录 `thinking_mode_source=explicit_request|not_requested`，只说明发出的配置，不声称知道服务器内部采用了哪种策略。测试 provider 不伪造真实 API 模式。日志仍不记录 API key。

此修改没有更换模型、训练权重、部署本地推理，也没有放宽模型 JSON 结构、输出截断判定或功能正确性判据。它只让 API 调用配置可控、可检查。

## 本地验证与后续边界

本轮没有调用真实 API。HTTP transport stub 检查实际发出的 body、缺省行为、非法值、Chat/Responses 排斥、切换协议防漏、轨迹配置以及凭据不落盘。现有 Agent、planner、streaming、API handoff 的相关回归一起执行：

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m pytest -q tests/ai/test_provider_thinking_mode.py tests/ai/test_agent.py tests/ai/test_planner.py tests/ai/test_streaming_provider.py tests/ai/test_api_handoff.py --basetemp .tmp-codex/deepseek-thinking-mode-tests-20261004
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m mypy src/iverilog_ai/ai/provider.py src/iverilog_ai/ai/agent.py
```

结果：106 项测试通过，10.26 秒；mypy 两个源码文件通过。没有修改预跑实验原件，没有提交 Git。

后续真实评测应使用新目录、重新冻结的源码 SHA 与运行设置，在各 API 策略中使用相同的显式模式。旧预跑不能回填成功结果，也不能与新完整实验直接拼接为能力统计。关闭思考是否降低截断和延迟，要由新的实际响应检验；它不保证结构错误消失，也不保证计划、时序或功能验证成功。
