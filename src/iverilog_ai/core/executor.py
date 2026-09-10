"""受控的 Icarus Verilog 编译、vvp 执行和结构化结果解析。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
from typing import Iterable

from .config import ExecutionConfig, ResolvedExecutionConfig
from .models import (
    FailureRecord,
    ModelValidationError,
    ProcessResult,
    ProcessStatus,
    ResultRecord,
    ResultStatus,
    SimulationResult,
)


RESULT_MARKER = "IVERILOG_AI_RESULT"
"""testbench 应输出的结构化 JSON 行前缀。"""

_RESULT_LINE_RE = re.compile(
    r"^\s*(?:IVERILOG_AI_RESULT|\[IVERILOG_AI_RESULT\]|@iverilog-ai-result)"
    r"\s*(?::|=|\s)\s*(\{.*\})\s*$",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    # Keep both the beginning (usually the command context) and the end
    # (usually the final assertion) so the report remains useful.
    half = max(1, (limit - 80) // 2)
    marker = "\n...[output truncated]...\n"
    return value[:half] + marker + value[-half:], True


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_result_records(output: str) -> tuple[tuple[ResultRecord, ...], tuple[str, ...]]:
    """解析 testbench 的标记行，返回 records 与可审计诊断。

    只有带有明确前缀的 JSON 行才会被解释为测试结果；普通 display 文本
    不会意外改变仿真结论。单条损坏的标记行会令上层结果变成
    inconclusive，避免“部分结果通过”被误报成完全通过。
    """

    records: list[ResultRecord] = []
    diagnostics: list[str] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        match = _RESULT_LINE_RE.match(line)
        if not match:
            continue
        raw_json = match.group(1)
        try:
            value = json.loads(raw_json)
            records.append(ResultRecord.from_dict(value, index=len(records)))
        except (json.JSONDecodeError, ModelValidationError, TypeError) as exc:
            diagnostics.append(f"malformed structured result at line {line_number}: {exc}")
    return tuple(records), tuple(diagnostics)


def _safe_env() -> dict[str, str]:
    """Construct a small environment without forwarding model/API secrets."""

    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "COMSPEC",
        "LANG",
        "LC_ALL",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.setdefault("LC_ALL", "C")
    return environment


def _run_process(
    command: Iterable[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    max_output_chars: int,
) -> ProcessResult:
    command_tuple = tuple(str(item) for item in command)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command_tuple),
            cwd=str(cwd),
            env=_safe_env(),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, stdout_truncated = _truncate(_decode_output(exc.stdout), max_output_chars)
        stderr, stderr_truncated = _truncate(_decode_output(exc.stderr), max_output_chars)
        return ProcessResult(
            status=ProcessStatus.TIMEOUT,
            returncode=None,
            command=command_tuple,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=True,
            error=f"process exceeded timeout of {timeout_seconds:g}s",
            output_truncated=stdout_truncated or stderr_truncated,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ProcessResult(
            status=ProcessStatus.ERROR,
            returncode=None,
            command=command_tuple,
            duration_ms=duration_ms,
            error=f"could not start process: {exc}",
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout, stdout_truncated = _truncate(_decode_output(completed.stdout), max_output_chars)
    stderr, stderr_truncated = _truncate(_decode_output(completed.stderr), max_output_chars)
    return ProcessResult(
        status=ProcessStatus.PASSED if completed.returncode == 0 else ProcessStatus.FAILED,
        returncode=completed.returncode,
        command=command_tuple,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        output_truncated=stdout_truncated or stderr_truncated,
    )


@dataclass
class IcarusExecutor:
    """运行一次受控的 Icarus compile + vvp 流程。

    ExecutionConfig 的输入文件和输出目录先由 SafePathPolicy 校验，然后
    每次执行使用独立的 run 目录。执行器不接受 shell 字符串、不执行
    模型提供的额外参数，也不覆盖原始 RTL。
    """

    config: ExecutionConfig | ResolvedExecutionConfig

    def _resolved(self) -> ResolvedExecutionConfig:
        return self.config if isinstance(self.config, ResolvedExecutionConfig) else self.config.resolve()

    def run(self) -> SimulationResult:
        config = self._resolved()
        started_at = _utc_now()
        run_id = uuid.uuid4().hex[:12]
        config.output_dir.mkdir(parents=True, exist_ok=True)
        # Re-resolve after mkdir in case an untrusted process replaced a parent
        # component with a symlink between validation and creation.
        output_dir = config.policy.output_dir(config.output_dir)
        # 在 Windows 某些受控磁盘上，tempfile.mkdtemp 可能创建带特殊 ACL
        # 的目录，导致 vvp 或资源管理器无法访问。显式 mkdir 让目录继承
        # 项目 output_dir 的权限，并用写读探针尽早暴露权限问题。
        run_dir = (output_dir / f"run-{run_id}").resolve()
        run_dir.mkdir(parents=False, exist_ok=False)
        config.policy.check(run_dir, must_exist=True)
        probe = run_dir / ".write_probe"
        probe.write_text("ok", encoding="ascii")
        if probe.read_text(encoding="ascii") != "ok":
            raise PermissionError(f"run directory is not readable: {run_dir}")
        probe.unlink()
        compile_output = run_dir / "compile.vvp"

        compile_command: list[str] = [
            str(config.iverilog_path),
            f"-g{config.language}",
            "-o",
            str(compile_output),
            "-s",
            config.top_module,
        ]
        for include_dir in config.include_dirs:
            compile_command.extend(["-I", str(include_dir)])
        for define in config.defines:
            compile_command.append(f"-D{define}")
        compile_command.extend([str(config.rtl_path), str(config.testbench_path)])

        compile_result = _run_process(
            compile_command,
            cwd=run_dir,
            timeout_seconds=config.timeout_seconds,
            max_output_chars=config.max_output_chars,
        )
        (run_dir / "compile.stdout.txt").write_text(compile_result.stdout, encoding="utf-8")
        (run_dir / "compile.stderr.txt").write_text(compile_result.stderr, encoding="utf-8")

        run_result: ProcessResult | None = None
        records: tuple[ResultRecord, ...] = ()
        failures: tuple[FailureRecord, ...] = ()
        diagnostics: list[str] = []
        error: str | None = None
        if compile_result.status is ProcessStatus.PASSED:
            run_command = [str(config.vvp_path), str(compile_output)]
            run_result = _run_process(
                run_command,
                cwd=run_dir,
                timeout_seconds=config.timeout_seconds,
                max_output_chars=config.max_output_chars,
            )
            (run_dir / "run.stdout.txt").write_text(run_result.stdout, encoding="utf-8")
            (run_dir / "run.stderr.txt").write_text(run_result.stderr, encoding="utf-8")
            records, parse_diagnostics = parse_result_records(run_result.stdout + "\n" + run_result.stderr)
            diagnostics.extend(parse_diagnostics)
            failures = tuple(FailureRecord.from_result(record) for record in records if not record.ok)
        else:
            error = compile_result.error or "iverilog compilation failed"

        if compile_result.status is ProcessStatus.TIMEOUT:
            status = ResultStatus.TIMEOUT
        elif compile_result.status is not ProcessStatus.PASSED:
            status = ResultStatus.COMPILE_FAILED
        elif run_result is None:
            status = ResultStatus.INCONCLUSIVE
            error = error or "vvp was not executed"
        elif run_result.status is ProcessStatus.TIMEOUT:
            status = ResultStatus.TIMEOUT
            error = run_result.error
        elif run_result.status is not ProcessStatus.PASSED:
            status = ResultStatus.FAILED
            error = run_result.error or "vvp execution failed"
        elif diagnostics:
            status = ResultStatus.INCONCLUSIVE
            error = "one or more structured result lines were invalid"
        elif not records:
            status = ResultStatus.INCONCLUSIVE
            error = "testbench produced no structured result records"
            diagnostics.append("expected lines beginning with IVERILOG_AI_RESULT")
        elif failures:
            # Functional mismatches are warnings unless explicitly marked
            # error; infrastructure failures above remain hard failures.
            fatal_failures = tuple(item for item in failures if item.severity == "error")
            status = ResultStatus.FAILED if fatal_failures else ResultStatus.PASSED_WITH_WARNINGS
        else:
            status = ResultStatus.PASSED

        vcd_path = next((candidate for candidate in sorted(run_dir.glob("*.vcd")) if candidate.is_file() and not candidate.is_symlink()), None)
        artifacts = {
            "run_dir": str(run_dir),
            "compile_vvp": str(compile_output),
            "compile_stdout": str(run_dir / "compile.stdout.txt"),
            "compile_stderr": str(run_dir / "compile.stderr.txt"),
            "run_stdout": str(run_dir / "run.stdout.txt") if run_result is not None else "",
            "run_stderr": str(run_dir / "run.stderr.txt") if run_result is not None else "",
            "vcd": str(vcd_path) if vcd_path is not None else "",
        }
        config_data = config.to_dict()
        config_data.update(
            {
                "rtl_sha256": _hash_file(config.rtl_path),
                "testbench_sha256": _hash_file(config.testbench_path),
            }
        )
        result = SimulationResult(
            run_id=run_id,
            status=status,
            compile=compile_result,
            run=run_result,
            records=records,
            failures=failures,
            diagnostics=tuple(diagnostics),
            artifacts=artifacts,
            config=config_data,
            started_at=started_at,
            finished_at=_utc_now(),
            error=error,
        )
        result_path = run_dir / "result.json"
        artifacts["result_json"] = str(result_path)
        result = SimulationResult(
            run_id=result.run_id,
            status=result.status,
            compile=result.compile,
            run=result.run,
            records=result.records,
            failures=result.failures,
            diagnostics=result.diagnostics,
            artifacts=artifacts,
            config=result.config,
            started_at=result.started_at,
            finished_at=result.finished_at,
            error=result.error,
        )
        result_path.write_text(result.to_json() + "\n", encoding="utf-8")
        return result

    execute = run


SimulationRunner = IcarusExecutor


__all__ = [
    "IcarusExecutor",
    "RESULT_MARKER",
    "SimulationRunner",
    "parse_result_records",
]
