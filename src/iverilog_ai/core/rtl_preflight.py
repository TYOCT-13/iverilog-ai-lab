"""上传 RTL 的编译预检查：只解析和展开，不执行用户设计。"""
from __future__ import annotations

import math
from pathlib import Path

from .config import SafePathPolicy, _resolve_tool, _safe_define, _safe_top
from .executor import _run_process
from .models import ProcessResult
from .toolchain import locate_tools


def check_rtl_syntax(
    rtl_path: str | Path,
    *,
    project_root: str | Path,
    top_module: str,
    defines: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    iverilog_path: str | None = None,
    timeout_seconds: float = 10.0,
) -> ProcessResult:
    """用 Icarus null 目标预检查当前源文件及依赖；不生成或执行 vvp。"""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("syntax check timeout must be finite and positive")
    root = Path(project_root).resolve()
    policy = SafePathPolicy((root,))
    source = policy.input_file(rtl_path)
    top = _safe_top(top_module)
    includes = tuple(policy.include_dir(root / item) for item in include_dirs)
    macros = tuple(_safe_define(item) for item in defines)
    compiler = _resolve_tool(iverilog_path or locate_tools().iverilog, "iverilog")
    command = [str(compiler), "-g2012", "-tnull", "-s", top]
    for directory in includes:
        command.extend(["-I", str(directory)])
    command.extend(f"-D{macro}" for macro in macros)
    command.append(str(source))
    return _run_process(
        command, cwd=root, timeout_seconds=timeout_seconds, max_output_chars=20_000,
    )
