# API 驱动的自动验证 Agent

本功能继续调用现有 API，不安装本地推理模型。当前完成的是自动验证、轨迹采集与候选数据导出；没有训练模型权重，也没有自动上传任何训练数据。若后续使用服务商托管微调，须另行核实该服务的模型支持、数据格式及费用。

## 目标与边界

模型读取人工规格、接口定义、已有计划和最近一轮仿真摘要，选择追加输入序列或停止。每次动作经过结构校验，再由项目现有流水线生成 testbench、调用 Icarus 并记录结果。模型不能改 RTL、参考模型、已有计划或期望输出。

首次可从已有计划开始，也可以让 API 生成第一组激励。后续轮次会重新执行包含旧向量的完整计划，因此累计周期统计包含重复执行的旧向量，不只计算新增部分；它统计计划声明的激励周期，不是包括复位开销的总物理时钟数或代码覆盖率。

发现带独立判据的反例就停止并保留证据，不通过改期望值把失败“修成通过”。停止、预算耗尽或未发现差异，都不证明设计对全部输入正确。当前自动补测需要内置参考模型；自定义 RTL 缺少独立判据时保留第一次运行并停止，不自动把 AI 期望值当成真值。

## 网页使用

1. 启动现有网页，到「工具设置 → 测试计划与模型」选择「在线模型」，填写服务地址、模型名和密钥。
2. 在「工作台」选设计、填写验证目标；可以先生成计划，也可以直接展开「自动验证 Agent」。
3. 设置验证轮数、API 请求和累计激励周期上限，点击「启动自动验证」。
4. 查看停止原因和每轮检查数；最后一轮实际执行的结果进入原有结果、波形和证据导出区。点击「下载完整 Agent 轨迹」保存整个过程。

每次运行创建新目录。导航与同会话 rerun 保留结果；修改 RTL、接口或编译选项会清理页面上的相关旧证据，磁盘记录仍保留。设置为离线时自动验证按钮不可用；不会静默切换为本地模型。

本机可在被 Git 忽略的 `.iverilog-ai/local-api.json` 中保存 `endpoint`、`model`、`api_key_file`（绝对路径）和 `max_output_tokens`（2048–8192）。这里保存密钥文件路径，密钥正文仍在原文件中。网页只在执行操作时读取；API Key 输入框留空即可，手动输入优先。修改目标地址后，不会沿用原地址的文件密钥。

2026-10-04 已配置 DeepSeek 4.1 Flash：Base URL 为 `https://api.deepseek.com`，模型 ID 为 `deepseek-flash`。对应关系见 [DeepSeek 官方更新日志](https://api-docs.deepseek.com/updates/)。默认仍需用户主动选择在线模式和点击操作；打开网页不会发送模型请求。

## CLI：先预检

沿用 `api_handoff.md` 的环境配置：`IVERILOG_AI_BASE_URL`（或 `IVERILOG_AI_ENDPOINT`）、`IVERILOG_AI_MODEL`，以及 `--api-key-env` 指定的密钥变量。密钥不放在命令行或文档中。

```powershell
python -X utf8 scripts/run_verification_agent.py --dry-run --case mod10_counter --api-key-env DEEPSEEK_API_KEY --max-rounds 3 --max-requests 3
```

默认仅预检，不联网、不创建运行目录。检查输出中的 `missing`；预检成功不代表凭据有效。确认配置后执行：

```powershell
python -X utf8 scripts/run_verification_agent.py --execute --case mod10_counter --api-key-env DEEPSEEK_API_KEY --max-rounds 3 --max-requests 3
```

可用 `--endpoint`、`--model` 覆盖地址与模型，`--wire-api responses` 选择另一协议。需要 SSE 时显式设置 `--stream on`。`--plan` 可传已有计划；`--rtl` 可换同接口的缺陷变体；`--spec` 可提供经人工核对的规格文本。默认规格来自 `spec/<案例>_spec.md`。

密钥保存在单行文本文件时，可用 `--api-key-file 'C:\path\to\api-key.txt'` 替代 `--api-key-env`，两个参数互斥。文件不存在或内容无效时直接停止，不读取其他环境变量中的密钥。CLI 不自动加载网页的本机配置，服务地址和模型仍按显式参数或环境变量指定。

请求在 HTTP 传输前计数，失败也消耗尝试；不自动重试、不自动切换流式、不接受重定向。每次输出上限默认 2048 tokens。次数和 tokens 上限不是金额封顶，输入也可能计费。运行时间预算在操作之间检查；单次 API 和仿真另有超时，不是可中断任意网络阻塞的严格进程截止时间。

网页 Agent 沿用「工具设置」中的输出长度（最多 8192）与请求超时（最多 180 秒）。本次 DeepSeek 联调使用 8192 tokens 完成反馈补测；CLI 可显式加 `--max-output-tokens 8192 --timeout 120`。当服务明确报告输出截断时，停止原因显示 `output_truncated`，不会执行截断内容。

CLI 的退出码 0 表示流程完成，包括“已发现反例”和“达到预算”；须结合 `stop_reason` 判断。1 表示缺少判据、执行失败等需处理状态；2 表示配置或启动错误。

## 轨迹内容

CLI 默认保存至 `.iverilog-ai/agent-runs/<新编号>/`；网页保存至 `.iverilog-ai/pipeline-ui/agent-<新编号>/`：

- `agent_trajectory.json`：提示词版本、模型标签、输入哈希、规格、预算、每次动作及其上下文、请求数、可用 token 用量、每轮摘要和停止原因。
- `round-01/` 等：原有流水线的测试计划、合约、testbench、日志、波形、结构化结果。

轨迹包含用户规格和测试输入，默认留在 Git 忽略目录。导出或上传前检查授权与私密信息。失败响应不保存原始正文；只存错误类别和可用 HTTP 状态码，不存 Authorization 或密钥。模型标签仅代表调用配置，不构成服务商身份认证。

从提示词 v2 起，结构校验失败也保存可用的数字 token 用量、完成状态和校验错误代码，不保存原始响应、字段值或异常正文。v1 历史轨迹保持原样；导出器仍只接受当前提示词版本，避免将历史状态配上新版提示词。

## 为后续托管微调整理数据

先积累多个独立模块的真实 API 轨迹，再导出候选数据。例如明确把 `sync_fifo`、`uart_tx` 全部分到验证集：

```powershell
python scripts/export_agent_trajectories.py '.iverilog-ai/agent-runs/*/agent_trajectory.json' --holdout-designs sync_fifo uart_tx --output-dir .iverilog-ai/agent-datasets/round-1
```

导出器只接受当前版本、声明来自 API、且实际执行后有参考模型与检查记录的追加动作。测试替身、未执行动作、缺少独立判据、执行失败均不能作为训练效果证据。保留检出反例的记录，不把所有 PASS 当成好样本。`stop` 动作尚不导入首版训练候选，因为自动判断其停止是否合理需要额外人工标注。

输出 `train.jsonl`、`validation.jsonl` 和 `manifest.json`；每条都标为 `review_status=pending`。同一模块和变体不会被随机拆开；同一 RTL 内容跨集合会拒绝导出。不同名称但同源、同功能的近重复模块仍需人工归组。两边均有有效数据才写文件，旧数据集不覆盖。

这些文件是通用对话形式的候选记录，不是任何服务商已经验收的上传格式。人工还需检查补测是否有实际价值、标签是否正确及训练权利，再转换成目标服务要求。训练之后仍通过服务商 API 推理，不要求本机运行开源模型。

## 效果验收

正式比较应固定独立留出模块、累计激励周期、请求与 token 预算，对比固定 / 随机、单次 API 规划、API Agent，并报告发现的真实反例、误报、不可判定、无效动作、人工修改与耗时。单次接口连通或模型输出合法，只证明功能可运行，不能代替 Agent 提升效果的实验。
