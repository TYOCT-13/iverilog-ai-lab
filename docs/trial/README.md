# Icarus 智测真人试用材料

本套文件用于组织不同需求、环境和经验水平的真实使用者试用，记录成功、卡点与失败。现在提供的是任务和空白表格；`results.md` 仍为“待收集”，不代表已经有人试用。

材料日期：2026-10-04。每次试用另记实际 Git commit、环境和未提交改动。人数、任务组合和时间安排是项目建议，不是赛事规定的最低人数，也不能据此保证获奖。

2026-10-08补充：真人工程复现从[新版指南](../reproduce_current.md)开始，首次安装已并入第2节，使用已上传的f7867db代码及[空白复现记录表](forms/reproduction_record.md)。可直接发送[r2复现资料包](reproduction_guide_2026-10-08-r2.zip)。基础复现无需API；另一台电脑、共享主机、预装和协助分别记录，真实结果仍待收集。旧资料包及校验记录保留。

## 文件怎么发

| 对象 | 文件 | 用途 |
|---|---|---|
| 参与者 | `participant_start.md`、分配的 `tasks/T*.md`、`forms/participant_feedback.docx` 或 `.md` | 按任务操作并留原话，不要求会写 JSON |
| 工程复现人 | 新版复现指南、`forms/reproduction_record.md`、复现资料包 | 固定代码、安装、CLI与网页流程，收回原始输出；知道预期结果，不当作盲测 |
| 组织者 | `organizer_workflow.md`、`personas_and_coverage.md`、`tasks/organizer_checks.md` | 分配任务、预检、观察、收集和复测，检查答案不提前给参与者 |
| 记录人员 | `forms/observer_log.md`、`forms/issue_log.md`、`forms/session_feedback_template.json` | 留下协助与证据，将原件转录为可汇总记录 |
| 视频制作人员 | `docs/demo/recording_workflow.md`、`docs/demo/demo_script.md` | 保存原始录屏，再剪辑比赛视频 |
| 独立审核者 | `docs/review/README.md` 及同目录指南和模板 | 复核规格、代码、测试输入、运行记录与结论 |

运行 `python scripts/build_trial_kit.py` 后，两个资料包位于 `dist/trial-kit/`：参与者包排除组织者检查答案；组织者包保留完整流程和模板。资料包不含 Python、Icarus 安装程序或 API 凭据，也不替代项目程序包。

## 按需求选择任务

| 使用者 | 主要观察点 | 建议组合 |
|---|---|---|
| 新手 | 能找入口、理解结果、知道下一步 | T02、T03、T07、T08 |
| RTL 开发者 | 上传与合约、行为对比、代码审查 | T04、T05、T06、T07 |
| 助教或技术复核者 | 追溯反例、解释不同结论 | T03、T05、T08、T09 |
| 首次安装或 CLI 使用者 | 安装文档可复现、故障可定位 | T01、T09、T12 |
| 在线模型用户 | 预检、预算、失败反馈 | T10；先 dry-run，真实调用可跳过 |
| 手机阅读或键盘使用者 | 导航、表单、长结果可访问 | T11，搭配适合设备的 T02/T08 步骤 |

一个人可以有多个角色。建议先找 1 人试跑材料，再找 3–5 位未参与对应功能开发的人正式试用；每人按角色做 3–5 个任务，约 30–60 分钟。安装可另留 20–30 分钟，超时如实记卡点。详细任务覆盖见 `personas_and_coverage.md`。

## 从试用到提交

1. 冻结程序版本与样例，组织者先预检。
2. 分配任务，分别确认匿名引用和录屏意愿。
3. 参与者独立操作，观察者记录；提示和代操作计入协助。
4. 收回原件、截图、运行证据和同意保存的原始录屏。
5. 汇总卡点，修复后用新版本复测，保留首次失败记录。
6. 另录比赛演示，审核字幕、结果、匿名性和文件规格。

执行话术与目录规则见 `organizer_workflow.md`。独立技术审核可与试用并行；真人试用、技术审核和视频展示不能互相替代。

## 填表与汇总

参与者填写 Word 或 Markdown；组织者依据原件转录成 2.0 JSON，并请参与者核对。模板默认 `record_kind=template`；只有真实发生的会话才能改为 human。同一人复测保留匿名代号，但使用不同 session_id。

```powershell
# 在项目根目录执行，文件必须来自真实试用原件
python scripts/summarize_trial_sessions.py .iverilog-ai/trial-sessions/round-1/*.json
# 对外摘要只使用同意匿名引用的样本
python scripts/summarize_trial_sessions.py .iverilog-ai/trial-sessions/round-1/*.json --public
```

工具不自动改 `results.md`。已分配但无记录的任务保留在分母；未分配的不计失败；未知耗时不按 0；公开汇总只代表授权公开样本。

## 旧版与官方依据

`feedback_template.json` 与 `scripts/summarize_trial_feedback.py` 保留给 1.0 三任务历史记录。新试用采用 `forms/session_feedback_template.json` 与新脚本；不要直接混合两套数据。

[官方通知](https://www.aicomp.cn/notice/notice-3/4890.html)及其附件列出用户反馈、测试记录等可选佐证材料。分角色试用与独立复核是本项目补强证据的安排，不是新增比赛硬性门槛。视频格式和匿名性核对见录制指南。
