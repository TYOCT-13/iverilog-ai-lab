# 静态检查规则清单

更新日期：2026-09-10
规则总数：**44**（error 4 / warn 27 / info 13）
事实来源：`src/iverilog_ai/core/static_review.py` 的 `_RULE_REGISTRY`。本文由脚本从注册表生成，避免"代码改了文档没改"。

## 一、规则分组

### 可综合性：明确的综合陷阱（error/warn）

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `synth-delay` | error | 可综合 RTL 中出现 `#delay` | lowRISC Verilog 风格指南 / 通用综合实践 |
| `initial-block` | warn | 设计文件中的 `initial` 块 | lowRISC Verilog 风格指南 / FPGA 综合实践 |
| `real-type` | warn | 使用 `real`/`shortreal` 类型 | IEEE 1364 综合子集 |
| `time-type` | warn | 使用 `time` 类型 | IEEE 1364 综合子集 |
| `event-type` | warn | 使用 `event` 类型 | IEEE 1364 综合子集 |
| `fork-join` | warn | 使用 `fork`/`join` 并行块 | IEEE 1364 综合子集 |
| `wait-statement` | warn | 使用 `wait` 语句 | IEEE 1364 综合子集 |
| `disable-statement` | warn | 使用 `disable` 语句 | IEEE 1364 综合子集 |
| `while-loop` | warn | 使用 `while` 循环 | IEEE 1364 综合子集 |
| `forever-loop` | warn | 使用 `forever` 循环 | IEEE 1364 综合子集 |
| `repeat-loop` | warn | 使用 `repeat` 循环 | IEEE 1364 综合子集 |
| `system-task-file-io` | warn | 使用 `$fopen`/`$readmemh` 等文件 IO | IEEE 1364 综合子集 |
| `system-task-time` | warn | 使用 `$time`/`$stime`/`$realtime` | IEEE 1364 综合子集 |
| `system-task-display` | info | 设计文件中出现 `$display`/`$write` | lowRISC Verilog 风格指南 |
| `division-operator` | warn | 使用除法或取模运算符 | FPGA 综合实践 |
| `real-division` | warn | 对非 2 的幂常量做截断除法 | 通用 RTL 实践 |

### 时序与复位

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `blocking-in-sequential` | warn | 时序 `always` 块中使用阻塞赋值 | lowRISC Verilog 风格指南 / 通用 RTL 实践 |
| `non-blocking-combinational` | warn | 组合 `always` 块中使用非阻塞赋值 | lowRISC Verilog 风格指南 / 通用 RTL 实践 |
| `incomplete-sensitivity` | warn | 显式组合敏感列表可能不完整 | lowRISC Verilog 风格指南 / 通用 RTL 实践 |
| `async-reset-no-sync` | warn | 使用异步复位但没有明显同步器（每文件一条） | ZipCPU wb2axip / 通用 CDC 实践 |
| `reset-polarity-mixed` | warn | 同一模块混用高有效与低有效复位 | lowRISC Verilog 风格指南 |
| `clock-in-always-sensitivity` | warn | 时钟出现在敏感列表但未作为边沿 | 通用 RTL 实践 |
| `reset-in-data-path` | warn | 复位信号出现在时钟 `always` 的数据路径条件中 | 通用 RTL 实践 |

### 组合逻辑与锁存器

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `inferred-latch` | error | 组合 `always` 块存在未赋值路径（推断锁存器） | 通用 RTL 实践 / FPGA 综合实践 |
| `missing-default-case` | warn | `case` 语句没有 `default` 分支 | lowRISC Verilog 风格指南 / 通用 RTL 实践 |
| `incomplete-case-assignment` | warn | `default` 分支为空、没有赋值 | 通用 RTL 实践 |
| `comb-loop` | warn | `always` 块内存在看似自身的组合反馈 | 通用 RTL 实践 |

### 多驱动与时钟域

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `multiple-procedural-drivers` | error | 信号在多个过程块中被赋值 | 通用 RTL 实践 / verilog-axi 接口约定 |
| `mixed-block-assignment` | error | 同一信号同时用阻塞与非阻塞赋值 | 通用 RTL 实践 |
| `missing-async-reg` | info | 疑似同步器寄存器缺少 `ASYNC_REG` 属性 | Xilinx/Intel 厂商 CDC 指南 / ZipCPU wb2axip |

### 位宽与常量

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `width-truncation` | warn | 赋值右侧常量超出左侧位宽（会被截断） | verilog-axi 位宽约定 / 通用 RTL 实践 |
| `unsized-literal` | info | 未指定位宽的常量赋给窄信号 | lowRISC Verilog 风格指南 |
| `parameter-no-default` | info | `parameter` 未给出默认值 | 通用 RTL 实践 |
| `localparam-missing` | info | 状态编码使用 `parameter` 而非 `localparam` | lowRISC Verilog 风格指南 |

### 接口与可读性

| 规则 | 级别 | 说明 | 来源 |
|---|---|---|---|
| `missing-timescale` | info | 文件缺少 `` `timescale `` 指令（每文件一条） | lowRISC Verilog 风格指南 |
| `missing-port-direction` | warn | 端口没有声明方向 | 通用 Verilog 语法要求 |
| `non-ansi-port-list` | info | 使用非 ANSI 端口列表 | lowRISC Verilog 风格指南 / SystemVerilog 实践 |
| `long-line` | info | 行宽超过 120 字符（每文件一条） | lowRISC Verilog 风格指南 |
| `trailing-whitespace` | info | 行尾有多余空白（每文件一条） | lowRISC Verilog 风格指南 |
| `tab-indent` | info | 使用制表符缩进（每文件一条） | lowRISC Verilog 风格指南 |
| `floating-net` | warn | 声明了 `wire` 但从未被驱动（每文件一条） | 通用 RTL 实践 |
| `unused-signal` | info | 信号被声明但未使用 | lowRISC Verilog 风格指南 |
| `empty-port-connection` | info | 实例化时存在空端口连接 | lowRISC Verilog 风格指南 |
| `generate-no-label` | info | `generate` 块缺少标号 | lowRISC Verilog 风格指南 |

## 二、怎么保证规则是真的在工作

每条规则都必须在 `tests/core/test_static_review_rules.py` 的用例表中出现，并配一个**最小反例**（必须命中）与一个**最小正例**（必须不命中）。测试还会断言注册表与用例表一一对应，防止"加了规则不加测试"。

```powershell
python -m pytest tests/core/test_static_review_rules.py -q
```

当前状态：44 条规则全部有用例，47 项断言全部通过。

## 三、噪声校准记录

规则集一开始对仓库内 84 个 RTL 文件报出 317 条命中，其中包含会严重误导报告的误报。逐条核实后修掉了这些：

| 现象 | 根因 | 处理 |
|---|---|---|
| `division-operator` 84/84 全命中 | 正则把 `*/` 注释结尾与换行空白当成除法 | 收紧为"操作数 / 操作数"形态，并跳过 `` `timescale `` 行 |
| `inferred-latch` 15 条 error | 启发式把"有 default 的 case""begin 后无条件赋值"误判为锁存器 | 改为分支覆盖分析：只有确认存在未赋值路径才报 |
| `missing-timescale` 84/84 | 注释剥离把 `` `timescale `` 一并吃掉 | 在未剥离的原文上检查；并给 `rtl/` 全部补齐 timescale |
| `async-reset-no-sync` / `missing-async-reg` 从不命中 | 时钟/复位名只匹配前缀（`rst*`），而实际命名是后缀（`rst_n`） | 改为"捕获完整标识符 + 判断是否含 rst/clk 词元" |
| `for-no-begin` 误报合法单语句循环 | 单语句 `for` 循环体本就是合法写法 | 删除该规则（无法可靠区分漏写 begin 与合法写法） |
| 风格规则刷屏 | 逐行重复报告同类问题 | 标记 `once_per_file`，文件级提示每文件只保留一条 |

校准后：84 个 RTL 文件共 163 条命中、**0 条 error**（参考设计与缺陷变体都不应触发 error 级规则）。
`tb/` 目录的测试平台不再触发 `synth-delay`（延时是测试平台的正常写法）。

## 四、能力边界（如实说明）

- 这是**保守的 lint 式静态检查**，不是综合、时序或形式验证的替代品；
- 规则基于文本与轻量结构分析，不做完整 Verilog 语法树解析，因此对宏展开、`generate` 内动态结构、跨文件实例化的判断能力有限；
- 判定策略是"宁可漏报也不误报"：解析不出来的结构一律不报；
- 报告会显式声明这一点，网页与 CLI 输出都带同一句免责声明。
