# 真人复现指南（2026-10-08）

这份说明用于在另一台电脑运行公开代码，并保存安装、操作和结果证据。代码统一固定到已上传的 **f7867db67cde354e8664205b0470ade8ba18dc17**，不要在一次会话中途改用新的 main。

仓库：[TYOCT-13/iverilog-ai-lab](https://github.com/TYOCT-13/iverilog-ai-lab)。远程提交核对见[上传确认记录](competition/repository_publication_2026-10-08.md)。本指南和[空白复现记录表](trial/forms/reproduction_record.md)可单独发给参与者；它们是执行材料，尚不代表有真人复现结果。

## 1. 先确定本次范围

| 需求 | 执行范围 | 交回的主要证据 |
|---|---|---|
| 基础复现 | 第2至6节：安装、离线矩阵、行为对比、网页操作 | 环境、commit、完整终端记录、运行产物、截图、反馈 |
| 完整源码回归 | 基础复现后，选第7节源码检查 | pytest/JUnit、通过/失败/错误/跳过明细、mypy与扫描输出 |
| RTL维护版重放 | 第7节维护包；另需技能脚本、Node和WaveDrom | 双侧运行、规格重建与门禁的实际结果 |
| 独立技术审核 | 按独立复核指南；另交冻结审核输入包 | 对规格、变体、判据和证据的逐条判断 |

基础复现使用离线确定性规划器，不需要模型API密钥或GPU。Yosys、WaveDrom和作者电脑上的技能不属于基础复现必需项。建议先安排1人预试，再按角色安排3–5人；这是组织建议，不是赛事人数硬要求。

组织者先分配匿名代号和任务。真正用自己的另一台电脑记 independent_machine；共享作者电脑记 shared_host。预装工具、获得提示、接受代操作分别记录，不能据此自动写成“独立安装成功”。

## 2. 开始记录，再检查工具

下面以Windows PowerShell为例。把P01-R1换成本人的会话编号；复测另用R2，保留首次文件。

```powershell
$reproSession = 'P01-R1'
$reproRoot = Join-Path (Join-Path $env:USERPROFILE 'icarus-repro') $reproSession
if (Test-Path -LiteralPath $reproRoot) { throw '该目录已存在，请使用新的会话编号，保留旧记录。' }
New-Item -ItemType Directory -Path $reproRoot -ErrorAction Stop | Out-Null
Start-Transcript -Path (Join-Path $reproRoot 'terminal.txt') -NoClobber
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$PSVersionTable.PSVersion
git --version
uv --version
python --version
iverilog -V
vvp -V
Get-Command git,uv,python,iverilog,vvp -ErrorAction SilentlyContinue | Select-Object Name,Source
```

需要Git、Python、uv及配套的iverilog/vvp。本示例使用Python3.12；作者本机证据为Windows/Python3.12.7/Icarus12.0。其他系统、Python小版本或Icarus版本记录实际值，不沿用作者环境声明。

缺工具时先保存现象，再按官方说明安装：[Git for Windows](https://git-scm.com/downloads/win)、[Python](https://www.python.org/downloads/windows/)、[uv](https://docs.astral.sh/uv/getting-started/installation/)、[Icarus](https://steveicarus.github.io/iverilog/usage/installation.html)。选择Python3.12的Windows安装器；不要直接换成下载页上的最新大版本。Windows可以使用适合本机的Icarus预编译包；由组织者提供包时，记录来源、版本和安装协助。

安装后需要重开终端时，先执行Stop-Transcript。新终端用相同会话编号恢复变量，并记录到新的续记文件；安装前的terminal.txt不覆盖：

```powershell
$reproSession = 'P01-R1'
$reproRoot = Join-Path (Join-Path $env:USERPROFILE 'icarus-repro') $reproSession
if (-not (Test-Path -LiteralPath $reproRoot)) { throw '找不到原会话目录，请核对编号。' }
$reproSegment = 'terminal-resume-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt'
Start-Transcript -Path (Join-Path $reproRoot $reproSegment) -NoClobber
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:IVERILOG_AI_ALLOW_NETWORK = '0'
if (Test-Path -LiteralPath (Join-Path $reproRoot 'source')) {
    Set-Location (Join-Path $reproRoot 'source')
    if (Test-Path -LiteralPath '.venv/Scripts/python.exe') { $reviewPy = (Resolve-Path '.venv/Scripts/python.exe').Path }
}
$reproOut = Join-Path '.iverilog-ai/reproduction' $reproSession
```

恢复后重新输出本节的工具版本，接着做上次尚未完成的步骤；不要重新创建已有运行目录或覆盖原结果。

版本命令不存在、需要管理员权限或网络下载失败，都如实记录。不要把未安装或预装写成参与者自行安装成功。没有GPU信息也不影响基础复现；只做操作复现时不需要收集显卡、设备序列号、MAC或IP地址。

## 3. 从GitHub克隆并固定版本

```powershell
git -c core.longpaths=true -c core.autocrlf=false clone https://github.com/TYOCT-13/iverilog-ai-lab.git (Join-Path $reproRoot 'source')
$reproCloneExit = $LASTEXITCODE
"clone_exit=$reproCloneExit"
if ($reproCloneExit -ne 0) { throw '克隆失败，先保留记录，不继续安装。' }

Set-Location (Join-Path $reproRoot 'source')
git config --local core.longpaths true
git config --local core.autocrlf false
git checkout --detach f7867db67cde354e8664205b0470ade8ba18dc17
$reproCheckoutExit = $LASTEXITCODE
"checkout_exit=$reproCheckoutExit"
if ($reproCheckoutExit -ne 0) { throw '固定版本失败，先保留记录。' }
git rev-parse HEAD
git status --porcelain
Get-FileHash -Algorithm SHA256 -LiteralPath 'uv.lock','benchmarks/manifest.json','rtl/mod10_counter.v','rtl/mod10_counter_bug_wrap9.v'
```

未修改的副本应为空Git状态。长路径与换行设置用于避免归档缺文件及登记输入的字节差异。完整克隆可能需要几分钟；出现超时或Filename too long时保留首次输出，新会话另建目录，不覆盖自己的旧记录。

同一台电脑上的新克隆或新虚拟环境仍是同机验证。只有在另一台实际设备执行，才记录为异机复现。

## 4. 安装锁定依赖

```powershell
uv sync --locked --extra dev --extra ui --python 3.12 --no-python-downloads
$reproInstallExit = $LASTEXITCODE
"install_exit=$reproInstallExit"
if ($reproInstallExit -ne 0) { throw '依赖安装失败，先保留输出并联系组织者。' }
$reviewPy = (Resolve-Path '.venv/Scripts/python.exe').Path
& $reviewPy -V
& $reviewPy -m iverilog_ai --help
& $reviewPy -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; t=locate_tools(); print(describe_tools(t)); raise SystemExit(0 if t.can_simulate else 1)"
"toolchain_exit=$LASTEXITCODE"
```

首次安装需要访问包仓库。记录下载等待和总用时；缓存已齐后才考虑离线安装。锁检查失败时保留错误，不能为得到成功结果改锁文件或混装随机新版依赖。若选择Python3.11，应同步修改上面的解释器选择并另记实际版本。

工具探测应找到iverilog与vvp；未找到时暂停仿真，检查本机PATH或工具设置。Yosys未安装可记录为未做综合，本轮基础复现不要求给出综合结果。

## 5. 运行离线核心流程

运行目录必须在仓库内；以下目录已被Git忽略，不能改到仓库外直接交给矩阵脚本。

```powershell
$env:IVERILOG_AI_ALLOW_NETWORK = '0'
$reproOut = Join-Path '.iverilog-ai/reproduction' $reproSession
New-Item -ItemType Directory -Path $reproOut -ErrorAction Stop | Out-Null

& $reviewPy scripts/run_benchmark_matrix.py --output-dir "$reproOut/benchmark"
"matrix_exit=$LASTEXITCODE"

& $reviewPy -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter.v --output-dir "$reproOut/same"
"same_exit=$LASTEXITCODE"

& $reviewPy -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter_bug_wrap9.v --output-dir "$reproOut/different" --print-markdown
"different_exit=$LASTEXITCODE"

if (Test-Path -LiteralPath 'rtl/__repro_missing_input__.v') { throw '预检控制文件意外存在，请保留现象并联系组织者。' }
& $reviewPy -m iverilog_ai verify-diff --baseline rtl/mod10_counter.v --candidate rtl/__repro_missing_input__.v --output-dir "$reproOut/missing"
"missing_exit=$LASTEXITCODE"
```

| 操作 | 预期 | 怎样记录 |
|---|---|---|
| 手写测试台矩阵 | 15参考、误报0、83/83缺陷检出、不可判定0；退出0 | 保存benchmark/matrix.json、矩阵报告和各运行日志 |
| 同文件对比 | 当前有限计划下identical；退出0 | 保存同侧输入、计划、报告与波形 |
| wrap9缺陷对比 | different；退出1 | 退出1表示检出差异，不能直接叫作程序崩溃 |
| 不存在的输入 | 输入预检失败；退出2 | 该操作DUT执行为0，不称为实际编译失败仿真 |

实际结果不符就记失败或不可判定，并保存原文；不得重跑到成功后删除首次记录。矩阵是固定手写测试台的复测，不能据83/83写成API Agent超过随机或全输入正确性证明。

以上四项属于T09的子步骤。转录到会话JSON时合并为一条T09任务记录，子步骤结果和产物另留；不要新增汇总脚本不支持的任务ID。

## 6. 在网页上完成一条真实流程

```powershell
& $reviewPy -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
```

在这台电脑打开 http://127.0.0.1:8600/ ，按分配的任务完成：

1. 工具设置选择“离线确定性规划器（无需密钥、进程内）”，保存工具状态截图。
2. 工作台选择一个内置案例，填写验证目标，生成计划并执行；保存计划与结果页。对应T02。
3. 查看一个缺陷变体的结论、失败依据和波形说明，写下自己如何判断。对应T03。
4. 输入非默认目标或设置，切换页面后返回，检查当前输入和结果是否保留；不同设计的结果须能区分。对应T07。
5. 导出运行包，保存下载文件；按包内说明在新目录重放，保存实际结果和失败原文。对应T08。

RTL开发者可追加T04自定义输入、T05行为对比、T06规则审查。API体验另分配T10，基础复现不需要任何模型凭据。实体手机另记设备及受控访问地址；电脑缩窄窗口不能算真实手机。

8600被占用时记下错误，改用8601并同步浏览器地址。localhost只代表当前设备，不能直接作为另一台手机的访问地址。结束时在自己启动的服务终端按Ctrl+C。

## 7. 按需追加进阶检查

### 完整源码检查

```powershell
& $reviewPy -m pytest -q "--junitxml=$reproOut/pytest.xml"
"pytest_exit=$LASTEXITCODE"
& $reviewPy -m mypy
"mypy_exit=$LASTEXITCODE"
& $reviewPy scripts/check_dead_code.py
"dead_code_exit=$LASTEXITCODE"
& $reviewPy scripts/check_doc_index.py
"doc_index_exit=$LASTEXITCODE"
```

保留JUnit和终端输出，分别登记通过、失败、错误、跳过及原因。作者同机锁环境历史为2020通过/16跳过，其中14项缺少未随Git提供的历史外部输入；该数目不能硬套到另一台电脑。额外工具、平台和权限会影响实际结果，缺文件的跳过不能算通过。

源码检查或技能门禁未执行时，写“未分配/未执行”，不能写全门禁通过。

### RTL维护版重放

需要独立提供并安装readable-verilog-generator技能及其依赖、Node/npm和WaveDrom3.6.1；仓库没有打包这些工具。组织者应先检查实际技能路径，不要求普通使用者为基础复现安装它们。

```powershell
& $reviewPy -B -X utf8 benchmarks/rtl_style_maintenance_20261007/publishable_reproduce.py --out-dir "$reproOut/rtl-maintenance" --mode all --skill-root "$env:USERPROFILE/.codex/skills/readable-verilog-generator"
"rtl_maintenance_exit=$LASTEXITCODE"
```

同组每轮36次原/新DUT、5115输出比较、18规格文件重建，均需查看实际输出。维护版B/C故意缺陷应保留；两项正式门禁仍为not_requested。不把同组复测当成新模型成绩、形式等价或硬件签核。

### 独立人审

按[独立复核指南](review/independent_review_guide.md)执行。审核者应没有编写对应功能、变体、计划或判据，并披露与团队的关系。普通复现成功不自动算H02。

历史3个外部模块的审核输入部分位于作者的被忽略目录，组织者需另交冻结输入、来源许可、规格、哈希、计划及原始日志。单纯Git克隆不包含这些文件；资料未齐时应记无法审核，不能补造结论。

## 8. 结束后交回什么

```powershell
git rev-parse HEAD
git status --porcelain
if ($reproOut -and (Test-Path -LiteralPath $reproOut)) {
    $reproReturnDir = Join-Path $reproRoot 'run-artifacts'
    if (Test-Path -LiteralPath $reproReturnDir) { throw '回收目录已存在，请另取名称，不覆盖旧证据。' }
    Copy-Item -LiteralPath $reproOut -Destination $reproReturnDir -Recurse
}
Stop-Transcript
```

只有确实创建并使用了reproOut时才复制；未做到这一节也保留此前日志。选择以下文件整理成一个回收包，不打包source、.git、.venv或模型凭据：

- 填写的复现记录表、开始/结束时间、环境与实际commit。
- terminal.txt及续记文件，包含克隆、安装、工具版本、命令、退出码和首次失败。
- run-artifacts：矩阵、对比、计划、testbench、编译/仿真日志、波形；做了源码检查时包含JUnit。
- 网页截图、运行导出包及其重放记录；录屏仅在事先同意时保存。
- 提示、解释、代操作的记录；本人核对后的反馈和引用选择。

复现人用匿名代号即可。无需姓名、学号、电话、学校、精确地址、IP、MAC或API密钥。公开材料使用去标识副本，私人路径等信息按授权范围处理，原件由约定人员保存。

结果应由实际操作人确认。没有计时填未记录，未知协助不填0。首次失败、帮助完成、跳过和复测分别保留；同人复测不重复计人数，安装/网络等待不从总耗时中抹去。

组织者按[组织流程](trial/organizer_workflow.md)将真人原件存到被Git忽略的目录，再转录现有2.0模板并由本人核对。公开汇总只使用同意匿名引用的会话；录屏同意不自动等于允许公开完整视频。没有实际人员原件时，results.md继续保持待收集。
