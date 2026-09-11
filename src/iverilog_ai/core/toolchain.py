"""外部工具探测：把"这台机器上 Icarus/Yosys 在哪"收敛到一个地方。

为什么需要它：测试与 CI 必须能在不同平台上找到工具。此前四个测试文件各自写死
`D:\\iverilog\\bin\\iverilog.exe`，导致：

- 只在本机通过，换到 Linux CI 上全部 skipped，CI 就成了摆设；
- 工具路径一改要动多处；
- 无法通过环境变量在无 PATH 的环境里指定。

解析顺序（先显式、后隐式）：

1. 显式入参（调用方指定）；
2. 环境变量 `IVERILOG_PATH` / `VVP_PATH` / `YOSYS_PATH`（本项目 CLI 与网页也已
   使用这组变量名）；
3. `PATH` 查找（Windows 上额外尝试 `.exe`）。

探测不到时返回 ``None``，由调用方决定是 skip 还是报错——**绝不猜测路径**。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ToolPaths", "locate_tools", "find_executable", "describe_tools"]

#: 常见安装位置（仅作为 PATH 之后的兜底，不覆盖显式配置）
_FALLBACK_DIRS = (
    r"D:\iverilog\bin",
    r"C:\iverilog\bin",
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

    @property
    def can_simulate(self) -> bool:
        return bool(self.iverilog and self.vvp)

    @property
    def can_synthesize(self) -> bool:
        return bool(self.yosys)

    def to_dict(self) -> dict[str, object]:
        return {
            "iverilog": self.iverilog,
            "vvp": self.vvp,
            "yosys": self.yosys,
            "can_simulate": self.can_simulate,
            "can_synthesize": self.can_synthesize,
        }


def locate_tools(*, iverilog: str | Path | None = None, vvp: str | Path | None = None,
                 yosys: str | Path | None = None) -> ToolPaths:
    """探测三个外部工具的位置。"""

    return ToolPaths(
        iverilog=find_executable(("iverilog", "iverilog.exe"), explicit=iverilog, env_var="IVERILOG_PATH"),
        vvp=find_executable(("vvp", "vvp.exe"), explicit=vvp, env_var="VVP_PATH"),
        yosys=find_executable(
            ("yosys", "yosys.exe", "yowasp-yosys", "yowasp-yosys.exe"),
            explicit=yosys, env_var="YOSYS_PATH",
        ),
    )


def describe_tools(tools: ToolPaths | None = None) -> str:
    """生成一行可读的探测结果，供 CI 日志与环境自检使用。"""

    tools = tools or locate_tools()
    parts = []
    for label, value in (("iverilog", tools.iverilog), ("vvp", tools.vvp), ("yosys", tools.yosys)):
        parts.append(f"{label}={'未找到' if value is None else value}")
    return "；".join(parts)
