# ICARUS 答辩材料 v2 源码

材料为 16:9，采用灰黑底色、白色正文和少量青色重点。表格、条形图、流程节点与正文保留为 PowerPoint 原生可编辑对象。封面示意图使用项目已有 SVG；产品图片是本机实际网页截图。

## 数据口径

`data.json` 保存数值、证据相对路径和截图裁切记录。`source_checksums.json` 是最近一次构建时引用原件的 SHA-256 快照，私有构建目录还保存当次数据副本；快照只证明引用文件的身份，不代替独立人工复核。各页备注补充来源与适用范围。旧 pilot 的冻结版本为 `e9b7b8a`，新 v2 实验必须按自己的实际执行原件填入，不能混用版本、分母或预算。

- FIFO 独立队列验证：同一 76 周期、228 次比较，修复前 66 次差异，修复后 0 次；这是人工规格核验与实现修复的结果。
- 外部重放：同一 24 个冻结候选模块，UART RX、UART TX、优先编码器各 8 项，合计 15 个历史人工变体的检出从 13 个变为 15 个；收益来自 UART TX 人工计时判据补全。其余正确、等价和编译失败控制项分别保留，不能加入变体检出分母。
- 网页运行数字来自离线 Icarus；预算控件截图没有真实在线 API Agent 执行结果。手机结果是桌面浏览器视口模拟。
- 历史五策略 pilot 只执行一次重复；失败、未知和不可判定保留。不能将新 RTL、判据、预算与采样的综合变化归因为 AI 单独提升。
- 真人试用和独立人工复核原件尚未补入。机器自动运行与同主机证据重放不能代替真人或独立人审。

`v2_registration.executed_results` 对应源码 `c7bb280` 的真实三次重复：252 行、157 请求、289219 tokens；137 行动作拒绝、125 行完全无仿真轮。`eligible_for_frozen_comparison=false` 指内部的完整仿真证据条件未满足，不是比赛报名资格判定。表中的失败不剔除，也不宣称 AI 优于本地基线或覆盖反馈增益。335 是这一轮实际冻结的请求上限；360 是原计划理论最大请求数，二者均不是实付请求数。

`v4_smoke_results` 单列源码 `28be1ed` 的一次开发烟测：84 行、94 请求（上限 120）、201710 tokens；94/94 决策通过 schema、0 拒绝。七策略完整列出，反馈 Agent 6/8、无反馈 7/8、无覆盖反馈 5/8，本地均匀和协议随机各 8/8。1 个 UART 正确基线执行失败且无仿真轮，内部完整证据条件仍未满足。动作合法率不能替代执行成功率；一次烟测不能证明覆盖因果或反馈收益，也不替换 c7 结果。正式构建检查这个单列摘要已到位。`--draft` 只构建前 10 页；`--review` 渲染含实际成绩的 12 页私有审阅稿，两者都不输出公开正式文件。

产品图来自最终 r3 浏览器记录，对应 `28be1ed`。全仓工程回归为 1073 通过、2 跳过、0 失败，mypy 76 源码文件无错误；它不等于 Agent 能力或真人验收结果。此前脚本定位和旧服务缓存问题的 r1/r2 记录保持原样。

## 构建

依赖由 Codex 桌面内置 runtime 提供，不在仓库内安装或链接 `node_modules`。`build_defense.mjs` 目前记录本机 runtime 与演示技能的绝对路径；在另一台电脑运行前，应通过 `load_workspace_dependencies` 解析当地路径并更新这些常量。

从仓库根目录运行：

```powershell
$env:DEFENSE_REVISION = 'r7'
& 'C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' docs/competition/ic/defense_v2/build_defense.mjs
```

构建使用 `@oai/artifact-tool` ES modules。正式候选先进入 `.iverilog-ai/defense-v2-build/`，经过原生表格/图表、版面几何、字体及重新导入校验后生成：

```text
docs/competition/ic/ICARUS_答辩材料_v2.pptx
docs/competition/ic/ICARUS_答辩材料_v2.pdf
```

每次使用新的 `DEFENSE_REVISION`，避免覆盖 finalization 的证据文件。PNG、版面 JSON、检查日志及 validation receipt 都存于上述私有构建目录。构建不会执行 API 请求、修改业务代码或提交 Git。

## 图片与匿名性

`assets/agent-controls-1440.png` 是最终 r3 完整原始控件截图的逐字节副本。`agent-budget-crop.png` 仅裁切 `(690, 526, 1396, 874)` 这一像素范围，没有修改控件内容。裁切只是摘取预算与功能场景区域，完整原件与独立来源 SHA 仍保留。`assets/verification-map.svg` 是项目原创示意图，不能表述为设备实拍或现场验证照片。

PDF 使用空作者元数据；页面没有成员姓名、学校、联系方式或 API 凭据。源代码里的本机 runtime 路径不进入投递 PDF。外部仓库与历史记录的归属需保留在技术报告原件中，匿名材料不改变证据的来源。

## 导出与检查限制

PowerPoint 文件包含可编辑正文、流程、5 张原生表格和 3 张原生图表，并将图表数据写入嵌入式工作簿。PDF 从正式 PPTX 重新导入后的 2560×1440 页面图像生成，因此它是图像式 PDF，不支持文本选择与检索；如需编辑，请使用 PPTX 或重建源码。

版面检查采用 artifact-tool 渲染和 PDF 页面重渲染。当前机器没有 Microsoft PowerPoint 或 LibreOffice，不能声称已经用这些程序打开验证。编辑 PPTX 的机器需要安装 `Noto Sans SC` 与 `Bahnschrift`，或主动替换并重新检查字体排版；图像式 PDF 的显示不依赖这些字体。交付前需逐页检查正式导出的 12 页，特别是实际成绩页的分母、失败记录、字体、零起点刻度、截图与匿名性。

`speaker_notes.md` 提供 5–7 分钟讲述稿和常见追问。每页讲述稿自动写入 PPTX 的演讲者备注，来源和口径紧随其后。实际 v2 数据改变时，应同步数据文件、成绩页和讲述稿，而不只修改页面上的数字。

## 本次交付检查

正式构建修订为 `r7`，12 页，PPTX 219083 字节，PDF 2232128 字节。12 页正式 PPTX 重新导入后均渲染为 2560×1440 PNG，并逐页查看；12 页 PDF 也重新渲染并逐页查看。以同一分辨率对比，PDF 页面与对应 PPTX 页面图像逐像素一致。未见文字重叠、控件裁切、刻度截断或身份信息；这属于机器版面检查。

| 记录 | 路径与范围 |
|---|---|
| 数据逐项核对 | `data_audit.json`：c7 三次和 v4 单次的分母、计数、失败、请求与 tokens 分开核对原件 |
| 引用原件快照 | `source_checksums.json`：构建时实际读取的来源、作者数据与源码 SHA-256 |
| 公开校验摘要 | `finalization_summary.json`：原生对象、包结构、版面、字体及重新导入结果，附原 receipt SHA |
| 逐页检查 | `qa_report.json`：两个正式文件 SHA、12 页截图 SHA、观察记录、限制与匿名性 |
| 完整原始 receipt | `.iverilog-ai/defense-v2-build/defense-r7.validation.json` |
| PPTX 导入渲染 | `.iverilog-ai/defense-v2-build/r7-final/`：12 张 PNG、版面 JSON 与检查日志 |
| PDF 页面重渲染 | `.iverilog-ai/defense-v2-build/r7-pdf-qa/`：12 张 PNG |
| 机器核对脚本 | `.iverilog-ai/defense-v2-build/qa_r7.py`；视觉查看结果另行写入 QA 记录 |

文件 SHA-256：

```text
PPTX 20838083fcfdecb65172175b54cbf68a1e0521941953dc44ed5165052fd8aa40
PDF  747f238e6af1d9b41fbce3e76962e4de81860577fa235a50d91e117227aaee50
```

公开源码目录不含依赖，临时图表工作簿均位于私有构建目录。本次材料生成没有 API 请求、Git 提交或业务代码修改。H01 真人试用、H02 独立人工复核仍未执行；这些文件不能当作对应通过记录。
