# 分层证据：仿真 → 综合 → 时序 → 比特流 → 上板

更新日期：2026-09-10
实现位置：`src/iverilog_ai/core/synthesis.py`
测试：`tests/core/test_synthesis.py`（8 项）
上游工具：Yosys 0.69（WASM 版，`pip install yowasp-yosys`）

## 一、为什么要有这一层

在这之前，项目只有一种证据：**仿真**。仿真通过说明"在这组激励下行为符合期望"，说明不了这份 RTL 能不能被综合成电路。这两件事是独立的——一个模块可以仿真完全正确但不可综合，也可以可综合但行为错误。

因此引入第二个证据层，并且**把没做的层也写出来**：

| 层级 | 状态 | 谁做的 |
|---|---|---|
| 功能仿真 | 本次流水线提供 | Icarus Verilog 编译 + vvp 执行 + 结构化断言 |
| 逻辑综合 | 通过 / 失败 / 工具不可用 | Yosys `read_verilog` + `synth`（到通用门级） |
| 时序分析 | **未运行** | 需要目标器件时序库与时钟约束；本项目不提供 |
| 布局布线/比特流 | **未运行** | 需要厂商工具链（Vivado/Quartus 等） |
| 上板验证 | **未运行** | 需要实际硬件与测试装置 |

报告与网页都会渲染这张表，未做的层级显式标"未运行"，而不是留空让人误以为通过。

## 二、口径边界（写进报告免责声明）

- 综合通过**只**说明 RTL 可被 Yosys 映射到通用门级单元，不代表时序收敛、布局布线或上板可用；
- 本项目**不做时序签核**，也不给出任何频率结论；
- 综合失败是**强证据**：它说明这份 RTL 不可综合，仿真通过也改变不了这一点；
- 综合层**不参与 PASS/FAIL 裁决**。仿真裁决仍只由 Icarus + 结构化断言给出。

## 三、可核验的实测结果

### 全部参考 RTL 与缺陷 RTL

对 14 个参考 RTL + 78 个缺陷 RTL 共 **92 个变体**逐个跑综合：

| 结果 | 数量 |
|---|---:|
| 综合通过 | **92** |
| 综合失败 | 0 |
| 其它（超时/工具缺失/错误） | 0 |

这是符合预期的结论：缺陷变体是**功能**缺陷（回绕少了、位序反了、多发一位），它们都是可综合的。综合层要抓的是另一类问题——不可综合的写法。

单元统计示例（通用门级单元，非器件映射）：

| 案例 | 门级单元 | 类型数 | 主要单元 |
|---|---:|---:|---|
| `mod10_counter` | 4 | 4 | — |
| `sequence_101_overlap` | 3 | 2 | — |
| `pwm` | 5 | 3 | `$adff`×2, `$alu`×2, `$not`×1 |
| `debounce` | 9 | 7 | — |
| `traffic_light_emergency` | 12 | 6 | — |
| `simple_alu` | 20 | 10 | — |
| `uart_tx` | 29 | 10 | `$mux`×14, `$adffe`×4, `$alu`×2, `$eq`×2 |
| `spi_master` | 33 | 9 | — |
| `sync_fifo` | 34 | 10 | `$eq`×7, `$logic_not`×5, `$adffe`×4 |
| `handshake_stage` | 5 | 4 | — |
| `mux4` | 4 | 3 | — |
| `sync_reset` | 2 | 1 | — |

### 负例：这一层真的能抓到问题

用变量上界的 `while` 循环（`while (i < d)`）构造不可综合的 RTL，Yosys 明确拒绝：

```
ERROR: While loops are only allowed in constant functions!
```

测试断言这种输入必须报 `failed`、`synthesizable=False`，且五层证据表里综合那行是"失败"。没有这条负例，这一层就只是装饰。

### 一个反直觉的实测结论

`#5 q <= d;` 这种延时**不会**让 Yosys 报错——它被静默忽略，综合结果与去掉延时完全一样。这说明：

- 不能拿"综合通过"反过来当作"这段代码的时序语义被正确实现了"的证据；
- 这正是本层只声明可综合性、绝不外推时序结论的原因。

静态审查里的 `synth-delay` 规则（error 级）承担的是另一半职责：在文本层面就把可综合 RTL 里的延时标出来。

## 四、实现约束（WASM 版 Yosys 的两个坑）

1. **不能用 `-s <脚本文件>`**：WASM 版会报
   `Can't open script file ... Operation not permitted`。改用 `-p` 内联命令，RTL 路径写成**绝对正斜杠**形式（`E:/.../rtl/pwm.v`），并把子进程 cwd 固定为可执行文件所在目录——WASI 只映射那一处虚拟文件系统。
2. **不能加 `-q`**：它会把 `stat -json` 的输出一起静默掉。噪音由 Python 侧控制（日志落盘、只解析需要的片段）。
3. **ABC 工艺映射会静默中断**：进程退出码 0 但脚本不再往下执行，因此综合跑到 `synth -run begin:fine` 为止。该阶段已完成 `proc`/`opt`/`memory`/`techmap`/`simplemap`，产出的通用门级统计正是本层需要的东西。判据也据此改为"有没有拿到统计"，而不是只看退出码。

## 五、怎么用

命令行（`plan-run` 子命令）：

```powershell
python -m iverilog_ai plan-run `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --rtl rtl/simple_alu.v `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe `
  --synth
```

Python API：

```python
from iverilog_ai.core.pipeline import VerificationPipeline
result = VerificationPipeline(run_synthesis=True).run(plan, contract, rtl, out_dir, ...)
print(result.synthesis["status"], result.synthesis["cell_count"])
```

网页端：勾选「附加 Yosys 综合证据层（可选）」后再执行计划，结果区会多出分层证据表与门级单元明细。

工具缺失时状态是 `unavailable` 并给出安装提示（`pip install yowasp-yosys`），**不会**把流水线判成失败——可选证据层不该有能力影响主结论。
