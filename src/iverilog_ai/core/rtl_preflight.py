"""上传 RTL 的编译预检查：只解析和展开，不执行用户设计。"""
from __future__ import annotations

import math
import re
from dataclasses import replace
from pathlib import Path

from .config import SafePathPolicy, _resolve_tool, _safe_define, _safe_top
from .executor import _run_process
from .models import ProcessResult, ProcessStatus
from .toolchain import locate_tools


def check_rtl_syntax(
    rtl_path: str | Path,
    *,
    project_root: str | Path,
    top_module: str,
    defines: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    source_files: tuple[str | Path, ...] = (),
    iverilog_path: str | None = None,
    timeout_seconds: float = 10.0,
) -> ProcessResult:
    """用 Icarus null 目标预检查当前源文件及依赖；不生成或执行 vvp。"""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("syntax check timeout must be finite and positive")
    root = Path(project_root).resolve()
    policy = SafePathPolicy((root,))
    source = policy.input_file(rtl_path)
    sources = tuple(policy.input_file(path) for path in source_files) or (source,)
    top = _safe_top(top_module)
    includes = tuple(dict.fromkeys(
        [policy.include_dir(root / item) for item in include_dirs]
        + [policy.include_dir(path.parent) for path in sources]
    ))
    macros = tuple(_safe_define(item) for item in defines)
    compiler = _resolve_tool(iverilog_path or locate_tools().iverilog, "iverilog")
    command = [str(compiler), "-g2012", "-tnull", "-s", top]
    for directory in includes:
        command.extend(["-I", str(directory)])
    command.extend(f"-D{macro}" for macro in macros)
    command.extend(str(path) for path in sources)
    result = _run_process(
        command, cwd=root, timeout_seconds=timeout_seconds, max_output_chars=20_000,
    )
    # Icarus may return zero after substituting an undefined macro with empty
    # text. Keep its actual exit code and diagnostic, but reject the preflight.
    if result.returncode == 0 and re.search(r"\bmacro\s+\S+\s+undefined\b", result.stderr, re.I):
        return replace(result, status=ProcessStatus.FAILED,
                       error="RTL contains an undefined macro; compilation precheck rejected")
    if result.output_truncated:
        return replace(result, status=ProcessStatus.FAILED,
                       error="Compiler diagnostics were truncated; precheck is incomplete")
    return result
