"""执行配置与受控路径策略。

路径策略是运行时边界的一部分：RTL、testbench、include 目录和输出目录必须
落在显式允许的根目录内；Icarus 本身是本机可信工具，工具路径仍然只接受
iverilog/vvp 这两个固定 basename。所有进程调用由 executor 以参数列表启动，
不经过 shell。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
from typing import Iterable, Sequence


class SafePathError(ValueError):
    """路径越过允许根、不是预期文件类型或存在符号链接逃逸。"""


class ConfigurationError(ValueError):
    """执行配置不完整或含有不安全参数。"""


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_DEFINE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:=[^\r\n]*)?$")
_TOOL_NAMES = {
    "iverilog": {"iverilog", "iverilog.exe"},
    "vvp": {"vvp", "vvp.exe"},
}
_KNOWN_TOOL_DIRS = (
    Path(r"D:\iverilog\bin"),
    Path(r"C:\iverilog\bin"),
)


def _absolute(path: str | os.PathLike[str]) -> Path:
    # Path.resolve(strict=False) normalizes existing symlink components and lets
    # the policy reject a link which points outside an allowed root.
    return Path(path).expanduser().resolve(strict=False)


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current.resolve(strict=True)


def _find_scope_root(start: Path) -> Path:
    start = _absolute(start)
    for candidate in (start, *start.parents):
        if (candidate / "PROJECT_SCOPE.md").is_file():
            return candidate
    return start


@dataclass(frozen=True)
class SafePathPolicy:
    """限制输入、include 和输出路径的不可变策略。"""

    allowed_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not self.allowed_roots:
            raise SafePathError("at least one allowed root is required")
        normalized: list[Path] = []
        for raw_root in self.allowed_roots:
            root = _absolute(raw_root)
            if not root.exists() or not root.is_dir():
                raise SafePathError(f"allowed root is not an existing directory: {raw_root}")
            if root not in normalized:
                normalized.append(root)
        object.__setattr__(self, "allowed_roots", tuple(normalized))

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[str | os.PathLike[str]] | None = None,
        *,
        start: str | os.PathLike[str] | None = None,
    ) -> "SafePathPolicy":
        roots = tuple(roots or ())
        if not roots:
            roots = (_find_scope_root(_absolute(start or Path.cwd())),)
        return cls(tuple(_absolute(root) for root in roots))

    def check(self, path: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
        candidate = _absolute(path)
        if not any(_is_below(candidate, root) for root in self.allowed_roots):
            roots = ", ".join(str(root) for root in self.allowed_roots)
            raise SafePathError(f"path is outside allowed roots: {candidate} (allowed: {roots})")
        if must_exist and not candidate.exists():
            raise SafePathError(f"path does not exist: {candidate}")
        return candidate

    def input_file(
        self,
        path: str | os.PathLike[str],
        *,
        extensions: Sequence[str] = (".v", ".sv", ".vh", ".svh"),
    ) -> Path:
        candidate = self.check(path, must_exist=True)
        if not candidate.is_file():
            raise SafePathError(f"input is not a regular file: {candidate}")
        if extensions and candidate.suffix.lower() not in {suffix.lower() for suffix in extensions}:
            raise SafePathError(f"unsupported HDL input extension: {candidate.suffix}")
        return candidate

    def include_dir(self, path: str | os.PathLike[str]) -> Path:
        candidate = self.check(path, must_exist=True)
        if not candidate.is_dir():
            raise SafePathError(f"include path is not a directory: {candidate}")
        return candidate

    def output_dir(self, path: str | os.PathLike[str]) -> Path:
        candidate = self.check(path, must_exist=False)
        # Resolve all existing parents so a symlinked output directory cannot
        # redirect generated artifacts outside the policy.
        parent = _nearest_existing_parent(candidate.parent)
        if not any(_is_below(parent, root) for root in self.allowed_roots):
            raise SafePathError(f"output parent is outside allowed roots: {parent}")
        if candidate.exists() and not candidate.is_dir():
            raise SafePathError(f"output path is not a directory: {candidate}")
        return candidate

    def relative(self, path: str | os.PathLike[str]) -> str:
        candidate = self.check(path, must_exist=False)
        for root in self.allowed_roots:
            if _is_below(candidate, root):
                return candidate.relative_to(root).as_posix() or "."
        return candidate.name


def _resolve_tool(value: str | os.PathLike[str] | None, kind: str) -> Path:
    expected = _TOOL_NAMES[kind]
    raw = None if value is None else str(value).strip().strip('"')
    candidates: list[Path] = []
    if raw:
        supplied = Path(raw)
        # A bare executable name is resolved through PATH. A path-like value is
        # never passed to a shell and must resolve to the expected tool name.
        if supplied.name.lower() in expected and (supplied.is_absolute() or supplied.parent != Path(".")):
            candidates.append(_absolute(supplied))
        elif supplied.name.lower() in expected:
            located = shutil.which(raw)
            if located:
                candidates.append(_absolute(located))
        else:
            raise ConfigurationError(
                f"{kind} executable must be named one of {sorted(expected)}, got {supplied.name!r}"
            )
    else:
        env_name = "IVERILOG_PATH" if kind == "iverilog" else "VVP_PATH"
        env_value = os.environ.get(env_name)
        if env_value:
            candidates.append(_absolute(env_value))
        for directory in _KNOWN_TOOL_DIRS:
            candidates.append(directory / next(name for name in expected if name.endswith(".exe")))
        located = shutil.which(kind)
        if located:
            candidates.append(_absolute(located))
    for candidate in candidates:
        if candidate.name.lower() not in expected:
            continue
        if candidate.is_file():
            return candidate
    hint = raw or kind
    raise ConfigurationError(f"cannot find {kind} executable {hint!r}; use --{kind} or install Icarus Verilog")


def _safe_top(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value.strip()):
        raise ConfigurationError(f"top module is not a safe Verilog identifier: {value!r}")
    return value.strip()


def _safe_define(value: str) -> str:
    if not isinstance(value, str) or not _DEFINE_RE.fullmatch(value) or len(value) > 500:
        raise ConfigurationError(f"invalid preprocessor define: {value!r}")
    return value


@dataclass(frozen=True)
class ExecutionConfig:
    """Icarus compile/run configuration before path resolution."""

    rtl_path: str | os.PathLike[str]
    testbench_path: str | os.PathLike[str]
    top_module: str
    output_dir: str | os.PathLike[str] = ".iverilog-ai/runs"
    iverilog_path: str | os.PathLike[str] | None = None
    vvp_path: str | os.PathLike[str] | None = None
    timeout_seconds: float = 30.0
    allowed_roots: tuple[str | os.PathLike[str], ...] = ()
    include_dirs: tuple[str | os.PathLike[str], ...] = ()
    defines: tuple[str, ...] = ()
    max_output_chars: int = 200_000
    language: str = "2012"
    keep_artifacts: bool = True

    def resolve(self) -> "ResolvedExecutionConfig":
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise ConfigurationError("timeout_seconds must be a number")
        if not 0.1 <= float(self.timeout_seconds) <= 3_600:
            raise ConfigurationError("timeout_seconds must be in [0.1, 3600]")
        if isinstance(self.max_output_chars, bool) or not isinstance(self.max_output_chars, int):
            raise ConfigurationError("max_output_chars must be an integer")
        if not 1_000 <= self.max_output_chars <= 10_000_000:
            raise ConfigurationError("max_output_chars must be in [1000, 10000000]")
        if self.language not in {"1995", "2001", "2005", "2005-sv", "2009", "2012"}:
            raise ConfigurationError("language must be a supported Icarus generation (1995/2001/2005/2012)")
        top = _safe_top(self.top_module)
        policy = SafePathPolicy.from_roots(self.allowed_roots)
        rtl = policy.input_file(self.rtl_path)
        testbench = policy.input_file(self.testbench_path)
        output_dir = policy.output_dir(self.output_dir)
        includes = tuple(policy.include_dir(path) for path in self.include_dirs)
        defines = tuple(_safe_define(value) for value in self.defines)
        iverilog = _resolve_tool(self.iverilog_path, "iverilog")
        vvp = _resolve_tool(self.vvp_path, "vvp")
        return ResolvedExecutionConfig(
            rtl_path=rtl,
            testbench_path=testbench,
            top_module=top,
            output_dir=output_dir,
            iverilog_path=iverilog,
            vvp_path=vvp,
            timeout_seconds=float(self.timeout_seconds),
            policy=policy,
            include_dirs=includes,
            defines=defines,
            max_output_chars=self.max_output_chars,
            language=self.language,
            keep_artifacts=bool(self.keep_artifacts),
        )

    validate = resolve


@dataclass(frozen=True)
class ResolvedExecutionConfig:
    """All paths validated and normalized for the executor."""

    rtl_path: Path
    testbench_path: Path
    top_module: str
    output_dir: Path
    iverilog_path: Path
    vvp_path: Path
    timeout_seconds: float
    policy: SafePathPolicy
    include_dirs: tuple[Path, ...] = ()
    defines: tuple[str, ...] = ()
    max_output_chars: int = 200_000
    language: str = "2012"
    keep_artifacts: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "rtl_path": str(self.rtl_path),
            "testbench_path": str(self.testbench_path),
            "top_module": self.top_module,
            "output_dir": str(self.output_dir),
            "iverilog_path": str(self.iverilog_path),
            "vvp_path": str(self.vvp_path),
            "timeout_seconds": self.timeout_seconds,
            "allowed_roots": [str(root) for root in self.policy.allowed_roots],
            "include_dirs": [str(path) for path in self.include_dirs],
            "defines": list(self.defines),
            "language": self.language,
            "keep_artifacts": self.keep_artifacts,
        }


__all__ = [
    "ConfigurationError",
    "ExecutionConfig",
    "ResolvedExecutionConfig",
    "SafePathError",
    "SafePathPolicy",
]
