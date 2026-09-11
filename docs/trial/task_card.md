# 试用任务卡（约 40 分钟）

## 先读这一段

- 你的任务不是"证明这个工具好用"，而是**如实记录你遇到了什么**。
- **卡住就是有效结果**：请记下卡在哪一步、报什么错、你期望发生什么。
  需要提示的地方说明文档写得不够好，这比一句"挺顺利"有价值得多。
- 全程**不需要** API 密钥，任务 1、2 完全离线。
- 遇到报错先看第 4 节的排查表，仍然解决不了就跳过该步继续，把问题记下来。

## 准备（约 5 分钟）

```powershell
# 1. Python 3.11 或更高
python -V

# 2. 安装本项目（在仓库根目录执行）
python -m pip install -e .
python -m pip install pytest

# 3. Icarus Verilog：Windows 用安装包 https://bleyer.org/icarus/ ，Linux 用 apt
#    装好后确认工具能被找到：
python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
```

**记录点 1**：上一条命令打印出什么？三个工具（iverilog / vvp / yosys）各找到了吗？

---

## 任务 1：复现基准结论（约 8 分钟）

**目标**：不看任何代码，只跑一条命令，判断这个工具"能不能检出已知缺陷、会不会误报"。

```powershell
python scripts/run_benchmark_matrix.py
```

它会跑 14 个参考设计与 83 个缺陷变体。结束后：

```powershell
# 看汇总
Get-Content .iverilog-ai/benchmark-matrix/matrix.md -TotalCount 40
```

**请回答**：

1. 五个汇总数字各是多少（参考通过 / 缺陷检出 / 参考误报 / 不可判定）？
2. 你相信这些数字吗？**为什么信 / 为什么不信**？（例如：你能从产物里看到逐条证据吗？）
3. 打开 `matrix.md`，随便挑一个缺陷，能看出"是哪个检查项、第几拍、期望什么、实际什么"吗？

**记录点 2**：三个问题的答案 + 命令实际耗时。

---

## 任务 2：走一遍 AI 流程（离线，约 12 分钟）

**目标**：搞清楚"AI 在这个工具里到底做了什么、没做什么"。

```powershell
# 终端 A：启动本地调试模型（只监听本机、不联网、不需要密钥）
python -m iverilog_ai.ai.debug_server

# 终端 B：启动网页
streamlit run ui/app.py
```

在浏览器打开 `http://localhost:8501`，然后：

1. 在「AI 接口设置」里选「**本地调试模型**」；
2. 选一个案例（建议「PWM」或「按键去抖」）；
3. 点「生成 AI 测试计划」，看一眼生成的 JSON —— 它长什么样？你能读懂吗？
4. 点「执行 AI 计划并生成 testbench」，等它跑完；
5. 看结果区，特别留意这三处：
   - **期望值来源**提示（写的是"参考模型复算"还是"AI 生成"？）
   - **分层证据**表（哪些层级写着"未运行"？）
   - **波形语义结论**（有没有给出具体结论，还是说"未发现"？）

**请回答**：

1. 生成一个测试计划大概花了多久？
2. 页面有没有让你困惑的地方？哪个信息你觉得找不到或者看不懂？
3. 如果让你跟同学解释"这个工具的 AI 到底做了什么"，你会怎么说？

**记录点 3**：三个问题的答案 + 你认为**最该改的一处界面**。

---

## 任务 3：拿自己的 RTL 试（约 12 分钟，需要一点 Verilog 基础）

**目标**：体验"行为级对比"——它能不能区分"行为不同"与"只是写法不同"。

1. 写一个简单模块（或从 `rtl/` 里借一个），例如：

```verilog
`timescale 1ns/1ps
module my_counter(input wire clk, input wire rst_n, input wire enable, output reg [3:0] count);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) count <= 4'd0;
    else if (enable) count <= count + 4'd1;   // 注意：没有取模，会自然回绕
  end
endmodule
```

2. 在网页切到「自定义 RTL」，上传这个文件，确认/编辑 DUT 合约（端口、时钟、复位），
   然后走一遍生成计划 → 执行；
3. 把它的行为与仓库里的 `rtl/mod10_counter.v` 对比：

```powershell
python -m iverilog_ai compare-rtl `
  --plan <刚生成的计划.json> `
  --contract examples/mod10_counter_contract.json `
  --user-rtl <你的文件.v> `
  --reference-rtl rtl/mod10_counter.v
```

**请回答**：

1. 对比结论是 `identical` 还是 `different`？你认为这个结论对吗？
2. 合约编辑那一步顺利吗？有没有你不确定该怎么填的字段？
3. 如果这个工具只能保留一个功能，你会保留哪个？

**记录点 4**：三个问题的答案 + 退出码。

---

## 4. 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `未找到 Icarus Verilog` | 工具不在 PATH 且不在常见目录 | 设环境变量：`$env:IVERILOG_PATH="D:\iverilog\bin\iverilog.exe"`、`$env:VVP_PATH="D:\iverilog\bin\vvp.exe"` |
| `ModuleNotFoundError: iverilog_ai` | 没安装或不在仓库根目录 | 在仓库根目录执行 `python -m pip install -e .` |
| 基准矩阵某条 `inconclusive` | 仿真超时或编译失败 | 把该条记录与 `.iverilog-ai/benchmark-matrix/` 下对应日志一并记下来 |
| 网页起不来 / 端口被占 | 8501 被占用 | `streamlit run ui/app.py --server.port 8502` |
| 综合层显示"工具不可用" | 没装 Yosys（可选） | `python -m pip install yowasp-yosys`，或忽略该层 |
| `streamlit` 命令找不到 | 没装 UI 依赖 | `python -m pip install -e ".[ui]"` |
| PowerShell 报执行策略错误 | 脚本被拦 | 用 `python <脚本路径>` 直接跑，不要用 `.\script.ps1` |

## 5. 交回什么

1. 填好的 `feedback_template.json`（复制一份改名，如 `feedback-你的代号.json`）；
2. 你写的那个 Verilog 文件（如果任务 3 做了）；
3. 任何截图（报错、界面困惑处）。

交回前请**不要**润色，原始记录更有价值。**不要在反馈里粘贴任何 API 密钥。**
