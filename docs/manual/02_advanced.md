# 进阶手册 · 自定义验证与工具配置

适用对象：已完成基本运行流程，需要验证自定义 RTL，或将工具接入脚本与 CI 的用户。

---

## 1. 自定义 RTL 验证流程

1. **上传 RTL**：网页顶部进入**工作台**，工作方式选"验证一份 RTL" → **选择设计**，案例选"自定义 RTL"。同时选择顶层和子模块的源码；只上传顶层文件会缺少依赖。文件名可以与模块名不同，顶层选择框按 `module` 声明选择。不要同时上传两个定义相同模块的版本，也不要把含替身模块的 testbench 当作设计文件。
2. **校验合约（DUT contract）**：合约声明端口方向、位宽、时钟与复位。
   - 网页：上传后可以直接点蓝色的"从表格生成 JSON"和"校验接口"。**端口与时钟**、**接口 JSON 与导出**默认收起；需要修改时再展开。表格改完生成 JSON，直接修改 JSON 后可点"用 JSON 刷新表格"。两者需要手动同步，接口校验通过后才开放计划生成；修改后需重新校验。
   - 命令行：可参考 `examples/<case>_contract.json`，字段示例如下。
3. **生成计划并执行**：在**运行测试**中点"生成测试计划"，再点"运行测试计划"，与内置案例使用相同流程。

接口校验检查端口信息、时钟和复位定义；RTL 编译预检查调用 Icarus 检查实际源码及依赖。两项都需要确认。编译失败、工具缺失或超时会阻止运行测试计划和自动验证，展开编译错误查看具体位置。编译通过后仍需仿真检查功能。

以 OneWire 字节模块为例，若源码里实例化了 `one_wire_master_bit`，就要同时上传它的真实源码。选择 `one_wire_master_byte` 为顶层。修改文件名不能补齐依赖。

```json
{
  "module": "my_dut",
  "parameters": {"WIDTH": 8},
  "ports": [
    {"name": "clk",   "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "d",     "direction": "input",  "width": 8},
    {"name": "q",     "direction": "output", "width": 8}
  ],
  "clock": {"signal": "clk", "period_ns": 10},
  "reset": {"signal": "rst_n", "active_level": 0, "synchronous": false, "assert_cycles": 2}
}
```

**接口定义需要先校验**。例如把 `enable` 写成 `en`，工具会在执行前拒绝该计划，避免生成端口不匹配的 testbench。

### 编译选项

```powershell
iverilog-ai run --rtl dut.v --testbench tb_dut.v --top tb_dut `
  --include-dir ./inc --define WIDTH=16 --define SYNTHESIS
```

网页在**工具设置**的"编译选项"中有对应输入框（宏定义、include 目录，逗号分隔）。

---

## 2. 命令行入口与适用范围

| 操作目标 | 入口 | 命令 |
|---|---|---|
| 执行已有 testbench | `run` | `iverilog-ai run --rtl ... --testbench ... --top ...` |
| 根据 TestPlan JSON 生成 testbench 并判定结果 | `plan-run` | `iverilog-ai plan-run --plan ... --contract ... --rtl ...` |
| 比较候选 RTL 与参考 RTL 的行为 | `compare-rtl` | `iverilog-ai compare-rtl --plan ... --contract ... --user-rtl ... --reference-rtl ...` |
| 执行 RTL 静态审查（不执行仿真） | `scripts/review_rtl.py` | `python scripts/review_rtl.py rtl/pwm.v` |

退出码供脚本判断执行结果：`run` → 0 通过 / 1 有失败；`plan-run` → 0/1，输入问题 2；
`compare-rtl` → **0 一致 / 1 不同 / 2 无法判定**。

---

## 3. 结构化断言的配置与语义

测试计划里可以带五种受限模板（**不接受自由 Verilog/SVA 代码**）：

网页生成计划时，最终的断言列表来自**断言与综合**输入框，会替换模型返回的 `assertions`。该框为空时，计划可能仍有向量期望值，但不会保留模型自行生成的断言。要求某项必须检查时，要核对生成计划和最终断言列表。

| 模板 | 用途 | 字段 |
|---|---|---|
| `signal_equals` | 该信号在**整个采样序列**里都等于某值 | `signal`, `value` |
| `signal_stable` | 连续 N 拍保持不变（N 至少 2；N=1 恒真，等于没有检查） | `signal`, `cycles` |
| `never_high` | 整个序列里从未为高 | `signal` |
| `signal_sequence` | 采样序列正好等于给定的取值序列 | `signal`, `values`（`cycles` 可省略，省略时等于 `values` 长度） |
| `signal_implies` | when 条件成立后，within N 拍内 then 成立 | `when_signal`, `when_value`, `then_signal`, `then_value`, `within_cycles` |

> `signal_implies` 使用 when/then 两个信号名，不接受额外的 `signal` 字段。字段定义见 `ai/schema.py`，提示内容与解析校验共用该定义。

> `signal_implies` 应明确填写 `when_value` 与 `then_value`。省略时默认值为 `None`，无法与正常采样值匹配，可能造成无有效检查的断言。

> 采样值是 Verilog 位串（`'0000'`），断言中的 `value` 可填写整数（`0`），比较按值
> 进行，`'0000'` 与 `0` 相等；`x`/`z` 是不定值，只与同形的不定值相等，不会作为 0 参与比较。

**断言按该信号的整个采样序列判定**，没有作用域概念，因此只有全局不变量
（"永不为高"、"始终等于某值"、"req 之后必有 ack"）才适合写成断言。配置前需确认该性质在
整个采样序列中均应成立。当前没有通过参考设计检查的默认推荐项，新增条件见
`src/iverilog_ai/core/rule_assertions.py`。

---

## 4. 波形分析与 GTKWave 配置

页面**不依赖 GTKWave**：`core/vcd.py` 自带 VCD 解析，可提供时间范围、信号数和变化次数，
边沿统计、毛刺型不稳定、晚/早一拍相位检查，以及"失败周期对应的波形时间窗"。

在**工作台 → 测试结果 → 波形**中，可以进行以下操作：

| 操作 | 功能 | 说明 |
|---|---|---|
| **选择时间范围** | 按当前 VCD 的时间范围展开两个输入框 | 纯 Python 解析，不调用任何外部程序 |
| **读取波形** | 解析该时间窗内的变化，显示变化次数、涉及信号数量和变化列表 | 页面和下载的 JSON 均最多保留 2000 条变化记录；完整波形请下载 VCD |
| **用 GTKWave 打开** | 以独立进程启动 GTKWave 并打开这份 VCD | 可选人工复核；启动失败时显示已检查的路径 |

这三个按钮位于同一个 `@st.fragment`，点击时只重跑波形区域。

GTKWave 的路径按"**工具设置页手填 → 环境变量 `GTKWAVE_PATH` → PATH → 常见安装目录 →
从 iverilog 安装位置推断**"的顺序解析。Windows 环境还可通过最后一种方式定位：Icarus 官方安装包
把 GTKWave 放在同级 `gtkwave\bin\` 下，因此，已定位 Icarus 时通常也可推断 GTKWave 路径。

```powershell
# 方式一：工具设置 → 「波形查看器（GTKWave）」→ 填完整路径 → 点「自动检测」清空并重新探测
# 方式二：环境变量（重启页面后生效）
$env:GTKWAVE_PATH = "D:\iverilog\gtkwave\bin\gtkwave.exe"
```

> GTKWave 缺失不影响 Icarus/vvp 的仿真检查。独立波形查看用于人工复核，页面内仍可解析 VCD。

---

## 5. RTL 静态审查的输出与限制

「规则审查」页的静态审查**只读 RTL 文本**，不跑仿真、不做综合与时序分析。审查结果记录
代码是否命中已知规则；功能是否正确需要仿真检查。审查表有六列。

| 列 | 含义 |
|---|---|
| 规则ID | 英文稳定标识（如 `blocking-in-sequential`），可用于问题反馈及规则检索；规则表在 `core/static_review.py` 的 `_RULE_REGISTRY` |
| 严重度 | 错误 / 警告 / 提示（机器值仍是 `error` / `warn` / `info`） |
| 行号 | 命中的行（文件级提示固定为第 1 行） |
| 问题 | 中文问题描述 |
| 建议 | 中文修改建议 |
| 代码片段 | 命中的那一行原文 |

评分为按严重度加权扣分的 100 分制参考值（error 20 分、warn 5 分、info 1 分），
不是功能正确性结论；同一节还给出命中条数分布、文件 sha256（用于标识被审查的源码版本）、
44 条规则的完整清单与出处，以及 Markdown/JSON 导出。

### 5.1 规则结果与 AI 修复建议

静态审查分两层，页面上也分栏显示：

| 层 | 生成方式 | 性质 |
|---|---|---|
| **事实层**（命中表、评分、sha256） | 44 条**确定性规则** | 可复现、参与评分、逐条配正反例；**AI 无权修改** |
| **建议层**（AI 复核与修复建议） | AI（或离线时的规则表） | 排优先级、标注疑似误报，并提出未被规则命中的可疑问题；**不改命中、不参与评分** |

在「规则审查」中点「生成修复建议」后，依据**工具设置 → 测试计划与模型 → 生成方式**的选择：

- **在线模型**：真实模型复核。会消耗一次请求；输出若不合法，会把拒绝原因发回并重试一次。
  它会给出处理优先级（必须改 / 建议改 / 可选）、**疑似误报候选**（明确标注"仅候选，
  命中与评分不变"）、以及**额外怀疑**（明确标注"未经规则验证"）。AI 引用的规则 ID 必须真实存在，
  否则该条被丢弃并在元信息里记录（幻觉防护）。
- **离线模式**：不调用任何模型，直接按严重度排序并复用规则表自带的建议文本，
  提示语明确写着"**非 AI**"。
- **本地调试**：请求发送至回环地址上的 `debug_server`，它用确定性规则回答同一套
  Schema（自报"非 AI 输出"）；用于在无凭据环境中验证含 HTTP 交互的完整流程，
  不代表任何模型能力。

**发送内容**与《开源及第三方资源使用清单》一致。

- 默认只发**结构化字段**：规则 ID、严重度、行号、规则名、命中的信号名 + 44 条规则目录；
  **不含任何 RTL 源码文本**，也不发文件路径。
- 勾选「同时发送相关代码片段」后，额外发送**命中行的单行片段**（≤200 字符）。
  这个选项默认关闭，页面上有独立说明。

建议层记录对应源码的 SHA256；源码发生变化时，页面提示建议对应上一版本，
导出的 JSON 里 `ai_advice` 与事实层也分开存放，不会互相覆盖。

---

## 6. 批量与回归

```powershell
# 全量测试（含真实跑 Icarus 的端到端用例）
python -m pytest -q

# 固定矩阵：15 参考 + 83 缺陷，逐项实跑，产出 JSON/Markdown
python scripts/run_benchmark_matrix.py

# 综合矩阵：98 个变体逐个跑 Yosys（未装会明确报 unavailable）
python scripts/run_synthesis_matrix.py

# 离线 AI 路径矩阵：15 个案例逐个"规划 → 生成 testbench → 判决"
python scripts/run_pipeline_matrix.py
```

产物都在 `.iverilog-ai/<矩阵名>/` 下，`matrix.json` 用于程序处理，`matrix.md` 用于人工阅读。

---

## 7. CI 集成

```yaml
- run: python -m pip install -e . pytest mypy yowasp-yosys
- run: python -m pytest -q
- run: python scripts/run_benchmark_matrix.py      # 缺陷检出回归
- run: python scripts/run_pipeline_matrix.py       # AI 路径回归
- run: python -m mypy && python scripts/check_dead_code.py && python scripts/strip_bom.py --check
```

CI 需要 Icarus：Linux `apt-get install iverilog`，Windows `choco install iverilog`，
或设 `IVERILOG_PATH` / `VVP_PATH`。项目自带的
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) 提供了现有 CI 配置。

---

## 8. 在线模型配置

```powershell
$env:IVERILOG_AI_API_KEY = "sk-..."        # 只走环境变量，不写入任何文件
$env:IVERILOG_AI_ALLOW_NETWORK = "1"       # 网络请求需要显式允许
```

新网页会话默认选中**在线模型**，点**进入配置**后填写**API 地址 / 模型名称 / API Key**；已有会话从**工具设置 → 测试计划与模型**切换。可先点"检查配置"（不调用模型），再点**前往工作台**。离线和本地调试模式不显示在线API配置；切换回来时保留当前会话中已填的配置。

**API 使用约定**：密钥不进仓库、不进报告、不进日志；超时/限流不自动重试（避免放大费用）；
内置案例使用已对齐的参考模型复算期望值，AI 数字只作诊断。自定义设计没有参考模型时，可能使用 AI 给出的期望值，需要人工核对。

### 输出长度与用量

**输出长度上限（token）**限制单次回复的生成长度，不限制输入上下文，也不代表整个 Agent 的累计用量。未配置本机预设时默认为 4096；已配置预设时使用预设值，可按计划大小调整。勾选**不设置输出 token 上限（使用服务端默认）**后，普通计划生成和 Agent 都省略 API 请求中的输出长度参数；服务商仍可能限制长度。取消勾选后恢复滑块设定的上限。

累计用量应查看每次请求的输入和输出，并保留未知用量。Agent 的请求次数、轮数和仿真周期是不同的预算。事前登记的实验批次如有 token 总预算，需按实验账本控制，不能靠输出长度滑块保证。

### 验证目标的填写与作用

验证目标会发送给在线规划器和 Agent，但它是规划方向，系统目前不会逐条证明文字要求都已落实。写完目标后检查计划是否包含相应的输入过程和输出检查。修改目标需要重新生成计划，运行旧计划不会自动更新。

例如“FIFO 满时拒绝写入，原有数据不能被覆盖”，需要先填满，再尝试额外写入，随后读取并检查原数据顺序。只有一个名为“满写测试”的向量，不能说明这个要求已被检查。

---

## 9. 验证结果的复核要求

1. 使用边界 testbench，覆盖正常流程之外的行为；仓库中的 `tb/tb_<case>_boundary.v` 可作为参考；
2. 优先使用参考模型或人工确认的判据提供期望值；AI 生成的期望值需独立核对；
3. 检查信号活动覆盖率：取值覆盖较低时，应评估激励是否充分（实测弱激励下同一个计数器取值覆盖只有 6%）；
4. 把 `report.md`、`result.json`、`waveform.vcd` 一起归档，核对三者是否对应同一次运行。
