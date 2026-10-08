# 复现电脑的Icarus路径问题（2026-10-08）

参与者在对话中报告：工具探测已找到C:/iverilog/bin，但网页“运行测试计划”仍报找不到D:/iverilog/bin/iverilog.exe。这里记录代码排查和处理方法，尚未收到该参与者的完整日志、截图及复测结果，不登记成真人任务完成。

## 原因与代码修复

公开冻结代码f7867db有自动检测模块，可查环境变量、PATH和常见安装目录；网页的部分执行入口却显式传入作者电脑的D:盘路径，覆盖了自动检测。工具状态显示可用与执行时找错路径因而同时出现。这是项目代码遗漏，不是参与者没有安装Icarus。

本地修复将计划执行、示例测试、两种行为对比、修复候选验证和Agent执行六个入口统一接入检测结果。缺少编译器或vvp时先给出可操作的提示；工具设置增加“重新检测工具”，刷新工具缓存，不清空用户输入与计划。修复未自动推送到GitHub，冻结提交不因本地修改而自动更新。

## 已在f7867db开始的会话怎样继续

保留第一次报错及原来的P01-R1日志，在启动网页的终端按Ctrl+C停止自己启动的Streamlit。保持在source目录，用此前已确认的实际安装路径设置环境变量，然后重启网页；无需改源文件或切换commit：

```powershell
$env:IVERILOG_PATH = (Get-Item -LiteralPath 'C:/iverilog/bin/iverilog.exe' -ErrorAction Stop).FullName
$env:VVP_PATH = (Get-Item -LiteralPath 'C:/iverilog/bin/vvp.exe' -ErrorAction Stop).FullName
$env:Path = (Split-Path -Parent $env:IVERILOG_PATH) + ';' + $env:Path
$reviewPy = (Resolve-Path '.venv/Scripts/python.exe').Path
& $reviewPy -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
& $reviewPy -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
```

安装在其他位置时换成真实路径，不改成作者D:盘目录。环境变量仅影响当前终端及其随后启动的进程；给已经运行的服务修改父终端变量不会生效。重开终端按主指南续记并重新确认环境。已有网页计划若因重启丢失，重新生成并记录该次操作；不声称跨进程保存成功。

重新执行T02后，记录首次失败、得到的指导、环境调整和实际复测结果。若以后换成修复后的代码，另记新的commit与复测编号，不将两个版本混成一次无失败运行。r1/r2/r3资料包及已有冻结结果保留原字节。

## 作者验证范围

作者同机已运行新增路径回归、工具探测、网页行为对比、网页Agent（HTTP测试替身）和界面流程测试：59项通过（113.93秒）。类型检查发现字典展开的类型标注及Streamlit缓存方法标注问题，修正后mypy检查ui/app.py为0错误，新增路径测试再次4项通过（12.99秒），不将重复执行加成63个不同用例。不同安装目录用测试替身检查控件传入的路径；真实仿真仍来自作者的本机Icarus。上述测试不等于在参与者C:盘安装环境运行，不等于真实API实验、真人试用或独立人审通过。

检查命令（使用锁定项目环境；不请求外部模型）：

```text
python -m pytest -q tests/core/test_ui_toolchain.py tests/core/test_toolchain.py tests/core/test_ui_comparison.py tests/core/test_ui_agent.py tests/core/test_ui_smoke.py
python -m mypy ui/app.py
python -m pytest -q tests/core/test_ui_toolchain.py
```

新测试文件：[test_ui_toolchain.py](../tests/core/test_ui_toolchain.py)。主流程：[真人复现指南](reproduce_current.md)。
