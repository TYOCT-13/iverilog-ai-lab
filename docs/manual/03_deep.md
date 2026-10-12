# 深度手册 · 判据、口径与可复现实验

适用对象：需要评估验证结论、复核实验结果，或继续扩展本项目的用户。

---

## 1. 验证流程与判定依据

```
自然语言验证目标
   ↓  AI 提出结构化 TestPlan（受 JSON Schema 约束）
[门 1] 严格 Schema 校验         → 字段名错/杜撰字段/越界取值，直接拒绝
[门 2] DUT 合约端口匹配          → 端口名或方向对不上，直接拒绝
[门 3] 已对齐参考模型复算期望值   → 内置案例采用复算值作为判据
[门 4] 结构化断言只用受限模板      → 模型无法注入自由 Verilog/SVA 代码
   ↓  确定性模板生成 testbench（不解析、不拼接模型给的任何文本）
Icarus Verilog + vvp 编译与仿真   → 产生执行日志与实际采样
   ↓
结构化记录（IVERILOG_AI_RESULT）→ 报告 / VCD 分析 / 覆盖率 / 分层证据
```

AI 的自评、解释和置信度不参与判决。模型可以提出更合适的激励；结果可信度还取决于规格是否明确、期望值是否正确，以及实际执行了哪些检查。

### 参考模型的实现与作用

**参考模型是独立手写的确定性状态机，与 AI、RTL 和 testbench 分开实现。**
代码在 `src/iverilog_ai/core/reference_model.py`：每个内置案例对应 `step()` 里的一段
分支（形如 `if design == "pulse_stretcher": ...`），按 Verilog 的**非阻塞赋值**语义
逐步推进寄存器状态，计算当前周期的预期输出。

**参考模型依据下表复算输出**，不使用 AI 写的期望值。

| 依据 | 内容 | 固定依据的原因 |
|---|---|---|
| ① 激励 | **同一份 TestPlan 的 `vectors[].inputs`** | 它复用 AI 给出的激励，独立计算输出，因此比较双方使用相同的输入 |
| ② 端口表 | DUT contract 的 `ports` | 仅返回接口定义中声明的端口，避免使用未声明的信号 |
| ③ 未列出输入的默认值 | `INPUT_DEFAULTS`（每个案例一张表） | 向量可能仅声明当前周期涉及的输入。模型与 testbench 若采用不同的未声明输入默认值，可能计算出不同的期望值。实测中 `debounce` 因此产生过 **25 条伪失败** |

**参考模型按用途分级**。

- `SUPPORTED`：15 个内置案例都已建模；
- `AUTHORITATIVE`：**只有已与 RTL 逐拍对齐的模型才有资格覆盖 AI 数字**。未对齐的模型
  只用于诊断（`check_plan_consistency`），不参与裁决；错误的模型语义可能使正确 RTL 被报告为失败；
- 覆盖不到的设计（自定义 RTL）**显式回退**，并把期望值证据等级如实降级标注（见第 4 节）。

**参考模型对齐检查**：`tests/core/test_reference_model_alignment.py` 将同一组向量分别输入
模型和 RTL，逐拍比较可观测输出，要求**零差异**。模型经对齐后才加入权威集合，测试通过
`SUPPORTED == AUTHORITATIVE` 检查两个集合是否一致。复现命令如下。

```powershell
python -m pytest tests/core/test_reference_model_alignment.py -q   # 4 个种子逐拍零差异
```

**参考模型复算的作用**：缺少独立判据时，AI 期望值错误可能产生两类误判。它可能让一个
正确的设计被判"失败"（假失败），也可能让一个错误的实现被判"通过"（假通过），而这两种
情况在旧统计口径中都被计入缺陷检出。门 3 将 AI 期望值与参考模型的差异记录为诊断指标
（`ai_expected_mismatch`），裁决只用参考模型复算的值。

---

## 2. TestPlan 结构与字段约束

TestPlan 描述待验证设计、验证目标及具体测试向量。主要字段如下。

1. **设计标识**：`design`；
2. **验证目标与测试说明**：`objective` 与每个向量的 `rationale`（用于人工审查）；
3. **输入激励与期望输出**：每个向量的 `inputs`（输入值及持续周期）
   与 `expected`（哪些输出应该是什么值）。

还可以填写 `assertions`，检查**不依赖期望值**的时序性质（见第 3 节末尾）。

计划示例（`examples/simple_alu_plan.json`，8 位 ALU）：

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

`add_boundary` 将 **a=255、b=1、op=0（加法）** 驱动到输入，检查 result=0、carry=1、zero=1。测试意图是同时覆盖进位和零标志，具体输入和期望值决定这条测试如何执行。

**结构化计划具有以下约束**。

- **可校验**：字段名、类型、取值范围都由 JSON Schema 约束。额外字段、缺失必填字段或
  端口名错误会导致校验失败；
- **可复算**：有了 `inputs`，参考模型才能独立算出 `expected` 并覆盖 AI 的数字（第 1 节门 3）；
- **不可越权**：计划字段不接受自由 Verilog/SVA 代码或 shell 命令。模型仅提供结构化数据，
  testbench 由确定性模板生成，对应门 4。

**内置案例的期望值由参考模型复算**：内置案例里，AI 写的 `expected` 只作为"AI 期望值准确率"
这一项诊断指标；用于裁决的是参考模型复算值。自定义设计没有参考模型时才回退到
AI 的 `expected`，并如实标注证据等级（第 4 节）。

---

## 3. 运行状态与结果字段

这四个字段同时出现在同一份 JSON 里，而且 `status` 与 `verdict` 的取值**同名**
（都可能是 `passed`）。此外，一次检出 3 个缺陷的运行中
`"passed": true`，因为功能不匹配按裁决策略记 WARN。读取时需要区分这些字段。

项目分别为各层定义显示用语。措辞表位于
`src/iverilog_ai/core/labels.py`，报告、网页和手册共用该表，避免含义不一致。

| 层 | 含义 | 字段 | 显示用语 |
|---|---|---|---|
| **运行层** | 工具执行状态 | `status` | 运行完成 / 运行完成（有告警）/ **运行失败** / 编译失败 / 超时 / 配置错误 / 无法判定 |
| **比对层** | 检查结果 | `passed` | **无错误级失败**：是 / 否。它**只**表示"没有 ERROR 级失败"，不代表设计功能正确 |
| **比对层** | 同上 | `failures` | **比对不一致条数**（不匹配的检查项个数） |
| **结论层** | 本轮设计结论 | `verdict` | **符合预期** / **检出设计问题** / **未得出结论（工具出错）** / **证据不足** |

一次检出 3 个缺陷的运行可以记录为下列状态。

```
status   = passed_with_warnings  → 运行状态：运行完成（有告警）
passed   = true                  → 比对层：无错误级失败
failures = 3                     → 比对情况：3 条比对不一致
verdict  = failed_checks         → 设计结果：检出设计问题
退出码   = 1
```

读取设计结果时应结合 `verdict`、期望值来源和检查数。`status` 表示工具执行状态，`passed` 表示
是否无 ERROR 级失败记录。各字段含义如下。

- `status` 记录工具状态，不用于判断功能正确性。`compile_failed` 表示编译失败，
  `timeout` 表示执行超时；
- `passed` 是执行结果的辅助标志，正常检出缺陷时它也是 `true`。它的历史用途是让脚本
  筛选仿真执行异常，不能单独用于判断功能正确性；
- `verdict` 区分工具异常、检查不一致及证据不足。`未得出结论（工具出错）`
  不构成设计功能失败的证据，`证据不足` 也不能认定设计符合预期。

### 结构化断言的判定

`assertions` 是**不依赖期望值**的另一层证据，由工具在采样记录上判定，模板只有五种
（`signal_equals` / `signal_stable` / `never_high` / `signal_sequence` / `signal_implies`）。
未提供向量期望值时，有效断言仍可在采样记录上检查对应性质。
字段清单与判定语义见 `src/iverilog_ai/ai/schema.py` 的 `ASSERTION_FIELDS`
（**单一事实来源**，校验器、执行器与提示词共用它）。

---

## 4. 期望值来源与证据等级

期望值来源与第 3 节的结果字段分别记录。结果字段描述本轮结论，证据等级说明检查所使用的判据来源。

| 证据等级 | 显示用语 | 含义 | 适用情况 |
|---|---|---|---|
| `reference_model` | **参考模型复算** | 期望值由与 RTL 逐拍对齐的确定性模型独立复算并覆盖 AI 数字 | 15 个内置案例 |
| `ai_generated` | **AI 生成** | 没有参考模型，用的是 AI 生成的期望值；该期望值出错会直接影响结论 | 自定义 RTL |
| `none_given` | **未给出期望值** | 计划和参考模型都没给期望值，这一轮只有激励与断言起作用 | 自定义 RTL + 离线规划 |

括号里的英文枚举值是**机器字段**，保留可检索性；用户界面采用对应的中文显示用语。

参考模型需要通过逐拍对齐检查。一个周期的偏差就可能造成正确 RTL 被报告为失败，因此只有完成对齐的模型才加入权威集合（见第 1 节门 3）。

---

## 5. 覆盖率定义与适用范围

| 指标 | 计算方法 | 指标含义 |
|---|---|---|
| 测试计划执行覆盖率 | 计划中已执行向量或检查项的比例 | 计划执行情况 |
| **信号活动覆盖率** | VCD 中发生变化的信号 / 声明信号 | 存在活动的信号范围 |
| **取值覆盖** | 信号到达过的不同取值 / 位宽可能取值 | 信号的已观察取值范围 |

Icarus 没有编译期插桩，**本项目不声称**语句/分支/条件/翻转覆盖率。实测：仅统计信号是否发生变化缺乏
区分力（弱激励也能 100%），加入取值覆盖后才能区分 38% vs 6%。口径见 `docs/coverage.md`。

Agent 另有功能场景覆盖，按实际采样判断是否遇到已登记场景。内置 FIFO 的场景包含空、满、读写请求，以及空读、满写和同拍读写请求。请求场景命中不表示请求被接受，也不表示功能正确。自定义 RTL 未配置场景时，页面会明确提示，不能把没有场景记录解释为覆盖完整。

验证目标、向量说明和场景名称都只是文字。确认某项是否完成，要查看对应激励、采样证据和有效判据；`expected` 与断言均为空、又没有参考模型补充检查时，只能观察行为。编译失败时仿真未执行，覆盖为零不表示全部功能测试失败。

---

## 6. 实验结果复现

```powershell
python -m pytest -q                            # 应全部通过；数量以本次输出为准
python scripts/run_benchmark_matrix.py         # 15/15 参考、83/83 检出、0 误报、0 不可判定
python scripts/run_synthesis_matrix.py         # 98/98 可综合
python scripts/run_pipeline_matrix.py          # 离线 AI 路径 15/15
python scripts/compare_models.py <模型目录...>  # 多模型对比表（含可比性检查）
```

产物：`.iverilog-ai/{benchmark-matrix,synthesis-matrix,pipeline-matrix}/` 下有 `matrix.json`
（程序处理）与 `matrix.md`（人工阅读），每个变体保留原始日志。

### 实验统计要求

1. **token 按 `request_id` 去重**：一次请求的计划被同案例所有变体复用，按行累加会放大 6–13 倍；
2. **检出率分两个口径**：单轮平均（可与只跑 1 轮的基线比较）vs 多轮累计并集（任一轮检出即计入并集，
   不能据此推断单轮检出能力）；
3. **不可判定如实记录**：计划被拒绝/超时/编译失败都记为 `证据不足`，不折算成检出或漏检。

---

## 7. 项目扩展

### 基准案例的新增要求

| 文件 | 要求 |
|---|---|
| `rtl/<case>.v` | Verilog-2001，首行 `` `timescale `` |
| `examples/<case>_contract.json` | 显式端口方向与位宽、时钟、复位；参数写进 `parameters` |
| `spec/<case>_spec.md` | 行为规格（含边界条件） |
| `tb/tb_<case>.v` + `tb/tb_<case>_boundary.v` | 功能与边界 testbench，每条断言打印 `IVERILOG_AI_RESULT {...}` |
| `benchmarks/manifest.json` | 加入 `categories`，并为每个缺陷补 `defects` 条目 |
| `src/iverilog_ai/core/benchmark_cases.py` | 在 `CASE_TABLE` 补 `rtl`/`testbench`/`top` |
| `src/iverilog_ai/core/reference_model.py` | 加入 `SUPPORTED`/`AUTHORITATIVE`/`INPUT_DEFAULTS` 并实现 `step` |

**门禁检查内容**：案例表与清单不一致 → 基准矩阵**开跑前**报错；两个缺陷代码相同 →
测试失败；参考模型与 RTL 不对齐 → 对齐测试失败。详见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

### 静态规则的新增要求

在 `core/static_review.py` 的规则注册表加条目，并在
`tests/core/test_static_review_rules.py` 的 `RULE_CASES` 里提供正例和反例；
缺少反例时，不满足规则新增要求。

### 参考模型的新增要求

先与 RTL 逐拍对齐，再进 `AUTHORITATIVE`。对齐过程中需要核对非阻塞赋值语义：
`a <= b; c <= a;` 里 `c` 使用更新前的 `a`。历史复核记录了 9 项相关错误，详见
`docs/reference_model_alignment.md`。

### 结果显示用语的维护

三层结果的显示用语集中在 `src/iverilog_ai/core/labels.py`，报告与页面都从那里取。**不要**在
报告或页面里另写一套中文，以免同一个 `passed` 在三处被解释成三件事。

---

## 8. 已知限制

- 不做时序签核、不做布局布线/比特流、不做上板验证；
- 不做代码覆盖率、不做形式化等价证明；
- 参考模型只覆盖内置案例，自定义设计只能回退到 AI 或人工期望值；
- "综合通过"只说明可映射到通用门级单元，**与功能正确性无关**（实测：一个缺陷变体综合出
  0 个单元，仍被标记为“综合通过”）；
- 自定义 RTL 的执行环境不提供完整安全沙箱，运行前需确认源码来源。
