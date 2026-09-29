#Requires -Version 5.1
<#
.SYNOPSIS
    在本仓库和桌面上创建「启动/停止网页演示」快捷方式。

.DESCRIPTION
    给不想碰命令行的人用：双击快捷方式即可启动，再双击另一个即可停止。

    几个刻意的决定：

    - **窗口不隐藏。** 启动脚本会打印端口、地址与 Icarus 探测结果，而那个窗口同时就是
      Ctrl+C 的停止按钮。把它藏起来，用户就只剩任务管理器一条路了。启动脚本在**页面就绪后**
      会把它最小化到任务栏（`Hide-ConsoleWindow`）——是"退到一边"，不是"藏起来"。
    - **工作目录固定为仓库根。** 快捷方式默认继承"起始位置"，若用户把 .lnk 挪到别处，
      相对路径就会失效；这里显式写死。
    - **图标是我们自己画的**（`assets/iverilog-ai.ico`，由 `scripts/make_app_icon.py`
      生成），不借浏览器或 shell32 的图标——借来的图标会让人以为这是个网页书签。

.PARAMETER NoDesktop
    只在仓库目录里建，不往桌面放。

.EXAMPLE
    .\scripts\make_shortcuts.ps1
    .\scripts\make_shortcuts.ps1 -NoDesktop
#>
[CmdletBinding()]
param(
    [switch]$NoDesktop
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$icon = Join-Path $Root 'assets\iverilog-ai.ico'
if (-not (Test-Path $icon)) {
    Write-Host "图标不存在，先生成：$icon" -ForegroundColor Yellow
    & python (Join-Path $Root 'scripts\make_app_icon.py')
}

$shell = New-Object -ComObject WScript.Shell

function New-DemoShortcut {
    param(
        [string]$Directory,
        [string]$Name,
        [string]$Script,
        [string]$Description
    )
    $path = Join-Path $Directory "$Name.lnk"
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = Join-Path $Root $Script
    $shortcut.WorkingDirectory = $Root
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = $Description
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host "  已创建 $path" -ForegroundColor Green
}

#: 快捷方式名 → 目标脚本 → 说明
$entries = @(
    @{ Name = '启动网页演示'; Script = 'start_ui.cmd'; Description = '启动 Icarus 智测网页演示（自动挑端口、检查 Icarus、打开浏览器）' },
    @{ Name = '停止网页演示'; Script = 'stop_ui.cmd';  Description = '停止正在运行的 Icarus 智测网页演示' }
)

Write-Host "仓库目录：$Root"
foreach ($entry in $entries) { New-DemoShortcut -Directory $Root -Name $entry.Name -Script $entry.Script -Description $entry.Description }

if (-not $NoDesktop) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($desktop -and (Test-Path $desktop)) {
        Write-Host "桌面：$desktop"
        foreach ($entry in $entries) { New-DemoShortcut -Directory $desktop -Name $entry.Name -Script $entry.Script -Description $entry.Description }
    } else {
        Write-Host '找不到桌面目录，跳过（可用 -NoDesktop 显式跳过）。' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '完成。以后双击「启动网页演示」即可，不需要命令行。' -ForegroundColor Cyan
