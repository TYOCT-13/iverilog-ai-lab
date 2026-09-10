# 往届高分开源作品分析与 Icarus 智测改进方向

更新日期：2026-09-08

本文记录对往届高分开源作品的阅读结论，并将可借鉴经验转化为 Icarus 智测的后续建设方向。

## 一、参考作品

- `ymir-twice/24-Global-AI-challange-eighth`：钢材表面缺陷检测与分割，2024 国一。
- `AnikiFan/JSAI-BIRADS-track`：超声乳腺影像 BIRADS 分类与特征识别。
- `nhdzTVlxb/Noise-FGVC`：网络监督细粒度识别，2025 国二。
- `ceasonen/aicomp-2025`：医工交叉赛道，2025 国二。

## 二、往届作品做得好的共同点

### 1. README 是复现手册

优秀作品通常同时说明项目背景、任务定义、目录结构、安装方式、运行命令、实验流程、结果和限制，而不是只写一句项目简介。

### 2. 目录结构与系统流程一致

数据、模型、训练、预测、评分、工具和文档职责清晰，陌生用户可以通过目录快速理解项目。

### 3. 记录完整实验过程

高分作品会说明尝试过哪些方法、为什么放弃某些方案、性能提升来自哪里，以及算力和时间约束下的取舍。

### 4. 诚实公开失败与局限

例如算力不足、模型未收敛、复杂方案效果不佳、数据处理风险等。公开失败原因反而增强了可复现性和可信度。

### 5. 提供可直接运行的 Demo

包括在线演示、VS Code 任务、Notebook、一键预测/评分脚本或 Hugging Face Demo，使评委能够快速验证成果。

### 6. 具备开源项目意识

明确许可证、Issue 入口、贡献方式、引用信息和后续论文/衍生成果，使比赛作品可以继续发展。

## 三、对 Icarus 智测的启示

当前项目的验证内核和安全边界已经较完整，下一阶段要重点提升“实验叙事、复现体验、公开证据和成果包装”。

### 方向 A：完善项目叙事和 README

- 用一句话明确系统价值：将自然语言验证目标转换为受约束的 RTL 测试计划，并由 Icarus/vvp 产生可复现证据。
- 增加 30 秒核心流程图：DUT contract → AI TestPlan → Schema → testbench → Icarus/vvp → result/report/VCD。
- 增加网页截图、报告示例、VCD/GTKWave 截图。
- 同时提供 PyCharm 图形化启动和命令行启动方式。
- 明确离线 Mock 与真实在线模型的区别。
- 明确 Icarus 仿真通过不等于综合、时序收敛或 FPGA 上板通过。

### 方向 B：建设可审计实验报告

在现有 `run_strategy_experiment.py` 基础上生成 Markdown 汇总报告，至少包含：

- 模型名称和接口协议；
- 请求次数和重复次数；
- TestPlan 请求级合法率；
- 参考模型一致率；
- 参考 RTL 误报率；
- 缺陷检出率；
- 平均生成延迟和仿真耗时；
- 不可判定请求及原因；
- token 使用量和费用估算；
- 原始逐次结果索引。

所有实验必须同时公开未检出缺陷和失败请求，不能只展示最佳成绩。

### 方向 C：建立项目专用验证规则包

新增仓库目录：

```text
verification_rules/
├── common.md
├── mod10_counter.md
├── simple_alu.md
├── sequence_101_overlap.md
├── traffic_light_emergency.md
└── custom_rtl.md
```

规则包用于告诉模型：

- 只能使用 contract 中的真实端口名；
- 输入值必须符合位宽；
- 1 位信号只能取 0 或 1；
- 序列输入必须按周期拆分；
- 时钟由 testbench 生成；
- reset 字段必须符合 Schema；
- 不确定的 expected 必须声明，不能猜测。

规则包不能替代程序校验。最终仍由 Schema、contract、reference model 和 Icarus 共同裁决。

当前已完成通用规则以及 FIFO、UART、SPI、Valid/Ready 握手、按键去抖、PWM、多路选择器和同步复位的专用规则文件。网页和在线实验脚本会在生成 TestPlan 时自动加载对应规则与 contract。

规则包已根据公开开源资料进一步整理，来源和提炼原则记录在 `verification_rules/opensource_synthesis.md`。参考包括 lowRISC Verilog Coding Style、verilog-axi、verilog-ethernet、cocotb、LiteX、ZipCPU wb2axip 和 Project F；项目只吸收时序/复位/CDC/接口/验证工程规则，不复制第三方代码。

已新增规则到结构化断言的安全建议映射。网页可以为案例载入保守的断言候选，用户仍需审查并确认；没有可观察样本时断言会报告 `no observable samples`，不会伪造通过。

### 方向 D：降低 AI 预言机风险

- AI 主要生成测试意图和输入向量；
- 内置案例由 Python reference model 独立计算 expected；
- AI expected 与参考模型不一致时标记 `plan_inconsistent`；
- 正确 RTL 出现失败反例时计入参考误报，不计入有效缺陷检出率；
- 自定义 RTL 标明 expected 证据等级：`reference_model`、`specification`、`human_confirmed`、`ai_generated`、`unknown`；
- 增加关系型和 metamorphic assertions，减少对绝对 expected 的依赖。

当前已落地：流水线会在仿真后写入 `simulation.config.oracle`，记录参考模型证据等级、检查项数量、匹配数量和一致率；Markdown 报告新增“期望值可信度”章节。该检查仍是独立诊断证据，不会静默改写 AI 计划或替代 Icarus 裁决。

同时已接入受控结构化断言和证据结论：报告会记录 `structured_assertions`、`cross_validation` 和 `verification_status`。证据结论区分 `verified`、`passed_unverified`、`plan_inconsistent`、`assertion_failed` 以及基础仿真错误，避免把“仿真通过”误写成“高可信验证通过”。

### 方向 E：增强 Demo 和证据包

准备两套固定证据包：

1. 正确 RTL 通过案例：包括 TestPlan、testbench、result.json、report.md、VCD 和截图。
2. 缺陷 RTL 检出案例：包括失败反例、失败指纹、波形、报告和修复前后对比。

演示顺序：

```text
固定案例通过
→ 自定义 RTL 导入
→ AI 生成 TestPlan
→ 自动生成 testbench
→ Icarus 仿真
→ 展示结构化结果
→ 展示报告和 VCD
→ 展示失败解释与候选修复
```

### 方向 F：补齐开源协作规范

新增：

```text
CONTRIBUTING.md
CODE_OF_CONDUCT.md
SECURITY.md
CHANGELOG.md
.github/ISSUE_TEMPLATE/
.github/pull_request_template.md
```

同时核验 `THIRD_PARTY.md` 中的依赖版本和许可证，提供可复现依赖锁定说明。

## 四、实施优先级

当前已扩展常见 FPGA 案例：同步上升沿检测器和脉冲展宽器，均提供标准 RTL、DUT contract、规格和可执行 testbench。后续可继续加入 FIFO、UART、SPI、握手协议和按键去抖。

### 第一阶段：近期

1. 生成真实在线模型实验 Markdown 报告。
2. 修正并展示请求级合法率、参考误报率和有效检出率。
3. 建立 common 和四个内置案例规则文件。
4. 让规则文件哈希写入实验结果。

### 第二阶段：中期

1. 内置案例全部接入 reference model 重新计算 expected。
2. 完成 README、截图、流程图和证据包。
3. 增加一键启动和环境自检。
4. 扩展缺陷基准到至少 30 个。

### 第三阶段：提交前

1. 完成 2～3 个真实在线模型的公平实验。
2. 补齐开源社区文件。
3. 完成技术方案 PDF、答辩 PPT 和演示视频。
4. 可选增加 Yosys 综合状态，但必须与仿真结论分开显示。

## 五、评价标准

项目最终不只报告：

```text
缺陷检出率
```

还必须同时报告：

```text
TestPlan 合法率
参考模型一致率
参考 RTL 误报率
有效计划缺陷检出率
不可判定率
平均延迟
成本估算
```

只有这些指标、原始证据和运行方法同时公开，项目才真正具备比赛提交级别的可信度和可复现性。
