"""外部工具探测：把"这台机器上 Icarus/Yosys/GTKWave 在哪"收敛到一个地方。

为什么需要它：测试与 CI 必须能在不同平台上找到工具。此前四个测试文件各自写死
`D:\\iverilog\\bin\\iverilog.exe`，导致：

- 只在本机通过，换到 Linux CI 上全部 skipped，CI 就成了摆设；
- 工具路径一改要动多处；
- 无法通过环境变量在无 PATH 的环境里指定。

解析顺序（先显式、后隐式）：

1. 显式入参（调用方指定）；
2. 环境变量 `IVERILOG_PATH` / `VVP_PATH` / `YOSYS_PATH` / `GTKWAVE_PATH`；
3. `PATH` 查找（Windows 上额外尝试 `.exe`）；
4. 常见安装目录；GTKWave 还会**从已找到的 iverilog 位置推断**
   （Icarus 官方 Windows 安装包把 GTKWave 放在同级 `gtkwave\\bin\\`，
   网页里"自动打开波形"就靠这条推断，不必手工填路径）。

探测不到时返回 ``None``，由调用方决定是 skip 还是报错——**绝不猜测路径**。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ToolPaths", "locate_tools", "find_executable", "gtkwave_candidates", "describe_tools"]

#: 常见安装位置（仅作为 PATH 之后的兜底，不覆盖显式配置）
_FALLBACK_DIRS = (
    r"D:\iverilog\bin",
    r"C:\iverilog\bin",
    r"D:\iverilog\gtkwave\bin",
    r"C:\iverilog\gtkwave\bin",
    r"C:\Program Files\gtkwave\bin",
    r"C:\Program Files (x86)\gtkwave\bin",
    r"D:\gtkwave\bin",
    "/usr/bin",
    "/usr/local/bin",
)


def find_executable(names: str | tuple[str, ...], *, explicit: str | Path | None = None,
                    env_var: str | None = None) -> str | None:
    """按"显式 → 环境变量 → PATH → 常见目录"的顺序查找可执行文件。"""

    candidates: list[str] = []
    if explicit:
        candidates.append(str(explicit))
    if env_var:
        value = os.environ.get(env_var)
        if value:
            candidates.append(value)
    if isinstance(names, str):
        names = (names,)
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for directory in _FALLBACK_DIRS:
        for name in names:
            candidates.append(str(Path(directory) / name))
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


@dataclass(frozen=True)
class ToolPaths:
    """一次探测的结果。任一字段为 None 表示该工具不可用。"""

    iverilog: str | None = None
    vvp: str | None = None
    yosys: str | None = None
    gtkwave: str | None = None

    @property
    def can_simulate(self) -> bool:
        return bool(self.iverilog and self.vvp)

    @property
    def can_synthesize(self) -> bool:
        return bool(self.yosys)

    @property
    def can_view_waveforms(self) -> bool:
        return bool(self.gtkwave)

    def to_dict(self) -> dict[str, object]:
        return {
            "iverilog": self.iverilog,
            "vvp": self.vvp,
            "yosys": self.yosys,
            "gtkwave": self.gtkwave,
            "can_simulate": self.can_simulate,
            "can_synthesize": self.can_synthesize,
            "can_view_waveforms": self.can_view_waveforms,
        }


def gtkwave_candidates(iverilog: str | Path | None = None) -> tuple[str, ...]:
    """GTKWave 的候选路径（含"Icarus 官方安装包"里的相对位置）。

    Icarus 的 Windows 安装包把 GTKWave 放在与 `bin` 同级的 `gtkwave/bin/` 下，
    因此只要找到了 `iverilog.exe`，就大概率能推出 `gtkwave.exe`：
    `<iverilog 目录>/../gtkwave/bin/gtkwave.exe`。这条推断比枚举盘符可靠得多。
    """

    candidates: list[str] = []
    if iverilog:
        binary = Path(iverilog)
        for parent in (binary.parent, binary.parent.parent):
            candidates.append(str(parent / "gtkwave" / "bin" / "gtkwave.exe"))
            candidates.append(str(parent / "gtkwave" / "bin" / "gtkwave"))
            candidates.append(str(parent / "gtkwave.exe"))
    return tuple(candidates)


def locate_tools(*, iverilog: str | Path | None = None, vvp: str | Path | None = None,
                 yosys: str | Path | None = None,
                 gtkwave: str | Path | None = None) -> ToolPaths:
    """探测四个外部工具的位置（波形查看器可选，缺失不影响仿真判决）。"""

    iverilog_path = find_executable(("iverilog", "iverilog.exe"), explicit=iverilog, env_var="IVERILOG_PATH")
    # GTKWave：显式 → 环境变量 → PATH → 常见目录 → 从 iverilog 位置推断。
    # `find_executable` 的兜底目录是全局的，随机型不同可能是别的盘；这里把推断出的
    # 候选放在它之后单独再找一轮，保持"显式 > 环境变量 > PATH > 猜测"的优先级。
    gtkwave_path = find_executable(("gtkwave", "gtkwave.exe"), explicit=gtkwave, env_var="GTKWAVE_PATH")
    if gtkwave_path is None:
        for candidate in gtkwave_candidates(iverilog_path):
            if Path(candidate).is_file():
                gtkwave_path = candidate
                break
    return ToolPaths(
        iverilog=iverilog_path,
        vvp=find_executable(("vvp", "vvp.exe"), explicit=vvp, env_var="VVP_PATH"),
        yosys=find_executable(
            ("yosys", "yosys.exe", "yowasp-yosys", "yowasp-yosys.exe"),
            explicit=yosys, env_var="YOSYS_PATH",
        ),
        gtkwave=gtkwave_path,
    )


def describe_tools(tools: ToolPaths | None = None) -> str:
    """生成一行可读的探测结果，供 CI 日志与环境自检使用。"""

    tools = tools or locate_tools()
    parts = []
    for label, value in (("iverilog", tools.iverilog), ("vvp", tools.vvp),
                         ("yosys", tools.yosys), ("gtkwave", tools.gtkwave)):
        parts.append(f"{label}={'未找到' if value is None else value}")
    return "；".join(parts)
