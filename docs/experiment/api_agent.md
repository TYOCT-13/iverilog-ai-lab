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

请求在 HTTP 传输前计数，失败也消耗尝试；不自动重试、不自动切换流式、不接受重定向。每次输出上限默认 2048 tokens。次数和 tokens 上限不是金额封顶，输入也可能计费。运行时间预算在操作之间检查；单次 API 和仿真另有超时，不是可中断任意网络阻塞的严格进程截止时间。

CLI 的退出码 0 表示流程完成，包括“已发现反例”和“达到预算”；须结合 `stop_reason` 判断。1 表示缺少判据、执行失败等需处理状态；2 表示配置或启动错误。

## 轨迹内容

CLI 默认保存至 `.iverilog-ai/agent-runs/<新编号>/`；网页保存至 `.iverilog-ai/pipeline-ui/agent-<新编号>/`：

- `agent_trajectory.json`：提示词版本、模型标签、输入哈希、规格、预算、每次动作及其上下文、请求数、可用 token 用量、每轮摘要和停止原因。
- `round-01/` 等：原有流水线的测试计划、合约、testbench、日志、波形、结构化结果。

轨迹包含用户规格和测试输入，默认留在 Git 忽略目录。导出或上传前检查授权与私密信息。失败响应不保存原始正文；只存错误类别和可用 HTTP 状态码，不存 Authorization 或密钥。模型标签仅代表调用配置，不构成服务商身份认证。

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
