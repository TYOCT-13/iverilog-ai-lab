# T10｜API 预检与可选联调

标签：可选 / API 配置 / 预算与诊断。状态：**任务方案，尚无真人执行记录；本卡编写未调用 API**。

## 参与者任务

**目标**：判断一个模型接口是否准备好使用，区分本地预检、回环联调和真实服务调用所能证明的事情。

**前提**：CLI 环境可用；基础任务不需要密钥。组织者在发卡前标明只做 A，还是另做 B/C。详细接口说明见 `docs/experiment/api_handoff.md`。

**时间盒**：A 为 5 分钟；B 另加 5 分钟；C 另加 5 分钟。未分配的分支不要执行。

**步骤 A：不联网预检（默认任务）**：

1. 在仓库根目录运行：

   ```powershell
   python -X utf8 scripts/check_online_api.py --dry-run --cases simple_alu --repeats 1 --max-requests 1
   Write-Output "exit=$LASTEXITCODE"
   ```

2. 阅读输出，找出缺失配置、案例、计划请求数、输出 token 上限、提示词指纹。说明仅凭这些信息你认为能确认什么。
3. 可选网页观察：进入“工具设置 → 测试计划与模型”，查看“API 地址”“模型名称”“接口格式”，点击“检查配置”。不点击“读取模型列表”，不在在线模式生成计划；这些是不同操作。

**步骤 B：本地回环联调（可选，不使用远端模型）**：

1. 终端 A 运行：

   ```powershell
   python -m iverilog_ai.ai.debug_server --port 11435 --vector-count 6
   ```

2. 终端 B 运行，保存输出与产物：

   ```powershell
   python -X utf8 scripts/check_online_api.py --execute --endpoint http://127.0.0.1:11435/v1 --model debug-local --cases simple_alu --repeats 1 --max-requests 1 --simulate
   Write-Output "exit=$LASTEXITCODE"
   ```

3. 记录 `api_check.json` 的请求次数、状态与仿真目录。结束后在终端 A 按 Ctrl+C，关闭自己启动的服务。

**步骤 C：真实服务（单独分配并确认费用责任后才做）**：

1. 由凭据持有人通过本机环境管理方式注入密钥；不将密钥填进命令、反馈、截图或视频。按账户当前可用配置设置 Base URL、模型及协议。
2. 先按 `api_handoff.md` 预检；确认没有缺项且组织者已记录该次真实调用授权、服务商及账户额度限制。若密钥变量名为 `DEEPSEEK_API_KEY`，最小样本命令为：

   ```powershell
   python -X utf8 scripts/check_online_api.py --dry-run --api-key-env DEEPSEEK_API_KEY --cases simple_alu --repeats 1 --max-requests 1 --max-output-tokens 2048 --simulate
   python -X utf8 scripts/check_online_api.py --execute --api-key-env DEEPSEEK_API_KEY --cases simple_alu --repeats 1 --max-requests 1 --max-output-tokens 2048 --simulate
   ```

3. 只执行约定的单次请求。失败后不自动增加次数、不运行完整在线策略实验。请求数和 token 参数不构成金额硬上限；实际费用按账户账单另记。

**观察与证据**：脱敏预检输出、实际执行时的 `api_check.json`、分支标记、耗时与错误类别。token 用量和实付费用分别记录；没有账单就留空，不按 token 猜金额。

**终止与支持条件**：A 不完整配置是有效观察，不要求你现场买服务；B 端口冲突请组织者调整两个终端的端口；C 未明确授权、预算、凭据来源或出现首次错误时停止，不反复点击。凭据误入记录时停止录制并交由持有人处理后再继续。

## 任务记录

同一会话只填一条 T10 任务记录：按实际分配的分支填写总体 `completed`、`partial`、`blocked` 或 `skipped`，在客观结果、原因与证据中分列 A/B/C 各自做了什么。另填 `prompt_count` 与 `assistance`。未分配的 C 不算失败，A 完成也不能代替 C 的鉴权、模型可用性或真实计费验证。
