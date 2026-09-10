# 阶段四提交大纲：Icarus智测

## 技术创新

项目在 Icarus Verilog 之上提供受控的 AI 测试规划、`TestPlan` JSON 合同、结构化 `IVERILOG_AI_RESULT` 记录、失败反例和 Markdown/HTML 报告。执行器使用参数列表、固定工具名、路径策略、超时和独立 run 目录，形成可复核证据链。

## 开源生态对应

这是围绕 Icarus 的非官方扩展，不修改或代表 Icarus 上游。Apache-2.0 项目提供中文案例、可复用 pytest/CI、离线 MockProvider 和兼容 OpenAI 的可选 provider；贡献者可替换 provider，但不能绕过模型校验和执行边界。

## AI 边界与合规

AI 只提出 JSON 计划和解释，不能直接生成或执行命令，不能把 UI 输入当 shell/RTL；正确性只由本地 iverilog/vvp 和 testbench 记录决定。网络默认关闭；不上传密钥、日志或 RTL，不自动提交 PR/Issue。

## 证据链

规格 → 固定案例 testbench → Icarus 编译 → vvp 仿真 → 结构化记录 → `SimulationResult` → 失败反例/报告。报告保留 run ID、配置、输入哈希、进程状态、诊断和工件路径。Icarus 的版本、OS、Python 版本应随评测记录。

## 评测指标

以固定案例的通过率、结构化记录完整率、编译/仿真成功率、缺陷反例召回率、运行时间、超时率和报告可复现率为主；对固定随机种子重复运行，报告均值、标准差和样本数。不得以 AI 自评替代仿真结果。

## 风险与缓解

Icarus 与商业仿真器语义/覆盖能力不同：声明工具版本并限制结论范围；testbench 漏检：保留规格映射和缺陷变体；模型幻觉：严格 schema、重试后拒绝；资源耗尽：超时和输出上限；密钥泄露：默认 Mock、最小环境变量；路径逃逸：SafePathPolicy。
