# Windows首次安装补充（2026-10-08）

适用于另一台Windows x64复现电脑，在开始克隆前准备Git、Python、uv、Icarus/vvp。代码仍固定f7867db，完整流程见[复现指南](reproduce_current.md)。这份补充不是安装成功记录，未执行真人仿真或API。

## 1. 当前报错怎样理解

- Git、uv、iverilog、vvp无法识别：这些命令尚不可用，可能未安装，也可能未加入当前终端PATH。
- Python只显示WindowsApps入口，且没有输出版本：尚未确认真实Python解释器可用；Windows提供的商店快捷入口可以产生这种现象。见[Microsoft说明](https://learn.microsoft.com/zh-cn/windows/python/faqs)。
- `python -v`是详细运行输出，查询版本用`python -V`或`python --version`。

保留已创建的P01-R1/terminal.txt。如果原终端还开着，下面安装过程继续记录到该文件；不删除或重建会话目录。给复现人提供安装指导应记为协助，不当作零提示独立安装。

## 2. 使用WinGet安装

先在原PowerShell确认：

```powershell
winget --version
$env:PROCESSOR_ARCHITECTURE
```

AMD64表示本节适用的x64环境。若没有winget，跳到第5节；其他架构记录实际环境，另选适配工具，不直接运行x64安装器。

逐条执行，前一条安装完成后再执行下一条；失败时保存完整输出，不用忽略哈希检查或反复运行全部命令：

```powershell
winget install --id Git.Git -e --source winget
"git_install_exit=$LASTEXITCODE"
```

```powershell
winget install --id Python.Python.3.12 -e --source winget --version 3.12.10 --scope user --architecture x64
"python_install_exit=$LASTEXITCODE"
```

```powershell
winget install --id astral-sh.uv -e --source winget --version 0.9.9
"uv_install_exit=$LASTEXITCODE"
```

```powershell
winget install --id Icarus.Verilog -e --source winget --version 12.2022.06.11
"icarus_install_exit=$LASTEXITCODE"
```

本机已只读核对以上包ID及Python3.12.10、uv0.9.9和Icarus12.2022.06.11的可获取性；没有替参与者执行安装。uv0.9.9对应作者已有工具；Python3.12.10与作者3.12.7不同，需按参与者实际版本登记。Icarus包同时提供编译器和vvp运行器，不需要分别下载两套工具。

包管理器或安装器出现许可证和安装确认时，参与者按自己电脑的实际情况处理。具体参数见[WinGet文档](https://learn.microsoft.com/en-us/windows/package-manager/winget/install)。

## 3. 刷新当前终端并检查

全部安装完成后，在同一个终端刷新进程PATH，从已保存的系统和用户配置重新读取。这不会改写永久PATH，原会话变量和终端记录继续保留：

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
Get-Command git,uv,python,iverilog,vvp -ErrorAction SilentlyContinue | Select-Object Name,Source
git --version
uv --version
python --version
iverilog -V
vvp -V
```

应能看到五个命令的实际来源及版本。不因安装命令返回成功就跳过版本检查。

如果Python仍指向WindowsApps且不输出版本，在开始菜单搜索“管理应用执行别名”，关闭“应用安装程序”下的python.exe/python3.exe快捷入口；再次检查版本。关闭快捷入口不等于安装Python。安装器运行时勾选Add Python to PATH，或使用已安装解释器的完整路径。

如果仅Icarus不可用，先确认自己实际选择的安装目录。若使用默认C:/iverilog且两个文件确实存在，可以仅为当前终端加入：

```powershell
$reproIcarusBin = 'C:/iverilog/bin'
if (-not (Test-Path -LiteralPath (Join-Path $reproIcarusBin 'iverilog.exe'))) { throw '这里不是实际Icarus安装目录，请核对安装位置。' }
if (-not (Test-Path -LiteralPath (Join-Path $reproIcarusBin 'vvp.exe'))) { throw '安装目录缺少vvp，请保留现象并检查安装。' }
$env:Path = $reproIcarusBin + ';' + $env:Path
iverilog -V
vvp -V
```

安装在其他位置时只修改reproIcarusBin为本人的实际bin目录，不能照抄作者D:盘路径。这个临时设置在关闭终端后失效；本次在同一终端启动项目，后续新终端需自行确认工具路径。

## 4. 接着做什么

工具版本均可读取后，继续主指南第3节“从GitHub克隆并固定版本”。不要重跑创建P01-R1目录的代码，现有目录是用来保留首次记录的。

如果必须关闭终端，先Stop-Transcript；新终端按主指南第2节的续记代码恢复P01-R1变量并新建terminal-resume文件。其他人代为安装、下载等待、安装失败和重开终端都记录，未知次数和用时不填0。安装准备完成不代表矩阵、网页或独立H02已完成。

## 5. WinGet不可用或下载失败

可以在Microsoft Store安装或更新“应用安装程序”（Microsoft），再重开终端检查winget；说明见[获取WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/)。也可使用下列发布者提供的安装方式，记录自己实际选择及失败尝试：

| 工具 | 来源与选择 |
|---|---|
| Git | [Git for Windows](https://git-scm.com/install/windows)，x64安装器；安装时允许从命令行使用 |
| Python | [Python3.12.10](https://www.python.org/downloads/release/python-31210/)，Windows installer (64-bit)，勾选Add Python to PATH |
| uv | [Astral安装说明](https://docs.astral.sh/uv/getting-started/installation/)，可选0.9.9 Windows发布包或固定版本安装器 |
| Icarus | [Windows打包者页面](https://bleyer.org/icarus/)，选iverilog-v12-20220611-x64_setup.exe，不把其他版本写成已测试的12 |

网络错误只说明此次下载失败，保留原文；未成功下载前不继续宣称安装完成。此补充不修改此前已发ZIP或它的SHA清单，可作为独立附件一并发送。
