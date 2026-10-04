# 资料索引（Icarus 智测 / iverilog-ai-lab）

这一份是**全部材料的入口**。当前准备转入 AI＋集成电路赛道，优先阅读下方 IC 材料；原开源赛道报告继续保留，提交时须核对所选赛道。所有路径都相对仓库根 `E:\FPGA_WORK\iverilog-ai-lab`，
带盘符的除外。路径可用 `python scripts/check_doc_index.py` 校验是否仍然存在。

- 仓库：`iverilog-ai-lab`，Apache-2.0；第三方资源保留各自许可；判定权威是 Icarus Verilog 12.0（`s20150603`）
- 本次材料修订：**2026-10-04**；最新生产源码与验收 `28be1ed`，v3三重复 `c7bb280`，旧pilot `e9b7b8a`；各版本、提示与结果分别引用（提交截止2026-10-15 20:00北京时间）
- 状态记号：**有效** = 当前口径，可直接对外引用；**历史** = 反映当时状态，只读归档，
  引用时必须带"旧口径"标注；**待补** = 尚未完成

---

## 0. 最快的阅读路径

| 你想干什么 | 按顺序读 |
|---|---|
| 5 分钟了解这个项目 | `README.md` → `docs/project_overview.md` → `docs/competition/ic/report_draft.md` |
| 准备 AI＋集成电路提交 | `docs/competition/ic/v2/README.md` → `docs/competition/ic/v2/technical_report.md` → `docs/competition/ic/v2/supporting_evidence.md`；真人与H02待真实原件，新版事实稿优先 |
| 复核数字是否可信 | `docs/experiment/metric_inventory.md`（每个数字一行：口径/来源/时间/复现命令）→ `docs/competition/submission_gate_checklist.md` → 产物目录 |
| IC提交当天照着做 | `docs/competition/ic/v2/README.md` → `docs/competition/ic/gap_checklist.md`；先核对所选赛道、真人/H02原件和团队字段 |
| 组织真人试用与反馈 | `docs/trial/README.md` → `docs/trial/organizer_workflow.md`；发给参与者从 `docs/trial/participant_start.md` 开始 |

---

## 1. 要交的东西

### 1.1 AI＋集成电路材料

| 材料 | 路径 | 状态 |
|---|---|---|
| 最新技术方案源稿与PDF | `docs/competition/ic/v2/technical_report.md`、`docs/competition/ic/ICARUS_技术方案_v2.pdf` | 有效；9页/正文8页，约1.02MB；c7与v4分版本，真人/H02事实待补 |
| 最新佐证源稿与PDF | `docs/competition/ic/v2/supporting_evidence.md`、`docs/competition/ic/ICARUS_佐证材料_v2.pdf` | 有效；5页、约0.86MB；V01–V06真实来源，保留失败，不以假设替代人审 |
| 最新材料入口与PDF回执 | `docs/competition/ic/v2/README.md`、`docs/competition/ic/v2/validation.json` | 名称15字符、简介172字符；全部14页渲染查看，文字可选择、身份元数据空 |
| 最新答辩稿与构建来源 | `docs/competition/ic/ICARUS_答辩材料_v2.pptx`、`docs/competition/ic/ICARUS_答辩材料_v2.pdf`、`docs/competition/ic/defense_v2/README.md`、`docs/competition/ic/defense_v2/qa_report.json` | 12页，5原生表格/3原生图表/12页备注；PPTX可编辑，PDF图像式；逐页机器检查，不是独立人审 |
| 本轮c7/v4冻结交接包 | `docs/competition/ic/evidence_pack_v4_2026-10-04.md`、`docs/competition/ic/evidence_pack_v4_2026-10-04.json`、`.iverilog-ai/ic-agent-v4-evidence-20261004.zip` | 127,448,982字节；10,330项文件SHA/CRC通过；281登记中280精确匹配，1早期计划MD未恢复；完整结果及失败保留 |
| 本轮包后代理字节核查 | `docs/review/ic_v4_pack_review_2026-10-04.md`、`docs/review/ic-v4-pack-review-2026-10-04/receipt.json` | CRC/10,330项SHA与280输入均匹配；4 Git归档重新导出字节一致，预期CRLF差异明记；不是H02或异机 |
| 新包内反例实际重放 | `docs/experiment/ic-agent-v4-pack-replay-2026-10-04/receipt.json`、`docs/experiment/ic-agent-v4-pack-replay-2026-10-04/stdout.log`、`docs/experiment/ic-agent-v4-pack-replay-2026-10-04/stderr.log` | 从外层ZIP取内层小包，在新目录运行包内replay.py；338比较/48失败，failed_checks，0API；同机已有工具，不是异机或真人 |
| v4单重复API烟测 | `docs/experiment/agent_comparison_v4_smoke_2026-10-04.md`、`docs/experiment/agent-comparison-v4-smoke-2026-10-04/receipt.json` | 84行、94请求、94/94动作校验；反馈6/8，随机8/8；1正确基线执行失败、严格资格false |
| v2正式小型回执 | `docs/experiment/agent-comparison-v2-2026-10-04/receipt.json` | 是摘要摘录，不是完整results；全部252行和完整原件另存，SHA可追溯 |
| 本轮API预算账 | `docs/experiment/ic_agent_v4_api_budget_2026-10-04.json` | 保守277/360请求；已知276响应，预跑另1可能在途，未知不作零；不是账单 |
| 最新完整回归与浏览器 | `docs/experiment/ic_agent_v4_validation_2026-10-04.md`、`docs/experiment/ic-agent-v4-validation-2026-10-04/validation.json`、`docs/experiment/ic-agent-v4-validation-2026-10-04/browser/results.json` | 28be1ed：1073/2skip；291冻结SHA无变；r3三尺寸0横溢出、UART58/58、切页保持；失败r1/r2保留 |
| v4非实现者代理复核 | `docs/review/ic_agent_v4_proxy_review_2026-10-04.md` | 复现重复JSON键/转义凭据问题，冻结修复复测；模拟凭据、真实API0，不是H02 |
| 历史条件稿技术方案源 | `docs/competition/ic/report_submission.md` | 条件稿；按真人、人审均通过的前提起草，H01/H02未核实，实验数字沿用真实记录 |
| 历史条件稿技术方案PDF | `docs/competition/ic/ICARUS_技术方案.pdf` | 条件稿；11页/正文10页，七节大纲；匿名版式与逐页检查完成 |
| 历史条件稿佐证源与PDF | `docs/competition/ic/supporting_evidence_submission.md`、`docs/competition/ic/ICARUS_佐证材料.pdf` | 条件稿；5页，E01–E07为真实记录，H01/H02原件待补 |
| 历史报名短文本与说明 | `docs/competition/ic/submission_copy.md`、`docs/competition/ic/submission_package_readme.md` | 名称15字、简介199字；提交位置、命名和条件转事实流程 |
| 本轮报告配图 | `docs/competition/ic/submission_figures/architecture.png`、`docs/competition/ic/submission_figures/agent_comparison.png` | 原创架构图与真实五策略结果图，不改写实验成绩 |
| 本轮报告校验回执 | `docs/competition/ic/submission_validation_2026-10-04.json` | 文档与PDF校验，不是新的全仓回归、真人试用或独立人审 |
| IC 技术报告源 | `docs/competition/ic/report_draft.md` | 按官方七节大纲整理；真人和人工复核缺口如实保留 |
| IC 技术报告 PDF | `docs/competition/ic/report_draft.pdf` | 已导出工作稿，逐页检查；正式团队字段与人审仍待完成 |
| PDF 版面与文件核验 | `docs/competition/ic/pdf_validation_2026-10-04.json` | IC稿10页/正文9页；元数据、文件哈希与逐页检查；旧两份PDF按原稿同步重导出 |
| 报名名称与简介 | `docs/competition/ic/submission_text.md` | 已备，报名系统字段另核对 |
| IC 差距与提交清单 | `docs/competition/ic/gap_checklist.md` | 当前待办入口 |
| 多模块 Agent 试验协议 | `docs/experiment/agent_comparison_protocol.md`、`scripts/run_agent_comparison.py` | 预注册、固定分母、请求与累计激励周期上限 |
| 四类完整协议与预算 | `spec/agent_protocols.json`、`spec/sync_fifo_spec.md`、`spec/uart_tx_spec.md`、`spec/spi_master_spec.md`、`spec/handshake_stage_spec.md` | 有效；对应默认参数，FIFO160 / UART512 / SPI384 / 握手160累计激励周期 |
| 判据修正与单点控制 | `docs/experiment/protocol_oracle_improvements_2026-10-04.md`、`benchmarks/agent_v2/mutation_manifest.json` | FIFO独立队列修复、两个新单点变体；外部人工SPEC检出15/15，原13/15档案保留，非AI增益 |
| 功能场景及真实采样 | `docs/experiment/functional_coverage_2026-10-04.md`、`src/iverilog_ai/core/functional_coverage.py`、`src/iverilog_ai/core/observations.py` | 有效；24项有限场景，实际stdout与来源SHA绑定，未知不记命中 |
| v2三次重复API实测 | `docs/experiment/agent_comparison_v2_live_2026-10-04.md` | c7bb280，252行/157请求；API未胜基线，保留137次动作拒绝和全分母，不证明覆盖增益 |
| 思考模式与动作格式修复 | `docs/experiment/deepseek_thinking_mode_2026-10-04.md`、`docs/experiment/deepseek_decision_v4_2026-10-04.md` | 配置和真实消息角色；与c7实验分别版本化，预跑失败未改写 |
| UART应用与证据重放 | `docs/demo/ic_agent_v2_walkthrough.md`、`scripts/replay_evidence_pack.py` | 零API协议随机演练；512周期，两个已知变体检出；包内338比较/48不一致可离线重放，非真人记录 |
| v2采样与计分代理复核 | `docs/review/ic_agent_v2_proxy_review_2026-10-04.md` | 两项真实篡改反例及修复复测；不是H02独立真人审核 |
| 历史多模块 API pilot | `docs/experiment/agent_comparison_live_2026-10-04.md`、`docs/experiment/agent-comparison-chat-2026-10-04/summary.json` | 60 行、52 请求；反馈 4/8，固定/随机 5/8；单次开发集观察 |
| 首轮接线失败记录 | `docs/experiment/agent_comparison_interrupted_2026-10-04.md` | 已保留原始失败与未知在途用量，不能并入有效能力成绩 |
| 代理交叉检查 | `docs/review/agent_comparison_cross_review_2026-10-04.md`、`docs/review/external_agent_cross_review_2026-10-04.md` | 机器与代理检查，非独立人工审核 |
| 机器功能验收 | `docs/trial/machine_acceptance_2026-10-04.md` | 22 项选定 UI/CLI 测试通过；不计为真人试用 |
| 历史外部冻结重放 | `docs/experiment/external_agent_readiness.md` | 旧判据24输入重放；13/15，含漏检；新人工判据15/15见上方修正记录 |
| 外部 API Agent 适配 | `docs/experiment/external_api_agent.md`、`scripts/run_external_verification_agent.py` | 限定合约输出、资格检查与即时快照；实际联调另列 |
| 外部真实 API 联调 | `docs/experiment/external_agent_live_2026-10-04.md`、`docs/experiment/external-agent-live-2026-10-04/summary.json` | 1 请求、2 轮、782 双侧周期；固定计划已有的差异不归功于新增 AI 输入 |
| 内置参考告警诊断 | `docs/review/reference_alarm_diagnosis_2026-10-04.md` | 旧 before 假警保留，当前实现拒绝缺少独立判据的顺序逻辑 before 计划 |
| 历史完整回归与浏览器验收 | `docs/experiment/ic_validation_2026-10-04.md`、`docs/experiment/ic-validation-2026-10-04/validation.json` | 914 通过 / 1 跳过；148 源码指纹冻结；三尺寸及实际上传、仿真、导航保持 |
| PDF 排版修正后的全仓回归 | `docs/experiment/ic-validation-pdf-final-2026-10-04/validation.json` | 867b8bd，914 通过 / 1 跳过，227.34 秒；之前的完整回归分开保留 |
| 最终非实现者代理检查 | `docs/review/ic_final_agent_review_2026-10-04.md` | 核心修复、工件与材料核对；材料作者参与，非独立真人审核 |
| 历史 IC 本地证据包与回执 | `docs/competition/ic/evidence_pack_2026-10-04.md`、`docs/competition/ic/evidence_pack_2026-10-04.json` | 历史86.4 MB本地ZIP，6源码快照、41,006项文件哈希复核一致；不含本轮c7/v4原件，未异机复现或正式提交 |
| 包后代理字节审计 | `docs/review/ic_pack_review_2026-10-04.md` | CRC、完整集合、全部文件哈希、424注册输入及换行差异已核查；内部作者参与，非独立人审 |
| 包内源码离线运行 | `docs/experiment/ic-pack-smoke-2026-10-04/smoke.json`、`docs/experiment/ic-pack-smoke-2026-10-04/stdout.log`、`docs/experiment/ic-pack-smoke-2026-10-04/stderr.log` | 同机从外层ZIP提取源码执行：0API、547输出比较/0差异；辅助脚本字段错误单列保留 |

### 1.2 原开源赛道资料与共用交付

| 材料 | 路径 | 状态 | 备注 |
|---|---|---|---|
| 原开源技术报告（PDF） | `docs/competition/technical_report_draft.pdf` | 原赛道稿 | 26 页 / 正文 21 页 / 924 KB（2026-10-04 排版修复后按原稿重渲染）；当前 IC 报告独立使用 |
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

### 2.1 原在线规划实验：每计划预算对齐与同轮数子集（固定分母）

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
| API自动验证Agent | `docs/experiment/api_agent.md`、`scripts/run_verification_agent.py`、`scripts/export_agent_trajectories.py` | 实际角色、受控动作、覆盖反馈与三重复/单重复分别完成；仍API推理。托管微调、独立留出、真人效果未完成 |
| API Agent 本地验收 | `docs/experiment/api_agent_validation_2026-10-04.md` | 先前离线验收快照：195 项相关回归通过 |
| API Agent 真实联调 | `docs/experiment/api_agent_live_2026-10-04.md`、`docs/experiment/api-agent-live-2026-10-04/summary.json` | 3 次 DeepSeek 4.1 Flash 请求；反馈补测与已知缺陷回放通过，211 项相关回归通过 |
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

当前完整回归及浏览器操作见 `docs/experiment/ic_agent_v4_validation_2026-10-04.md`。
1073项通过/2跳过对应28be1ed源码与291项指纹；914/1及更早记录均为历史快照，不相加。文档改动后的索引数量另核，不改写原验收日志。

| 门禁 | 命令 | 结果 |
|---|---|---|
| 当前完整回归 | `docs/experiment/ic_agent_v4_validation_2026-10-04.md` | 28be1ed，1073 passed / 2 skipped / 0 failed；mypy76文件0错误，未可达187文件0，BOM0 |
| 历史867全回归 | `docs/experiment/ic_validation_2026-10-04.md` | 914 passed / 1 skipped，保留原日志 |
| 上次完整验证快照 | `docs/experiment/local_validation_2026-10-04.md` | 2026-10-04：768 passed / 1 skipped，mypy 64 文件 0 error；PDF 9 项复核通过 |
| 测试（2026-10-01 历史） | `python -m pytest -q` | **720 passed / 1 skipped**（历史干净 venv：675 / 3 / 0） |
| 类型 | `python -m mypy` | 61 文件 0 error |
| 死代码 | `python scripts/check_dead_code.py` | 121 文件 0 处 |
| 编码/BOM | `python scripts/strip_bom.py --check` | 0 问题 |
| 交付体检 | `python scripts/check_submission.py --repo .` | **1 error**（`CITATION.cff` 占位符） |
| 报告页数/体积 | `python scripts/check_submission.py --kind report docs/competition/technical_report_draft.pdf` | 原开源稿：0 error / 1 warning（正文21页超建议值）；原IC工作稿10页/正文9页；本轮条件技术方案11页/正文10页，佐证5页，均0 error / 0 warning |
| 索引路径存在性 | `python scripts/check_doc_index.py` | **195/195 条路径存在**（2026-10-04；此前反向测试：故意写错一条则退出码 1） |

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
| 原开源报告正文 21 页 | 历史取舍 | 原赛道稿正文21页；旧IC工作稿正文9页，最新v2正文8页；各版本分别计量 |

试用与复核的完整入口见 §3.1。v1 原始表和汇总脚本保留兼容，新记录不覆盖旧表；缺少真人反馈、独立审核或视频时继续标注待补。

---

## 8. 索引维护规则

1. **新增材料必须登记在这里**，并写明状态（有效 / 历史 / 待补）；没有来源文件的不登记。
2. **数字只在 `docs/experiment/metric_inventory.md` 定义**；本索引与报告只引用、不另立口径。
3. 口径变化时，新结果**另存新目录**，旧目录只读保留，引用旧数字必须带"旧口径"。
4. 改完材料跑一遍 `python scripts/check_doc_index.py`：它会检查本文件里每个路径是否还存在，
   防止索引变成过期路标。
