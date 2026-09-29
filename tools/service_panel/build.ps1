#Requires -Version 5.1
<#
.SYNOPSIS
    把 tools/service_panel/ServicePanel.cs 编译成仓库根目录的 IcarusPanel.exe。

.DESCRIPTION
    为什么用 csc.exe 而不是 PyInstaller / Nuitka：

    - **不需要下载任何东西。** csc 是 Windows 自带的 .NET Framework 编译器
      （`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`），所以在一台
      只装了 Python 和 Icarus 的机器上也能重新编译这个 exe。
    - **产物小。** 这个 exe 是 20 多 KB；PyInstaller 会把整个 Python 运行时打进去，
      变成几十 MB，而且每次启动都要解包。
    - **它本来也不需要 Python。** 面板只做三件事：轮询一个 HTTP 健康检查、
      调两个 PowerShell 脚本、显示一个窗口——WinForms 全都有。

    `/codepage:65001` 是必需的：源码是不带 BOM 的 UTF-8（仓库约定，见
    `scripts/strip_bom.py`），不指定代码页的话 csc 会按系统 ANSI（中文机器上是 GBK）
    解码，界面上的中文会变成乱码——而乱码的界面在编译期没有任何警告。
    `tests/core/test_demo_scripts.py` 钉住了这条参数，改掉会红。

.EXAMPLE
    .\tools\service_panel\build.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
# 仓库根 = 本脚本往上两层（tools\service_panel\build.ps1 → tools\service_panel → tools → 根）
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Source = Join-Path $Root 'tools\service_panel\ServicePanel.cs'
$Manifest = Join-Path $Root 'tools\service_panel\app.manifest'
$Icon = Join-Path $Root 'assets\iverilog-ai.ico'
$Output = Join-Path $Root 'IcarusPanel.exe'

foreach ($required in @($Source, $Manifest)) {
    if (-not (Test-Path $required)) { throw "缺少必需文件：$required" }
}
if (-not (Test-Path $Icon)) {
    Write-Host "图标不存在，先生成：$Icon" -ForegroundColor Yellow
    & python (Join-Path $Root 'scripts\make_app_icon.py')
}

# 优先 4.0：WinForms 与高 DPI 清单都要它；3.5 只是兜底（老机器上可能只剩这个）。
$compiler = $null
foreach ($version in @('v4.0.30319', 'v3.5')) {
    $candidate = Join-Path $env:WINDIR "Microsoft.NET\Framework64\$version\csc.exe"
    if (Test-Path $candidate) { $compiler = $candidate; break }
}
if (-not $compiler) {
    throw "找不到 csc.exe。它属于 .NET Framework（Windows 自带）；装了 .NET Framework 4.x 就有。"
}

Write-Host "编译器：$compiler"
$arguments = @(
    '/nologo'
    '/target:winexe'          # GUI 子系统：双击不弹黑窗口（控制台子系统会闪一个）
    '/platform:anycpu'
    '/optimize+'
    '/codepage:65001'         # 源码是不带 BOM 的 UTF-8，不指定就会按 GBK 解码成乱码
    "/win32icon:$Icon"
    "/win32manifest:$Manifest"
    "/out:$Output"
    '/reference:System.dll'
    '/reference:System.Drawing.dll'
    '/reference:System.Windows.Forms.dll'
    $Source
)

& $compiler $arguments
if ($LASTEXITCODE -ne 0) { throw "编译失败（csc 退出码 $LASTEXITCODE）" }
if (-not (Test-Path $Output)) { throw "csc 报成功但没有产物：$Output" }

$size = (Get-Item $Output).Length
Write-Host ("已生成 {0}（{1:N0} 字节）" -f $Output, $size) -ForegroundColor Green
Write-Host '双击它即可打开开关面板；命令行也可以用 /start、/stop、/status。'
