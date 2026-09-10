# 验证与阶段进度记录

记录日期：2026-09-05

## 工具环境

- Icarus Verilog：`D:\iverilog\bin\iverilog.exe`
- vvp：`D:\iverilog\bin\vvp.exe`
- Python：3.11+

## 四类参考设计闭环

所有参考设计均使用仓库内自检 testbench，并输出 `IVERILOG_AI_RESULT` 结构化记录：

| 设计 | 编译 | vvp | 结构化记录 | 结果 |
|---|---|---|---:|---|
| `rtl/mod10_counter.v` | 通过 | 通过 | 13/13 | `passed` |
| `rtl/traffic_light_emergency.v` | 通过 | 通过 | 6/6 | `passed` |
| `rtl/simple_alu.v` | 通过 | 通过 | 9/9 | `passed` |
| `rtl/sequence_101_overlap.v` | 通过 | 通过 | 8/8 | `passed` |

每次运行会生成 `compile.stdout.txt`、`compile.stderr.txt`、`run.stdout.txt`、`run.stderr.txt`、`result.json` 和报告。没有结构化结果行时，执行器会返回 `inconclusive`，不会把普通 `PASS` 文本当作充分证据。

## 缺陷基准检出（当前 70 个 / 12 个案例）

同一组自检 testbench 替换为缺陷 RTL 后，当前固定矩阵共登记 **70 个缺陷**，覆盖 12 个案例；最近一次实跑结果为 **70/70 检出、参考误报 0、不可判定 0**。

| 类别 | 缺陷数 | 说明 |
|---|---:|---|
| 模十计数器 | 12 | 使能、回绕、复位、位宽、异步复位等 |
| 交通灯状态机 | 11 | 状态序列、紧急模式、非法状态恢复等 |
| 简单 ALU | 14 | 运算、标志位、移位、默认分支等 |
| 可重叠 101 检测器 | 13 | 位序、重叠、锁存、复位极性等 |
| 同步 FIFO | 3 | 满标志差一、满时写入、复位读数据 |
| UART 发送 | 2 | 位序、busy 生命周期 |
| SPI 主机 | 3 | 时钟极性、done 缺失、多发一位 |
| Valid/Ready 握手 | 3 | ready 依赖、valid 撤销、数据误捕获 |
| 按键去抖 | 3 | 门限差一、计数清零、复位状态 |
| PWM | 2 | 输出极性、占空比差一 |
| 多路选择器 | 2 | 选择分支接错、default 分支 |
| 同步复位 | 2 | 同步级数不足、极性反相 |

常用 FPGA 案例使用**专门的边界 testbench**（`tb/tb_*_boundary.v`）而不是浅层冒烟测试，因为上述缺陷只在写满、回绕、位序、握手保持、门限、占空比边界、同步级数等特定触发条件下才可观测。

完整字段、触发条件和文件映射见 `benchmarks/manifest.json`。

> 能力边界（如实记录）：生成式 testbench 的激励均在时钟沿更新，因此**只在时钟边沿之间变化才可见**的缺陷（例如"停止位单拍被拉低"）无法由生成式 testbench 稳定检出；这类缺陷没有登记进基准，而是由手写边界 testbench 覆盖可观测的部分。

## 自动化测试与门禁

- Python 回归：当前自动化测试数量以 CI/本机 pytest 输出为准（覆盖核心模型、执行器、报告、AI 规划器、合约、生成器、规则和证据包）。
- 新增流水线回归覆盖：显式 DUT 合约、确定性 testbench 生成、组合/时序真实 Icarus/vvp 执行、失败解释，以及越界 `output_dir` 在校验失败前不会被创建。
- `readable-verilog-generator` 严格交付门禁（`tb/`）：`delivery_ready=True`，0 errors，0 strict warnings。
- `tb/` 的 `compile`、`ast`、`readability`、`comment`、`naming`、`profile` 已通过；`toolchain` 的真实仿真证据由上表给出。

## RTL 静态质量审查

`scripts/review_rtl.py` 可对标准或自定义 RTL 生成 `rtl_quality_report.json` 和
`rtl_quality_report.md`，记录规则 ID、严重级别、行号、证据片段、源码 SHA-256、
质量评分和修复建议。该审查用于教学和问题分流，不等同于综合、时序收敛或 FPGA 上板验证。

## 固定向量基准矩阵

使用 `scripts/run_benchmark_matrix.py` 逐项调用 `IcarusExecutor`，并保留每次运行的
`result.json`、编译/仿真日志和源码哈希。2026-09-05 本机实跑结果：

| 指标 | 结果 |
|---|---:|
| 参考设计 | 12/12 通过 |
| 参考误报 | 0/12 |
| 缺陷版本 | 70/70 产生结构化失败反例 |
| 缺陷检出 | 70/70（100%） |
| `inconclusive` | 0 |

机器可读汇总位于 `.iverilog-ai/benchmark-matrix/matrix.json`，Markdown 摘要位于
`.iverilog-ai/benchmark-matrix/matrix.md`。

## 三策略公平比较（5 个 seed）

`scripts/run_strategy_experiment.py` 使用同一组显式 DUT 合约和
`VerificationPipeline`，固定策略运行 1 组、随机和离线 AI（`MockProvider`）各运行
5 个 seed。所有计划均经过 `ai.schema.TestPlan` 校验，所有结论均由 Icarus/vvp
结构化结果裁决：

| 策略 | 运行数 | 计划合法率 | 参考误报 | 缺陷检出 | 检出率 | 首次失败平均耗时 |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 20 | 100% | 0 | 16/16 | 100% | 68.19 ms |
| random（5 seed） | 100 | 100% | 0 | 13/16 | 81.25% | 70.95 ms |
| ai / MockProvider（5 seed） | 100 | 100% | 0 | 13/16 | 81.25% | 71.18 ms |

完整逐次运行记录和 `result.json` 路径保存在
`.iverilog-ai/strategy-experiment-final/strategy_matrix.json`。AI 结果是离线、
确定性的 MockProvider 基线，不宣称代表任意在线模型能力。

## 阶段状态与待办

- 阶段一：确定性验证闭环已满足退出条件。
- 阶段二：Provider、计划校验、显式 DUT 合约、确定性 testbench 生成和
  `plan-run` CLI 已完成，并通过真实 Icarus/vvp 流水线回归。
- 阶段三：70 个缺陷基准（12 个案例）、固定向量矩阵和 5-seed fixed/random/AI 公平比较已完成；
  最近固定矩阵检出 70/70、参考误报 0、不可判定 0。在线模型结果应以对应策略实验报告为准。
- 阶段四：UI、CI、申报大纲和演示脚本已完成；正式视频和上游贡献仍需人工执行。
- 整个 `rtl/` 目录仍保留旧风格参考/缺陷文件，按 `erie_strict` 会报告头部、缩进和注释问题；这不改变 Icarus/vvp 的功能结论，正式发布前应规范化两个参考 RTL，并将缺陷版本作为非严格历史基准单独审计。

## 可复现命令

在 `E:\FPGA_WORK\iverilog-ai-lab` 根目录运行：

```powershell
python -m pip install -e .
python -m iverilog_ai run --rtl rtl/mod10_counter.v --testbench tb/tb_mod10_counter.v --top tb_mod10_counter --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python -m iverilog_ai run --rtl rtl/traffic_light_emergency.v --testbench tb/tb_traffic_light_emergency.v --top tb_traffic_light_emergency --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python -m iverilog_ai run --rtl rtl/simple_alu.v --testbench tb/tb_simple_alu.v --top tb_simple_alu --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python -m iverilog_ai run --rtl rtl/sequence_101_overlap.v --testbench tb/tb_sequence_101_overlap.v --top tb_sequence_101_overlap --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python -m iverilog_ai plan-run --plan examples/simple_alu_plan.json --contract examples/simple_alu_contract.json --rtl rtl/simple_alu.v --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python scripts/run_benchmark_matrix.py --project-root . --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python scripts/run_strategy_experiment.py --project-root . --seeds 5 --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
python -m pytest -q
```

缺陷版本只需把 `--rtl` 替换为 `rtl/` 下对应的 `*_bug_*.v` 文件；预期 CLI 返回 1，并在 `result.json` 中记录 `status=failed` 及失败反例。
