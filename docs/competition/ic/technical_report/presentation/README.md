# 与当前技术报告同步的答辩材料

- [可编辑PPT](ICARUS_答辩材料.pptx)：20页，16:9。
- [答辩PDF](ICARUS_答辩材料.pdf)：同一PPT最终渲染生成的图像式PDF，共20页。
- [来源与检查回执](delivery_receipt.json)：记录报告源码、PPT来源、文件SHA和逐页渲染绑定。

正文对应上级目录的23页技术报告，包括当前实现、多文件预检、FIFO与UART判据、完整策略对照、用户自定义RTL运行和复核意见处理。原有两张实验图表保留原工作簿，新增FIFO图表使用固定数值快照；文字、8页原生表格及3页原生图表可在PPT中编辑。图片、旧界面截图和规格波形分别标明用途，没有将历史截图当成本次界面验收。

20页PPT已逐页渲染检查，PDF的20页已实际渲染并核对嵌入像素。当前检查使用artifact-tool和Poppler，未在Microsoft PowerPoint或其他Office软件中打开。PDF用于阅读，修改内容应使用PPTX。

## 构建来源

`sync_from_report.mjs`从Git提交`9b39751748b5739459c0f06bc69fcf344c7b94b7`读取原20页PPT，保留布局及视觉样式，更新文字、表格、图表和讲稿来源；`restore_source_workbooks.py`恢复导入导出过程中丢失的原图表工作簿链接，并核对缓存数值。

脚本依赖Codex随附的`@oai/artifact-tool`和演示文稿检查工具，路径在脚本顶部指定，不是运行ICARUS网页的依赖。在完整Git历史及该运行时可用的环境中，从本目录执行：

```powershell
node sync_from_report.mjs r10
```

使用未存在的revision以保留上次产物。构建输出位于本目录`output/<revision>`，检查和预览位于仓库的`.iverilog-ai/presentation-sync-20261020/<revision>`；重新构建后应重新检查全部页面，不能沿用当前回执。PDF可使用`docs/competition/ic/v4/presentation/export_image_pdf.py`从最终PPT渲染的20张PNG生成。稳定交付文件仅在检查通过后更新。

旧入口`docs/competition/ic/v4/presentation/output/ICARUS_AI_IC_defense_v4.pptx`及同名PDF已同步相同字节。原18页报告、旧PPT构建脚本和历史讲稿仍属于当时材料，阅读当前内容请使用本目录文件和PPT内的讲稿。
