# 按目的使用 · 四条最短路径

面向：**已经知道自己要干什么**，只想找那条最短路径的人。四条路径互不依赖，按需跳读。

---

## 路径 A：我只想对比两份 RTL（不关心 AI）

**场景**：我自己重写了一份 RTL，想知道它和标准实现的行为是否一致。

```powershell
iverilog-ai compare-rtl `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --user-rtl my_alu.v --reference-rtl rtl/simple_alu.v `
  --output-dir runs\cmp
echo $LASTEXITCODE      # 0 一致 / 1 不同 / 2 无法判定
```

**网页版**：概览页选"自定义 RTL" → 上传 → 验证页校验合约 → 质量与对比页 → "标准 RTL 参考实现"
里选一份 → 点"对比自定义 RTL 与标准实现"（看结构差异）→ 再点"运行行为级对比"（看行为差异）。

**读数**：

- `status=identical` → 记录与波形都一致（多出内部辅助信号算实现细节，不算差异）；
- `status=different` → 看 `mismatched_checks`：**哪个检查项、期望什么、实际什么**；
- `status=records_identical_waveform_unavailable` → 记录一致但拿不到波形，判"无法判定"而不是"一致"。

**只想要静态对比（不仿真）**：网页"结构对比"给端口匹配、复位风格、赋值风格等文本特征，
或用 `python scripts/review_rtl.py my_alu.v`。

---

## 路径 B：我要深入验证一个设计（AI 提假设 + 开源工具裁决）

**场景**：手上有个模块，想系统地测复位、状态转换、边界时序，并留下可复核的证据。

```powershell
# 1) 合约（端口/时钟/复位）—— 决定后面一切
notepad examples\my_dut_contract.json

# 2) 有计划后执行（内联计划文件，由网页或 API 生成）
iverilog-ai plan-run --plan my_plan.json --contract examples\my_dut_contract.json `
  --rtl my_dut.v --output-dir runs\deep --synth

# 3) 看三处：期望值来源 / 分层证据 / 失败反例
Get-Content runs\deep\report.md -TotalCount 60
```

**网页版**（推荐，能看到覆盖率与波形结论）：概览选案例或上传 RTL → 验证页填验证目标
（例如"覆盖复位释放、写满回绕、使能无效时保持"）→ 生成计划 → 执行 → 依次看：

1. **结论 + 期望值来源**：`reference_model` 最可信；
2. **分层证据**：仿真/综合/时序/比特流/上板五层，没做的显式写"未运行"；
3. **信号活动覆盖率**：取值覆盖低 → 说明激励太弱，回去把目标写细；
4. **失败反例与解释** → 波形语义结论（毛刺、相位）→ 失败周期对应的时间窗；
5. **证据包**：一次导出报告 + 计划 + testbench + result.json + VCD，便于交付复核。

**加分动作**：把失败反例喂回 AI 让它补向量（网页"根据失败补充测试向量"），再看新计划是否
把边界补上——这是"AI 提假设、工具裁决"的闭环。

---

## 路径 C：我要评测"AI 到底能不能测出缺陷"

**场景**：写论文/做汇报，需要可复现的检出率与对照数据。

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

**读数纪律**（我们踩过坑，写进文档了）：

- 检出率要分**单轮平均**与**多轮累计并集**；后者不能和只跑 1 轮的基线比；
- token 要按 `request_id` **去重**，否则会放大 6–13 倍；
- 参考误报必须单列——它是"乱报"的唯一约束；
- 未检出缺陷要逐条给原因（我们的实测：4 条全部是**激励相位/观测点**问题，不是模型不会分析）。

---

## 路径 D：我要在课堂 / 分享里演示它

**场景**：10 分钟内让观众看懂"AI 提假设、开源工具裁决"。

```powershell
python -m iverilog_ai.ai.debug_server        # 终端 A：离线模型，无密钥
streamlit run ui/app.py                      # 终端 B：网页
```

演示脚本：**概览**看实证状态 → **验证**页选"脉冲展宽器" → 生成计划 → 执行（参考设计，通过）
→ 换成缺陷变体（`rtl/pulse_stretcher_bug_stuck_high.v`）再执行 → **同一个计划**，缺陷被检出，
报告写明失败在第几拍、期望什么、实际什么 → 收尾一句：**"判决来自 Icarus，不来自 AI。"**

配套材料：[演示脚本](../demo/demo_script.md)、[证据包说明](../demo/evidence_pack_guide.md)、
[四张插图](../competition/figures) 可直接用在 PPT 里。

---

## 我该选哪条路径？

| 你的目标 | 路径 | 大概耗时 |
|---|---|---|
| 只想知道两份 RTL 是否等价 | A | 5 分钟 |
| 想给自己的模块做一轮系统验证 | B | 30 分钟起 |
| 想要可复现的 AI 效果数据 | C | 1 小时（含等待模型） |
| 想给别人讲清楚这个项目 | D | 15 分钟 |

> 不确定就从 [入门手册](01_beginner.md) 开始——它 15 分钟就能让你看到全部三样产物。
