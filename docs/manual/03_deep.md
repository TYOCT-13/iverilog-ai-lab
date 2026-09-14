# 深度手册 · 判据、口径与可复现实验

面向：**要判断结论能不能信**、要复核我们的实验、或要在这个项目上继续做研究的人。

---

## 1. 谁有判决权（这是本项目的第一原则）

```
自然语言验证目标
   ↓  AI 只做这一件事：提出结构化的 TestPlan（受 JSON Schema 约束）
[门 1] 严格 Schema 校验         → 字段名错/杜撰字段/越界取值，直接拒绝
[门 2] DUT 合约端口匹配          → 端口名或方向对不上，直接拒绝
[门 3] 参考模型复算并覆盖 AI 数字  → AI 猜错期望值不能制造"通过"或"失败"
[门 4] 结构化断言只用受限模板      → 模型无法注入自由 Verilog/SVA 代码
   ↓  确定性模板生成 testbench（不解析、不拼接模型给的任何文本）
Icarus Verilog + vvp 编译与仿真   ← 唯一的 PASS/FAIL 权威
   ↓
结构化记录（IVERILOG_AI_RESULT）→ 报告 / VCD 分析 / 覆盖率 / 分层证据
```

**推论**：AI 的"自评""解释""置信度"都不参与判决；模型再强也不会让结论更可信，
只会让**激励更容易覆盖到边界**。

---

## 2. 四个容易读错的字段

| 字段 | 真实含义 | 常见误读 |
|---|---|---|
| `status` | 本次运行的总体状态（`passed` / `passed_with_warnings` / `failed` / …） | 以为 `passed` 就等于"设计对了" |
| `passed` | **只表示"没有 ERROR 级失败"**；功能不匹配按策略记 WARN，所以缺陷变体也是 `true` | 用它判断设计是否正确 |
| `failures` | 结构化失败记录条数（不匹配的检查项） | 忽略它，只看 `passed` |
| `verdict` | 单一结论词：`passed` / `failed_checks` / `failed` / `inconclusive` | —— **判"这次算不算过"应该看它** |

一次"检出 3 个缺陷"的运行长这样：`status=passed_with_warnings`、`passed=true`、
`failures=3`、`verdict=failed_checks`、退出码 1。

---

## 3. 证据等级：结论有多可信

| 等级 | 含义 | 什么时候出现 |
|---|---|---|
| `reference_model` | 期望值由与 RTL 逐拍对齐的确定性模型复算并覆盖 | 15 个内置案例 |
| `ai_generated` | 没有参考模型，用的是 AI 写的期望值 | 自定义 RTL |
| `none_given` | 计划和参考模型都没给期望值，这一轮只有激励与断言起作用 | 自定义 RTL + 离线规划 |

**对齐是硬要求**：模型与 RTL 差一拍，预言机就会把"参考设计通过"改写成"失败"——比没有预言机
更糟。所以规则是"**对齐一个、加入一个**"，`SUPPORTED == AUTHORITATIVE` 有测试断言守着。
复现：

```powershell
python -m pytest tests/core/test_reference_model_alignment.py -q   # 4 个种子逐拍零差异
```

---

## 4. 覆盖率的口径（不要读成代码覆盖率）

| 指标 | 怎么算 | 能说明什么 |
|---|---|---|
| 测试计划执行覆盖率 | 计划里的向量/检查项跑完比例 | 计划有没有被执行完 |
| **信号活动覆盖率** | VCD 里动过的信号 / 声明信号 | 激励碰到了哪些信号 |
| **取值覆盖** | 信号到达过的不同取值 / 位宽可能取值 | 激励是否真的把信号驱动起来 |

Icarus 没有编译期插桩，**本项目不声称**语句/分支/条件/翻转覆盖率。实测：只看"动没动"没有
区分力（弱激励也能 100%），加入取值覆盖后才能区分 38% vs 6%。口径见 `docs/coverage.md`。

---

## 5. 复现我们发布的每一个数字

```powershell
python -m pytest -q                            # 513 passed，0 warning
python scripts/run_benchmark_matrix.py         # 15/15 参考、83/83 检出、0 误报、0 不可判定
python scripts/run_synthesis_matrix.py         # 98/98 可综合
python scripts/run_pipeline_matrix.py          # 离线 AI 路径 15/15
python scripts/compare_models.py <模型目录...>  # 多模型对比表（含可比性检查）
```

产物：`.iverilog-ai/{benchmark-matrix,synthesis-matrix,pipeline-matrix}/` 下有 `matrix.json`
（机器读）与 `matrix.md`（人读），每个变体保留原始日志。

### 实验口径的三条纪律（我们踩过的坑）

1. **token 按 `request_id` 去重**：一次请求的计划被同案例所有变体复用，按行累加会放大 6–13 倍；
2. **检出率分两个口径**：单轮平均（可与只跑 1 轮的基线比较）vs 多轮累计并集（"命中过就算"，
   不能拿来证明"模型一轮就行"）；
3. **不可判定如实记录**：计划被拒绝/超时/编译失败都记为 `inconclusive`，不折算成检出或漏检。

---

## 6. 扩展这个项目

### 加一个基准案例（成套提交，缺一不可）

| 文件 | 要求 |
|---|---|
| `rtl/<case>.v` | Verilog-2001，首行 `` `timescale `` |
| `examples/<case>_contract.json` | 显式端口方向与位宽、时钟、复位；参数写进 `parameters` |
| `spec/<case>_spec.md` | 行为规格（含边界条件） |
| `tb/tb_<case>.v` + `tb/tb_<case>_boundary.v` | 功能与边界 testbench，每条断言打印 `IVERILOG_AI_RESULT {...}` |
| `benchmarks/manifest.json` | 加入 `categories`，并为每个缺陷补 `defects` 条目 |
| `src/iverilog_ai/core/benchmark_cases.py` | 在 `CASE_TABLE` 补 `rtl`/`testbench`/`top` |
| `src/iverilog_ai/core/reference_model.py` | 加入 `SUPPORTED`/`AUTHORITATIVE`/`INPUT_DEFAULTS` 并实现 `step` |

**门禁会替你检查**：案例表与清单不一致 → 基准矩阵**开跑前**报错；两个缺陷代码相同 →
测试失败；参考模型与 RTL 不对齐 → 对齐测试失败。详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

### 加一条静态规则

在 `core/static_review.py` 的规则注册表加条目，并在
`tests/core/test_static_review_rules.py` 的 `RULE_CASES` 里给**正例和反例**——
没有反例的规则不算完成。

### 加一个参考模型

先与 RTL 逐拍对齐，再进 `AUTHORITATIVE`。对齐过程中最容易犯的错是**非阻塞赋值语义**：
`a <= b; c <= a;` 里 `c` 拿到的是**旧的** `a`。我们踩过 9 个这类错误，逐条记在
`docs/reference_model_alignment.md`。

---

## 7. 已知边界（不要越界解读）

- 不做时序签核、不做布局布线/比特流、不做上板验证；
- 不做代码覆盖率、不做形式化等价证明；
- 参考模型只覆盖内置案例，自定义设计只能回退到 AI 或人工期望值；
- "综合通过"只说明可映射到通用门级单元，**与功能正确性无关**（实测：一个缺陷变体综合出
  0 个单元，照样"综合通过"）；
- 自定义 RTL 不是安全沙箱：不要跑来路不明的设计。
