# 比赛合规与交付行动计划

编制日期：2026-09-14  
适用项目：`E:\FPGA_WORK\iverilog-ai-lab`（独立项目）  
目标：在提交前完成比赛要求核对、材料准备和可复现性验收。

## 一、当前结论

项目技术方向符合“AI 开发工具与开源协作”，核心功能已经基本完成，当前主要风险集中在交付材料、公开发布、干净环境安装和文档口径一致性。

当前不能直接判定为“全部符合比赛要求”。完成本文件中的 P0 项并通过最终检查后，才可判定为具备正式提交条件。

## 二、P0：提交前必须完成

### 1. 修复干净环境安装

当前问题：`pyproject.toml` 的构建依赖为空，干净环境执行 `pip install -e .` 可能报 `No module named 'setuptools'`。

- [ ] 修复 `pyproject.toml` 的 `[build-system]` 配置。
- [ ] 在全新虚拟环境中执行：

  ```powershell
  python -m pip install -e ".[ui]"
  ```

- [ ] 在全新环境中完成 pytest、基准矩阵、综合矩阵和离线 AI 矩阵。
- [ ] 把成功安装和运行命令写入 README。

验收标准：陌生用户不依赖已有 `.venv`，仅按 README 可以启动项目并完成一次验证。

### 2. 统一所有文档数字

当前已核验的基线数字：

| 项目 | 最终数字 |
|---|---:|
| 基准案例 | 15 |
| 缺陷变体 | 83 |
| RTL 文件 | 98 |
| 自动化测试 | 436 passed（0 warning） |
| 静态规则 | 44 |
| 参考模型对齐 | 15/15 |
| 基准矩阵 | 15/15、83/83、0 误报、0 不可判定 |
| 综合矩阵 | 98/98 |
| 离线 AI 流程 | 15/15 |

- [ ] 修正技术报告中“80 个缺陷”等旧数字。
- [x] 修正第三方资源清单中“380 项测试”等旧数字。（已统一为 436 项）
- [ ] 区分当前结果、历史结果和实验结果，避免不同日期的数据混写。
- [ ] 检查所有 PDF 是否由最新 Markdown 重新生成。

### 3. 修正在线实验比较口径

当前在线模型报告的 `97.0% / 95.5%` 是 10 次实验后的累计覆盖率；固定、随机基线不是同样的统计口径。

- [ ] 同时报告“单 seed 平均检出率”和“10 次累计覆盖率”。
- [ ] 报告标准差或至少列出每个 seed 的检出数。
- [ ] 明确固定、随机、Mock AI、在线模型的重复次数和向量预算。
- [ ] 保留并公开未检出缺陷、不可判定请求和计划校验失败。
- [ ] 不使用累计覆盖率直接证明单轮 AI 优于基线。

建议使用的现有原始记录：

- Flash：10 个 seed 的平均检出率约 85.8%，累计覆盖 65/67。
- Pro：10 个 seed 的平均检出率约 87.8%，累计覆盖 64/67。
- 两模型并集：66/67。

### 4. 完成最终技术报告

- [ ] 以 `docs/competition/technical_report_draft.md` 为基础定稿。
- [ ] 统一项目名称、版本号、日期和所有实验数字。
- [ ] 包含问题场景、方案架构、AI 作用、开源融合、实验方法、效果、局限和安全边界。
- [ ] 明确 AI 只提出测试计划，最终判决来自参考模型与 Icarus/vvp。
- [ ] 明确仿真通过不等于综合、时序收敛或 FPGA 上板通过。
- [ ] 包含 AI 使用说明和人工审核方式。
- [ ] 检查不得出现学校名称、校徽、指导教师信息或其他不应披露信息。
- [ ] 控制在官方建议页数和文件大小以内。
- [ ] 从最终 Markdown 重新生成 PDF，并检查页数、图片、表格和中文字体。

### 5. 制作演示视频

- [ ] 制作 3–5 分钟 MP4。
- [ ] 使用真实工具运行过程，不只播放 PPT。
- [ ] 建议主线：用户痛点 → AI 生成 TestPlan → Schema 校验 → testbench → Icarus/vvp 裁决 → 缺陷反例 → 报告/VCD。
- [ ] 展示一个正确设计通过案例。
- [ ] 展示一个缺陷设计被检出的案例。
- [ ] 展示 AI 计划不是最终裁决者。
- [ ] 检查视频中没有学校、校徽、指导教师、密钥或未经授权素材。
- [ ] 检查时长、格式、分辨率和文件大小符合官方要求。

### 6. 建立公开成果链接

- [ ] 创建公开代码托管仓库或确认现有仓库公开可访问。
- [ ] 配置 Git remote。
- [ ] 更新 `CITATION.cff` 中的 `example.invalid` 占位链接。
- [ ] 检查 README 中的克隆地址、运行命令和文件链接。
- [ ] 创建提交前版本标签，例如 `v0.1.0` 或正式提交版本号。
- [ ] 从一台不依赖本机路径的环境访问仓库并完成最小复现。

## 三、P1：强烈建议完成

### 1. 真人试用

- [ ] 找 1–2 位未参与开发的试用者。
- [ ] 只提供 README 和 `docs/trial/task_card.md`，尽量不现场提示。
- [ ] 记录安装成功率、任务完成率、耗时和阻断问题。
- [ ] 保存原始 `feedback-*.json`。
- [ ] 用 `scripts/summarize_trial_feedback.py` 汇总结果。
- [ ] 将真实反馈写入 `docs/trial/results.md`。

### 2. 清理测试与终端输出问题

- [x] 处理 pytest 的 6 个 collection warning，避免项目看起来像有测试收集问题。
      （已修：`TestPlan` / `TestbenchGenerator` / `TestbenchGenerationError` 声明
      `__test__ = False`，现在 `python -m pytest -q` 是 436 passed、0 warning。）
- [x] 检查 Windows PowerShell 中矩阵脚本的中文输出乱码。
      （已在 README 写明重定向要用 `$env:PYTHONUTF8="1"`；控制台直出本身正常。）
- [ ] 确保 JSON、Markdown 和 PDF 产物中的中文内容正常显示。
- [ ] 在 README 中写明 Windows UTF-8 环境要求或改进脚本输出方式。

### 3. 完善第三方资源信息

- [ ] 再次核对 Icarus、Yosys、Python、Pydantic、Streamlit、pytest 和 GTKWave 的版本及许可证。
- [ ] 确保 `THIRD_PARTY.md` 与比赛版资源清单一致。
- [ ] 价格未核验时继续保留 `null`，核验后记录来源和日期。

## 四、人工确认事项

以下内容无法仅通过代码仓库确认，必须由参赛团队核对：

- [ ] 团队人数符合官方限制。
- [ ] 队长、成员和指导教师信息符合官方要求。
- [ ] 报名信息已经提交并缴费（如适用）。
- [ ] 团队拥有项目成果的合法权利。
- [ ] 没有未披露的第三方代码、数据、图片、音视频或知识产权争议。
- [ ] 最终材料中没有学校名称、校徽和指导教师信息。
- [ ] 提交时间不晚于官方截止时间：2026-10-15 20:00。

## 五、最终验收命令

在干净环境完成安装后，在项目根目录执行：

```powershell
python -m pytest -q
python scripts/run_benchmark_matrix.py
python scripts/run_synthesis_matrix.py
python scripts/run_pipeline_matrix.py
python -m mypy
python scripts/check_dead_code.py
python scripts/strip_bom.py --check
```

预期核心结果：

```text
436 passed（0 warning）
15/15 reference cases
83/83 defects detected
0 reference false positives
0 inconclusive benchmark runs
98/98 synthesis checks passed
15/15 offline pipeline cases passed
mypy: Success
dead code check: passed
encoding check: passed
```

## 六、提交包目录建议

```text
submission/
├── technical_report.pdf
├── demo.mp4
├── opensource_resource_list.pdf 或 .xlsx
├── project_summary.md 或 .pdf
├── evidence/
│   ├── benchmark_matrix.json
│   ├── synthesis_matrix.json
│   ├── pipeline_matrix.json
│   ├── representative_pass_report.html
│   ├── representative_defect_report.html
│   └── waveform.vcd
└── links.txt
```

## 七、提交前最终判定

只有同时满足以下条件，才可以标记为“符合比赛提交要求”：

- [ ] P0 的 6 项全部完成。
- [ ] 技术报告与实际代码、实验结果完全一致。
- [ ] 视频已经真实录制并通过内容合规检查。
- [ ] 公开仓库链接可访问，且不再使用占位链接。
- [ ] 干净环境安装和核心验收命令全部通过。
- [ ] 团队、报名、知识产权和材料禁忌事项已人工确认。

当前建议判定：**技术成果基本符合主题，但提交材料和公开发布尚未完全符合要求。**
