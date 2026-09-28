#Requires -Version 5.1
<#
.SYNOPSIS
    一键启动 Icarus 智测的网页演示。

.DESCRIPTION
    为什么需要这个脚本：手动启动要记三件事——PYTHONPATH 指向 src、选一个没被占的端口、
    以及 Icarus 的路径。少记一样的表现都不一样（模块导入失败 / 端口冲突报错看不懂 /
    页面起来但仿真层显示"工具缺失"），而它们与"代码坏了"看起来没什么区别。

    这个脚本把这三件事都替你做完，并且**每一步都打印结论**，所以出问题时你能直接看到
    是哪一环。

.PARAMETER Port
    首选端口，默认 8501。被占用时会自动往后找空闲端口。

.PARAMETER Restart
    端口上已经有本项目的实例在跑时，先把它停掉再启。默认是**直接复用**（打印地址后退出），
    因为多数情况下你只是想打开页面，而不是重启。

.PARAMETER NoBrowser
    不自动打开浏览器。

.PARAMETER Headless
    无头模式：不打印额外提示、不打开浏览器，适合放进别的脚本里调用。

.EXAMPLE
    .\start_ui.ps1
    .\start_ui.ps1 -Port 8600
    .\start_ui.ps1 -Restart
#>
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$Restart,
    [switch]$NoBrowser,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'

# 用脚本自身位置定位仓库根：这样从任何目录、双击、或计划任务里调用都能工作。
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root 'src'
$env:PYTHONIOENCODING = 'utf-8'

function Write-Step { param([string]$Text) Write-Host "[启动] $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  OK   $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  注意 $Text" -ForegroundColor Yellow }
function Write-Bad  { param([string]$Text) Write-Host "  失败 $Text" -ForegroundColor Red }

function Test-PortBusy {
    param([int]$Candidate)
    return [bool](Get-NetTCPConnection -LocalPort $Candidate -State Listen -ErrorAction SilentlyContinue)
}

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

function Get-LanAddress {
    # 只在**物理/真实**网卡上找地址。
    #
    # 为什么不能只看 IP 段：实测这台机器上 192.168.240.1 是 VMware 的 VMnet 虚拟网卡，
    # 而真正的局域网地址在 172.17.x（Realtek 有线网卡）。按"常见内网段优先"的启发式
    # 正好会挑中那个虚拟地址——用户拿去手机上打开必然连不上，而脚本还说"就绪"。
    # 所以先按网卡名与描述剔掉虚拟适配器，再在剩下的里面挑。
    $virtualPattern = 'VMware|VirtualBox|Hyper-V|vEthernet|WSL|Loopback|TAP-|Tunnel|VPN|Radmin|ZeroTier|Tailscale|Docker|Npcap'
    $candidates = @()
    foreach ($adapter in (Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' })) {
        if ($adapter.Name -match $virtualPattern -or $adapter.InterfaceDescription -match $virtualPattern) { continue }
        foreach ($address in (Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
            if ($address.IPAddress -like '127.*' -or $address.IPAddress -like '169.254.*') { continue }
            $candidates += $address.IPAddress
        }
    }
    # 一块真实网卡都没识别出来时，退回不筛网卡的旧行为：宁可给一个可能不对的地址，
    # 也好过什么都不给（用户至少还能自己判断）。
    if (-not $candidates) {
        $candidates = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress)
    }
    if (-not $candidates) { return $null }
    $preferred = $candidates | Where-Object { $_ -like '192.168.*' -or $_ -like '10.*' -or $_ -match '^172\.(1[6-9]|2[0-9]|3[01])\.' }
    if ($preferred) { return $preferred | Select-Object -First 1 }
    return $candidates | Select-Object -First 1
}

# ---------------------------------------------------------------- 1. 环境
if (-not $Headless) { Write-Step '检查 Python…' }
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Bad '找不到 python。请安装 Python 3.11+ 并确保它在 PATH 里。'
    exit 2
}
& python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    $current = (& python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])") -join ''
    Write-Bad "需要 Python 3.11 或更高，当前是 $current。"
    exit 2
}
if (-not $Headless) { Write-Ok ((& python -V) -join '') }

& python -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn 'streamlit 未安装，尝试 python -m pip install -e ".[ui]" …'
    & python -m pip install -e '.[ui]'
    if ($LASTEXITCODE -ne 0) { Write-Bad '安装失败。请手动执行：python -m pip install -e ".[ui]"'; exit 2 }
}
if (-not $Headless) { Write-Ok 'streamlit 可用' }

if (-not $Headless) { Write-Step '检查 Icarus Verilog…' }
$toolsText = (& python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))" 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    Write-Warn "无法探测工具链：$toolsText"
} else {
    if (-not $Headless) { Write-Host "  $($toolsText -replace "`n", "`n  ")" }
    & python -c "from iverilog_ai.core.toolchain import locate_tools; raise SystemExit(0 if locate_tools().can_simulate else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn '没有找到 iverilog/vvp：页面能打开，但跑不了仿真。'
        Write-Warn '装好后重跑本脚本；或设环境变量 IVERILOG_PATH / VVP_PATH。'
    } elseif (-not $Headless) {
        Write-Ok '仿真工具链就绪'
    }
}

# ---------------------------------------------------------------- 2. 端口
if ((Test-PortBusy -Candidate $Port) -and (Test-IsOurApp -Candidate $Port)) {
    $url = "http://127.0.0.1:$Port"
    if (-not $Restart) {
        Write-Host ''
        Write-Ok "已有一个实例在 $Port 上运行，直接打开即可：$url"
        Write-Host "      （想重启请加 -Restart；想换端口请加 -Port 8600）"
        if (-not $NoBrowser -and -not $Headless) { Start-Process $url }
        exit 0
    }
    Write-Step "端口 $Port 上有正在运行的实例，按 -Restart 停掉它…"
    foreach ($connection in (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

if (Test-PortBusy -Candidate $Port) {
    $original = $Port
    while ((Test-PortBusy -Candidate $Port) -and $Port -lt $original + 20) { $Port++ }
    if (Test-PortBusy -Candidate $Port) {
        Write-Bad "从 $original 起找了 20 个端口都被占用。请用 -Port 指定一个空闲端口。"
        exit 2
    }
    Write-Warn "端口 $original 被别的程序占用，改用 $Port。"
}

# ---------------------------------------------------------------- 3. 启动
$streamlitArgs = @(
    '-m', 'streamlit', 'run', 'ui/app.py',
    '--server.port', "$Port",
    '--server.address', '0.0.0.0',
    '--server.headless', 'true',
    '--browser.gatherUsageStats', 'false'
)

$url = "http://127.0.0.1:$Port"
if (-not $Headless) {
    Write-Step "启动 Streamlit（端口 $Port）…"
    Write-Host ''
}

$process = Start-Process -FilePath 'python' -ArgumentList $streamlitArgs -NoNewWindow -PassThru

# 轮询健康检查：Streamlit 起来要几秒，直接打印地址会让用户点开一个还没就绪的页面。
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { break }
    if (Test-IsOurApp -Candidate $Port) { $ready = $true; break }
}

if (-not $ready) {
    if ($process.HasExited) {
        Write-Bad "Streamlit 退出（退出码 $($process.ExitCode)）。上面的日志里有原因。"
    } else {
        Write-Bad '等了一分钟还没就绪。请直接看上面的 Streamlit 日志。'
    }
    exit 2
}

if (-not $Headless) {
    Write-Host ''
    Write-Host '  网页已就绪：' -NoNewline -ForegroundColor Green
    Write-Host $url
    $lan = Get-LanAddress
    if ($lan) { Write-Host "  同局域网其他设备：http://${lan}:$Port" }
    Write-Host '  停止服务：在本窗口按 Ctrl+C'
    Write-Host ''
}
if (-not $NoBrowser -and -not $Headless) { Start-Process $url }

Wait-Process -Id $process.Id
