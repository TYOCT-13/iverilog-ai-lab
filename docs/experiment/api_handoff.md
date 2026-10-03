# API 接入与小规模验收

入口：`scripts/check_online_api.py`。它复用现有 Provider、计划校验器和 Icarus 流水线，先检查接入是否可用。默认只预检，不联网；小样本结果不能替代策略实验，也不能用来证明模型优势。现有实验的轮次、共同种子和累计检出率可以直接从原始 JSON 复算，不需要再调用模型。

## 1. 离线预检

在仓库根目录执行，Python 环境需已安装本项目：

```powershell
python -X utf8 scripts/check_online_api.py --dry-run
```

预检会显示缺失配置、案例、轮次、请求预算、输出 token 上限、提示词大小及 SHA-256。即使环境中已有联网开关和密钥，它也不会调用服务；不会创建运行目录。默认一个 `simple_alu` 案例、一轮、最多一次请求。

配置沿用项目的环境变量：

| 配置 | 来源 |
| --- | --- |
| Base URL | `--endpoint`，否则 `IVERILOG_AI_BASE_URL` / `IVERILOG_AI_ENDPOINT` |
| 模型 | `--model`，否则 `IVERILOG_AI_MODEL` |
| 密钥 | `--api-key-env` 指定的环境变量，默认 `IVERILOG_AI_API_KEY` |
| 协议 | `--wire-api chat_completions`（默认）或 `responses` |

密钥不会作为命令行参数传入。入口不自动加载 `.env`，也不会回退读取另一个密钥变量。例如凭据已经由本机环境管理器注入 `DEEPSEEK_API_KEY`，就使用 `--api-key-env DEEPSEEK_API_KEY`。服务地址和模型名应使用当前账户实际可用的配置，不从历史实验标签推断。

```powershell
python -X utf8 scripts/check_online_api.py --dry-run --api-key-env DEEPSEEK_API_KEY --cases simple_alu --repeats 1 --max-requests 1
```

## 2. 不花费模型额度的完整联调

在一个终端启动项目自带的回环调试服务：

```powershell
python -m iverilog_ai.ai.debug_server --port 11435 --vector-count 6
```

在另一个终端执行同一入口，生成计划并调用本机 Icarus：

```powershell
python -X utf8 scripts/check_online_api.py --execute --endpoint http://127.0.0.1:11435/v1 --model debug-local --simulate
```

这是确定性本地调试数据，不是真实 LLM 输出。没有密钥也能运行；退出调试终端即可停止服务。自定义 Icarus 安装可以用 `--iverilog` 和 `--vvp` 指定。

## 3. 已确认配置后的真实接入

先设置 Base URL、模型和密钥对应的环境变量，检查预检输出，再显式执行：

```powershell
python -X utf8 scripts/check_online_api.py --dry-run --api-key-env DEEPSEEK_API_KEY --simulate
python -X utf8 scripts/check_online_api.py --execute --api-key-env DEEPSEEK_API_KEY --simulate
```

第二条命令会对配置的服务产生真实请求，可能计费。本轮交付只执行了本地调试服务，未执行这一步。

入口最多允许三个案例、每个案例三轮、九次请求。增加样本必须同时明确增加预算，例如 `--cases simple_alu mod10_counter --repeats 1 --max-requests 2`。生成或仿真失败会立即停止后续样本。

## 4. 预算与失败处理

- 请求数在 HTTP transport 调用前计数，失败也消耗一次尝试；计数达到上限后不能再发送。启用预算的 Provider 拒绝重定向，避免隐含请求。
- 本入口不自动修复非法计划，不自动重试网络错误，不自动从普通请求切换为流式。若网关明确要求 SSE，可显式使用 `--stream on`；仍受同一请求预算约束。
- `--max-output-tokens` 默认 2048，会显式传给服务；包括值为 4096 时也会发送。`--timeout` 默认 60 秒，允许 1–180 秒，是单次连接/读取等待参数，不是整个进程的严格截止时间。
- **请求次数和输出 token 限制不是金额硬封顶。** 输入也可能计费，服务端需遵守输出参数；货币预算还需服务商账户侧的额度限制。报告不估造账单或价格。
- HTTP 错误只存状态码；网络或校验错误只存类别，不记录响应正文、原始异常或 Authorization。端点仅显示域名和端口，自定义路径隐藏。

## 5. 产物与交接标准

实际执行默认写入新的 `.iverilog-ai/api-checks/<UTC时间>-<随机后缀>/`。可用 `--output-dir` 指定新目录；已存在的目录会拒绝，避免覆盖历史证据。

- `api_check.json`：预检配置、提示词指纹、请求尝试数、逐次状态与可用的数字 token 用量。
- `<案例>/<轮次>/plan.json`：严格校验后的计划。返回内容若包含当前凭据，会拒绝保存。
- 开启 `--simulate` 后，同目录的 `simulation/` 保存真实流水线产物。

退出码：`0` 表示预检完成或所选小样本通过；`1` 表示已执行但生成/仿真需处理；`2` 表示配置或预算不合规。预检退出 `0` 不代表凭据有效，请同时检查 `missing`；只有实际执行成功才能证明服务可用。

交接给下一位代理时，应提供本文件、预检输出和新生成的 `api_check.json`，不要提供密钥正文。后续正式实验仍使用 `run_strategy_experiment.py`，先明确相同案例、共同轮次、刺激预算与成本口径；不要把它默认的完整在线批次当作接入测试。

自动验证覆盖：无网络预检、密钥来源隔离、超额拒绝、默认 token 上限实际发送、HTTP 请求计数、拒绝重定向、失败停止及日志脱敏，以及本地 Chat Completions / Responses 两种协议的计划生成和真实 Icarus 仿真。真实服务的鉴权、模型可用性、远端限流及实际账单尚未验证。
