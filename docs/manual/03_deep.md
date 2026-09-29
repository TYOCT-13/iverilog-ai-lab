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

### 门 3 里的"参考模型"是什么

**它是一个独立手写的确定性状态机，不是 AI，不是 RTL 的复制品，也不是 testbench。**
代码在 `src/iverilog_ai/core/reference_model.py`：每个内置案例对应 `step()` 里的一段
分支（形如 `if design == "pulse_stretcher": ...`），按 Verilog 的**非阻塞赋值**语义
逐步推进寄存器状态，算出"这一拍输出应该是什么"。

**它依据三样东西复算**（其中**不包含** AI 写的期望值）：

| 依据 | 具体是什么 | 为什么必须固定 |
|---|---|---|
| ① 激励 | **同一份 TestPlan 的 `vectors[].inputs`** | 它不重新生成激励，而是复用 AI 给的激励、只独立算输出——这样比的才是"同一个激励下谁算得对" |
| ② 端口表 | DUT contract 的 `ports` | 只返回 contract 里真实存在的端口，避免模型凭空造出一个信号名 |
| ③ 未列出的输入取什么值 | `INPUT_DEFAULTS`（每个案例一张表） | 向量经常只写本拍关心的端口。模型和 testbench 若对这个"没写的端口"理解不同，就会算出不同的期望值——实测中 `debounce` 因此产生过 **25 条伪失败** |

**覆盖范围是分级的，不是"全都有"**：

- `SUPPORTED`：15 个内置案例都已建模；
- `AUTHORITATIVE`：**只有已与 RTL 逐拍对齐的模型才有资格覆盖 AI 数字**。未对齐的模型
  只用于诊断（`check_plan_consistency`），不参与裁决——否则模型里一句写错的语义就会把
  "参考设计通过"改写成"失败"，比没有预言机更糟；
- 覆盖不到的设计（自定义 RTL）**显式回退**，并把期望值证据等级如实降级标注（见第 4 节）。

**对齐怎么证明**：`tests/core/test_reference_model_alignment.py` 把同一组向量同时喂给
模型和 RTL，逐拍比较可观测输出，要求**零差异**。规则是"对齐一个、加入一个"，并有
`SUPPORTED == AUTHORITATIVE` 的断言守着。复现：

```powershell
python -m pytest tests/core/test_reference_model_alignment.py -q   # 4 个种子逐拍零差异
```

**为什么值得这么做**：没有门 3 时，AI 猜错期望值会同时制造两种假象——它可能让一个
正确的设计被判"失败"（假失败），也可能让一个错误的实现被判"通过"（假通过），而这两种
情况在旧口径下都被算作"AI 找到了问题"。门 3 把 AI 的数字降级成**一项诊断指标**
（`ai_expected_mismatch`），裁决只用参考模型复算的值。

---

## 2. AI 交出来的东西：结构化 TestPlan

**是"指出要测什么"，但不止于此。** 一份 TestPlan 必须回答三个问题，缺一个都无法执行：

1. **测哪个设计**：`design`；
2. **打算覆盖什么意图**：`objective` 与每个向量的 `rationale`（给人读，用于审查）；
3. **具体怎么激励、期望看到什么**：每个向量的 `inputs`（每个输入端口给什么值、跑几拍）
   与 `expected`（哪些输出应该是什么值）。

再加可选的一层：`assertions`——**不依赖期望值**的时序性质（见第 3 节末尾）。

一个真实例子（`examples/simple_alu_plan.json`，8 位 ALU）：

```json
{
  "schema_version": "1.0",
  "design": "simple_alu",
  "objective": "cover addition, bitwise operation, shift, and zero flag",
  "vectors": [
    {
      "name": "add_boundary",
      "inputs": {"a": 255, "b": 1, "op": 0},
      "expected": {"result": 0, "carry": 1, "zero": 1},
      "rationale": "exercise carry and zero at the same boundary"
    },
    {
      "name": "and_mask",
      "inputs": {"a": 240, "b": 15, "op": 2},
      "expected": {"result": 0, "carry": 0, "zero": 1},
      "rationale": "verify bitwise AND"
    }
  ]
}
```

读法：`add_boundary` 这条不是"检查一下加法"，而是"**把 a=255、b=1、op=0（加法）驱动进去，
跑完看 result 是否为 0、carry 是否为 1、zero 是否被置起**"。第一行是意图（边界：进位与
零标志同时发生），第二行落到具体数值——这才叫可执行、可复算、可判对错的计划。

**"结构化"是关键限定词**，它带来三件事：

- **可校验**：字段名、类型、取值范围都由 JSON Schema 约束。多写一个字段、少写一个必填、
  端口名拼错，都会被**拒绝**，而不是"尽力理解"后接着跑；
- **可复算**：有了 `inputs`，参考模型才能独立算出 `expected` 并覆盖 AI 的数字（第 1 节门 3）；
- **不可越权**：计划里**没有**任何地方能塞进 Verilog/SVA 代码或 shell 命令。模型只填数据，
  testbench 由确定性模板生成——这是门 4。

**AI 猜的 `expected` 会被覆盖**：内置案例里，AI 写的 `expected` 只作为"AI 期望值准确率"
这一项诊断指标；真正用于裁决的是参考模型复算值。自定义设计没有参考模型时才回退到
AI 的 `expected`，并如实标注证据等级（第 4 节）。

---

## 3. 四个字段，分三层读（不要混着看）

这四个字段同时出现在同一份 JSON 里，而且 `status` 与 `verdict` 的取值**同名**
（都可能是 `passed`）。更麻烦的是：一次**成功检出 3 个缺陷**的运行里
`"passed": true`——因为功能不匹配按裁决策略记 WARN。混着看必然读错。

所以本项目给**每一层**一套互不重叠的说法。措辞表就是代码里的
`src/iverilog_ai/core/labels.py`，报告、网页、手册共用同一份，不允许各写一套：

| 层 | 这一层回答的问题 | 字段 | 该层的说法（用这些词，不要用"通过"） |
|---|---|---|---|
| **运行层** | 工具跑完了吗？ | `status` | 运行完成 / 运行完成（有告警）/ **运行失败** / 编译失败 / 超时 / 配置错误 / 无法判定 |
| **比对层** | 逐项检查对上了几条？ | `passed` | **无错误级失败**：是 / 否。它**只**表示"没有 ERROR 级失败"，不代表设计对了 |
| **比对层** | 同上 | `failures` | **比对不一致条数**（不匹配的检查项个数） |
| **结论层** | 这份设计到底对不对？ | `verdict` | **符合预期** / **检出设计问题** / **未得出结论（工具出错）** / **证据不足** |

一次"检出 3 个缺陷"的运行长这样——**整段没有一处说"通过"**：

```
status   = passed_with_warnings  → 运行状态：运行完成（有告警）
passed   = true                  → 比对层：无错误级失败
failures = 3                     → 比对情况：3 条比对不一致
verdict  = failed_checks         → 设计结果：检出设计问题
退出码   = 1
```

**判"这份设计对不对"永远看 `verdict`**；`status` 只回答"工具跑完了吗"，`passed` 只回答
"有没有 ERROR 级失败记录"。三层的关系是：

- `status` 说工具状态，**与设计好坏无关**——`compile_failed` 只说明代码没编译过，
  `timeout` 只说明跑太久；
- `passed` 是个**很弱的**标志位，正常检出缺陷时它也是 `true`。它的历史用途是让脚本
  快速过滤"仿真有没有炸"，**不要**用它判断功能正确性；
- `verdict` 才是结论，并且把"工具出错"和"设计有问题"分开：`未得出结论（工具出错）`
  绝不是"设计错了"，`证据不足` 也不是"设计对了"。

### 与之正交的第四层：结构化断言

`assertions` 是**不依赖期望值**的另一层证据，由工具在采样记录上判定，模板只有五种
（`signal_equals` / `signal_stable` / `never_high` / `signal_sequence` / `signal_implies`）。
它的价值在"没有期望值"的那些运行里：期望值证据等级是 `未给出期望值` 时，断言仍在起作用。
字段清单与判定语义见 `src/iverilog_ai/ai/schema.py` 的 `ASSERTION_FIELDS`
（**单一事实来源**，校验器、执行器与提示词共用它）。

---

## 4. 期望值证据等级：结论有多可信

这一层与第 3 节的三层**正交**：它不改变"设计对不对"，只说明**凭什么这么说**。

| 证据等级 | 中文说法 | 含义 | 什么时候出现 |
|---|---|---|---|
| `reference_model` | **参考模型复算** | 期望值由与 RTL 逐拍对齐的确定性模型独立复算并覆盖 AI 数字 | 15 个内置案例 |
| `ai_generated` | **AI 生成** | 没有参考模型，用的是 AI 写的期望值——AI 猜错会直接影响结论 | 自定义 RTL |
| `none_given` | **未给出期望值** | 计划和参考模型都没给期望值，这一轮只有激励与断言起作用 | 自定义 RTL + 离线规划 |

括号里的英文枚举值是**机器字段**，保留可检索性；给人看的一律用中文说法。

**对齐是硬要求**：模型与 RTL 差一拍，预言机就会把"参考设计通过"改写成"失败"——比没有
预言机更糟。所以规则是"**对齐一个、加入一个**"（见第 1 节门 3）。

---

## 5. 覆盖率的口径（不要读成代码覆盖率）

| 指标 | 怎么算 | 能说明什么 |
|---|---|---|
| 测试计划执行覆盖率 | 计划里的向量/检查项跑完比例 | 计划有没有被执行完 |
| **信号活动覆盖率** | VCD 里动过的信号 / 声明信号 | 激励碰到了哪些信号 |
| **取值覆盖** | 信号到达过的不同取值 / 位宽可能取值 | 激励是否真的把信号驱动起来 |

Icarus 没有编译期插桩，**本项目不声称**语句/分支/条件/翻转覆盖率。实测：只看"动没动"没有
区分力（弱激励也能 100%），加入取值覆盖后才能区分 38% vs 6%。口径见 `docs/coverage.md`。

---

## 6. 复现我们发布的每一个数字

```powershell
python -m pytest -q                            # 700 passed / 1 skipped
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
3. **不可判定如实记录**：计划被拒绝/超时/编译失败都记为 `证据不足`，不折算成检出或漏检。

---

## 7. 扩展这个项目

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

### 加一层的显示措辞

三层的说法集中在 `src/iverilog_ai/core/labels.py`，报告与页面都从那里取。**不要**在
报告或页面里另写一套中文——那正是"同一个 `passed` 在三处表示三件事"的来源。

---

## 8. 已知边界（不要越界解读）

- 不做时序签核、不做布局布线/比特流、不做上板验证；
- 不做代码覆盖率、不做形式化等价证明；
- 参考模型只覆盖内置案例，自定义设计只能回退到 AI 或人工期望值；
- "综合通过"只说明可映射到通用门级单元，**与功能正确性无关**（实测：一个缺陷变体综合出
  0 个单元，照样"综合通过"）；
- 自定义 RTL 不是安全沙箱：不要跑来路不明的设计。
