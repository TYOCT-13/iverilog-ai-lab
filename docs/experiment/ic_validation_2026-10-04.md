# 集成电路方向机器验收与最终回归（2026-10-04）

本记录是实际执行的自动回归和浏览器操作，参与真人 **0 人**。它证明所列工程流程在本机运行过，不替代真人试用、独立人工复核或芯片签核。

## 1. 测试对象与来源

- 被测源码提交：`1c1e0dc5b30a65a83673951cc495b1a7b700511c`。
- 开始前冻结 `src/`、`ui/`、`scripts/`、`tests/` 的 Python 文件，以及 `pyproject.toml`、基准清单，共 **148 个文件 SHA-256**。
- 本节落盘时逐项复核：源码变化 **0 项**。后续 PDF 渲染器修复及其完整回归另记于第六节；旧 API 试验成绩不当作新源码成绩。
- 实测环境：Windows，本机 Python 3.12.7、Icarus Verilog 12.0；确切版本输出见 [validation.json](ic-validation-2026-10-04/validation.json)。
- 源码指纹与完整命令见 [metadata.json](ic-validation-2026-10-04/metadata.json)。

## 2. 完整工程门禁

| 检查 | 实际结果 | 持久证据 |
|---|---|---|
| 完整 pytest | **914 passed / 1 skipped / 0 failed**，211.47 秒 | [原日志](ic-validation-2026-10-04/pytest.log)、[JUnit](ic-validation-2026-10-04/pytest.xml) |
| mypy，`src ui scripts` | **72 个源码文件，0 error** | [类型日志](ic-validation-2026-10-04/mypy.log) |
| 未可达代码检查 | **160 个扫描文件，未发现** | [检查日志](ic-validation-2026-10-04/deadcode.log) |
| 编码 / BOM | **0 个问题** | [编码日志](ic-validation-2026-10-04/bom.log) |

唯一跳过项是 `tests/core/test_rule_assertions.py:55`：当前推荐断言表为空，无可验证条目。915 是本轮收集用例总数，914 是通过数；它们不是 RTL 缺陷数量，也不是 AI 检出率。

核心重跑命令：

```powershell
python -X utf8 -m pytest -q --junitxml .iverilog-ai/ic-validation-sampling-guard-20261004/pytest.xml --basetemp C:/Users/TYOCT/AppData/Local/Temp/ic-sampling-guard-full-regression-20261004
python -X utf8 -m mypy src ui scripts
python -X utf8 scripts/check_dead_code.py
python -X utf8 scripts/strip_bom.py --check
```

重新执行应另选输出和临时目录，保留本次日志。pytest 的 `--basetemp` 目录必须在仓库之外。

## 3. 本次修复的边界

多模块在线试验暴露了顺序逻辑 `before` 采样与内置参考模型更新顺序不一致的问题。当前实现拒绝给这类计划生成权威的 `reference_model` 期望；没有其他独立判据时，Agent 以证据不足停止。它是安全拒绝机制，**没有声称完成 before 相位的通用参考模型支持**。

测试还覆盖了省略输入的保持语义：向量未重新列出某输入时，参考模型跟随生成测试台保持前值，不再逐向量重置为默认值。实际计数器 Icarus 仿真和模型比对均已执行。

外部适配器通过测试台实际采样位置输出快照，使用单独的 `qualified_baseline_differential` 观察类型；其 before / after 快照不依赖上述内置参考模型。详见 [外部交叉检查](../review/external_agent_cross_review_2026-10-04.md)与[内置参考告警诊断](../review/reference_alarm_diagnosis_2026-10-04.md)。

**原 60 行在线试验保留冻结提交 `e9b7b8a` 的成绩，未在本修复后重跑或重算。** 旧误报、漏检、错误和用量仍见 [在线试验报告](agent_comparison_live_2026-10-04.md)。

## 4. 浏览器实际操作

使用本机 Edge 和 Playwright 打开 `http://127.0.0.1:8600/`，不是只检查页面源码。规划器选离线模式，仿真使用真实 Icarus。

| 操作 | 结果 |
|---|---|
| 1440×900、1920×1080 桌面，390×844 手机宽度 | 三个尺寸均未检测到横向溢出，生成按钮可访问 |
| 上传现有 `rtl/simple_alu.v` 并校验接口 | 完成 |
| 生成计划并执行仿真 | **28 组向量、84/84 条实际比对一致** |
| 从工作台进入设置，再返回 | 上传文件、计划与结果仍显示，`84/84` 结果保留 |
| 执行后再次检查 390 宽度 | 无横向溢出，结果文字可读 |

浏览器事实、页面文字和检查结果保存于 [browser/results.json](ic-validation-2026-10-04/browser/results.json)。截图如下：

- [1440 桌面](ic-validation-2026-10-04/browser/workspace-1440.png)
- [1920 桌面](ic-validation-2026-10-04/browser/workspace-1920.png)
- [390 手机宽度](ic-validation-2026-10-04/browser/workspace-390.png)
- [上传后桌面工作区](ic-validation-2026-10-04/browser/workspace-run-desktop.png)
- [运行后手机工作区](ic-validation-2026-10-04/browser/workspace-run-mobile.png)
- [手机结果区](ic-validation-2026-10-04/browser/results-mobile.png)

手机检查是桌面浏览器视口模拟，不是实体手机测试。截图使用 Streamlit 自身滚动容器，部分图片只显示当时视口，不代表整页没有其他内容。此轮没有重新逐项运行所有网页功能；规则审查、导出、错误分支等已有的选定自动验收另见 [22 项 UI / CLI 机器验收](../trial/machine_acceptance_2026-10-04.md)。

## 5. 保留的失败与局限

本轮完整回归前，曾将 pytest 的 `--basetemp` 放入仓库内部，得到 909 通过、1 失败、1 跳过。已有安全测试要求临时测试目录在项目外，因此此设置违反测试前提；未删改断言，换到仓库外临时目录后得到 910 通过、1 跳过。其后加入采样保护和输入保持的四项测试，得到本记录的 914 / 1。

上述两个历史输出目录仍保留：`.iverilog-ai/ic-validation-exact-snapshot-20261004/`、`.iverilog-ai/ic-validation-final-20261004/`。浏览器辅助脚本的早期尝试也保留：首次未上传必需输入，第二次用错误按钮文字判定成功，第三次改用实际 `84/84` 结果签名。没有删除页面的前提校验，也没有伪造成功结果。

所有记录都是机器或代理执行；尚无真实人员满意度、真人完成时间或独立人工认证。不能凭这些记录推出获奖等级、AI 全面优于固定 / 随机向量，或工业设计签核结论。

持久附件指纹统一见 [validation.json](ic-validation-2026-10-04/validation.json)。原始本机目录在 Git 忽略范围，公开材料只收录明确的证据白名单。

## 6. PDF 渲染器修复后的最终源码验证

实际逐页检查报告时，发现原转换器列表首行与编号重叠，且中英文混排在长中文词段前会提前换行。源码 `867b8bd564c881954c98cc18813884a4074d1ed5` 修正了文本换行和列表间距；Agent、参考模型与冻结 API 试验成绩没有随之变化。

旧技术报告和项目概览也使用该转换器，因此同步按原 Markdown 重导出，实验数字没有更新。已有渲染器测试在重导出后 **9 项通过**；之前两项新鲜度失败保留为修复过程，不能将它们写成当时全部通过。该次定向测试结束时还出现 Windows 默认临时目录的退出清理权限提示，进程退出码为零；最终完整回归改用显式独立临时目录，原定向输出没有作为最终回归凭据。

最终完整回归在新目录实跑，**914 passed / 1 skipped / 0 failed，227.34 秒**。冻结 148 个源码与配置指纹，结束时变化 **0 项**；mypy 72 文件无错误，未可达扫描 163 文件未发现，BOM 0 问题。163 包含当时辅助脚本等扫描对象，不是产品功能数。

- [最终验证摘要](ic-validation-pdf-final-2026-10-04/validation.json)
- [完整 pytest 日志](ic-validation-pdf-final-2026-10-04/pytest.log)与[JUnit](ic-validation-pdf-final-2026-10-04/pytest.xml)
- [冻结源码和命令](ic-validation-pdf-final-2026-10-04/metadata.json)
- [mypy](ic-validation-pdf-final-2026-10-04/mypy.log)、[未可达检查](ic-validation-pdf-final-2026-10-04/deadcode.log)、[BOM](ic-validation-pdf-final-2026-10-04/bom.log)

此轮没有重新调用 API，也没有重测原 60 行 pilot。文档与 PDF 的后续修改不改变所冻结的 Python 源码，最终 IC PDF 的篇幅、元数据、版面与 SHA-256 另行登记。

## 7. 冻结字节与 Git 归档

Windows 工作区的换行符与 Git 规范化后的源码字节可能不同。单独提供 Git archive 不能保证逐文件匹配原实验登记的 SHA-256。本轮另存 `.iverilog-ai/frozen-registered-inputs-20261004/`：有效 pilot 64 份、首次中断 64 份、采样保护验证 148 份、最终验证 148 份，合计 **424 份，全部匹配，未匹配 0 项**。这是四份快照的合计，包含重复文件。

其中 4 份从对应 Git blob 恢复 LF→CRLF 后与原登记哈希精确一致；其余来自当前精确字节或相同的 Git 原始字节。获取方式、对应提交、规范化字节哈希和原登记哈希都写入子清单，没有修改原始实验或重算成绩。该目录将随本地证据包交付；复放时先提取相应完整提交，再按子快照的相对路径覆盖登记文件。

新公开实验附件使用范围明确的 `-text` 属性保留原字节，避免再次提交时换行转换破坏工件哈希。未对历史原始文件整体改写换行符，也未据此宣称完成异机复现。
