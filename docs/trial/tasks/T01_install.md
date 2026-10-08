# T01｜安装并打开工具

标签：环境准备 / 安装角色。状态：**任务方案，尚无真人执行记录**。安装步骤于2026-10-08对齐公开代码与锁依赖。

## 参与者任务

**目标**：在自己的电脑上从提供的项目副本打开网页，判断是否具备继续试用的条件。

**前提**：组织者提供固定版本和任务，你有使用该电脑的权限。推荐Python3.12、Git、uv和Icarus/vvp，下载依赖需要网络。已有工具也要记录哪些预装；不用GPU或API密钥。开始时也检查Yosys并记录版本/未安装；需要综合检查时按复现指南2.3的固定版本命令安装。Yosys、GTKWave不是基础仿真的必需工具。

**时间盒**：15 分钟；不要求在时间盒内下载完所有依赖。任务总耗时包含下载、等待和求助，另外注明其中下载等待时间，不从总耗时扣除。

**步骤**：

1. 按[复现指南第2至3节](../../reproduce_current.md)先开启终端记录，检查并安装缺失工具，确认PATH后再从GitHub克隆并固定f7867db。已有P01-R1日志时按指南续记，不重新创建目录。记录实际Git commit、Git状态和输入校验值。如果提供的是压缩包，记录版本和包SHA-256，不能假填提交号。
2. 在新副本安装锁定依赖；不要覆盖已有试用环境或修改锁文件：

   ```powershell
   uv sync --locked --extra dev --extra ui --python 3.12 --no-python-downloads
   $installExit = $LASTEXITCODE
   "install_exit=$installExit"
   if ($installExit -ne 0) { throw '安装失败，先保留输出再求助。' }
   $trialPy = (Resolve-Path '.venv/Scripts/python.exe').Path
   & $trialPy -V
   & $trialPy -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; t=locate_tools(); print(describe_tools(t)); raise SystemExit(0 if t.can_simulate else 1)"
   "toolchain_exit=$LASTEXITCODE"
   ```

3. 记录探测到和未探测到的工具。若缺少iverilog或vvp，先按本机安装指引处理并记录协助；不要删除或改名已有工具。改用Python3.11时相应修改安装选择并记录实际环境。
4. 启动网页，保留这个终端：

   ```powershell
   & $trialPy -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
   ```

5. 在本机浏览器打开 http://127.0.0.1:8600/ 。找到“工具设置”和“使用手册”；记下你认为下一步应该做什么。后续CLI卡片中的python应使用这个项目环境，未激活时用`.venv/Scripts/python.exe`的完整路径。

**观察与证据**：记录每步实际耗时、错误原文、是否求助、帮助内容；保存工具探测输出和首次可见页面截图。请描述你如何判断“可以开始使用”，不要只写“成功”。截图中的用户名和私人路径可以遮盖，原始日志留给约定的复核人员。

**终止与支持条件**：连续3分钟找不到下一步、需要管理员权限、下载失败或环境冲突时可停止，保留输出后求助。端口占用可在记录后改8601，并同步浏览器地址。重开终端按指南续记，不覆盖首次日志。结束时在自己启动的终端按Ctrl+C，不结束其他人的服务。

---

## 任务记录

按实际情况填 `completed`（完成）、`partial`（部分完成）、`blocked`（受阻）或 `skipped`（跳过并注明原因）。完成不代表“没有求助”；另填 `prompt_count` 与 `assistance`，没有记录就不能认定为独立完成。
