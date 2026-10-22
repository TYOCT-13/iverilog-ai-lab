# 入门手册 · 安装与基本操作

适用对象：首次使用本项目，或需要在无 API 密钥的环境中验证运行流程的用户。

---

## 0. 输出文件与结果说明

工具根据验证目标生成可执行的测试计划，调用 Icarus Verilog 完成编译与仿真，再依据检查记录生成报告。AI 的自评不参与结果判定。

运行产物包括以下内容。

1. 已校验的测试计划（TestPlan，JSON）；
2. 由它生成的 testbench 与 Icarus 的编译/仿真输出；
3. 验证报告，记录期望值来源、被检查的信号及失败周期。

---

## 1. 安装与启动

首次使用需要 Git、Python、uv 和 Icarus Verilog。安装命令及 PATH 排查见[Windows 首次安装说明](../reproduce_windows_setup.md)。Yosys 用于综合，GTKWave 用于查看波形，两者都可以稍后安装。

在已经克隆的工程目录打开 PowerShell。下列目录为另一台复现电脑的工程位置；工程位于其他目录时，应修改第一行路径。

```powershell
Set-Location 'C:\Users\TYOCT\icarus-repro\P01-R2\source'
Test-Path '.\ui\app.py'

# Icarus 安装在其他位置时，改为实际的 bin 目录。
$env:Path = 'C:\iverilog\bin;' + $env:Path
uv sync --locked --extra dev --extra ui --python 3.12
& .\.venv\Scripts\python.exe -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
& .\.venv\Scripts\python.exe -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
```

`Test-Path` 应返回 `True`。工具检测会显示编译器和运行器的位置，随后启动网页。打开 <http://127.0.0.1:8600>，保留 PowerShell 窗口；按 Ctrl+C 停止服务。后面的 `python` 或 `iverilog-ai` 命令可以在另一个终端用 `uv run` 执行，也可以先运行 `.\.venv\Scripts\Activate.ps1` 激活环境。

| 现象 | 处理 |
|---|---|
| 找不到 `iverilog` 或 `vvp` | 检查安装位置和 PATH；可以分别设置 `IVERILOG_PATH`、`VVP_PATH` 为实际可执行文件路径 |
| 找不到 Yosys | 只影响综合。需要时运行 `uv pip install yowasp-yosys`，再重新检测工具 |
| `Test-Path` 返回 `False` | 当前目录不是工程根目录。先进入包含 `ui/app.py` 的目录，再检查 |

---

## 2. 命令行验证流程

```powershell
# 参考设计：应当"通过"（退出码 0）
iverilog-ai run --rtl rtl/pwm.v --testbench tb/tb_pwm.v --top tb_pwm --output-dir runs\demo-ok

# 缺陷变体：应当"被检出"（退出码 1，报告里有失败反例）
iverilog-ai run --rtl rtl/pulse_stretcher_bug_stuck_high.v `
  --testbench tb/tb_pulse_stretcher_boundary.v --top tb_pulse_stretcher_boundary `
  --output-dir runs\demo-bug

# 看报告
Get-Content runs\demo-bug\run-*\report.md -TotalCount 40
```

报告首部分为运行状态、比对情况和设计结果。运行状态记录工具是否完成执行，比对情况记录实际检查结果，设计结果给出本轮验证结论。读取结论时，还需核对期望值来源与有效检查数量。

- `运行状态：运行完成` + `设计结果：符合预期` → 这次仿真没有发现问题；
- `运行状态：运行完成（有告警）` + `设计结果：检出设计问题（N 条比对不一致）` →
  仿真已执行，输出与检查判据不一致；
- `运行状态：编译失败 / 运行失败 / 超时` + `设计结果：未得出结论（工具出错）` →
  本轮未完成有效验证。先看报告里的进程证据，再排查编译或运行问题。

报告中的 `passed` 表示无错误级失败。正常执行且检出缺陷时，该字段也可能为 `true`，不能单独用于判断设计正确性。字段说明见
[深度手册第 3 节](03_deep.md#3-运行状态与结果字段)。

---

## 3. 离线计划生成与仿真

新网页会话先选择生成方式，默认选中在线模型，再进入对应配置。打开页面不会自动请求模型。下列两种方式无需密钥，均不访问外部模型。验证离线流程时，应选择“离线模式”。

| 模式 | 启动方式 | 区别 |
|---|---|---|
| **离线模式** | 无需启动模型服务，也无需填写 API 或模型名称 | 在网页进程内按当前 DUT contract 生成激励，与调试服务同一个规则引擎 |
| **本地调试** | 先启动本地调试服务，再在网页确认服务地址；无需填写 API Key 或模型名称 | 使用相同规则引擎，通过 HTTP 回环和 JSON 协议验证接口层 |

```powershell
# 终端 A：本地规则调试服务（只监听本机、不联网、不需要密钥），可选
uv run python -m iverilog_ai.ai.debug_server

# 终端 B：网页
uv run python -m streamlit run ui/app.py --server.port 8600
```

浏览器打开 <http://127.0.0.1:8600>，按顺序操作。

1. 首次选择**离线模式**，点**进入配置**。工具设置确认生成方式后，点**前往工作台**；已有会话可直接在工具设置切换生成方式；
2. 工作台的工作方式选**验证一份 RTL**，在**选择设计 → 案例**中选一个内置案例（例如“模十计数器”；组合逻辑可选择“简单 ALU”或“四选一多路选择器”）。三个工作方式选项只在工作台出现；
3. 回到**工作台 → 运行测试**，点 **生成测试计划** → 点 **运行测试计划**；如只想运行案例自带的 testbench，可直接点 **运行示例测试**；
4. 在下方**测试结果**的**结论**和**波形**页签查看三处关键信息：
   - **期望值来源**：内置案例应显示 `reference_model`（已对齐参考模型复算）；
   - **分层证据**：仿真=通过、综合=未运行/通过、时序/比特流/上板=**未运行**；
   - **信号活动覆盖率**：信号变化情况及取值覆盖情况。

> 离线规划器是确定性规则生成器，用于无密钥条件下检查运行流程。它按当前接口生成激励，支持合约中未设置时钟与复位的组合逻辑案例，不代表在线模型的能力。

---

## 4. 回归检查

```powershell
python -m pytest -q                       # 应全部通过；数量以本次输出为准
python scripts/run_benchmark_matrix.py    # 期望 15/15、83/83、0 误报、0 不可判定
```

---

## 5. 常见问题与处理方法

| 现象 | 原因与处理 |
|---|---|
| 网页里"运行测试计划"按钮不可用 | 先生成计划；自定义 RTL 还须通过编译预检查。错误详情在上传区，修复后重新上传；更换顶层模块、宏或 include 配置后也会重新检查 |
| 上传区提示 RTL 编译预检查未通过 | 展开“查看编译错误”，按文件位置修复语法或补齐依赖；检查失败时测试计划和自动验证均暂停。检查只编译，不执行仿真、不调用模型 API，通过不代表功能或协议正确 |
| 点击按钮后一直显示正在处理 | 在线模型可能需要几十秒；若提示超时，可在工具设置中调整请求超时 |
| 长内容未完整显示 | 表格、JSON、代码与手册正文使用固定高度区域，可在对应区域内滚动查看 |
| “生成测试计划”不可用 | 自定义 RTL 要先通过“校验接口”。上传区的按钮常驻显示，端口、时钟和 JSON 默认收起，需要修改时再展开 |
| 提示 `Unknown module type` | 编译输入缺少子模块源码。应上传顶层文件及其全部依赖，并选择待验证模块为顶层；同一目录中的文件不会自动上传 |
| 显示“0项比对” | 查看编译、运行状态，再看计划是否有期望值或有效断言。只有观察记录时不能认定功能通过 |
| 结果里"期望值来源 = `ai_generated`" | 该设计没有参考模型，本轮使用 AI 生成的期望值，需进一步核对（见报告里的 advice） |
| 综合层显示"工具不可用" | 未安装 Yosys；综合未执行，不影响仿真检查 |
| 端口 8600 被占 | 停止原服务，或改用 `uv run python -m streamlit run ui/app.py --server.port 8601`，浏览器也使用新端口 |

后续文档包括**进阶手册**（自定义验证与工具配置）、**深度手册**（判据与统计口径）和**按目的手册**（行为对比、功能验证及缺陷评测）。
