"""网页演示的"非命令行入口"回归测试：启动 / 停止 / 快捷方式 / 图标。

为什么值得单独测：这一层面向**不碰命令行的人**，所以他们遇到问题时不会去看日志、
也不会改用命令行绕过去——双击没反应就是没反应。而这里的失败模式又特别安静：
快捷方式指向一个被改名的脚本、图标文件被清理掉、停止脚本按进程名而不是按端口杀进程
（于是误杀别人的 Python）。这些都要靠断言钉住。
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SHELLS = [item for item in ("powershell", "pwsh") if shutil.which(item)]

_ICON_SPEC = importlib.util.spec_from_file_location(
    "_make_app_icon", ROOT / "scripts" / "make_app_icon.py"
)
assert _ICON_SPEC and _ICON_SPEC.loader
make_app_icon = importlib.util.module_from_spec(_ICON_SPEC)
_ICON_SPEC.loader.exec_module(make_app_icon)


# ------------------------------------------------------------------ 文件清单


@pytest.mark.parametrize(
    "name",
    ["start_ui.ps1", "start_ui.cmd", "stop_ui.ps1", "stop_ui.cmd", "scripts/make_shortcuts.ps1"],
)
def test_demo_entry_points_exist(name: str) -> None:
    assert (ROOT / name).is_file(), f"缺少 {name}"


def test_launcher_sets_up_the_environment_itself() -> None:
    """启动脚本要把三件事都做掉：PYTHONPATH、端口探测、仓库根定位。

    这三件事少记任何一样，报错都长得像"代码坏了"——那正是这个脚本存在的理由。
    """

    source = (ROOT / "start_ui.ps1").read_text(encoding="utf-8-sig")
    assert "PYTHONPATH" in source and "'src'" in source
    assert "'-m', 'streamlit', 'run', 'ui/app.py'" in source
    assert "$MyInvocation.MyCommand.Path" in source, "必须能从任意 cwd 启动"
    assert "Test-PortBusy" in source and "_stcore/health" in source, "必须探测端口是否已在本项目上"
    assert "Get-NetAdapter" in source, "局域网地址必须排除虚拟网卡（VMware/Hyper-V 会挑错地址）"


def test_stop_finds_the_process_by_port_not_by_name() -> None:
    """停止脚本必须**按端口**找进程，并在杀之前确认那是我们的服务。

    按进程名（`python`）杀会误杀用户自己跑的其他 Python 程序；不确认就杀则可能在
    端口被别的服务占用时杀错人。两个断言分别钉住这两点。
    """

    source = (ROOT / "stop_ui.ps1").read_text(encoding="utf-8-sig")
    assert "Get-NetTCPConnection -LocalPort" in source
    assert "_stcore/health" in source, "杀之前必须确认那是我们的服务"
    assert "Get-Process -Name" not in source, "不许按进程名杀"


def test_shortcut_names_match_the_documented_ones() -> None:
    """快捷方式名是用户界面的一部分——脚本里改了名，README 就会指向不存在的东西。"""

    source = (ROOT / "scripts" / "make_shortcuts.ps1").read_text(encoding="utf-8-sig")
    for name in ("启动网页演示", "停止网页演示"):
        assert name in source, f"快捷方式名缺少 {name}"
    assert "GetFolderPath('Desktop')" in source, "要放到桌面——那才是双击的地方"
    assert "$shortcut.WorkingDirectory" in source, "必须写死工作目录，否则 .lnk 被挪走就失效"


def test_readme_tells_people_about_the_shortcut() -> None:
    doc = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "启动网页演示" in doc and "make_shortcuts.ps1" in doc


def test_console_steps_aside_only_after_the_page_is_ready() -> None:
    """就绪后控制台要自己退到任务栏，但**只能最小化**，且不许拖垮服务。

    双击快捷方式的人要的是浏览器，不是一个停在桌面上的黑窗口；可这个窗口同时是
    唯一的日志窗口和"关掉即停止"的按钮，所以三条约束缺一不可：
    - 退让方式必须是"最小化"而不是隐藏——关窗口这条路得留着；
    - 按**标题**找窗口：控制台窗口属于 conhost，控制台进程自己的
      `MainWindowHandle` 是 0，那条常见写法在这里根本走不通；
    - 取窗口句柄在无交互控制台（计划任务、输出重定向）里必然失败，
      所以只能放在 try 里静默跳过——"收不了窗口"绝不该让服务起不来。
    """

    source = (ROOT / "start_ui.ps1").read_text(encoding="utf-8-sig")
    # 只看代码行：注释里恰好解释了这个坑（MainWindowHandle 是 0），不该被当成用法
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "$Host.UI.RawUI.WindowTitle" in code, "任务栏上要能认出这个窗口是什么"
    assert "关掉本窗口" in code, "标题要说明关掉它就等于停止服务"
    assert "FindWindow" in code, "按标题找窗口，而不是用 $PID 的 MainWindowHandle"
    assert "MainWindowHandle" not in code
    assert "ShowWindow($handle, 6)" in code, "6 = SW_MINIMIZE：只最小化，不隐藏"
    assert "} catch { }" in code, "拿不到窗口时静默跳过"

    # 顺序是刻意的：先打印就绪信息，再打开浏览器，最后才让控制台退让。
    ready = code.index("网页已就绪")
    browser = code.index("Start-Process $url", ready)
    assert browser > ready
    assert code.index("Hide-ConsoleWindow", browser) > browser
    assert "if (-not $Headless) { Hide-ConsoleWindow }" in code, "无头模式不要动窗口"


# ------------------------------------------------------------------ 图标


def test_icon_generator_is_deterministic_and_multi_size() -> None:
    """图标由脚本生成（离线、可重跑），且必须包含小尺寸。

    只放 256×256 的话，任务栏与资源管理器会自己缩放出锯齿——16/32/48 必须显式嵌进去。
    """

    first = make_app_icon.build(256).tobytes()
    second = make_app_icon.build(256).tobytes()
    assert first == second, "同一输入必须画出同一张图"
    assert set(make_app_icon.SIZES) >= {16, 32, 48, 256}
    # 小尺寸下对勾会被缩糊，脚本据此不画它——这是刻意的，不是遗漏
    assert make_app_icon.build(16).tobytes() != make_app_icon.build(32).tobytes()


def test_committed_icon_is_present_and_valid() -> None:
    """图标要进仓库：没有 Pillow 的机器也得能建出带图标的快捷方式。"""

    icon = ROOT / "assets" / "iverilog-ai.ico"
    assert icon.is_file(), "缺少 assets/iverilog-ai.ico"
    header = icon.read_bytes()[:6]
    assert header[:4] == b"\x00\x00\x01\x00", "不是有效的 .ico 头"
    count = int.from_bytes(header[4:6], "little")
    assert count >= 4, f".ico 里只嵌了 {count} 种尺寸，小尺寸会糊"


# ------------------------------------------------------------------ 真实解释器


@pytest.mark.skipif(not SHELLS, reason="环境里没有任何 PowerShell")
@pytest.mark.parametrize("script", ["start_ui.ps1", "stop_ui.ps1", "scripts/make_shortcuts.ps1"])
def test_scripts_parse_under_a_real_shell(script: str) -> None:
    """用真实解释器解析。

    `powershell`（5.1）是双击时的解释器，也是唯一会因为缺 BOM 而报错的；
    `pwsh`（7+）不会暴露那个问题。两者都试才算真的检查过。
    """

    target = ROOT / script
    for shell in SHELLS:
        completed = subprocess.run(
            [
                shell, "-NoProfile", "-Command",
                f"$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('{target}', [ref]$null, [ref]$e) | Out-Null; "
                "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 } else { exit 0 }",
            ],
            capture_output=True, text=True, timeout=120,
        )
        assert completed.returncode == 0, f"{shell} 解析 {script} 失败：{completed.stdout}{completed.stderr}"
