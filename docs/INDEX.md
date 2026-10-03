# 资料索引（Icarus 智测 / iverilog-ai-lab）

这一份是**全部材料的入口**。所有路径都相对仓库根 `E:\FPGA_WORK\iverilog-ai-lab`，
带盘符的除外。路径可用 `python scripts/check_doc_index.py` 校验是否仍然存在。

- 仓库：`iverilog-ai-lab`，MIT；判定权威是 Icarus Verilog 12.0（`s20150603`）
- 材料截止：**2026-10-01**；代码版本 `e58221b`（提交截止 2026-10-15 20:00 北京时间）
- 状态记号：**有效** = 当前口径，可直接对外引用；**历史** = 反映当时状态，只读归档，
  引用时必须带"旧口径"标注；**待补** = 尚未完成

---

## 0. 三条最快的阅读路径

| 你想干什么 | 按顺序读 |
|---|---|
| 5 分钟了解这个项目 | `README.md` → `docs/project_overview.md` → `docs/competition/technical_report_draft.pdf` |
| 复核数字是否可信 | `docs/experiment/metric_inventory.md`（每个数字一行：口径/来源/时间/复现命令）→ `docs/competition/submission_gate_checklist.md` → 产物目录 |
| 提交当天照着做 | `docs/competition/final_delivery_snapshot.md` → `docs/competition/submission_gate_checklist.md` → `docs/competition/submission_cover_text.md` |

---

## 1. 要交的东西

| 材料 | 路径 | 状态 | 备注 |
|---|---|---|---|
| 技术报告（PDF） | `docs/competition/technical_report_draft.pdf` | 有效 | 25 页 / 正文 21 页 / 921 KB；官方 PDF 上限 10 MB |
| 技术报告（源） | `docs/competition/technical_report_draft.md` | 有效 | 改完用 `python scripts/markdown_to_pdf.py` 重渲染 |
| 报告配图 | `docs/competition/figures/` | 有效 | 4 张（架构/流程/分层证据/基准），`scripts/make_report_figures.py` |
| 作品名称与简介 | `docs/competition/submission_cover_text.md` | 有效 | 简介实测 **293 字**（限 300）；字数校核脚本在 `.dsh-tmp/count_cover.py` |
| 提交前门禁清单 | `docs/competition/submission_gate_checklist.md` | 有效 | 逐项状态 + 证据 + 还差什么 |
| 交付快照 | `docs/competition/final_delivery_snapshot.md` | 有效 | 全部主指标、证据包、剩余外部依赖 |
| 演示视频脚本 | `docs/demo/demo_script.md` | 有效 | **视频尚未录制** |
| 证据包（正式） | `G:\iai-evidence-pack-final[.zip]` | 有效 | 8 文件 / 11.1 KB，sha256 已独立复核 |
| 证据包（演练） | `G:\iai-evidence-pack[.zip]` | 历史 | 9 文件 / 25.7 KB，含 `waveform.vcd` 样例 |
| 证据包说明 | `docs/demo/evidence_pack_guide.md` | 有效 | 包里每个文件是什么、怎么验 |
| 引用信息 | `CITATION.cff` | **待补** | `repository-code` 仍是 `example.invalid`，是提交体检里唯一的 error |
| 开源与合规清单 | `docs/competition/opensource_resource_list.md` | 有效 | 第三方来源与许可 |
| 上游贡献说明 | `docs/competition/upstream_contribution.md` | 有效 | Issue/PR 尚未提交 |

---

## 2. 实验与证据

### 2.1 主结果：同预算公平实验（新口径，固定分母）

| 内容 | 位置 |
|---|---|
| 口径定义（预算按规格定、执行前归一化、不可判定按未检出、参考告警作废） | `docs/experiment/experiment_plan.md` |
| **指标总账（每个数字一行）** | `docs/experiment/metric_inventory.md` §3 |
| 离线三组产物（fixed / random / ai-Mock，5 轮） | `.iverilog-ai/strategy-fair-5rounds/strategy_matrix.json` |
| **真实在线模型产物（deepseek-flash，5 轮）** | `.iverilog-ai/strategy-online-flash/strategy_matrix.json` |
| 运行脚本 | `scripts/run_strategy_experiment.py` |
| 计分与预算实现（纯函数） | `src/iverilog_ai/core/strategy_scoring.py` |

主数字（分母均为 67）：fixed 57/67（85.1%）；random 与 ai-Mock 累计 57/67、单轮均值 78.2%；
**真实在线模型累计 63/67（94.0%）、单轮均值 83.4%、不可判定 8、参考告警作废 5**。
去重后 128 次计费请求，费用上界 **$1.273**。两面结论见报告 §5.3(3)。

### 2.2 消融与基准

| 内容 | 位置 | 状态 |
|---|---|---|
| 消融矩阵（手写 TB / AI 计划 / 预言机，83 缺陷） | `.iverilog-ai/ablation-matrix/`；脚本 `scripts/run_ablation_matrix.py` | 有效 |
| 基准矩阵（今日复跑：参考 15 个误报 0、缺陷 83/83、不可判定 0） | `.iverilog-ai/matrix-final/`；脚本 `scripts/run_benchmark_matrix.py` | 有效 |
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

---

## 4. 工程门禁（2026-10-01 实测）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 测试 | `python -m pytest -q` | **720 passed / 1 skipped**（干净 venv：675 / 3 / 0） |
| 类型 | `python -m mypy` | 61 文件 0 error |
| 死代码 | `python scripts/check_dead_code.py` | 121 文件 0 处 |
| 编码/BOM | `python scripts/strip_bom.py --check` | 0 问题 |
| 交付体检 | `python scripts/check_submission.py --repo .` | **1 error**（`CITATION.cff` 占位符） |
| 报告页数/体积 | `python scripts/check_submission.py --kind report docs/competition/technical_report_draft.pdf` | 0 error / 1 warning（正文 21 页超建议值） |
| 索引路径存在性 | `python scripts/check_doc_index.py` | **95/95 条路径存在**（反向测试：故意写错一条则退出码 1） |

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
| `CITATION.cff` 真实地址 | 待补 | 仓库未公开；也是唯一门禁 error |
| 3 份真人试用记录 | 待补 | 需要 3 名试用者；任务卡与汇总工具已就绪 `docs/trial/` |
| 3–5 分钟演示视频 | 待补 | 需要录制；脚本 `docs/demo/demo_script.md` |
| 外部独立复核 | 待补 | 15 个外部变体待他人复核 |
| GitHub Action 外部调用验证 | 待补 | 需要一个调用方仓库 |
| 正文 21 页 | 已知取舍 | 超大纲"建议 ≤15 页"；官方不以篇幅评分，已披露 |

试用材料：`docs/trial/README.md`、`docs/trial/task_card.md`、`docs/trial/feedback_template.json`、
`docs/trial/results.md`（当前为空汇总）、`scripts/summarize_trial_feedback.py`。

---

## 8. 索引维护规则

1. **新增材料必须登记在这里**，并写明状态（有效 / 历史 / 待补）；没有来源文件的不登记。
2. **数字只在 `docs/experiment/metric_inventory.md` 定义**；本索引与报告只引用、不另立口径。
3. 口径变化时，新结果**另存新目录**，旧目录只读保留，引用旧数字必须带"旧口径"。
4. 改完材料跑一遍 `python scripts/check_doc_index.py`：它会检查本文件里每个路径是否还存在，
   防止索引变成过期路标。
