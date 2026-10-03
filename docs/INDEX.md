# 资料索引（Icarus 智测 / iverilog-ai-lab）

这一份是**全部材料的入口**。所有路径都相对仓库根 `E:\FPGA_WORK\iverilog-ai-lab`，
带盘符的除外。路径可用 `python scripts/check_doc_index.py` 校验是否仍然存在。

- 仓库：`iverilog-ai-lab`，Apache-2.0；第三方资源保留各自许可；判定权威是 Icarus Verilog 12.0（`s20150603`）
- 本次材料修订：**2026-10-04**；本地代码修改基线 `2ef75da`（提交截止 2026-10-15 20:00 北京时间）
- 状态记号：**有效** = 当前口径，可直接对外引用；**历史** = 反映当时状态，只读归档，
  引用时必须带"旧口径"标注；**待补** = 尚未完成

---

## 0. 最快的阅读路径

| 你想干什么 | 按顺序读 |
|---|---|
| 5 分钟了解这个项目 | `README.md` → `docs/project_overview.md` → `docs/competition/technical_report_draft.pdf` |
| 复核数字是否可信 | `docs/experiment/metric_inventory.md`（每个数字一行：口径/来源/时间/复现命令）→ `docs/competition/submission_gate_checklist.md` → 产物目录 |
| 提交当天照着做 | `docs/competition/final_delivery_snapshot.md` → `docs/competition/submission_gate_checklist.md` → `docs/competition/submission_cover_text.md` |
| 组织真人试用与反馈 | `docs/trial/README.md` → `docs/trial/organizer_workflow.md`；发给参与者从 `docs/trial/participant_start.md` 开始 |

---

## 1. 要交的东西

| 材料 | 路径 | 状态 | 备注 |
|---|---|---|---|
| 技术报告（PDF） | `docs/competition/technical_report_draft.pdf` | 有效 | 27 页 / 正文 22 页 / 925 KB（2026-10-04 重渲染）；官方 PDF 上限 10 MB |
| 技术报告（源） | `docs/competition/technical_report_draft.md` | 有效 | 改完用 `python scripts/markdown_to_pdf.py` 重渲染 |
| 报告配图 | `docs/competition/figures/` | 有效 | 4 张（架构/流程/分层证据/基准），`scripts/make_report_figures.py` |
| 作品名称与简介 | `docs/competition/submission_cover_text.md` | 有效 | 简介按 Unicode 码点实测 **242 字**（含空格标点，平台限制另行核对） |
| 提交前门禁清单 | `docs/competition/submission_gate_checklist.md` | 有效 | 逐项状态 + 证据 + 还差什么 |
| 交付快照 | `docs/competition/final_delivery_snapshot.md` | 历史 | 2026-10-01 的主指标、证据包与当时外部依赖 |
| 演示视频脚本 | `docs/demo/demo_script.md` | 有效 | **视频尚未录制** |
| 证据包（正式，历史快照） | `G:\iai-evidence-pack-final[.zip]` | 历史 | 2026-10-01 核验为 8 文件 / 11.1 KB，sha256 已复核；本轮未重新生成，不能视为当前代码的完整复现包 |
| 证据包（演练） | `G:\iai-evidence-pack[.zip]` | 历史 | 9 文件 / 25.7 KB，含 `waveform.vcd` 样例 |
| 证据包结构说明 | `docs/demo/evidence_pack_guide.md` | 部分历史 | 包结构可参考；旧按钮描述以当前 T08 任务卡与录制指南为准 |
| 引用信息 | `CITATION.cff` | **待补** | `repository-code` 仍是 `example.invalid`，是提交体检里唯一的 error |
| 开源与合规清单 | `docs/competition/opensource_resource_list.md` | 有效 | 第三方来源与许可 |
| 上游贡献说明 | `docs/competition/upstream_contribution.md` | 有效 | Issue/PR 尚未提交 |

---

## 2. 实验与证据

### 2.1 主结果：每计划预算对齐实验与同轮数子集（固定分母）

| 内容 | 位置 |
|---|---|
| 口径定义（预算按规格定、执行前归一化、不可判定按未检出、参考告警作废） | `docs/experiment/experiment_plan.md` |
| **指标总账（每个数字一行）** | `docs/experiment/metric_inventory.md` §3 |
| 离线三组产物（fixed 1 轮 / random 与 ai-Mock 各 5 轮） | `.iverilog-ai/strategy-fair-5rounds/strategy_matrix.json` |
| **真实在线模型原始产物（deepseek-flash，10 轮，seed 0–9）** | `.iverilog-ai/strategy-online-flash/strategy_matrix.json` |
| **seed 0–4 事后子集重算（online / random / Mock 各 5 轮）** | `docs/experiment/matched-budget-2026-10-04/README.md`、`docs/experiment/matched-budget-2026-10-04/summary.json`、`docs/experiment/matched-budget-2026-10-04/selected_runs.json` |
| 只读重算脚本（不调用模型） | `scripts/summarize_matched_budget.py` |
| 运行脚本 | `scripts/run_strategy_experiment.py` |
| 计分与预算实现（纯函数） | `src/iverilog_ai/core/strategy_scoring.py` |

原始在线组为 **10 轮、800 条 runs、130 次计划请求**，累计 63/67（94.0%）、单轮均值 83.4%；
不可判定为 8 条变体 runs，其中参考告警导致失效 5 条。文件总计 1,680 条 runs 包含基线。
random/Mock 各 5 轮，fixed 仅 1 轮，因此原始并集不是同总预算比较。

事后 seed 0–4 子集：在线 **61/67（91.0%）、单轮均值 83.9%、不可判定与参考失效均为 0**；
随机/Mock 57/67（85.1%）、单轮均值 78.2%；fixed 单轮 57/67（85.1%）。
在线相对随机累计净多 4 个，单轮均值仍低于人工固定向量；这是开发集描述性分析。
原始十轮有 128 个请求保存了 usage；按当时标价估算约 **$0.637–1.273**，不是实付账单。
详细边界见报告 §5.3(3) 与指标总账。

### 2.2 消融与基准

| 内容 | 位置 | 状态 |
|---|---|---|
| 消融矩阵（三组离线实测 + 并集推导，83 缺陷；不证明 LLM 增益） | `.iverilog-ai/ablation-matrix/`；脚本 `scripts/run_ablation_matrix.py` | 有效 |
| 基准矩阵（2026-10-01 复跑：参考 15 个误报 0、缺陷 83/83、不可判定 0） | `.iverilog-ai/matrix-final/`；脚本 `scripts/run_benchmark_matrix.py` | 有效 |
| 缺陷基准清单（15 分类 / 83 缺陷） | `benchmarks/manifest.json` | 有效 |
| 参考模型对齐（15/15 逐拍零差异） | `docs/reference_model_alignment.md` | 有效 |
| 分层证据说明 | `docs/layered_evidence.md` | 有效 |
| 管线矩阵 | `.iverilog-ai/pipeline-matrix/`；`scripts/run_pipeline_matrix.py` | 有效 |
| 综合检查（Yosys 可选） | `.iverilog-ai/synthesis-matrix/`；`scripts/run_synthesis_matrix.py` | 有效 |

### 2.3 外部模块（第三方 RTL）验证

| 内容 | 位置 |
|---|---|
| 方案与支持范围 | `docs/experiment/external_modules.md` |
| 结果（15/15 变体判"不同"、3 个等价改写判"一致"、3 个编不过判 `inconclusive`） | `docs/experiment/external_results.md` |
| 抓取与来源固定 | `scripts/fetch_external_modules.py`、`.iverilog-ai/external/manifest.json` |
| 逐案例检查 | `scripts/check_external_module.py` |

### 2.4 历史（旧口径）实验——只读，不得与新口径并列比较

| 内容 | 位置 |
|---|---|
| 双模型 10 次重复（flash 97.0% / pro 95.5%） | `docs/experiment/model_comparison_2026-09-12.md`、`docs/experiment/model_comparison_2026-09-11.md` |
| 首测（11 案例、256 次仿真） | `docs/experiment/online_model_experiment_2026-09-10.md` |
| R10 口径 | `docs/experiment/online_model_r10_2026-09-12.md`、`docs/experiment/model_comparison_r10.md`、`docs/experiment/model_comparison.md` |
| 旧原始产物 | `.iverilog-ai/model-compare-*/`、`.iverilog-ai/online-experiment-real*/` |

---

## 3. 产品、使用与集成

| 内容 | 位置 | 状态 |
|---|---|---|
| 项目总览（最全的一篇） | `docs/project_overview.md` | 有效 |
| 总览 PDF | `docs/project_overview.pdf` | 历史 |
| 架构 | `docs/architecture.md` | 有效 |
| API 集成入口 | `docs/experiment/api_handoff.md` | 有效 |
| 第一次用（分级手册） | `docs/manual/01_beginner.md` | 有效 |
| 进阶 | `docs/manual/02_advanced.md` | 有效 |
| 深入原理 | `docs/manual/03_deep.md` | 有效 |
| 按目标查手册 | `docs/manual/04_by_goal.md` | 有效 |
| 10 分钟复现（含干净环境实测：安装 52.5 s、健康检查 200） | `docs/reproduce_in_10_minutes.md` | 有效 |
| 服务对象与专门适配 | `docs/target_users.md` | 有效 |
| 四层结论词表（运行/比对/结论/对比） | `src/iverilog_ai/core/labels.py` | 有效 |
| 静态规则 | `docs/static_rules.md` | 有效 |
| 覆盖率 | `docs/coverage.md` | 有效 |
| 波形分析 | `docs/vcd_analysis.md` | 有效 |
| 行为对比 | `docs/behavior_compare.md` | 有效 |
| 调试接口 | `docs/debug_interface.md` | 有效 |
| 开源约定库 | `docs/opensource_conventions.md`、`data/opensource_conventions.json` | 有效 |
| 网页启动 / 停止 | `start_ui.cmd`、`stop_ui.cmd`、`start_ui.ps1`、`stop_ui.ps1` | 有效 |
| 图形面板（免命令行） | `IcarusPanel.exe`、`Icarus 智测面板.lnk`、`启动网页演示.lnk`、`停止网页演示.lnk`、`tools/service_panel/` | 有效 |
| GitHub Action | `action.yml`、`docs/upstream/verify-diff-action.md` | 部分：静态检查过，外部调用未验 |
| 第三方许可 | `THIRD_PARTY.md`、`NOTICE`、`LICENSE` | 有效 |

### 3.1 真人试用、独立复核与视频材料

以下是可执行的指南和空白表单，不代表已经收集到真人结果。建议安排 **3–5 名不同角色的试用者**，按能力分配部分任务；这是项目的组织安排，不是声称比赛官方规定了人数。

| 内容 | 位置 | 状态 / 使用范围 |
|---|---|---|
| 真人试用总入口 | `docs/trial/README.md` | 有效；区分参与者、组织者、复核者 |
| 组织者流程 | `docs/trial/organizer_workflow.md` | 有效；邀请、分配任务、观察、反馈与复测 |
| 参与者入口 | `docs/trial/participant_start.md` | 有效；只做分配的任务卡 |
| 角色与任务覆盖安排 | `docs/trial/personas_and_coverage.md` | 有效；独立机器与共享主机分别记录 |
| 12 张任务卡与组织者核对要点 | `docs/trial/tasks/` | 有效；核对要点不放入参与者包 |
| 可填写反馈表与观察模板 | `docs/trial/forms/` | 有效；匿名引用和录屏分别征求同意 |
| v2 会话汇总工具 | `scripts/summarize_trial_sessions.py` | 有效；按分配任务统计，保留跳过、卡住和缺记录；复测不重复计人数 |
| 参与者 / 组织者材料包构建 | `scripts/build_trial_kit.py` | 有效；明确文件白名单，两包及逐文件 SHA-256 清单，不包含真人原件 |
| 独立真人复核指南与空模板 | `docs/review/` | 有效；复核 3 个基线与 21 个候选，包含功能变体、拟等价改写和编译失败控制项 |
| 原始录屏与成片工作流 | `docs/demo/recording_workflow.md` | 有效；真人试用原片、独立审核记录和团队演示分别保留 |
| 3–5 分钟团队演示分镜 | `docs/demo/demo_script.md` | 有效；视频尚未录制，离线演示不称为真实 LLM 调用 |
| 本轮材料验收记录 | `docs/trial/validation_2026-10-04.md` | 有效；记录本次表单、脚本与交付包检查，不替代真人试用 |
| v1 反馈兼容入口 | `docs/trial/task_card.md`、`docs/trial/feedback_template.json`、`scripts/summarize_trial_feedback.py` | 保留旧表和旧汇总工具；新试用使用 v2 可变任务表 |
| 真人结果登记 | `docs/trial/results.md` | 待收集；不把自动测试或模板算作用户反馈 |

真人原始记录留在被 Git 忽略的本机目录，公开摘要仅使用同意匿名引用的会话。独立复核需要真人逐条检查规格、源码差异与运行证据；代理自查、外部开源来源和界面试用均不能替代。

---

## 4. 工程门禁（当前记录与历史快照）

上次完整回归及门禁快照见 `docs/experiment/local_validation_2026-10-04.md`。
其中 768 项通过是该次完整验证的记录，不包含之后新增试用工具测试；本轮材料验收另见试用验收记录。
下表的 2026-10-01 数字同样为历史快照。

| 门禁 | 命令 | 结果 |
|---|---|---|
| 上次完整验证快照 | `docs/experiment/local_validation_2026-10-04.md` | 2026-10-04：768 passed / 1 skipped，mypy 64 文件 0 error；PDF 9 项复核通过 |
| 测试（2026-10-01 历史） | `python -m pytest -q` | **720 passed / 1 skipped**（历史干净 venv：675 / 3 / 0） |
| 类型 | `python -m mypy` | 61 文件 0 error |
| 死代码 | `python scripts/check_dead_code.py` | 121 文件 0 处 |
| 编码/BOM | `python scripts/strip_bom.py --check` | 0 问题 |
| 交付体检 | `python scripts/check_submission.py --repo .` | **1 error**（`CITATION.cff` 占位符） |
| 报告页数/体积 | `python scripts/check_submission.py --kind report docs/competition/technical_report_draft.pdf` | 0 error / 1 warning（正文 22 页超建议值） |
| 索引路径存在性 | `python scripts/check_doc_index.py` | **109/109 条路径存在**（2026-10-04；反向测试：故意写错一条则退出码 1） |

---

## 5. 竞赛策略与写法（决策留痕）

| 内容 | 位置 | 状态 |
|---|---|---|
| 官方大纲与章节映射 | `docs/competition/submission_outline.md` | 有效 |
| 获奖写法 playbook | `docs/competition/award_report_playbook.md` | 有效 |
| 往年获奖项目经验 | `docs/competition/award_winning_project_lessons.md` | 有效 |
| 参考报告拆解 | `docs/competition/reference_report_analysis.md` | 有效 |
| 合规行动计划 | `docs/competition/competition_compliance_action_plan.md` | 有效 |
| 生态位 | `docs/competition/ecosystem.md` | 有效 |
| 后续路线图 | `docs/competition/scale_up_roadmap.md`、`docs/competition/improvement_plan.md`、`docs/competition/workload_backlog.md` | 有效 |
| 就绪度评估 | `docs/competition/competition_readiness_assessment.md` | 历史（基于修复前状态） |
| 项目评审 | `docs/competition/project_review_2026-09-10.md` | 历史 |
| 交付评审 | `docs/delivery_review.md` | 历史 |
| 剩余工作 | `docs/competition/remaining_work.md` | 部分过期，以门禁清单为准 |

---

## 6. 结构与可视化数据库（normify）

结构库在**仓库之外**，随结构一起回档：

- 目录：`E:\FPGA_WORK\Ti60F225_DemoBoard_v4\10_Ti60f225_sc431hai2hdmi_demo\Ti60f225_sc431hai2hdmi_v3\normify-iverilog-ai-lab`
- 规模：**157 模块 / 216 API / 53 依赖 / 25 布局 / 0 error**（含 9 条变更记录）
- 打开：该目录下的 `normify.html`（逐层下钻、悬停介绍、深链接、双语）
- 维护：源码或文档改动后 `normify_sync` → 刷新指纹 → `normify_change_close`（0 error 强制）

---

## 7. 尚未完成（都需要仓库之外的动作）

| 项 | 状态 | 卡在哪 |
|---|---|---|
| `CITATION.cff` 真实地址 | 待补 | 当前先完成本地 Git；公开仓库地址尚未确定，保留占位，不捏造链接 |
| 真人试用与复测记录 | 待补 | 建议安排 3–5 名不同角色试用者；材料就绪，尚待实际收集；不是官方人数硬要求 |
| 3–5 分钟演示视频 | 待补 | 需要录制；脚本 `docs/demo/demo_script.md` |
| 外部独立复核 | 待补 | 3 个基线与 21 个候选待真人逐条复核；记录关系、协助、分歧与不可判定 |
| GitHub Action 外部调用验证 | 待补 | 需要一个调用方仓库 |
| 正文 22 页 | 已知取舍 | 超大纲"建议 ≤15 页"；官方不以篇幅评分，已披露 |

试用与复核的完整入口见 §3.1。v1 原始表和汇总脚本保留兼容，新记录不覆盖旧表；缺少真人反馈、独立审核或视频时继续标注待补。

---

## 8. 索引维护规则

1. **新增材料必须登记在这里**，并写明状态（有效 / 历史 / 待补）；没有来源文件的不登记。
2. **数字只在 `docs/experiment/metric_inventory.md` 定义**；本索引与报告只引用、不另立口径。
3. 口径变化时，新结果**另存新目录**，旧目录只读保留，引用旧数字必须带"旧口径"。
4. 改完材料跑一遍 `python scripts/check_doc_index.py`：它会检查本文件里每个路径是否还存在，
   防止索引变成过期路标。
