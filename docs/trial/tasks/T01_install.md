# T01｜安装并打开工具

标签：环境准备 / 安装角色。状态：**任务方案，尚无真人执行记录**。

## 参与者任务

**目标**：在自己的电脑上从提供的项目副本打开网页，判断是否具备继续试用的条件。

**前提**：组织者提供同一版本的完整仓库副本、版本号和存放位置；你有使用该电脑的权限。需要 Python 3.11 或更高；下载依赖时需要网络。已预装的参与者可跳过安装，但要记录“预装”。不用 API 密钥。

**时间盒**：15 分钟；不要求在时间盒内下载完所有依赖。任务总耗时包含下载、等待和求助，另外注明其中下载等待时间，不从总耗时扣除。

**步骤**：

1. 打开 PowerShell，进入组织者给出的仓库根目录。记录操作系统、Python 版本、项目版本与开始时间：

   ```powershell
   python -V
   git rev-parse HEAD
   ```

   如果副本不含 Git 信息，抄录组织者提供的版本与包校验值，不自行填写提交号。
2. 在新的试用虚拟环境安装网页依赖。已有同名目录时，请组织者另取名称，不覆盖原环境：

   ```powershell
   python -m venv .venv-trial
   .\.venv-trial\Scripts\python.exe -m pip install -e ".[ui]"
   .\.venv-trial\Scripts\python.exe -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
   ```

3. 记录探测到和未探测到的工具。若缺少 `iverilog` 或 `vvp`，先向组织者获取本机安装指引；不要删除或改名现有工具。Yosys、GTKWave 是可选工具。
4. 启动网页，保留这个终端：

   ```powershell
   .\.venv-trial\Scripts\python.exe -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501
   ```

5. 在本机浏览器打开 `http://127.0.0.1:8501`。找到“工具设置”和“使用手册”；记下你认为下一步应该做什么。后续 CLI 卡片中的 `python` 应使用这个项目环境；未激活时可替换为上述 Python 完整路径。

**观察与证据**：记录每步实际耗时、错误原文、是否求助、帮助内容；保存工具探测输出和首次可见页面截图。请描述你如何判断“可以开始使用”，不要只写“成功”。截图中的用户名和私人路径可以遮盖，原始日志留给约定的复核人员。

**终止与支持条件**：连续 3 分钟找不到下一步、需要管理员权限、下载失败或环境冲突时停止安装操作，保留输出并求助。端口占用可在记录后改为 8502，同时更改浏览器地址。结束时在自己启动的终端按 Ctrl+C；不结束其他人的服务。

---

## 任务记录

按实际情况填 `completed`（完成）、`partial`（部分完成）、`blocked`（受阻）或 `skipped`（跳过并注明原因）。完成不代表“没有求助”；另填 `prompt_count` 与 `assistance`，没有记录就不能认定为独立完成。
