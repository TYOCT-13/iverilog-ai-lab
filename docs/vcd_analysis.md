# 波形（VCD）语义分析

更新日期：2026-09-10
实现位置：`src/iverilog_ai/core/vcd.py`
测试：`tests/core/test_vcd_insights.py`（11 项）
真实缺陷验证：`.dsh-tmp/verify_vcd_insights.py`、`.dsh-tmp/verify_waveform_semantics.py`

## 一、为什么要有这一层

流水线里 Icarus 的 PASS/FAIL 是**唯一裁决**，VCD 分析只做一件事：把"哪条断言失败在第几拍"这类难以阅读的信息，翻译成可核对的波形事实——**边沿、稳定性、相位、双波形差异、失败周期对应的时间窗**。它不参与判分，报告里带显式免责声明。

## 二、能力清单

| 能力 | 函数 | 输出 |
|---|---|---|
| 单信号沿序列 | `signal_edges` | `initial/rise/fall` 序列，`x`/`z` 会清空"上一个已知值" |
| 毛刺型不稳定 | `signal_stability` | 不稳定时间窗、最短间隔、该信号常规节奏 |
| 相位检查（晚/早一拍） | `detect_phase_violations` | `ok` / `late` / `early` / `unobservable` / `not_applicable` |
| 结论汇总 | `waveform_insights` | 结论行、边沿统计、稳定性表、相位表 |
| 双波形差异 | `compare_waveforms` | `edge_count` / `timing` / `value` 三类差异 |
| 失败周期时间窗 | `analyze_failure_windows` | 周期 → 时间窗 → 窗口内 VCD 片段 |

接入点：`VerificationPipeline` 在仿真后调用 `waveform_insights`，结果写入 `vcd_analysis["insights"]`；`report.py` 渲染四个章节；`ui/app.py` 提供同类视图与 JSON 下载。

## 三、毛刺判据是怎么定的（三轮校准）

第一版判据是"窗口内翻转多次即不稳定"。它在真实波形上**全是误报**：

| 轮次 | 判据 | 反例 | 结论 |
|---|---|---|---|
| 1 | 10 ns 窗口内翻转 ≥2 次 | `dut_i.clk`（每 5 ns 必然翻转）、`count`（每拍递增）、`busy` | 时钟与计数器被大面积误报 |
| 2 | 间隔 < 全局中位数的 1/3 | `busy` 的 10 ns 窄脉冲 vs 170 ns 空闲 | 单次窄脉冲是**正常**波形，仍误报 |
| 3 | 间隔 < 常规节奏的 1/3 **且连续 ≥3 个** | — | 计数器、时钟、脉冲、双峰节奏全部不再误报 |

第 3 版的两条附加规则来自实测：

- **复位沿不参与统计**：异步复位把 `count` 直接清零，会在复位时刻制造一次 1 ns 间隔（实测 `rst_n` 在 286 ns 拉低，`count` 紧随其后跳到 0）。`waveform_insights` 先收集疑似复位信号（`^|_` 分隔的 `rst/reset/arst/nrst`）的跳变时刻，跨过这些时刻的间隔不进入基线，也不参与毛刺分组。
- **必须是"连续快翻"而非"单个短间隔"**：脉冲信号（`busy` 高电平期间的 10 ns）只有两个相邻短间隔；组合环自激、握手错乱会表现为连续快翻。因此要求至少 3 个相邻异常间隔才出结论。

同时，**基线用全局中位数而不是局部邻域中位数**：局部中位数会被突发自身拉低（一段连续快翻的前几个短间隔会把邻居的中位数带下来），导致只有突发尾部被标记，反而凑不满"连续"条件。

### 噪声校准后的实测结果

| 波形 | 结论 |
|---|---|
| `dut_i.clk`（5 ns 均匀） | stable |
| `dut_i.count`（每拍递增，含复位清零） | stable |
| `busy`（10 ns 脉冲 + 170 ns 空闲） | stable |
| 常规 20 ns 节奏中插入 3 个连续 1 ns | unstable，最短间隔 1 ns，常规节奏 20 ns |

## 四、DUT 信号与 testbench 记账信号

生成的 testbench 顶层是 `tb_<module>`，DUT 实例名固定为 `dut_i`（`testbench.DUT_INSTANCE`，改名时 pipeline 的层次判定必须同步）。因此：

- DUT 内部信号 = 完整层次前缀 `tb_<module>.dut_i.*`；
- 其余（`tb_<module>.checks`、`tb_<module>.count`、检查任务的 `expected`/`actual` 等）是 **testbench 记账信号**，其跳变节奏完全由激励脚本决定。

`analyze_vcd_file` 为每个信号额外记录 `scope` 字段（VCD 的 `$scope` 只记相对名，`_full_scope` 会补回前缀），`waveform_insights` 据此把不稳定信号分成两个列表：

- `unstable_signals`：DUT 内部信号，报告里作为**电路结论**；
- `unstable_auxiliary`：testbench 记账信号，结论行会显式标注"不作为电路结论"。

实测中 `uart_tx` 参考波形的 `check.actual`/`check.expected`/`check.name`/`check.t_id` 都在检查任务里被频繁改写，第一版会把它们报成毛刺；现在它们落在辅助列表，不再污染结论。

## 五、相位检查的两个实现要点

1. **裸信号名要解析到 VCD 层次**。contract 写的是 `start`/`tx`，VCD 里是 `tb_uart_tx.start`、`tb_uart_tx.dut_i.tx`。`_resolve_signal_name` 优先取 DUT 内部的那份（相位问题问的是电路行为），报告里同时保留声明名与解析后的名字。
2. **取最小延迟**。相位问题是"响应最早应该在几个周期后出现"；若某次触发后响应更晚，那是握手/背压等正常行为。第一版取"第一个响应沿"会把单次触发 + 长期活动误判成 late（实测 `start → tx` 被算成 31.9 个周期），改成最小延迟后为 2.9 个周期。

多位信号没有上升沿语义，相位检查对它直接给出 `not_applicable` 而不是永远不成立的 `unobservable`：实测 `enable → count`（`count` 8 位）第一版报 unobservable，是一条没有信息量的噪声。

## 六、真实缺陷上的端到端验证

### 双波形差异（`compare_waveforms`）

对参考 RTL 与缺陷 RTL 跑同一份 testbench，比较两份 VCD：

| 案例 | 差异数 | 典型差异 |
|---|---:|---|
| `uart_tx_bug_msb_first` | 6 | `dut.tx` 参考 12 次跳变、被测 14 次；`errors` 1 次 vs 3 次 |
| `spi_master_bug_extra_bit` | 20 | `check.actual` 第 3 次跳变比参考晚 2 个周期 |
| `pwm_bug_inverted_polarity` | 5 | `dut.pwm_out` 参考 12 次跳变、被测 13 次 |

三个缺陷全部被 `status=different` 识别（`RESULT PASS`）。

### 报告章节（`verify_waveform_semantics.py`）

| 案例 | 期望 | 实测 |
|---|---|---|
| `uart_tx_bug_msb_first` | 相位章节出现且有具体结论 | `start → tx` 比声明晚 2.9 个周期（late），章节齐全 |
| `spi_master_bug_extra_bit` | `busy` 的 10 ns 窄脉冲**不得**被报成毛刺 | 结论 0 条，无毛刺误报 |
| `mod10_counter_bug_wrap9` | 四个章节同时出现；多位相位对为 not_applicable | 17 个失败周期 → 17 个时间窗；`enable → count` 判 not_applicable；无毛刺误报 |

`mod10_counter` 的波形本身是干净的，结论为 0 条——这正是期望行为：这一层的价值在于出结论时每条都站得住，而不是凑数量。

## 七、能力边界（如实说明）

- VCD 分析**不参与判分**，PASS/FAIL 只由 Icarus 的断言记录决定；
- 不是综合、时序或形式验证的替代品：只看仿真里真实出现的数值，不推断未激励到的行为；
- 相位检查依赖 contract 显式声明 `trigger`/`response`/`expected_delay_cycles`，不从波形反推期望值（避免"用现象解释现象"）；
- 多位信号的相位关系、内部状态机的状态序列没有专门建模；
- 失败周期 → 时间窗是按 contract 时钟周期估算的近似窗口，报告里带同一句说明；
- `compare_waveforms` 只描述"可观测行为差异"，是否构成缺陷仍由规格与 Icarus 判定。
