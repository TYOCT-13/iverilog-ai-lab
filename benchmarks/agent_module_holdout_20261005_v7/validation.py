"""以现有core判据运行真实Icarus，额外与独立时间语义交叉核对。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline


def simulate(plan: TestPlan, contract: DutContract, rtl: Path, directory: Path) -> dict[str, Any]:
    """失败也由pipeline保留原始日志；目录存在时拒绝覆盖已有证据。"""
    if directory.exists() or directory.is_symlink():
        raise ValueError("validation_output_exists")
    result = VerificationPipeline().run(
        plan, contract, rtl, directory, reference_sampling="per_cycle", capture_observations=True,
        emit_vcd=False, language="2001", iverilog_path="D:/iverilog/bin/iverilog.exe", vvp_path="D:/iverilog/bin/vvp.exe",
        max_output_chars=2_000_000,
    )
    packet = json.loads(Path(result.artifacts["observed_samples"]).read_text(encoding="utf-8"))
    output = "rising" if plan.design == "edge_detector" else "pulse_out"
    after = [int(sample["outputs"][output], 2) for sample in packet["samples"]]
    report = {
        "case": plan.design, "rtl": str(rtl), "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest(),
        "status": result.status.value, "verdict": result.simulation.verdict,
        "failure_count": len(result.simulation.failures),
        "failures": [failure.to_dict() for failure in result.simulation.failures],
        "compile_returncode": result.simulation.compile.returncode,
        "execution_returncode": result.simulation.run.returncode if result.simulation.run else None,
        "api_calls": 0, "network_used": False,
        "check_count": result.simulation.check_count, "observed_cycles": packet["observed_cycles"],
        "observation_status": packet["status"], "after": after,
        "artifacts": dict(result.artifacts), "source": "actual Icarus with original builtin per-cycle oracle",
    }
    (directory / "asset_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
