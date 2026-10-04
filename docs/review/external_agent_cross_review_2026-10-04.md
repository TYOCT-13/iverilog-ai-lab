# 外部 Agent 代理交叉检查（2026-10-04）

对象：Git `e9b7b8a` 的 AgentObservation、外部 gate、simulation_multiplier 和 reference_policy；随后仅修复外部适配器采样，不修改冻结中的 core 或内部 pilot 协议。执行者是外部适配器的实现代理，因此存在实现者关系。本记录是代理代码检查与机器实测，**不是独立人工审核或真人试用**。

## 发现与处理

### 阻断：VCD 时间戳最终值并非采样语句瞬时值（已在外部适配器修复）

生成器在 after 或无时钟路径中，采样语句、cycle 递增与下一向量输入赋值可处于同一仿真时间戳。VCD 最终值可能记录下一输入导致的组合输出变化。

真实取证：现有 priority_encoder 基线穷举 16 输入，将原测试台临时加入只读 `$display` 与最终 VCD 对照，出现 4 个不一致。cycle 0 的采样语句输出 valid=0，而同时间戳最后值 valid=1。UART RX 全部 before 相位、182 点的同类对照本次未见不一致，但这不证明所有模块/相位都安全。证据：`.iverilog-ai/external-agent/sampling-cross-review-20261004/audit.json` 及各目录 instrumented 日志；没有改原 RTL 或覆盖历史证据。

修复：外部适配器通过现有 TestbenchGenerator 接口生成真实测试台，再在确定且经过校验的采样锚点加入只读即时日志。要求锚点数量恰好等于计划周期，每个前置语句是原 IVERILOG_AI_RESULT 输出；不满足即失败。没有插入延时、断言、期望值或 DUT 赋值。保存原始/插桩测试台及原生成器、适配器、测试台哈希。运行使用即时日志取样，VCD 保留为旁证。

修复后新增真实组合逐点检查，before/after 均能按 0..15 当前输入得出正确 valid、encoded、onehot；UART before 第一采样时刻确认为 28 ns。旧 20 项测试只能说明当时检查范围，不能冒充此次修复验收。现为 **24 项测试通过**，脚本 mypy 通过。

### 核心 gate 与预算：在检查范围内通过

- AgentObservation 使用 strict/extra-forbid，差分证据要求三份 64 位 SHA256，checks/failures 为 0，differences 不超过 compared_samples；模型决策不能写入 observer。
- 外部 gate 拒绝未知证据类型、inconclusive、空采样、非合约输出和候选哈希不一致；差异停止为 behavior_difference，不冒充内置 counterexample_found。
- observer 必须与 multiplier=2 配套；追加动作前及仿真前按双侧累计预算检查，包含每轮重跑旧计划。真实 Icarus + mock HTTP 回归：预算 364 时初轮后停止、不调用 API；预算 1200 时 1 次 mock 请求、2 轮共 732 双侧激励周期。
- Pipeline reference_policy 默认 builtin 保持旧路径；disabled 同时绕开参考期望生成与一致性检查。外部 uart_tx 与内置案例同名的误套模型已被真实回归覆盖，不能只改标注而保留错误断言。
- 外部编译失败、X/Z/缺失/错位采样、冻结哈希变化均不产生一致结论。内部信号不参与采样；既有等价改写未误报。

信任边界仍是本地 Python runner/observer：core 检查数据类型与候选绑定，并不独立认证 arbitrary observer 所称的 baseline 资格。当前适配器真正执行资格检查并核验源哈希；不要向 API 或不可信配置开放任意 observer 注入。

## 非阻断限制

- wall_time 是轮次边界检查，不是对正在运行进程的全局硬实时抢占；每次编译/仿真及请求另有限时。
- 激励预算不包括资格检查和复位开销；报告须保留这项口径。资格检查是有限手写规格测试，不能证明参考基线对所有新增输入都正确。
- after/before 解释以现有生成器语句为准，快照记录该语句真实看到的值，没有声称修正电路本身可能存在的仿真竞争。
- 同作者、已开发使用的三模块不是独立留出集；网络 mock 测试不是真实服务商成绩。

## HDL 工作流证据口径

参考 readable-verilog-generator 的既有资产 analyze/validate 路由，保留真实输入与错误取证，并限定补丁为生成测试台只读日志。compile/toolchain 有真实 Icarus 证据，testbench 有即时采样回归；ast、readability、comment、naming、profile 的该技能专用门禁未运行，不宣称完整 VerilogGenerator 门禁认证或综合/硬件验证。冻结核心文件与原 RTL 未改动。

## 待主代理执行的真实 API 命令

以下命令未由本审核代理执行；预算为 1 次请求、2 轮、8192 输出 token、1200 双侧激励周期。正确 UART RX 基线用于确认追加补测，不选择已知缺陷来预设成绩。目录必须不存在，主代理统一安排付费请求。

```powershell
D:/Users/TYOCT/anaconda3/python.exe scripts/run_external_verification_agent.py --manifest .iverilog-ai/external/frozen-20261004-ic/manifest.json --candidate .iverilog-ai/external/uart_rx_check/uart_rx_baseline.v --module uart_rx --output-dir .iverilog-ai/external-agent/uart-rx-live-one-request-20261004 --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe --execute --endpoint https://api.deepseek.com --model deepseek-flash --api-key-file C:/Users/TYOCT/OneDrive/api/ds-aic.txt --max-requests 1 --max-rounds 2 --max-output-tokens 8192 --max-total-cycles 1200
```
