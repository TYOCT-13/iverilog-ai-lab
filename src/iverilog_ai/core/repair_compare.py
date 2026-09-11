"""Safe, deterministic comparison for candidate RTL verification."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import shutil
from typing import Any

@dataclass(frozen=True)
class RepairComparison:
    before_status: str
    after_status: str
    before_failures: int
    after_failures: int
    resolved: int
    introduced: int
    verdict: str
    before_fingerprints: tuple[str, ...] = ()
    after_fingerprints: tuple[str, ...] = ()

def _status_value(result: Any) -> str:
    """安全地取出结果对象的状态字符串（对象可能没有 status，或它是 None）。"""

    status = getattr(result, "status", None)
    if status is None:
        return ""
    return str(getattr(status, "value", status))


def _fp(f: Any) -> str:
    raw = "|".join(str(getattr(f, n, "")) for n in ("test_id", "cycle", "signal", "expected", "actual"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def compare_simulation_results(before: Any, after: Any) -> RepairComparison:
    b = tuple(_fp(f) for f in getattr(before, "failures", ()))
    a = tuple(_fp(f) for f in getattr(after, "failures", ()))
    resolved, introduced = len(set(b)-set(a)), len(set(a)-set(b))
    verdict = (
        "candidate_verified"
        if _status_value(after) == "passed" and not a
        else ("improved" if resolved > introduced else "not_verified")
    )
    return RepairComparison(
        _status_value(before),
        _status_value(after),
        len(b),
        len(a),
        resolved,
        introduced,
        verdict,
        b,
        a,
    )

def safe_candidate_copy(source: str | Path, workspace_root: str | Path) -> Path:
    src = Path(source).resolve(strict=True); root = Path(workspace_root).resolve()
    if not src.is_file() or src.suffix.lower() not in {".v", ".sv"}: raise ValueError("source must be a Verilog file")
    if root not in src.parents: raise ValueError("source is outside workspace")
    dest_dir = root / ".iverilog-ai" / "repair-candidates"; dest_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
    dest = (dest_dir / f"{src.stem}-{digest}{src.suffix.lower()}").resolve()
    if dest.parent != dest_dir.resolve(): raise ValueError("candidate path escapes workspace")
    shutil.copyfile(src, dest)
    return dest

__all__ = ["RepairComparison", "compare_simulation_results", "safe_candidate_copy"]
