# T09｜用命令行复现一次运行

标签：安装 / CLI / 独立复核。状态：**任务方案，尚无真人执行记录**。

## 参与者任务

**目标**：只依据输入文件和命令生成新结果，说明结果与原始日志如何对应。

**前提**：在仓库根目录，`python`指向已安装本项目的环境，iverilog与vvp可用。按2026-10-08版T01安装后，未激活时把命令开头python换为`.\.venv\Scripts\python.exe`。不需要联网或API。

**时间盒**：10–12 分钟；完整矩阵或全量测试不属于本卡必做范围。

**步骤**：

1. 记录版本与环境，为本次操作生成独立输出目录名：

   ```powershell
   git rev-parse HEAD
   python -V
   python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
   $TrialRun = Get-Date -Format "yyyyMMdd-HHmmss"
   ```

2. 用仓库已有计划与接口运行一个例子，保存完整输出和退出码：

   ```powershell
   python -X utf8 -m iverilog_ai plan-run --plan examples/simple_alu_plan.json --contract examples/simple_alu_contract.json --rtl rtl/simple_alu.v --output-dir ".iverilog-ai/trials/$TrialRun/T09-plan"
   Write-Output "exit=$LASTEXITCODE"
   ```

3. 根据终端实际返回路径，打开新生成的报告、结果 JSON和一份仿真日志。指出哪项输入决定了本次测试，哪里能看到实际检查结果。
4. 再运行一组版本对比；不预先猜退出码：

   ```powershell
   python -X utf8 -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter_bug_wrap9.v --output-dir ".iverilog-ai/trials/$TrialRun/T09-diff" --print-markdown
   Write-Output "exit=$LASTEXITCODE"
   ```

5. 查看对应目录里的 `verify_diff.json` 和报告。解释退出码、运行层状态和两侧对比结论是否表达同一件事。
6. 独立复核扩展（被分配才做）：使用 T08 提供的 RTL、接口和计划，在新的输出目录运行 `plan-run`。文件若在项目外，请先复制到自己的试用目录，或由组织者明确指定受允许目录；不要复用原产物目录。记录缺失输入、路径依赖、结果差异。

**观察与证据**：命令原文、执行时目录、退出码、版本、输出路径和新生成的 JSON/日志；记录原始文件与新输入的 SHA-256。截图可辅助，不能替代原始结果。

**终止与支持条件**：命令参数、工具路径或输入缺失时保存错误再求助；不要靠编辑结果 JSON 来使其匹配。一次运行超过 2 分钟请组织者检查；输入包不完整时停止独立复现分支并列出缺项。

## 任务记录

填 `completed`、`partial`、`blocked` 或 `skipped`，另记 `prompt_count` 与 `assistance`。命令执行完成、结果与历史一致、独立复核完成分别记录；团队预演不算外部独立复核。
