# ICARUS技术报告

报告按AI＋集成电路技术报告参考大纲的七章结构组织，正文采用连续排版，围绕模块、信号、时序和实际实验结果展开。

- [技术报告PDF](ICARUS_技术报告.pdf)：22页，约1万中文字、10幅图，865151字节。
- [可编辑文字稿](technical_report.md)：与PDF共用正文，图像使用相对路径。
- [构建脚本](build_report.py)：生成图表、目录和PDF，不调用模型API或运行DUT。
- [构建记录](build_receipt.json)与[视觉检查记录](visual_review.json)：绑定本次交付文件及逐页核验结果。

主要内容包括接口合约与编译预检、结构化测试生成、逐拍采样与参考比较、FIFO同拍读写、UART位计时、Agent执行状态，以及完整策略对照。实验数据引用既有运行记录；原始实验及历史材料保留。本报告未将未完成的异机功能复测或独立人工复核写成通过。

这是技术报告的重写，既有答辩PPT未在本次同步修改。

## 重新生成

在仓库根目录，使用包含Pillow、pypdf和reportlab的Python运行：

```powershell
python -X utf8 docs/competition/ic/technical_report/build_report.py
```

脚本使用Windows的宋体、黑体和微软雅黑字体，并读取仓库中已有的两幅规格波形及一幅实际界面截图。构建后需重新渲染和逐页检查；构建脚本会将视觉检查状态设回pending，不自动沿用旧的检查结论。
