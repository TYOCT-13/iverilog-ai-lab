# 上游贡献材料包（待提交）

更新日期：2026-09-11
状态：**材料已就绪，尚未提交** —— 实际提交需要项目维护者的 GitHub 账号，
本仓库不代替人工提交（`README.md` 的项目边界里也写明了"不自动提交 Issue/PR"）。

## 一、为什么做这件事

赛题方向（三）明确包含"向上游开源项目提交 Issue、Pull Request、补丁及其他贡献"，
评分项「开放成果与复用价值」也把"社区贡献记录"列为可核验的效果证据。

**但必须诚实**：截至本文件更新，本项目**没有任何**已提交的上游贡献。这里的
材料是"准备好了、可以一键提交"，不是"已经贡献了"。在提交并收到回复之前，
报告和 PPT 里都不得把它写成已完成的贡献。

## 二、候选贡献（按可行性排序）

| # | 形式 | 目标 | 价值 | 风险 |
|---|---|---|---|---|
| A | Issue：介绍可复现的验证基准集 | Icarus Verilog | 高——提供 14 案例 / 78 缺陷的可复现基准，上游社区可用它回归 | 低。不是报 bug，是提供资源 |
| B | Issue：文档补充建议 | Icarus Verilog | 中——把"如何在 CI 中调用 iverilog 并解析结构化输出"写成可复用片段 | 低 |
| C | PR：不涉及——本项目不修改上游代码 | — | — | — |

**明确不做的事**：不向上游提交本项目自己的代码（那是另一个项目，不是上游的补丁）；
不提"希望支持我们的工具"这类要求；不在上游 Issue 里做产品宣传。

## 三、候选 A 的 Issue 草稿

> 提交前请通读并改成你自己的语气。**链接在仓库公开后填入**，不要留占位符提交。

**标题**：`A reproducible verification benchmark (14 designs / 78 defect variants) built on Icarus`

**正文**：

```text
Hello,

I maintain a small open-source project built on top of Icarus Verilog. It generates
deterministic testbenches from a structured JSON test plan and uses Icarus + vvp as the
sole PASS/FAIL authority.

While building it I accumulated a benchmark that might be useful to others here: 14 small
RTL designs (counter, FSM, FIFO, UART TX, SPI master, valid/ready handshake, debounce, PWM,
mux, sync reset, Johnson counter, edge detector, ...) each with several defect variants,
78 in total. Every variant has a hand-written boundary testbench and a recorded detection
result. The current matrix run reports 78/78 detected, 0 false positives on the reference
designs.

Repository: <link>
Benchmark manifest: <link to benchmarks/manifest.json>
How to reproduce: python scripts/run_benchmark_matrix.py

Notes:
- Everything is Apache-2.0 and self-contained; no third-party code.
- It is a project *around* Icarus, not a patch to it. I am not asking for anything to be
  changed in Icarus.
- If a benchmark of this shape is not useful here, feel free to close this — I mainly
  wanted to make it discoverable rather than keep it private.

Thanks for Icarus; the fact that it is scriptable and dependable is what made this possible.
```

**提交前检查**：

- [ ] 仓库已公开可访问，链接有效
- [ ] `scripts/run_benchmark_matrix.py` 在干净环境下能跑通（对方会试）
- [ ] 确认 Issue 里**没有**学校名称、指导教师、密钥或个人信息
- [ ] 通读一遍，改成自己的语气——模板腔的 Issue 不受欢迎

## 四、候选 B 的 Issue 草稿

**标题**：`Docs suggestion: a minimal CI snippet for running iverilog and parsing structured output`

**正文**：

```text
Hello,

A pattern that took me a while to get right, in case it is worth a docs note: running
Icarus from CI and turning the simulation into machine-checkable output.

The approach I settled on is to have the testbench print one line per assertion:

    $display("IVERILOG_AI_RESULT {\"ok\":true,\"test_id\":\"reset\",\"cycle\":0}");

and have the driver parse only lines with that prefix, treating a JSON parse failure as a
testbench bug rather than a pass. Two things that bit me and might be worth mentioning:

1. `$finish` stops the run, so the last clock edge is never sampled — if you generate
   testbenches, the expected sequence length has to account for it.
2. Non-blocking assignment reads the OLD value in the same cycle (IEEE 1364), which is easy
   to get wrong when a reference model is written in another language.

Happy to write this up as a docs PR if it fits; otherwise feel free to close.

Thanks.
```

## 五、提交后要记录什么

提交后把下面这张表填上，并同步到 `docs/experiment/` 与竞赛材料：

| 项 | 内容 |
|---|---|
| 提交日期 | |
| 平台与链接 | |
| 形式 | Issue / PR |
| 对方回复 | |
| 结果 | 被接受 / 被关闭 / 无回复 |
| 学到的 | |

**无论结果如何都如实记录。** 被关闭也是一条真实的数据点——它说明我们的基准形态
与上游关注点不匹配，这比"我们提交了贡献"更有信息量。

## 六、后续可考虑的贡献（本轮不做）

| 形式 | 说明 | 前置条件 |
|---|---|---|
| 把基准集做成独立可引用的包 | 便于其他工具直接依赖，而不必 clone 整个仓库 | 需要先稳定 manifest 格式并发布版本 |
| 为其他开源仿真器提供执行层适配 | 让测试计划格式跨工具复用（Verilator / GHDL） | 需要各工具的驱动实现 |
| 教程与文档贡献 | 中文教程、CI 集成示例 | 需要先有公开仓库 |
