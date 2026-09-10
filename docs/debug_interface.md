# 本地调试模型接口（无需 API Key）

## 为什么需要它

本项目的在线模型路径过去只能在有 API Key、有网络、且服务商正常时才可测试。这带来两个实际问题：

1. **回归不可复现**：CI 和离线环境无法覆盖"在线"代码路径，只能测 MockProvider；
2. **故障难定位**：出现问题时无法区分"是流水线的 bug"还是"是模型/网关的问题"。

`debug-local` 用一个本地确定性服务填上这个缺口：它说 OpenAI 兼容协议、只监听回环地址、不联网、不需要任何凭据。

## 它是什么，不是什么

| 是 | 不是 |
|---|---|
| 一个离线、确定性、可复现的模型替身 | 任何真实模型能力的代表 |
| 用于联调、回归、故障复现和演示 | 可以写进实验结果或宣称 AI 效果的依据 |
| 由 DUT contract + 固定种子决定的计划生成器 | 会"理解"规格的推理系统 |

**真实在线模型实验必须使用 `OpenAICompatibleProvider` 请求真实服务商。** 实验报告中的 `debug-local` 数据会明确标注为离线调试数据。

## 启动

```powershell
python -m iverilog_ai.ai.debug_server
```

默认监听 `http://127.0.0.1:11434/v1`，启动后会打印：

```text
iverilog-ai-lab debug model (deterministic, offline)
listening on http://127.0.0.1:11434/v1
offline only: no outbound requests, no API key, deterministic plans
```

可选参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 只允许回环地址；传 `0.0.0.0` 会被拒绝 |
| `--port` | `11434` | 监听端口 |
| `--vector-count` | `24` | 每份计划生成的通用向量数（1–200） |
| `--seed` | `0` | 随机激励种子 |
| `--verbose` | 关 | 打印每个 HTTP 请求 |

## 接口

| 方法与路径 | 用途 |
|---|---|
| `GET /health` | 健康检查，返回 `{"status":"ok","offline":true}` |
| `GET /v1/models` | 返回 `debug-local` 与 `debug-local-invalid-json` 两个模型 ID |
| `POST /v1/chat/completions` | Chat Completions 协议 |
| `POST /v1/responses` | Responses 协议（返回 `output_text`） |

请求体里的设计名和 DUT contract 从提示词中按 `Design: <name>` 与 `DUT context: {json}` 解析，与 `plan_tests` 生成的提示词格式一致。

## 三种用法

### 1. 网页

在页面「AI 接口设置」中选择 **本地调试模型（无需密钥、不联网）**，然后正常点击"生成测试计划"、"根据失败补充测试向量"等按钮。

### 2. 实验脚本

```powershell
# 终端 1
python -m iverilog_ai.ai.debug_server
# 终端 2
python scripts/run_strategy_experiment.py `
  --project-root . `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe `
  --seeds 1 --debug-local --online-repeats 2
```

`online_ai` 策略会改为访问本地调试服务，实验报告中的端点与模型会标注为 `debug-local (offline)`。

### 3. 直接调库

```python
from iverilog_ai.ai import OpenAICompatibleProvider, plan_tests

provider = OpenAICompatibleProvider(
    endpoint="http://127.0.0.1:11434/v1",
    model="debug-local",
    wire_api="chat_completions",
    reasoning_effort=None,
    allow_network=False,   # 回环地址不需要放开出站网络
)
plan = plan_tests("覆盖复位和回绕", "mod10_counter", provider=provider)
```

## 计划是怎么生成的

`DeterministicLocalProvider` 完全依据 DUT contract 生成计划，分三步：

1. **复位向量**：contract 声明了复位信号时，先施加复位；
2. **通用激励**：按内置案例的取值表轮转，或对没有取值表的端口用固定种子随机取值。取值表的顺序经过挑选，保证计数器/状态机在一份计划内能走完状态空间并回绕；
3. **边界激励**：追加特征序列，覆盖紧急抢占、101 重叠边界、FIFO 满/空、UART 帧、复位释放等边界，并保证紧急窗口长于状态机周期，避免缺陷恰好落在正确相位上形成假阴性。

如果 contract 为输出端口声明了 `initial`，计划还会启用 `sample_before_reset`，在复位和激励之前观测一次上电初值——这是唯一能发现"初值本身不符合规格"这类缺陷的时刻。

**期望值不在这里填写。** 生成的向量只施加激励，`expected` 留空；期望值由 `core/reference_model.py` 的参考模型独立复算（见「权威预言机」一节）。这样本地调试模型无法通过猜期望值来伪造通过或失败。

## 受控故障注入

`model` 传 `debug-local-invalid-json` 时，服务会故意返回非法 JSON，用于验证严格 Schema 校验、重试上限和拒绝路径确实生效，而不是只写在文档里。

```python
provider = OpenAICompatibleProvider(endpoint="http://127.0.0.1:11434/v1", model="debug-local-invalid-json", ...)
```

`DeterministicLocalProvider` 还提供了 `invalid_json`、`empty`、`out_of_range` 三种模式，可直接在单元测试中使用。

## 安全边界

- 只绑定回环地址；`create_server("0.0.0.0", ...)` 会抛 `ValueError`；
- 不读取、不存储、不转发任何密钥；客户端即使不带密钥也会被接受，服务端返回的 `usage` 带 `debug_local: true` 标记；
- 不发起任何出站请求；
- 只服务 `KNOWN_DESIGNS` 中列出的内置案例，未知设计返回 HTTP 400，避免被当成通用模型；
- `provider._base_url` 仍拒绝非回环的明文 `http` 地址，真实服务商必须使用 `https`。

## 与其他 OpenAI 兼容网关的差异

本地调试服务对**非流式**请求（`stream: false`）正常工作。真实网关并不总是如此：

- 部分 OpenAI 兼容网关**只接受流式请求**，非流式 POST 会被对端在返回响应前直接断连，
  表现为 `Remote end closed connection without response`。
- 针对这类网关，`OpenAICompatibleProvider` 支持 `stream="auto"`：先试非流式，只有在
  连接被关闭时才自动改用 SSE 流式重试一次；认证失败、限流和格式错误**不会**重试。
- `stream=False`（默认）与 `stream=True` 分别强制单一模式。真实模型实验脚本使用
  `stream="auto"`，因此对两类网关都可用。
- SSE 响应会被拼成最终文本；流式响应通常不返回 `usage`，此时逐次记录的
  token 使用量为空，报告不会据此推断费用。

## 已知边界

用本地调试激励跑 50 个缺陷变体可以检出 47 个。剩下 3 个不是预言机的问题，而是生成式 testbench 的固有限制：

- `traffic_bug_emergency_output`：只在**时钟边沿之间**改变输入才可观测。生成的 testbench 所有激励都在时钟沿更新，因此看不到该差异（仓库内的手写 `tb/tb_traffic_light_emergency.v` 用半周期时序可以检出）。
- 另外两个同类边界缺陷同理。

这说明：**生成式 testbench 不能完全替代针对具体时序特征编写的手工 testbench**。固定缺陷基准仍以 `tb/` 下的手写 testbench 为准（当前 50/50 检出）。
