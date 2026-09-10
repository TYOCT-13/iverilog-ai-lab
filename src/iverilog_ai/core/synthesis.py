"""Yosys 综合证据层：把"可综合性"从口头声明变成可核验的机器证据。

本模块只做一件事：对同一份 RTL 跑一次综合，把结果整理成结构化证据。

**证据分级必须说清楚**（这是本项目的硬规则）：

- 仿真通过 ≠ 时序收敛。综合用的是 Yosys 通用单元库，没有目标器件的时序模型，
  因此本模块**不做任何时序分析**，也不给出频率结论；
- 综合成功 ≠ 能上板。没有引脚约束、IO 标准、时钟约束与布局布线，就不存在
  "已实现"的证据；
- 综合失败是**强证据**：它说明这份 RTL 不可综合，仿真通过也改变不了这一点。

因此结果里的 ``stages`` 会把 ``simulation`` / ``synthesis`` / ``timing`` /
``bitstream`` / ``hardware`` 五个层级显式列出，未做的层级标 ``not_run``，
而不是留空让人误以为通过。

实现上的两个实测约束（Yosys 0.69 / yowasp WASM 版）：

1. ``-s <脚本文件>`` 会报 ``Can't open script file ... Operation not permitted``
   ——WASI 版对脚本文件路径的访问受限，因此改用 ``-p`` 内联命令，并把 RTL 与
   网表路径都写成**相对工作目录**的路径；
2. ``synth`` 的 ABC 工艺映射在 WASM 版会静默中断（进程退出码 0 但脚本不再
   往下执行），因此综合跑到 ``begin:fine`` 为止——该阶段已经完成
   ``proc``/``opt``/``memory``/``techmap``/``simplemap``，拿到的是通用门级
   单元统计，正是本层需要的东西。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

__all__ = [
    "SynthConfig",
    "SynthResult",
    "YosysSynthRunner",
    "EVIDENCE_STAGES",
    "find_yosys",
    "parse_stat_json",
    "NOT_RUN",
    "PASSED",
    "FAILED",
    "UNAVAILABLE",
    "TIMEOUT",
    "ERROR",
]

#: 证据分层。顺序即"从软到硬"，报告按此顺序展示，未运行的层级显式标 not_run。
EVIDENCE_STAGES: tuple[tuple[str, str, str], ...] = (
    ("simulation", "功能仿真", "Icarus Verilog 编译 + vvp 执行 + 结构化断言"),
    ("synthesis", "逻辑综合", "Yosys read_verilog + synth（到通用门级），产出单元统计"),
    ("timing", "时序分析", "需要目标器件时序库与时钟约束；本项目不提供"),
    ("bitstream", "布局布线/比特流", "需要厂商工具链（Vivado/Quartus 等）；本项目不提供"),
    ("hardware", "上板验证", "需要实际硬件与测试装置；本项目不提供"),
)

NOT_RUN = "not_run"
PASSED = "passed"
FAILED = "failed"
UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"
ERROR = "error"

# Yosys 的 `synth` 阶段名。跑到 fine 为止：已完成 proc/opt/memory/techmap/
# simplemap，产出通用门级单元；跳过 ABC 是因为 WASM 版会在该阶段静默中断。
_SYNTH_STAGES = "begin:fine"

_WARNING_RE = re.compile(r"^Warning:?\s*(.+)$", re.I | re.M)
_ERROR_RE = re.compile(r"^ERROR:?\s*(.+)$", re.I | re.M)


@dataclass(frozen=True)
class SynthConfig:
    """一次综合运行的全部输入参数（路径与超时都必须显式给出）。"""

    rtl_path: Path
    top: str
    work_dir: Path
    yosys_path: str | None = None
    timeout_s: float = 180.0
    emit_stat_json: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rtl_path": str(self.rtl_path),
            "top": self.top,
            "work_dir": str(self.work_dir),
            "yosys_path": self.yosys_path,
            "timeout_s": self.timeout_s,
            "synth_stages": _SYNTH_STAGES,
        }


@dataclass(frozen=True)
class SynthResult:
    """综合证据：状态、命令、耗时、单元统计与工件路径。"""

    status: str
    top: str
    command: tuple[str, ...] = ()
    duration_ms: int = 0
    cell_count: int | None = None
    wire_count: int | None = None
    memory_count: int | None = None
    process_count: int | None = None
    port_count: int | None = None
    cells: tuple[tuple[str, int], ...] = ()
    cell_kinds: int = 0
    warnings: tuple[str, ...] = ()
    log_path: str | None = None
    stat_path: str | None = None
    error: str | None = None
    skipped_reason: str | None = None
    stages: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def ran(self) -> bool:
        return self.status in {PASSED, FAILED}

    @property
    def synthesizable(self) -> bool | None:
        """True/False 只在真的跑过综合时才有意义，否则为 None。"""

        if self.status == PASSED:
            return True
        if self.status == FAILED:
            return False
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": self.status,
            "top": self.top,
            "synthesizable": self.synthesizable,
            "command": list(self.command),
            "duration_ms": self.duration_ms,
            "cell_count": self.cell_count,
            "wire_count": self.wire_count,
            "memory_count": self.memory_count,
            "process_count": self.process_count,
            "port_count": self.port_count,
            "cells": [{"cell": name, "count": count} for name, count in self.cells],
            "cell_kinds": self.cell_kinds,
            "warnings": list(self.warnings),
            "log_path": self.log_path,
            "stat_path": self.stat_path,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
            "stages": [dict(item) for item in self.stages],
            "disclaimer": (
                "综合通过只说明 RTL 可被 Yosys 映射到通用门级单元，"
                "不代表时序收敛、布局布线或上板可用；本项目不做时序签核。"
            ),
        }


def find_yosys(explicit: str | None = None) -> str | None:
    """定位 Yosys 可执行文件。

    优先用显式路径；其次查 ``PATH``（含 ``yowasp-yosys`` 这种 WASM 版入口）。
    找不到就返回 None——调用方据此给出 ``unavailable``，而不是把整个流水线判失败。
    """

    if explicit:
        candidate = Path(explicit)
        return str(candidate) if candidate.is_file() else None
    for name in ("yosys", "yosys.exe", "yowasp-yosys", "yowasp-yosys.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def parse_stat_json(stdout: str) -> dict[str, Any]:
    """从 Yosys ``stat -json`` 的输出里解析统计。

    只解析明确出现的字段：解析不到就留 None，绝不用 0 冒充"没有单元"。
    """

    start = stdout.find('{\n   "creator"')
    if start < 0:
        start = stdout.find('{"creator"')
    if start < 0:
        return {"cell_count": None, "wire_count": None, "memory_count": None,
                "process_count": None, "port_count": None, "cells": (), "cell_kinds": 0}
    end = stdout.rfind("}")
    if end <= start:
        return {"cell_count": None, "wire_count": None, "memory_count": None,
                "process_count": None, "port_count": None, "cells": (), "cell_kinds": 0}
    try:
        payload = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError:
        return {"cell_count": None, "wire_count": None, "memory_count": None,
                "process_count": None, "port_count": None, "cells": (), "cell_kinds": 0}
    design = payload.get("design") or {}
    modules = payload.get("modules") or {}
    if not design and modules:
        # 没有 design 汇总时，把各模块相加作为兜底
        design = {
            key: sum(int(module.get(key) or 0) for module in modules.values())
            for key in ("num_cells", "num_wires", "num_memories", "num_processes", "num_ports")
        }
    by_type = design.get("num_cells_by_type") or {}
    if not by_type and modules:
        merged: dict[str, int] = {}
        for module in modules.values():
            for name, count in (module.get("num_cells_by_type") or {}).items():
                merged[name] = merged.get(name, 0) + int(count)
        by_type = merged
    cells = tuple(sorted(((str(name), int(count)) for name, count in by_type.items()), key=lambda item: (-item[1], item[0])))
    return {
        "cell_count": _int_or_none(design.get("num_cells")),
        "wire_count": _int_or_none(design.get("num_wires")),
        "memory_count": _int_or_none(design.get("num_memories")),
        "process_count": _int_or_none(design.get("num_processes")),
        "port_count": _int_or_none(design.get("num_ports")),
        "cells": cells,
        "cell_kinds": len(cells),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stage_table(synthesis_status: str) -> tuple[dict[str, Any], ...]:
    stages: list[dict[str, Any]] = []
    for key, title, detail in EVIDENCE_STAGES:
        if key == "simulation":
            status = "provided_by_pipeline"
        elif key == "synthesis":
            status = synthesis_status
        else:
            status = NOT_RUN
        stages.append({"stage": key, "title": title, "status": status, "detail": detail})
    return tuple(stages)


class YosysSynthRunner:
    """在指定工件目录内运行一次 Yosys 综合（无 shell、内联脚本、带超时）。"""

    def __init__(self, config: SynthConfig) -> None:
        self.config = config
        self.command: tuple[str, ...] = ()

    def _rtl_argument(self) -> str:
        """RTL 路径写成绝对正斜杠形式。

        WASI 版 Yosys 的虚拟文件系统只映射"可执行文件所在目录"，相对路径一
        离开该目录就会 ``File not found``。实测 `E:/.../rtl/pwm.v` 这类绝对
        正斜杠路径可以正常读取，因此统一用这种写法。
        """

        return str(self.config.rtl_path.resolve()).replace("\\", "/")

    def _script(self) -> str:
        rtl = self._rtl_argument()
        parts = [
            f"read_verilog -sv {rtl}",
            f"hierarchy -top {self.config.top}",
            f"synth -top {self.config.top} -run {_SYNTH_STAGES}",
        ]
        if self.config.emit_stat_json:
            parts.append("stat -json")
        else:
            parts.append("stat")
        return "; ".join(parts)

    def run(self) -> SynthResult:
        config = self.config
        yosys = find_yosys(config.yosys_path)
        if yosys is None:
            return SynthResult(
                status=UNAVAILABLE,
                top=config.top,
                skipped_reason=(
                    "未找到 Yosys 可执行文件；执行 `pip install yowasp-yosys` 或指定 yosys_path 后可启用综合证据层"
                ),
                stages=_stage_table(NOT_RUN),
            )
        rtl = Path(config.rtl_path)
        if not rtl.is_file():
            return SynthResult(
                status=ERROR,
                top=config.top,
                error=f"RTL 文件不存在：{rtl}",
                stages=_stage_table(NOT_RUN),
            )
        config.work_dir.mkdir(parents=True, exist_ok=True)
        # 不能用 -q：它会把 `stat -json` 的输出一起静默掉，导致拿不到统计。
        # 输出噪音由 Python 侧截取控制（日志文件与分析只取需要的部分）。
        command = (yosys, "-p", self._script())
        self.command = command
        started = time.perf_counter()
        # cwd 固定为可执行文件所在目录：WASI 版只映射这一处，换目录会让
        # Yosys 找不到自己的运行时资源。RTL 用绝对路径传入，因此不受影响。
        run_cwd = str(Path(yosys).resolve().parent)
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=config.timeout_s,
                cwd=run_cwd,
            )
        except subprocess.TimeoutExpired:
            return SynthResult(
                status=TIMEOUT,
                top=config.top,
                command=command,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"综合超时（>{config.timeout_s:g}s）",
                stages=_stage_table(TIMEOUT),
            )
        except OSError as exc:
            return SynthResult(
                status=ERROR,
                top=config.top,
                command=command,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"无法启动 Yosys：{exc}",
                stages=_stage_table(ERROR),
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, stderr = completed.stdout or "", completed.stderr or ""
        warnings = tuple(match.strip() for match in _WARNING_RE.findall(stdout + "\n" + stderr))
        log_path = config.work_dir / f"synth_{config.top}.log"
        log_path.write_text(stdout + ("\n--- stderr ---\n" + stderr if stderr else ""), encoding="utf-8")
        stats = parse_stat_json(stdout)
        stat_path = None
        if stats["cell_count"] is not None:
            stat_path = str(config.work_dir / f"synth_{config.top}.json")
            Path(stat_path).write_text(
                json.dumps(
                    {
                        "top": config.top,
                        "cell_count": stats["cell_count"],
                        "wire_count": stats["wire_count"],
                        "memory_count": stats["memory_count"],
                        "process_count": stats["process_count"],
                        "port_count": stats["port_count"],
                        "cells": [{"cell": name, "count": count} for name, count in stats["cells"]],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        # WASM 版 Yosys 在 ABC 阶段可能静默中断，退出码仍是 0；因此判据是
        # "有没有拿到统计"，而不是只看退出码。
        succeeded = completed.returncode == 0 and stats["cell_count"] is not None
        if not succeeded:
            errors = _ERROR_RE.findall(stdout + "\n" + stderr)
            if errors:
                detail = errors[-1].strip()
            elif completed.returncode != 0:
                tail = (stderr.strip() or stdout.strip()).splitlines()
                detail = tail[-1] if tail else f"Yosys 退出码 {completed.returncode}"
            else:
                detail = "Yosys 未产出统计输出（脚本未跑完 stat）"
            return SynthResult(
                status=FAILED,
                top=config.top,
                command=command,
                duration_ms=duration_ms,
                cells=stats["cells"],
                cell_kinds=stats["cell_kinds"],
                warnings=warnings,
                log_path=str(log_path),
                error=detail,
                stages=_stage_table(FAILED),
            )
        return SynthResult(
            status=PASSED,
            top=config.top,
            command=command,
            duration_ms=duration_ms,
            cell_count=stats["cell_count"],
            wire_count=stats["wire_count"],
            memory_count=stats["memory_count"],
            process_count=stats["process_count"],
            port_count=stats["port_count"],
            cells=stats["cells"],
            cell_kinds=stats["cell_kinds"],
            warnings=warnings,
            log_path=str(log_path),
            stat_path=stat_path,
            stages=_stage_table(PASSED),
        )
