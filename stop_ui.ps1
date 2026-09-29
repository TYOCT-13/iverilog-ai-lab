#Requires -Version 5.1
<#
.SYNOPSIS
    停止正在运行的网页演示。

.DESCRIPTION
    为什么需要它：启动脚本留下的那个控制台窗口就是"停止按钮"（Ctrl+C）。但用快捷方式
    启动的人往往会把窗口最小化或关掉，之后就没有干净的停止办法了——只能去任务管理器里
    猜哪个 python.exe 是它。这个脚本按**端口**找进程（而不是按进程名），因此不会误杀
    你在别处跑的其他 Python 程序。

    判断"是我们的实例"用的是健康检查端点 `/stcore/health`，与启动脚本同一套判据。

.PARAMETER Port
    要停的端口，默认 8501。

.PARAMETER ScanRange
    8501 被别的程序占用过、实例其实在别的端口上时，自动往后扫多少个端口。默认 10。

.EXAMPLE
    .\stop_ui.ps1
    .\stop_ui.ps1 -Port 8600
#>
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [int]$ScanRange = 10
)

$ErrorActionPreference = 'Stop'

function Test-IsOurApp {
    param([int]$Candidate)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Candidate/_stcore/health" `
            -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$target = $null
for ($candidate = $Port; $candidate -le $Port + $ScanRange; $candidate++) {
    if (Test-IsOurApp -Candidate $candidate) { $target = $candidate; break }
}

if ($null -eq $target) {
    Write-Host "没有找到正在运行的网页演示（在 $Port 起扫了 $($ScanRange + 1) 个端口）。" -ForegroundColor Yellow
    Write-Host '它可能已经停了；也可以用 -Port 指定你启动时用的端口。'
    exit 0
}

$connections = Get-NetTCPConnection -LocalPort $target -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    Write-Host "端口 $target 上探测到服务，但找不到监听进程——请用任务管理器结束 python.exe。" -ForegroundColor Yellow
    exit 2
}

foreach ($connection in $connections) {
    $processId = $connection.OwningProcess
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    $name = if ($process) { $process.ProcessName } else { '(已退出)' }
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    Write-Host "已停止端口 $target 上的进程 $processId（$name）。" -ForegroundColor Green
}

Start-Sleep -Milliseconds 800
if (Test-IsOurApp -Candidate $target) {
    Write-Host "端口 $target 上仍有响应，可能没停干净；再跑一次或查任务管理器。" -ForegroundColor Yellow
    exit 2
}
Write-Host "端口 $target 已释放。" -ForegroundColor Green
exit 0
