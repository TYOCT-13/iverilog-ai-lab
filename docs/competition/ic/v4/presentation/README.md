# ICARUS v4 答辩演示文稿

2026-10-21更新：本目录`output/ICARUS_AI_IC_defense_v4.pptx`及同名PDF已同步[当前技术报告对应的20页答辩材料](../../technical_report/presentation/README.md)。完整文字与来源以新PPT内讲稿及新交付回执为准；原稳定文件保存在Git提交`9b39751748b5739459c0f06bc69fcf344c7b94b7`。以下构建说明、旧讲稿和旧数据属于历史v4材料，不能用旧脚本直接覆盖当前稳定交付。

20 页、16:9，18 页正文后附 2 页真实规格渲染与浏览器截图。标题、正文、三张表、证据链及两张数据图为原生可编辑对象，原创技术图和实际截图作为独立图片嵌入。演讲背景、来源和实验边界写入每页 speaker notes。

作者源为 `build_presentation.mjs`、`data.json`、`speaker_notes.md`，图源读取上级 `figures`。脚本仅写本目录，不修改旧材料，不调用 API，不读凭据，不运行 DUT。

使用 Codex 的 JavaScript ES module 与 `@oai/artifact-tool`。首次本材料 authoring 前已成功运行一次 presentation marker，首次 PDF authoring 前已成功运行一次 PDF marker。已完成材料的重建不要重复这些首次操作。

运行新版本时用新 revision，保留历史 build 和 output：

```powershell
$env:V4_PPT_REVISION = 'r4'
& 'C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' './build_presentation.mjs'
```

脚本读取并核对旧事实源 SHA-256，核对最新与历史完整分母。原生图表附有从完整字面数据生成的工作簿快照。finalize 的结构、字体、布局和图表检查报告保存于 `build/<revision>/validation.json`。

每张最终 PNG 与 layout JSON 保存于 `build/<revision>/final-render`。PPTX 与答辩 PDF 保存于 `output/<revision>`。

稳定交付名为 `output/ICARUS_AI_IC_defense_v4.pptx` 和 `output/ICARUS_AI_IC_defense_v4.pdf`。当前来源见顶部更新及`delivery_receipt.json`，原r3材料由Git历史保留。

当前运行时的 native PDF 导出因缺少内部 `#standard-fonts/Helvetica` 模块失败。脚本保存此错误，并使用最终 artifact-tool 渲染 PNG 生成图像式答辩 PDF，相关来源 PNG 哈希保存在 `pdf_receipt.json`。PDF 用于阅读和投递，编辑使用 PPTX。

当前材料没有在 Microsoft PowerPoint、LibreOffice 或 Google Slides 中打开验证。artifact-tool 逐页预览和结构检查不等同于原生应用验收。
