"""工具探测（含 GTKWave）的回归测试。

GTKWave 是"可选但用户会点"的工具：网页上的「用 GTKWave 打开」找不到它时，用户看到的
只是一句"未找到"，很容易以为功能坏了。真实反馈就是"不知道是不是没办法自动获取路径"。
因此这里钉住三件事：

1. 显式路径 > 环境变量 > PATH 的优先级；
2. **从 iverilog 的安装位置推断 GTKWave**（Icarus 官方 Windows 包把它放在同级
   `gtkwave/bin/` 下）——这是"PATH 里没有也能找到"的关键；
3. 探测不到时返回 None，绝不猜测一个不存在的路径。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iverilog_ai.core.toolchain import (
    ToolPaths,
    describe_tools,
    find_executable,
    gtkwave_candidates,
    locate_tools,
)


def test_missing_tools_report_none_instead_of_garbage():
    tools = ToolPaths()
    assert tools.gtkwave is None and not tools.can_view_waveforms
    assert tools.iverilog is None and not tools.can_simulate
    assert set(tools.to_dict()) == {
        "iverilog", "vvp", "yosys", "gtkwave",
        "can_simulate", "can_synthesize", "can_view_waveforms",
    }


def test_find_executable_returns_none_for_a_missing_explicit_path():
    assert find_executable(("definitely-not-a-real-tool",), explicit=r"Z:\nope\tool.exe") is None


def test_explicit_path_wins_over_env_and_path(monkeypatch, tmp_path):
    fake = tmp_path / "gtkwave.exe"
    fake.write_bytes(b"stub")
    monkeypatch.setenv("GTKWAVE_PATH", str(tmp_path / "other.exe"))
    assert find_executable(("gtkwave",), explicit=fake, env_var="GTKWAVE_PATH") == str(fake)


def test_env_var_is_used_when_no_explicit_path(monkeypatch, tmp_path):
    fake = tmp_path / "gtkwave.exe"
    fake.write_bytes(b"stub")
    monkeypatch.setenv("GTKWAVE_PATH", str(fake))
    tools = locate_tools()
    assert tools.gtkwave == str(fake)


def test_gtkwave_is_inferred_from_the_iverilog_location(monkeypatch, tmp_path):
    """PATH 里没有 gtkwave 时，仍应能从 iverilog 的位置推出它。

    构造一个标准的 Icarus Windows 安装布局：
    ``<root>/bin/iverilog.exe`` + ``<root>/gtkwave/bin/gtkwave.exe``。
    """

    root = tmp_path / "iverilog"
    (root / "bin").mkdir(parents=True)
    (root / "gtkwave" / "bin").mkdir(parents=True)
    iv = root / "bin" / "iverilog.exe"
    gv = root / "gtkwave" / "bin" / "gtkwave.exe"
    iv.write_bytes(b"stub")
    gv.write_bytes(b"stub")

    monkeypatch.setenv("IVERILOG_PATH", str(iv))
    monkeypatch.delenv("GTKWAVE_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)  # PATH 里什么都没有
    # 同时清掉"常见安装目录"兜底，否则本机真的装了 GTKWave 时会先命中那一份，
    # 这条用例就测不到"从 iverilog 位置推断"这条路径了。
    monkeypatch.setattr("iverilog_ai.core.toolchain._FALLBACK_DIRS", ())

    tools = locate_tools()
    assert tools.iverilog == str(iv)
    assert tools.gtkwave == str(gv), tools.gtkwave
    assert tools.can_view_waveforms


def test_gtkwave_candidates_cover_the_official_layout(tmp_path):
    root = tmp_path / "iverilog"
    candidates = gtkwave_candidates(root / "bin" / "iverilog.exe")
    assert str(root / "gtkwave" / "bin" / "gtkwave.exe") in candidates
    assert gtkwave_candidates(None) == ()


def test_describe_tools_mentions_every_tool():
    text = describe_tools(ToolPaths(iverilog="i", vvp="v", yosys=None, gtkwave=None))
    for label in ("iverilog", "vvp", "yosys", "gtkwave"):
        assert label in text
    assert "未找到" in text


def test_real_environment_detection_does_not_crash():
    """本机实测：探测函数必须能在真实环境里跑通（找不到也只是 None）。"""

    tools = locate_tools()
    assert isinstance(tools.to_dict(), dict)
    if tools.gtkwave:
        assert Path(tools.gtkwave).is_file()


@pytest.mark.skipif(os.name != "nt", reason="此处只验证 Windows 官方安装包的推断规则")
def test_windows_official_bundle_layout_is_inferred_from_real_iverilog():
    """如果本机装了官方 Icarus 包，GTKWave 就该被推断出来（而不是必须手工填路径）。"""

    tools = locate_tools()
    if not tools.iverilog:
        pytest.skip("本机没有 iverilog")
    expected = Path(tools.iverilog).parent.parent / "gtkwave" / "bin" / "gtkwave.exe"
    if not expected.is_file():
        pytest.skip("本机的 iverilog 不是官方 Windows 安装包布局")
    assert tools.gtkwave is not None
    assert Path(tools.gtkwave).name.lower() in {"gtkwave.exe", "gtkwave"}
