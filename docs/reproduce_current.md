# 当前版本的干净克隆与复核

本指南用于先确认程序可运行，再组织真人试用或异机复核。仅用确定性规划器和已有测试输入，不读取模型凭据，不请求模型 API。API 实验成绩以各自封存原件为准。

需要 Python 3.11 或 3.12、Git、uv，以及可从 PATH 找到的 Icarus `iverilog/vvp`。Yosys 是可选综合层；RTL 维护包的规格重建另外需要已安装的 readable-verilog-generator 技能、Node/npm 和 WaveDrom 3.6.1。本指南不会把这些外部工具伪装成项目自带依赖。

## 1. 取得完整的已提交仓库

Windows 克隆前给本次 Git 命令启用长路径，避免深层归档日志缺失。真实仓库为[TYOCT-13/iverilog-ai-lab](https://github.com/TYOCT-13/iverilog-ai-lab)；2026-10-08建仓核对时远程尚无提交，见[核对记录](competition/repository_readiness_2026-10-08.md)。代码推送完成前，仍使用收到的完整本地仓库执行下列步骤。

```powershell
git -c core.longpaths=true clone --no-local E:/FPGA_WORK/iverilog-ai-lab E:/icarus-review
Set-Location E:/icarus-review
git config --local core.longpaths true
git status --short
git rev-parse HEAD
```

确认GitHub上已有代码后，第一条克隆命令可改为：

```powershell
git -c core.longpaths=true clone https://github.com/TYOCT-13/iverilog-ai-lab.git E:/icarus-review
```

远程克隆与另一台设备运行须另记实际结果，不沿用本机克隆的验收声明。

未修改的副本应为空状态。若已经遇到 `Filename too long`，保留首次 stderr 和状态记录；只在确认副本没有自己修改的文件后恢复其缺失文件，或者用新目录重新克隆。不要直接在有改动的工作目录里执行恢复。

## 2. 用锁文件安装复核环境

```powershell
uv sync --locked --extra dev --extra ui --no-python-downloads
$reviewPy = (Resolve-Path .venv/Scripts/python.exe).Path
& $reviewPy -V
& $reviewPy -m iverilog_ai --help
```

`--locked` 会在项目声明和锁文件不一致时失败，而不是偷偷重新解析版本。首次安装需要包仓库网络；缓存齐全后可以加 `--offline`。项目锁文件保存了已验收的主要依赖版本，mypy 固定为 1.11.2；不要以某个新版工具的结果替换旧版验收原件。

Linux 的解释器位置为 `.venv/bin/python`。本轮机器验证是 Windows、Python 3.12.7；其他平台和解释器版本需另记实际结果，不承诺所有支持范围都已经测试。

## 3. 先跑离线核心流程

```powershell
$env:IVERILOG_AI_ALLOW_NETWORK = '0'
& $reviewPy scripts/run_benchmark_matrix.py --output-dir .tmp-codex/review-benchmark-r1

& $reviewPy -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter.v --output-dir .tmp-codex/review-same-r1
$LASTEXITCODE

& $reviewPy -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter_bug_wrap9.v --output-dir .tmp-codex/review-different-r1 --print-markdown
$LASTEXITCODE
```

手写测试台矩阵的期望是 15 个参考、0 误报、83/83 缺陷检出、0 不可判定。这是旧基准的复测，不能写成 Agent 超过随机。两次行为对比的退出码依次为 0、1；2 表示没有获得可比证据或输入预检失败，不能当作一致。

为每次复核使用新目录，保留命令、退出码、stdout/stderr、报告和波形。只有“文件不存在”造成的退出码 2，不等于实际仿真了一个编译失败样本。

## 4. 检查源码和网页

```powershell
& $reviewPy -m pytest -q --junitxml=.tmp-codex/review-tests-r1.xml
& $reviewPy -m mypy
& $reviewPy scripts/check_dead_code.py
& $reviewPy scripts/check_doc_index.py
& $reviewPy -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
```

网页打开后先使用离线规划器，选择案例、生成计划、执行、导出，再切页查看输入和结果是否保留。真人记录按 [参与者入口](trial/participant_start.md) 的任务卡进行。

回归必须同时记录通过、失败、错误和跳过。干净副本里依赖历史私有输入的旧外部模块测试可能跳过；跳过不算通过，也不能据此声称所有历史实验均可纯克隆重放。本机产物和未随 Git 分发的旧 ZIP 见 [本机清单](local_artifacts.md)。

## 5. 单独重放 RTL 维护包

```powershell
& $reviewPy -B -X utf8 benchmarks/rtl_style_maintenance_20261007/publishable_reproduce.py --out-dir .tmp-codex/review-rtl-r1 --mode all --skill-root "$env:USERPROFILE/.codex/skills/readable-verilog-generator"
```

每轮会执行 36 次原/新双侧 DUT；它是同组向量复测，不是新的独立样本或模型检出率。检查 18 份规格产物、每轮 5115 项输出比较、正确 A 与保留故意缺陷的 B/C。正式门禁六项通过、两项 `not_requested`；不能用额外仿真改写正式门禁 JSON。

## 6. 第二台电脑与真人证据

异机复核必须在另一台实际设备上操作，记录设备、系统、Git commit、工具版本、安装失败、协助及所有命令。共享作者电脑、重新克隆或新建 venv 仍是同机复核。独立人审见 [复核指南](review/independent_review_guide.md)，代理执行不替真人签认。

提交 v3 PDF/PPT 的原件仍保持封存；本指南及后续维护验收是单独补充材料。实际上传、队号、转赛道、分享链接和可选录屏仍需真实操作与回执。
