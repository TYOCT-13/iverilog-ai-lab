# 按目的使用 · 操作流程与适用场景

适用对象：已明确操作目标，需要查阅对应流程的用户。四条流程可独立使用。

---

## 路径 A：两份 RTL 的行为对比

**适用场景**：比较重构后的 RTL 与参考实现的可观测行为。

```powershell
iverilog-ai compare-rtl `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --user-rtl my_alu.v --reference-rtl rtl/simple_alu.v `
  --output-dir runs\cmp
echo $LASTEXITCODE      # 0 一致 / 1 不同 / 2 无法判定
```

**网页版**：顶部进入**工作台**，工作方式选**对比两份 RTL** → 选择"基线 RTL"（内置设计或上传原版本）
→ 上传"候选 RTL" → 点"开始对比"。两份 RTL 的模块名须相同；接口信息不足时按页面提示补齐。

使用已确认的接口和测试计划时，先在**验证一份 RTL → 工作台**上传自定义 RTL，
点"校验接口"并生成测试计划，再切到**对比两份 RTL → 工作台**，选择"标准 RTL 参考实现"，
点"对比自定义 RTL 与标准实现"查看结构差异，再点"用当前计划对比"查看行为差异。

**结果字段说明**：

- `status=identical` → 记录与波形都一致（多出内部辅助信号算实现细节，不算差异）；
- `status=different` → 查看 `mismatched_checks` 中的检查项、期望值和实际值；
- `status=records_identical_waveform_unavailable` → 记录一致，但缺少波形证据，结论为“无法判定”。

**静态对比（不执行仿真）**：网页的"对比自定义 RTL 与标准实现"给端口匹配、复位风格、赋值风格等文本特征，
或用 `python scripts/review_rtl.py my_alu.v`。

---

## 路径 B：单份 RTL 的功能验证

**适用场景**：验证模块的复位、状态转换与边界时序，并保存可复核的运行证据。

```powershell
# 1) 定义端口、时钟和复位
notepad examples\my_dut_contract.json

# 2) 有计划后执行（内联计划文件，由网页或 API 生成）
iverilog-ai plan-run --plan my_plan.json --contract examples\my_dut_contract.json `
  --rtl my_dut.v --output-dir runs\deep --synth

# 3) 看三处：期望值来源 / 分层证据 / 失败反例
Get-Content runs\deep\report.md -TotalCount 60
```

**网页版**（提供覆盖统计与波形分析）：顶部进入**工作台**，工作方式选**验证一份 RTL**，在**选择设计**中
选案例或上传 RTL（自定义 RTL 先点"校验接口"）→ 在**运行测试**中填验证目标
（例如"覆盖复位释放、写满回绕、使能无效时保持"）→ 点"生成测试计划" → "运行测试计划" → 在**测试结果**中依次检查以下内容。

1. **结论 + 期望值来源**：核对 `reference_model` 等判据来源及其适用范围；
2. **分层证据**：仿真/综合/时序/比特流/上板五层，未执行的证据层标记为“未运行”；
3. **信号活动覆盖率**：取值覆盖较低时，检查激励是否充分，并细化验证目标；
4. **失败反例与解释** → 波形语义结论（毛刺、相位）→ 失败周期对应的时间窗；
5. **导出证据 → 打包本次结果**：一次导出报告 + 计划 + testbench + result.json + VCD，便于交付复核。

补测可将失败反例作为模型输入，生成追加向量，并通过仿真结果评估边界覆盖是否增加。

### 自动验证 Agent

已有明确测试计划时，可执行单轮验证。Agent 用于多轮探索：根据上一轮的检查结果和场景缺口，决定下一轮输入；Agent 不自动修改 RTL，也不提供缺失子模块的实现。

在**运行测试 → 自动验证 Agent**设置轮数、API 请求次数和累计激励周期。**每轮独立运行**从复位开始，只运行本轮计划；**重放已有输入后补测**先重放旧输入，再追加新输入，重放也计入周期预算。有已生成计划时，Agent 先执行该计划。遇到反例、模型停止或预算耗尽时结束，可在完整轨迹中查看停止原因。

观察补测效果时，可选择内置**单时钟 FIFO**，保留默认的8位数据、深度4。先生成计划，在 Agent 中设1轮、1次 API 请求、160周期，勾选逐拍检查与场景补测；保存轨迹和覆盖记录。再从同一起始计划设3轮、3次 API 请求、160周期运行，查看后续输入是否针对第一轮遗漏的场景。初始计划已经覆盖全部场景时，提前停止是合理结果。

这组操作用于观察补测过程。多轮比单轮发现更多场景，还不能证明 Agent 普遍更好；正式对照需匹配请求或 token 预算、检查口径和测试对象，重复运行并保留全部结果。检查数增加本身不是收益，应保留全部运行结果，避免仅采用最优结果。

### 学习模式与验证一份 RTL

学习模式把验证目标、断言和综合等设置收进高级区域，用于简化首次操作。**验证一份 RTL**直接显示这些配置。相同输入、计划与设置使用相同的验证逻辑；切换模式不会自动提高检查强度。

---

## 路径 C：AI 缺陷检出能力评测

**适用场景**：为研究或汇报收集可复现的缺陷检出率及对照数据。

```powershell
# 固定矩阵（人工 testbench 基线）
python scripts/run_benchmark_matrix.py

# 四策略对比（固定 / 随机 / 离线AI / 在线AI），含 token 与耗时
$env:IVERILOG_AI_API_KEY = "sk-..."
python scripts/run_strategy_experiment.py --project-root . `
  --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe `
  --seeds 1 --online --online-endpoint https://api.deepseek.com `
  --online-model deepseek-flash --online-api-key-env IVERILOG_AI_API_KEY `
  --online-repeats 10 --online-stream auto

# 两个模型同口径对比（脚本会拒绝不可比的数据）
python scripts/compare_models.py .iverilog-ai/model-A .iverilog-ai/model-B `
  --output docs\experiment\model_comparison.md
```

**结果统计要求**：

- 检出率要分**单轮平均**与**多轮累计并集**；后者不能和只跑 1 轮的基线比；
- token 要按 `request_id` **去重**，否则会放大 6–13 倍；
- 参考误报必须单列，用来观察错误报告的情况；
- 未检出缺陷需逐项分析原因；历史实测中的4项未检出记录均涉及激励相位或观测点，不能据此直接判断模型的分析能力。

---

## 路径 D：课堂与交流演示

**适用场景**：在10分钟演示中说明测试计划生成、仿真执行及结果判定流程。

```powershell
python -m iverilog_ai.ai.debug_server        # 终端 A：本地规则调试服务，无密钥
streamlit run ui/app.py                      # 终端 B：网页
```

演示脚本：**项目概览**查看实证状态 → **工作台**选"脉冲展宽器" → "生成测试计划" → "运行测试计划"（参考设计，通过）
→ 换成缺陷变体（`rtl/pulse_stretcher_bug_stuck_high.v`）再执行 → **同一个计划**，缺陷被检出，
报告记录失败周期、期望值和实际值。结果由实际仿真记录与检查判据共同确定，AI 自评不参与判定。

配套材料：[演示脚本](../demo/demo_script.md)、[证据包说明](../demo/evidence_pack_guide.md)、
[四张插图](../competition/figures) 可直接用在 PPT 里。

---

## 操作流程选择

| 操作目标 | 路径 | 预计耗时 |
|---|---|---|
| 比较两份 RTL 在同一组输入下的行为 | A | 5 分钟 |
| 对自定义模块执行一轮功能验证 | B | 30 分钟起 |
| 收集可复现的 AI 效果数据 | C | 1 小时（含等待模型） |
| 演示项目功能与验证流程 | D | 15 分钟 |

> 首次使用可从 [入门手册](01_beginner.md) 开始，按步骤生成计划、仿真记录和报告。
