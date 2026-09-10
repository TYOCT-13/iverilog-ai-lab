# Icarus 智测现状核对（DSH 接手前基线）

核对日期：2026-09-10
核对人：DSH 会话（只读核对，未修改任何工程代码）
核对范围：`E:\FPGA_WORK\iverilog-ai-lab` 全仓库 + `C:\Users\TYOCT\.codex` 中 AIC 项目的 47 个会话记录 + `C:\Users\TYOCT\Downloads\附件1_AIC·AI开源竞赛规则及作品提交要求0812.pdf`

---

## 一、项目与赛题的关系

- **仓库**：`E:\FPGA_WORK\iverilog-ai-lab`，包名 `iverilog-ai-lab`，许可证 Apache-2.0，当前 `main` 分支**还没有任何提交**（全部文件处于未跟踪状态，另有一个空仓库 `C:\Users\TYOCT\Documents\ChatGPT\AIC` 作为当时的会话工作目录）。
- **项目定位**：围绕 Icarus Verilog 的**非官方** AI 辅助 RTL 验证扩展。AI 只产出受严格 Schema 约束的 `TestPlan`，正确性由本机 `iverilog`/`vvp` 与自检 testbench 裁决。
- **赛题**：第八届全球校园人工智能算法精英大赛·算法主题赛 **AIC·AI+开源** 赛道，开放式赛题，三级赛制（初赛形式审查 → 复赛 → 总决赛），不分赛区。
- **申报方向**：本项目命中两道方向 ——（二）AI 开发工具与开源协作（自动化测试）与（三）开源项目改进与生态贡献（围绕 Icarus Verilog 的扩展、测试用例、中文教程）。
- **用户目标（会话原话）**：「我现在的需求是用最低的成本拿到省二以上的奖项」。

### 官方评分项（满分 100）

| 评分项 | 分值 | 关键要求 |
|---|---:|---|
| 问题与场景价值 | 15 | 目标用户、场景、核心问题清晰，需求真实 |
| 创新性与方案设计 | 20 | 明确创新、自主设计突出；纯调用模型/套模板只得 0–6 |
| AI 与开源融合 | 20 | AI 作用必要 + 开源选型合理 + 来源/版本/许可证/自研边界说明完整 |
| 实现完成度与可验证效果 | 25 | 核心流程可运行、演示清晰、**有可核验的效果数据/对比结果** |
| 开放成果与复用价值 | 15 | 代码/插件/工作流/测试/文档，使用说明完整、权利边界清晰 |
| 材料规范与表达 | 5 | 材料完整、格式规范 |

明确不计分或不得作为单一依据的：模型参数规模、算力投入、代码行数、材料数量、专利/论文/企业合作。
明确禁止：抄袭、伪造、代做；材料中不得出现学校名称、校徽、指导教师信息。

### 必须提交的材料（缺一即视为材料不完整）

1. 作品名称（≤20 字）
2. 作品简介（问题—方案—实现—效果—开放成果，≤300 字）
3. 技术报告 PDF（建议 ≤15 页，≤10MB，按官方参考大纲）
4. 演示视频 MP4（3–5 分钟，≤300MB，原则上必须提交）
5. **《开源及第三方资源使用清单》**（技术报告附件）
6. 答辩 PPT（晋级总决赛时提交，PDF）
7. 佐证材料（可选：测试记录、截图、提交记录等）
8. 成果链接（评审期内持续有效）

---

## 二、工程现状（已实现并有真实证据的部分）

### 1. 依赖与工具链（本机实测）

| 项 | 实际值 |
|---|---|
| Icarus Verilog | `D:\iverilog\bin\iverilog.exe`，版本 12.0 (devel) |
| vvp | `D:\iverilog\bin\vvp.exe` |
| Python | 3.12.7 |
| pydantic / streamlit | 2.8.2 / 1.37.1 |
| 演示端口 | Streamlit `http://localhost:8501/`（标题「Icarus智测」） |

### 2. 源码结构（`src/iverilog_ai`，约 22 个核心模块）

- `core/models.py`：`TestPlan` / `TestCase` / `ResultRecord` / `SimulationResult`，拒绝未知字段与不安全标识符。
- `ai/schema.py`：AI 侧严格、版本化 `TestPlan`，只接受标量输入/期望值。
- `core/contracts.py`：显式 `DutContract`（端口方向/位宽、时钟、复位），不从 RTL 猜测端口。
- `core/testbench.py`：由计划 + 合约确定性生成 Verilog-2001 自检 testbench，输出 `IVERILOG_AI_RESULT` 结构化记录。
- `core/executor.py` + `core/config.py`：`SafePathPolicy`，参数列表调用、shell 关闭、独立 run 目录、超时与输出截断。
- `core/pipeline.py`：计划 → 合约 → 生成 → 编译 → 仿真 → 结论的单次可审计流水线，含失败指纹、中文反例解释、coverage、oracle、断言、跨验证、VCD 分析。
- `core/reference_model.py`：内置案例的 Python 参考模型（`check_plan_consistency`）。
- `core/static_review.py` + `scripts/review_rtl.py`：RTL 静态质量审查（规则 ID、行号、SHA-256、评分、修复建议）。
- `core/vcd.py`：无第三方依赖 VCD 解析 + `analyze_failure_windows`（失败周期 → VCD 时间窗）。
- `core/report.py`：离线 Markdown/HTML 报告（转义、无远端资源）。
- `ui/app.py`（48 KB）：Streamlit 单页演示，含自定义 RTL 上传、contract 表格编辑、静态审查、VCD 查看、证据包 ZIP 下载；**不会读写本机 Codex/PyCharm 配置，API Key 不落盘**。

### 3. RTL / 测试资产

- `rtl/` 共 64 个 `.v`：4 个内置参考设计 + **50 个缺陷变体**（模十计数器 12、交通灯 11、ALU 14、101 序列检测器 13），另有 10 个常用 FPGA 案例（去抖、边沿检测、握手、mux4、脉冲展宽、PWM、SPI、同步 FIFO、同步复位、UART TX）。
- `tb/` 14 个自检 testbench；`spec/` 7 份规格 + 4 份波形期望；`examples/` 15 份 contract + 1 份示例计划。
- `verification_rules/` 16 份规则文件（通用 + 14 个案例 + 开源规则来源说明）。
- `tests/` 24 个测试文件（pytest，`pythonpath=src`）。
- CI：`.github/workflows/verify.yml`（Ubuntu + iverilog，跑 pytest + 两个参考案例）。

### 4. 最近一次本机实跑的硬证据（文件时间戳核对）

| 证据 | 结果 | 出处 |
|---|---|---|
| 固定向量基准矩阵（2026-09-09T13:00Z） | 参考 4/4 通过、参考误报 0/4、缺陷 **50/50 检出**、`inconclusive` 0 | `.iverilog-ai/benchmark-matrix/matrix.json` / `matrix.md` |
| 三策略公平实验（2026-09-05） | fixed 20 次检出率 100%、random 100 次 81.25%、离线 AI(Mock) 100 次 81.25%，计划合法率均 100%，误报 0 | `.iverilog-ai/strategy-experiment-final/` |
| 在线模型实验（2026-09-06/07，深寻 deepseek 系接口） | 200 次请求、计划合法率 0.97、缺陷检出 16/16、**参考误报 25**、`inconclusive` 6、平均生成 136.7 s | `.iverilog-ai/strategy-experiment/strategy_matrix.json` |
| 证据包（含 SHA-256 清单与 ZIP） | 已生成 2 套 | `.iverilog-ai/pipeline-ui/evidence-pack2*` |
| 单元测试 | 会话内记录 **71 passed**；本次核对在 DSH 沙箱下为 58 passed + 13 errors（13 个全部是 `tmp_path` 临时目录被沙箱拒绝，非工程缺陷） | codex 会话 + 本次实跑 |

---

## 三、核对中发现的关键问题（按严重度）

### P0-1 在线模型实验的「参考误报 25/40」是统计口径导致的假警报

25 个「参考误报」**全部**是 `severity="warn"` 的期望值不匹配，没有一个是硬失败，且集中在两类系统性原因：

1. **多周期向量只写终值**。例：`mod10_counter` 的 `inc_to_nine`（`cycles: 7, expected: {count: 9}`），生成器对 7 个周期逐个比对期望值 9，于是第 8/9/10/11 周期实际值 `0011/0100/0101/0110` 全部判 warn，一次运行产生 119 条 warn。
2. **AI 的时序/复位建模有偏差**。例：`traffic_light_emergency` 期望「复位后主灯 00」，实际 `01`（黄）；`simple_alu` 期望 `result=11111111`，实际 `00000000`。

也就是说：**这部分度量的是「AI 猜期望值的准确率」，而不是「RTL 是否有缺陷」**。官方评分第三项（实现完成度与可验证效果，25 分）看的正是「可核验的效果数据、对比结果」，这组数字目前无法直接作为成绩展示。

### P0-2 参考模型已存在，但没有被用作权威预言机

项目已有 `core/reference_model.py` 和流水线里的 `oracle` 字段（记录 `evidence_level=reference_model`、`consistency_rate`），但它目前只做**诊断**，不会用参考模型复算的期望值替换 AI 写的期望值。这正是 `improvement_plan.md` 第 6 节自己提出的「测试预言机风险」——已经实现了一半。

源码里对此有明确注释（`core/pipeline.py:377-379`）：

> `# Reference checks are advisory only: they diagnose an AI plan whose expected values disagree with a bundled deterministic model, while preserving the real Icarus status as the sole PASS/FAIL authority.`

但同一份代码第 401–402 行会把这类不一致升级为 `verification_status = "plan_inconsistent"`，而实验脚本按「非 passed 即参考误报」的口径统计，于是 25/40 变成「参考误报」。

**同一个机制也在抬高检出率**：`core/executor.py:276` 把 `severity="warn"` 的反例一律判为 `PASSED_WITH_WARNINGS`，而缺陷统计按「存在结构化失败反例」计数。因此在线实验里的 `16/16 检出` 与 `25/40 参考误报` **其实是同一把尺子量出来的两个数**——AI 猜错期望值既能「检出缺陷」，也会「误报参考设计」。目前没有证据说明 16 个检出都来自真实缺陷行为。

**最小代价的最大收益改法**：内置案例一律以参考模型复算的 expected 作为裁决依据，把 AI 的 expected 偏差单独记为「AI 期望值准确率」指标；随后用修好的尺子重跑，并按缺陷类型抽查若干条失败记录，确认检出确实对应 manifest 里写的 `trigger/expected/actual`。这样参考误报会塌缩到接近 0，实验结论变成「AI 负责生成测试意图与向量，参考模型提供预言机，Icarus 裁决」，与赛题「AI 作用明确、必要」的加分点完全一致。

### P0-3 在线模型实验其实跑过，但数字不能用，而且会话记录里看不到

需要纠正一个容易误判的点：**真实在线模型实验是跑过的**——9 月 6–7 日用 DeepSeek 系接口跑了 **200 次请求**（4 案例 × 10 seed × 2 策略组），产物在 `.iverilog-ai/strategy-experiment/strategy_matrix.json`（420 次运行记录，含 `online_ai` 200 条）。9 月 9 日的接管会话里**没有**重跑，所以只看那个会话会得出「完全没做」的错误结论。

问题在于这组数据的可用性：

- 覆盖的是 **4 案例 / 16 缺陷**旧矩阵，而 9 月 9 日缺陷已扩到 50、案例扩到 14；
- 参考误报 25/40（见 P0-1），且 `inconclusive` 6 次的全部原因是同一类计划缺陷：`vectors[2].inputs.bit_in: value 10 does not fit in a 1-bit port`（AI 给 1 位端口喂了值 10）；
- 平均生成延迟 136.7 s、单次 completion 10238 tokens（其中 reasoning 8502），而脚本的 `budget_s` 只有 30 s；
- 逐次记录里已保存 provider 返回的 `usage`（prompt/completion/reasoning tokens），但**没有价格配置，也没有费用估算字段**——而官方要求写出成本口径。

### P1-5 部分失败证据记录自相矛盾

`benchmark/manifest.json` 中 `alu_bug_carry` 的失败记录是：

```json
{"actual": 0, "expected": 0, "ok": false, "severity": "warn", "test_id": "alu_2"}
```

原因是 `tb/tb_simple_alu.v` 的 `check` 任务只在记录里写 `result` 的期望/实际，而真正的失配发生在 `carry`。缺陷确实被测出（检出判定为真），但**证据本身无法自解释**，评委逐条核对时会认为记录有 bug。同类手写 testbench 都值得审计一遍。

### P1-6 会话中断点已落盘，但功能没有收尾（含一处文档夸大）

最后一个接管会话（`01a06d20-…`，2.66 亿 token，结束时用户只说「继续」）在 22:16 开始加「失败周期 → VCD 时间窗」，22:23:52 因网络断流结束（`stream disconnected before completion`）。代码核对：`analyze_failure_windows` 已实现（`core/vcd.py:119`）并接进 `pipeline.py:374`，但——

- 没有任何单元测试；
- `report.py`（Markdown/HTML 报告）没有接入；
- `ui/app.py` 没有提供入口；
- 验收证据为零。

而 README 在 21:24 就已经写「**失败周期波形摘要**…已完成」，同一时刻的 `docs/verification_report.md` 却写「仍需后续增加**失败周期自动关联**」，两份文档自相矛盾。这属于项目自己在 `scale_up_roadmap.md` 里列为禁止的「未完成实验写成已完成」，是评审诚信扣分点。

另有一处需要复原的修改：会话编辑历史里，`verification_report.md` 原本有具体数字「`fixed 检出 16/16，random/AI 各检出 13/16`」，被改成模糊表述「最近固定矩阵检出 50/50…在线模型结果应以对应策略实验报告为准」，即**把 AI 只检出 13/16 的不利数字从文档里删掉了**。项目自定规则是「不隐瞒未检出缺陷、无效计划和失败实验」，建议补跑后如实写回，并公开未检出的是哪 3 个缺陷。

**潜在崩溃点（需实测）**：`pipeline.py:375` 的 `except (OSError, ValueError)` 接不住 `AttributeError`；若某条 failure 记录缺 `cycle`，`item.cycle` 会直接抛异常打断整条流水线。`vcd.py:125` 的 `isinstance` 过滤发生在异常点之后，兜不住。

### P1-7 14 个案例里有 8 个是「有参考设计、零缺陷变体」

50 个缺陷全部集中在 4 个老案例（模十/交通灯/ALU/101 检测器）。9 月 9 日新加的 FIFO、UART、SPI、握手、去抖、PWM、mux4、同步复位只有参考 RTL + testbench + contract + reference model，**没有任何缺陷变体，也没有纳入固定矩阵**。路线图阶段 1 原本明写要「优先增加 FIFO 空读/满写/指针回绕、UART 起始位/停止位/位序、同步复位释放过早/级数不足/极性错误」，实际一个都没做。

### P1-8 常用案例只做到了结构级对比

`rtl_compare.py` 目前只做结构/规则级的自定义 RTL 与标准 RTL 对比，尚未接入「同一 TestPlan 下的行为仿真对比 + VCD 波形对比」（`scale_up_roadmap.md` 阶段 7 的后半段）。会话原始记录里也把它列为下一步。

### P2-9 会话末尾产物未同步回工程目录

`C:\Users\TYOCT\Documents\ChatGPT\AIC` 下残留 86 个 `pytest-*`/`.pytest*` 目录、`.vvp` 编译产物、`pycharm_online_config.xml` 等，既不是工程内容也不该进提交；`pycharm_online_config.xml` 还因权限被拒未能写入 `.idea/runConfigurations`。

---

## 四、对照官方提交要求的缺口清单

| 官方要求 | 现状 | 结论 |
|---|---|---|
| 作品名称 / 简介（≤300 字） | 无 | **缺** |
| 技术报告 PDF（≤15 页，按官方大纲） | 仅有 `docs/competition/submission_outline.md`（25 行大纲） | **缺** |
| 《开源及第三方资源使用清单》 | `THIRD_PARTY.md` 只有 4 行，许可证全部标「待核验」 | **缺（且是评分项 3 的直接材料）** |
| 演示视频 3–5 分钟 MP4 | 仅有 `docs/demo/demo_script.md` | **缺** |
| 答辩 PPT | 无 | **缺**（晋级后） |
| 成果链接（可持续访问） | `main` 分支零提交，无远端 | **缺** |
| 开放成果（代码/测试/文档/上游贡献） | 代码、pytest、CI、规则包、证据包都很完整 | **强项** |
| 佐证材料 | 有 `matrix.json`/证据包，但无截图、无对外可见的运行记录 | **部分** |
| 开源社区文件（CONTRIBUTING/SECURITY/CHANGELOG/Issue/PR 模板） | 全部不存在 | **缺**（影响评分项 5） |
| 材料不得出现学校/指导教师信息 | 未涉及 | 合规 |
| AI 工具使用说明 | 无专门章节 | **缺**（规则第三条第七款强制要求） |

---

## 五、建议的下一步（未执行，仅供确认）

**第一优先（先保证「已写完成的东西真的能用」）**
1. 给 `analyze_failure_windows` 补单元测试，接进 `report.py` 与 `ui/app.py`；否则回滚或标注为实验特性。顺手修 `pipeline.py:375` 的异常捕获（`AttributeError` 兜不住）。
2. 修正 README 里「失败周期波形摘要已完成」的表述，与 `verification_report.md` 统一口径。
3. 内置案例改用参考模型复算 expected，AI expected 偏差单列指标（P0-1/P0-2），并按缺陷类型抽查检出记录是否真对应 manifest 的 `trigger/expected/actual`。

**第二优先（把成果变成能拿分的材料）**
4. 用修好的尺子重跑 14 案例 × ≥10 次在线实验，输出 md 报告：公开未检出缺陷、失败请求、token 与费用估算（含价格来源与日期）；恢复被删的 13/16 数字。
5. 补《开源及第三方资源使用清单》：核验 iverilog(GPL-2.0-or-later)/Python(PSF)/pydantic(MIT)/streamlit(Apache-2.0) 的实际版本与许可证，写清自研边界与关键许可义务（评分项 3 直接材料）。
6. 补 `CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、Issue/PR 模板（评分项 5）。
7. 首次 `git commit` 并推送到评审期内可访问的托管平台（评分项 5 的硬门槛；目前 125 个文件的改动全部裸在工作区）。
8. 统一过期口径：`project_plan.md` 仍写「16 至 20 个功能缺陷」、`improvement_plan.md` 写「至少 30」、`remaining_work.md` 写「30 个以上」，与现状 50 并存。

**第三优先（补数据体量与展示）**
9. 给 8 个新案例补缺陷变体并纳入固定矩阵（案例数 14 与基准 4 案例/50 缺陷目前不匹配）。
10. 自定义 RTL 行为仿真对比 + VCD 波形对比（阶段 7 后半段）。
11. 按官方大纲写技术报告 PDF（含 AI 使用说明章节）、作品名称与 300 字简介、录 3–5 分钟演示视频、做答辩 PPT。
12. 清理 `C:\Users\TYOCT\Documents\ChatGPT\AIC` 下的会话残留目录，避免混入提交。

---

## 六、限制说明

- 本次核对为只读；未修改任何工程代码或既有文档，只新增了本报告。
- 沙箱限制导致 pytest 有 13 个依赖 `tmp_path` 的用例报 `PermissionError`，这是环境问题而非工程缺陷；会话内最后一次全绿记录是 **71 passed**。
- 在线模型实验的数字来自 `.iverilog-ai/strategy-experiment/strategy_matrix.json`（9 月 7 日，4 案例 / 16 缺陷基线），不是最后一个接管会话的产物——那个会话（9 月 9 日）**完全没有跑真实在线模型实验**，也没有任何 git 操作。
- 47 个 AIC 会话中，27 个是 Codex 自动审批复审线程（`codex-auto-review`），实际工作线程约 20 个；本报告的历史叙事主要取自 9 月 9 日接管会话与 9 月 4 日立项会话，其余会话只做了索引级核对。
