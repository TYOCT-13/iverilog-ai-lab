# T12｜遇到工具路径问题后恢复

标签：失败情形 / 安装与 CLI / 隔离配置。状态：**任务方案，尚无真人执行记录**。

## 参与者任务

**目标**：在不破坏当前安装的情况下遇到一次不可用工具路径，依据提示恢复运行。

**前提**：T09 的正常命令已经可运行；组织者为本任务准备新的输出目录。基础分支只在单次命令中传入不存在的工具路径，不卸载 Icarus、不改全局 PATH、不删除或改名系统文件。

**时间盒**：8–10 分钟。

**步骤**：

1. 在仓库根目录打开试用专用 PowerShell，准备本次目录名并确认演练路径不存在：

   ```powershell
   $RecoveryRun = Get-Date -Format "yyyyMMdd-HHmmss"
   $UnavailableIcarus = Join-Path (Get-Location) ".iverilog-ai/trials/$RecoveryRun/unavailable/iverilog.exe"
   Test-Path -LiteralPath $UnavailableIcarus
   ```

   如果返回 `True`，停止并请组织者另选目录；不要删除它。
2. 执行一次使用该路径的命令，保存提示及退出码：

   ```powershell
   python -X utf8 -m iverilog_ai run --rtl rtl/mod10_counter.v --testbench tb/tb_mod10_counter.v --top tb_mod10_counter --iverilog "$UnavailableIcarus" --output-dir ".iverilog-ai/trials/$RecoveryRun/T12-unavailable"
   Write-Output "exit=$LASTEXITCODE"
   ```

3. 根据实际提示说明你认为问题出在哪里、是否已经得到设计结论。先写下自己的下一步，再查看手册或求助。
4. 在新输出目录恢复普通工具选择：

   ```powershell
   python -X utf8 -m iverilog_ai run --rtl rtl/mod10_counter.v --testbench tb/tb_mod10_counter.v --top tb_mod10_counter --output-dir ".iverilog-ai/trials/$RecoveryRun/T12-recovered"
   Write-Output "exit=$LASTEXITCODE"
   ```

5. 对照两次输出，记录哪条信息帮助你区分配置问题与设计问题。运行结束无需修复全局环境，本卡没有修改它。

**可选完整缺环境分支**：只有组织者准备了可销毁的虚拟机/容器并确认其中原本没有 Icarus 时才做。先记录缺失诊断，再按该隔离系统的安装指引恢复；结束后由组织者保留记录并处理隔离实例。没有隔离环境就跳过，不在真实主机卸载工具。

**观察与证据**：两条命令、两个退出码、完整错误提示与恢复后结果路径；分别记录单次配置演练还是实际隔离系统缺工具，不把前者写成“干净机器安装验证”。

**终止与支持条件**：恢复命令仍失败时停止，保留首次与恢复日志，不继续修改系统配置。任何步骤需要管理其他人的安装或正在运行的服务时立即求助，不自行处理。

## 任务记录

填 `completed`、`partial`、`blocked` 或 `skipped`，另记 `prompt_count` 与 `assistance`。记录是否能恢复，不把预设错误的出现本身算产品故障。
