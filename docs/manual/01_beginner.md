# 入门手册 · 15 分钟跑通

面向：**第一次接触本项目**、或需要在没有 API 密钥的机器上验证它能不能跑的人。

---

## 0. 你会得到什么

一句话：**把"帮我测一下这个电路"变成可执行的测试**，最后由开源仿真器 Icarus Verilog 给出
判决，而不是由 AI 说"我觉得通过了"。

跑完这一页，你会看到三样东西：

1. 一个已校验的测试计划（TestPlan，JSON）；
2. 由它生成的 testbench 与 Icarus 的编译/仿真输出；
3. 一份报告，写明**期望值是谁给的**、**检查了哪些信号**、**失败在第几拍**。

---

## 1. 安装（约 3 分钟）

```powershell
cd E:\FPGA_WORK\iverilog-ai-lab
python -m pip install -e .            # 离线环境加 --no-build-isolation
python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
```

最后一条会打印 `iverilog=... vvp=... yosys=...`。

| 现象 | 处理 |
|---|---|
| `iverilog=None` | 装 Icarus Verilog，或设 `$env:IVERILOG_PATH="D:\iverilog\bin\iverilog.exe"` |
| `yosys=None` | 可选（综合层）：`python -m pip install yowasp-yosys` |
| `pip install` 报 setuptools | 加 `--no-build-isolation` |

---

## 2. 命令行跑一次（约 2 分钟）

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

**怎么看结论**：报告首部把三层分开写——`运行状态`（工具跑完了吗）、`比对情况`
（逐项检查对上了几条）、`设计结果`（这份设计到底对不对）。**判设计对不对只看"设计结果"。**

- `运行状态：运行完成` + `设计结果：符合预期` → 这次仿真没有发现问题；
- `运行状态：运行完成（有告警）` + `设计结果：检出设计问题（N 条比对不一致）` →
  **仿真是通的，但电路行为和期望不一致**，这就是"缺陷被检出"的正常样子；
- `运行状态：编译失败 / 运行失败 / 超时` + `设计结果：未得出结论（工具出错）` →
  是**工具**出了问题，不是设计被判错了，看报告里的进程证据。

注意报告里还有一个 `passed` 字段（比对层，含义是"无错误级失败"）：**检出缺陷的正常运行里
它也是 `true`**，所以不要用它判断设计正确性。三层的完整读法见
[深度手册第 3 节](03_deep.md#3-四个字段分三层读不要混着看)。

---

## 3. 走一遍 AI 路径（不需要密钥，约 5 分钟）

离线模式有两种，都不需要密钥、都不联网：

| 模式 | 怎么跑 | 差别 |
|---|---|---|
| **离线模式**（网页默认） | 什么都不用启动 | 在网页进程内按当前 DUT contract 生成激励，与调试服务同一个规则引擎 |
| **本地调试** | 先起下面的调试服务，再在网页里选它 | 同一引擎，但经 HTTP 回环 + JSON 协议，顺带验证接口层 |

```powershell
# 终端 A：离线调试模型（只监听本机、不联网、不需要密钥）——可选
python -m iverilog_ai.ai.debug_server

# 终端 B：网页
streamlit run ui/app.py
```

浏览器打开 <http://127.0.0.1:8501>，按顺序：

1. 顶部进入**工作台**，工作方式选**验证一份 RTL**，在**选择设计 → 案例**中选一个内置案例（例如"模十计数器"；想试组合逻辑就选"简单 ALU"或"四选一多路选择器"）；
2. 进**工具设置 → 测试计划与模型**，**生成方式**保持默认的"离线模式"；
3. 回到**工作台 → 运行测试**，点 **生成测试计划** → 点 **运行测试计划**；如只想运行案例自带的 testbench，可直接点 **运行示例测试**；
4. 在下方**测试结果**的**结论**和**波形**页签查看三处关键信息：
   - **期望值来源**：内置案例应显示 `reference_model`（参考模型复算，最可信的一档）；
   - **分层证据**：仿真=通过、综合=未运行/通过、时序/比特流/上板=**未运行**；
   - **信号活动覆盖率**：哪些信号动过、取值覆盖多少。

> 离线规划器只是**确定性规则生成器**，不代表任何真实模型的能力；它的用途是让没有密钥的人
> 也能把整条链路跑通。它按合约里真实存在的端口生成激励，因此组合逻辑案例（合约中没有时钟、
> 没有复位）同样可用——早期版本这里接的是一份写死的演示计划（固定驱动 `rst_n`），
> 在组合逻辑案例上会报 `vectors[0].inputs contains unknown port 'rst_n'`。

---

## 4. 每次都能这样验证（约 1 分钟）

```powershell
python -m pytest -q                       # 应全部通过；数量以本次输出为准
python scripts/run_benchmark_matrix.py    # 期望 15/15、83/83、0 误报、0 不可判定
```

---

## 5. 卡住了怎么办

| 现象 | 原因与处理 |
|---|---|
| 网页里"运行测试计划"按钮不可用 | 先点**生成测试计划**；执行依赖已校验的计划 |
| 点击按钮后一直显示正在处理 | 在线模型可能需要几十秒；若提示超时，可在工具设置中调整请求超时 |
| 某块内容很长，看不到结尾 | 长内容都在固定高度的框里，**框内滚轮**即可（表格、JSON、代码、手册正文都是） |
| 提示先上传 RTL 或校验接口 | 你选了"自定义 RTL"，需要先上传文件、确认接口定义，再点"校验接口" |
| 结果里"期望值来源 = `ai_generated`" | 该设计没有参考模型，这一轮用的是 AI 数字，结论可信度较低（见报告里的 advice） |
| 综合层显示"工具不可用" | 没装 Yosys，属正常，不影响判决 |
| 端口 8501 被占 | `streamlit run ui/app.py --server.port 8502` |

下一步：**进阶手册**（把工具接进你自己的流程）、**深度手册**（判据与口径）、
**按目的手册**（只想对比 RTL / 想做缺陷评测）。
