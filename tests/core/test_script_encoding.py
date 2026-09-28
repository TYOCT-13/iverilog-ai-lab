"""脚本编码约定的门禁测试。

这三条规则各对应一个真实事故，其中最隐蔽的是 `.ps1` 的 BOM：

- Windows PowerShell **5.1**（"右键 → 使用 PowerShell 运行"用的就是它）读**无 BOM** 的
  `.ps1` 时按系统 ANSI 代码页（中文 Windows 上是 GBK）解码，脚本里的中文全部乱码；
  pwsh 7+ 不受影响，所以这个问题只在特定入口暴露。
- 更麻烦的是它的**报错形态**：中文被读坏后引号配对失败，报的是
  `The string is missing the terminator`——看起来像语法错误，实际是编码问题。
  事故现场：`start_ui.ps1` 加完 BOM 后，一次普通的文本编辑又把 BOM 弄掉，脚本随即报这个错。

所以它必须由门禁守着，而不是靠"记得加 BOM"。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import strip_bom  # noqa: E402

BOM = b"\xef\xbb\xbf"


def _scan(tmp_path: Path, name: str, body: bytes) -> list[str]:
    target = tmp_path / name
    target.write_bytes(body)
    return strip_bom.scan_encoding_conventions(target)


# ------------------------------------------------------------------ .ps1


def test_ps1_with_chinese_requires_a_bom(tmp_path: Path) -> None:
    """含中文的 .ps1 没有 BOM → 必须报出来（否则 5.1 下中文全乱码）。"""

    issues = _scan(tmp_path, "a.ps1", "Write-Host '中文提示'\n".encode("utf-8"))
    assert issues and "BOM" in issues[0]


def test_ps1_with_chinese_and_bom_is_fine(tmp_path: Path) -> None:
    assert _scan(tmp_path, "b.ps1", BOM + "Write-Host '中文提示'\n".encode("utf-8")) == []


def test_ascii_only_ps1_needs_no_bom(tmp_path: Path) -> None:
    """纯 ASCII 的 .ps1 不需要 BOM——BOM 只在"有非 ASCII"时才有意义。"""

    assert _scan(tmp_path, "c.ps1", b"Write-Host 'plain'\n") == []


def test_ps1_that_is_not_utf8_is_reported(tmp_path: Path) -> None:
    issues = _scan(tmp_path, "d.ps1", "Write-Host '中文'\n".encode("gbk"))
    assert issues and "UTF-8" in issues[0]


# ------------------------------------------------------------------ .cmd


def test_cmd_with_chinese_is_rejected(tmp_path: Path) -> None:
    """cmd.exe 按 OEM 代码页解码，中文在 .cmd 里必然乱码，必须改成英文。"""

    issues = _scan(tmp_path, "a.cmd", "@echo off\r\nREM 中文注释\r\n".encode("utf-8"))
    assert issues and ("ASCII" in issues[0] or "OEM" in issues[0])


def test_cmd_with_bom_is_rejected(tmp_path: Path) -> None:
    """BOM 会让 cmd.exe 把第一行当成命令的一部分——比乱码更糟，直接报错。"""

    issues = _scan(tmp_path, "b.cmd", BOM + b"@echo off\r\n")
    assert issues and "BOM" in issues[0]


def test_ascii_cmd_is_fine(tmp_path: Path) -> None:
    assert _scan(tmp_path, "c.cmd", b"@echo off\r\necho hello\r\n") == []


# ------------------------------------------------------------------ 其它类型


def test_python_file_with_bom_is_rejected(tmp_path: Path) -> None:
    """Python 解析器不容忍 BOM——这正是这个门禁最初存在的理由。"""

    issues = _scan(tmp_path, "a.py", BOM + b"x = 1\n")
    assert issues and "BOM" in issues[0]


def test_mojibake_is_detected_from_the_encoding_operation(tmp_path: Path) -> None:
    """样本**由编码操作生成**，不是手打的字面量。

    两个理由：① 手打的样本会让这个测试文件自己被门禁拦下（第一版就是这样）；
    ② 手打的中日韩字符很容易写成"看起来一样但码位不同"的字——仓库原来的正则就栽在这里，
    它写死了几个码位不对的字符，于是永远不会命中，而测试和文档都显示它在站岗。
    """

    target = tmp_path / "bad.v"
    damaged = "中文".encode("utf-8").decode("gbk", errors="replace")
    target.write_bytes(f"// {damaged}\n".encode("utf-8"))
    issues = strip_bom.scan_mojibake(target)
    assert issues
    assert any("U+FFFD" in item or "mojibake" in item for item in issues)


def test_plain_replacement_character_is_detected(tmp_path: Path) -> None:
    """U+FFFD 本身就该报——正常源码里不该出现它，它是"某处用错了解码器"的通用痕迹。"""

    target = tmp_path / "bad2.v"
    target.write_bytes(("// 复位信号 " + "\ufffd" + "\n").encode("utf-8"))
    assert strip_bom.scan_mojibake(target)


def test_clean_utf8_chinese_is_not_flagged(tmp_path: Path) -> None:
    """正常中文不能被误报——误报会让这条门禁被绕过。"""

    target = tmp_path / "good.v"
    target.write_bytes("// 复位信号低有效，同步释放\n".encode("utf-8"))
    assert strip_bom.scan_mojibake(target) == []


# ------------------------------------------------------------------ 真实仓库与真实脚本


def test_repository_scripts_pass_the_gate(capsys: pytest.CaptureFixture) -> None:
    """仓库里所有脚本都必须过这条门禁——包括 `start_ui.ps1` 与 `start_ui.cmd`。"""

    assert strip_bom.main(["--check"]) == 0, capsys.readouterr().out


def test_launcher_scripts_exist() -> None:
    """启动脚本本身也是交付物：有人会直接双击它，路径与文件名不能漂。"""

    assert (ROOT / "start_ui.ps1").is_file()
    assert (ROOT / "start_ui.cmd").is_file()
    source = (ROOT / "start_ui.ps1").read_text(encoding="utf-8-sig")
    # 关键行为：设 PYTHONPATH 指向 src、用 python -m streamlit 启、从脚本自身定位仓库根
    assert "PYTHONPATH" in source and "'src'" in source
    assert "'-m', 'streamlit', 'run', 'ui/app.py'" in source
    assert "$MyInvocation.MyCommand.Path" in source, "必须能从任意 cwd 启动"
    assert "Test-PortBusy" in source and "_stcore/health" in source, "必须探测端口是否已在本项目上"


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_launcher_parses_under_a_real_shell(shell: str) -> None:
    """用真实解释器解析一遍——只有它在，才说明脚本真的没有语法错误。

    两者都试是刻意的：`powershell`（5.1）是双击时的解释器，也是唯一会因为缺 BOM
    而报错的；`pwsh`（7+）不会暴露那个问题，但它是开发时常用的。
    """

    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f"环境里没有 {shell}")
    script = ROOT / "start_ui.ps1"
    completed = subprocess.run(
        [
            executable, "-NoProfile", "-Command",
            f"$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$null, [ref]$e) | Out-Null; "
            "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 } else { exit 0 }",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
