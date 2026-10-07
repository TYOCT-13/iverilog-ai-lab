# ICARUS 答辩材料 v3

正式内部产物为 ../ICARUS_答辩材料_v3.pptx 和同名 PDF，共12页。PPTX保留原生正文、流程对象、7个表格、3个图表及3份嵌入式literal workbook。PDF从正式PPTX的完整slide PNG导出，是图像PDF，编辑请用PPTX。两份正式文件的文档身份元数据已清空，页面不填写机构、署名、签字或假队号。

事实源为 ../v3/material_data.json，SHA-256为33a11bcce08331a5ccf18ee1c7da05059a8978a4a233a87661ff409d2d1dc8b4。它绑定新108、旧432、预算、审计和工程原件。source_checksums.json绑定本次实际读取的原字节及制作工具；speaker_notes.md是逐页讲稿，并已进入PPTX备注；qa_questions.md提供21个追问的回答和证据定位。

新108与旧432在不同页呈现，不合并分母或画增益趋势。固定测试在新批中检出最多，反馈与随机/无反馈只差1项，不声称因果、显著性或普适收益。第108行实际执行后的终态格式失败、付费拒绝、原响应保存、内部同团队集合属性和无反馈信息边界均在页面或讲稿中保留。历史FIFO与人工SPEC案例没有记作AI表现。

## 实际使用的制作命令

在E:/FPGA_WORK/iverilog-ai-lab的PowerShell中，r3的完整构建命令为：

~~~powershell
$env:DEFENSE_V3_REVISION = 'r3'
& 'C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' 'docs/competition/ic/defense_v3/build_defense.mjs' *> '.iverilog-ai/defense-v3-build/r3-build.log'
~~~

构建使用JavaScript ES模块@oai/artifact-tool，调用finalizePresentation，设置materializeLiteralChartWorkbooks: true，然后重新导入正式PPTX，将全部12页输出为2560×1440完整PNG。原生图表、表格、图表缓存/工作簿、页面尺寸和字体策略分别核验。图表工作簿是本材料数值的literal快照，不是历史原工作簿或源公式保留的证明。

检查器使用预装bundled Python的pypdf、Pillow与pypdfium2，不安装软件。它把最终PDF的全部12页重新渲染，同尺寸RGB像素与正式PPTX的PNG全部一致。制作代理随后逐页实看了正式12页，检查数字、轴范围、中文字符、布局及限制文字。正式PNG位于assets/final_slides/；私有原渲染位于.iverilog-ai/defense-v3-build/r3/final-render/。

确认视觉检查后，实际发布命令为：

~~~powershell
& 'C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 'docs/competition/ic/defense_v3/publish_final.py' r3 *> '.iverilog-ai/defense-v3-build/r3-publication.log'
~~~

命令只核验和复制材料，不访问网络、凭据或仿真工具。已存在的revision、日志和正式文件不可覆盖。重新制作需使用全新revision，并重新渲染、逐页检查后生成新的材料版本；不要重跑r1/r2/r3或用这一发布器覆盖已闭合正式文件。

## 保留的尝试与检查口径

r1因把“必须保留原工作簿”策略误用于新literal数据而失败。修复是移除不适用的原工作簿来源策略，仍保留literal workbook materialization。r2的PPTX finalize、全部slide PNG和图像PDF已成功，后续检查因bundled Python无fitz而失败。r3改用已有的pypdfium2，同时修复artifact-tool图表part路径匹配后全链完成。build_attempts/保存各次原日志、当时工具和数据字节；私有目录还保留全部candidate、原件快照及失败流程。

qa_report.json是结构检查与制作代理的逐页视觉检查记录；finalization_summary.json摘要正式文件与检查边界。原生表格总数为7，通用算术检查器没有找到可无歧义自动求和的表，因此其checked_column_count为0；预算等明确算式由builder对冻结事实源核验，不能写成7表算术全检。

没有在Microsoft PowerPoint、LibreOffice或Google Slides中打开、编辑或放映测试。artifact-tool的重导入和预览不能代替Native Office验收。制作代理不是独立真人/H02，亦是本项目entry作者。材料制作追加API、读取凭据、DUT执行、工程测试、提交、推送均为0。

## 正式投递

官方要求见事实源的rules及第12页备注中的通知、规则PDF与技术大纲URL。截止为2026-10-15 20:00；方案PDF不超过10MB，答辩为PDF，佐证合为一份PDF，视频可选。投递文件名按“真实队号-赛题名称-作品名称-XX（材料名称）”组织。真实队号尚未提供，当前仅保留请求的内部v3文件名，不填写虚构编号。目标展示机器仍需做Native Office实际显示检查。
