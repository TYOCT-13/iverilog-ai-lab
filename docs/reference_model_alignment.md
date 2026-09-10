# 参考模型与 RTL 的逐拍对齐

更新日期：2026-09-10
实现位置：`src/iverilog_ai/core/reference_model.py`
对齐测试：`tests/core/test_reference_model_alignment.py`
当前状态：**14 / 14 个内置案例已对齐**，`SUPPORTED == AUTHORITATIVE`

## 一、为什么必须对齐

`reference_expectations` 会把参考模型的复算值当作**权威期望值**，用它覆盖 AI 给出的数字。这样 AI 就无法通过猜错期望值来"制造失败"或"掩盖失败"。

代价是：模型一旦与 RTL 差一拍，预言机就会把"参考设计通过"改写成"参考设计失败"——比没有预言机更糟。因此规则是 **对齐一个、加入一个**：

```powershell
python -m pytest tests/core/test_reference_model_alignment.py -q
```

测试把同一组向量同时喂给参考模型和 RTL，在 4 个确定性 seed 上逐拍比较全部可观测输出，要求**零差异**。另外两条断言防止"偷偷放宽"：

- `test_alignment_cases_cover_authoritative_set`：对齐用例表与 `AUTHORITATIVE` 集合必须一致；
- `test_every_supported_design_is_authoritative`：`SUPPORTED` 与 `AUTHORITATIVE` 必须相等，没对齐的设计不允许留在 `SUPPORTED` 里。

## 二、对齐测试台的口径

对齐测试台的顺序**必须与 `core/testbench.py` 生成的 testbench 完全一致**，否则会把模型"验证成"错的相位：

```
施加本拍激励 → 等时钟沿 → 沿之后 #1 采样
```

这条顺序决定了语义：**第 N 拍的采样值里已经包含第 N 拍激励的寄存器效果**。因此模型侧就是逐拍 `step(inputs)`——它返回的正是"施加 inputs 之后"的寄存器值。

踩过的坑：曾经把激励放在时钟沿**之后**施加，结果 `debounce` 的对齐"通过"了，但真实流水线里参考设计报出 25 条伪失败。判别方法是写一个对照脚本，同时用两种相位约定跑模型、拿真实 RTL 当裁判（见下节"采样相位"）。

复位也由激励驱动（而不是测试台隐式序列），这样模型与 RTL 看到的复位历史完全一致。

## 三、输入端口默认值：单一事实来源

激励经常只写本拍关心的端口，其余端口"保持上一次的值"。测试台对未赋值的输入端口只有端口初值（0），而模型有自己的默认值——两者不一致就会在参考设计上冒出伪失败。

因此 `reference_model.INPUT_DEFAULTS` 显式声明每个案例的输入默认值：

- 模型在 `step()` 入口用 `completed_inputs()` 补全；
- 实验激励生成器（`scripts/run_strategy_experiment.py`）用同一函数补全向量；
- `test_input_defaults_cover_every_input_port` 断言默认值表覆盖每个非时钟输入端口，且与 contract 的端口集合一致。

实测收益：`debounce` 参考设计的 25 条 `key_state` 伪失败归零，`reference_warn_mismatches` 从 10 → **0**。

## 四、对齐过程中发现并修掉的 8 个模型错误

| # | 设计 | 现象 | 根因 | 修法 |
|---|---|---|---|---|
| 1 | `uart_tx` | 终端拍 `tx` 早一拍上线 | RTL 写 `bit_idx<=bit_idx+1`（非阻塞）后同拍读 `frame[bit_idx+1]`，用的是**旧** `bit_idx` | 先用旧 `bit_idx` 决定本拍发什么，再推进 `bit_idx` |
| 2 | `spi_master` | `mosi`/`busy`/`done` 全体错位 | 同上的非阻塞语义：`sclk<=~sclk` 之后同拍读 `!sclk` 是旧值 | 用 `was_low` 记录旧的 `sclk`，`mosi` 取移位**之前**的 `shift[WIDTH-2]` |
| 3 | `spi_master` | `mosi` 取值位置错 | 模型取 `shift[WIDTH-1]`（移位后的新值），RTL 取 `shift[WIDTH-2]` | 统一为"移位前、`WIDTH-2`" |
| 4 | `debounce` | `key_state` 整体晚一拍 | 终端拍 RTL 三个非阻塞赋值同拍生效，模型返回了赋值前的 `state` | 终端拍直接写入 `sample/state/count` 的新值后返回 |
| 5 | `uart_tx` | — | `rst_n` 初值/默认值与 testbench 端口初值不一致 | 纳入 `INPUT_DEFAULTS` 统一口径 |
| 6 | `debounce` | 25 条参考伪失败 | 向量未列 `key_in`：测试台保持 0，模型默认 1 | `INPUT_DEFAULTS` 声明 `key_in: 0` 并补全向量 |
| 7 | `sync_reset` | — | 低有效复位端口默认电平未声明 | `INPUT_DEFAULTS` 显式给出非激活电平 |
| 8 | 全部 | 行数差一拍 | 生成式 testbench 末尾 `$finish` 少采最后一拍 | 模型序列丢弃尾部一拍，长度必须与 RTL 相等 |

## 五、能力边界（如实说明）

- 对齐测试用的是**确定性激励**（本地调试模型按案例给出的边界取值表），不是形式化等价性证明；
- 覆盖的是 contract 里声明的可观测输出端口，内部状态不做逐拍比较；
- 参数化只覆盖 contract 声明的参数取值（如 `CLKS_PER_BIT=4`、`WIDTH=8`、`COUNT_MAX=3`）；
- 未建模的设计不会进入 `AUTHORITATIVE`：`reference_expectations` 返回空字典，调用方回退为 AI 期望值并如实标注 `expectation_source="ai_generated"`。
