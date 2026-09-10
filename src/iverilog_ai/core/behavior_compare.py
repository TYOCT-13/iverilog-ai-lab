"""行为级对比：让用户 RTL 与参考 RTL 跑**同一份** TestPlan，比对结果与波形。

与 :mod:`rtl_compare` 的区别：那个模块做的是**结构级**对比（端口、复位、赋值风格等
文本特征），本模块做**行为级**对比——同一份激励、同一份 contract，两次真实仿真，
然后逐检查项、逐波形信号比较。

证据口径（必须与项目其他部分一致）：

- 判定"等价"的只有 Icarus：两侧都跑真实编译与仿真，任何一个检查项结果不同就是
  **行为差异**；
- 波形差异是**可观测行为**差异的旁证，用来定位"差在哪一拍、哪个信号"，它本身
  不构成缺陷结论；
- 两侧都用同一份 contract，因此"测试台相同"是构造保证，不是推断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import DutContract
from .models import SimulationResult
from .pipeline import PipelineResult, VerificationPipeline
from .vcd import analyze_vcd_file, compare_waveforms

__all__ = ["BehaviorCompareResult", "compare_pipeline_behavior", "compare_rtl_behavior"]


@dataclass(frozen=True)
class BehaviorCompareResult:
    """两份 RTL 在同一 TestPlan 下的行为对比结论。"""

    status: str
    module: str
    user: PipelineResult
    reference: PipelineResult
    record_summary: dict[str, Any] = field(default_factory=dict)
    mismatches: tuple[dict[str, Any], ...] = ()
    waveform: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    disclaimer: str = (
        "结论来自两次真实 Icarus 仿真：任何检查项结果不同即为行为差异；"
        "波形差异只描述可观测行为，是否构成缺陷仍由规格与人工判断。"
    )

    @property
    def identical(self) -> bool:
        return self.status == "identical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": self.status,
            "identical": self.identical,
            "module": self.module,
            "user_status": self.user.status.value,
            "reference_status": self.reference.status.value,
            "record_summary": dict(self.record_summary),
            "mismatches": [dict(item) for item in self.mismatches],
            "waveform": dict(self.waveform),
            "notes": list(self.notes),
            "disclaimer": self.disclaimer,
        }


def _record_key(record: Any, index: int) -> tuple[str, str]:
    """检查项的身份：测试 ID + 信号；缺 ID 时退回序号。"""

    test_id = record.test_id if record.test_id is not None else f"#{index}"
    return str(test_id), str(record.signal or "")


def _record_view(record: Any) -> dict[str, Any]:
    return {
        "test_id": record.test_id,
        "cycle": record.cycle,
        "signal": record.signal,
        "ok": record.ok,
        "expected": record.expected,
        "actual": record.actual,
        "severity": record.severity,
    }


def _summarize_records(user: SimulationResult, reference: SimulationResult) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """逐检查项比对两侧的结构化记录。

    比对的键是 ``(test_id, signal)``：同一份 testbench 生成自同一份 plan 与
    contract，因此两侧的检查项集合理应完全一致；数量或键不同本身就是差异。
    """

    user_records = {_record_key(record, index): record for index, record in enumerate(user.records)}
    reference_records = {_record_key(record, index): record for index, record in enumerate(reference.records)}
    shared = [key for key in user_records if key in reference_records]
    only_user = [key for key in user_records if key not in reference_records]
    only_reference = [key for key in reference_records if key not in user_records]

    mismatches: list[dict[str, Any]] = []
    for key in shared:
        left, right = user_records[key], reference_records[key]
        if left.ok == right.ok and left.actual == right.actual:
            continue
        mismatches.append(
            {
                "kind": "record",
                "test_id": key[0],
                "signal": key[1],
                "user": _record_view(left),
                "reference": _record_view(right),
                "message": (
                    f"{key[0]} 的 {key[1] or '整体'}：用户 RTL "
                    f"{'通过' if left.ok else '失败'}（actual={left.actual}），"
                    f"参考 RTL {'通过' if right.ok else '失败'}（actual={right.actual}）"
                ),
            }
        )
    for key in only_user:
        mismatches.append(
            {
                "kind": "record_missing_in_reference",
                "test_id": key[0],
                "signal": key[1],
                "user": _record_view(user_records[key]),
                "reference": None,
                "message": f"{key[0]}：只有用户 RTL 产出了这条检查记录",
            }
        )
    for key in only_reference:
        mismatches.append(
            {
                "kind": "record_missing_in_user",
                "test_id": key[0],
                "signal": key[1],
                "user": None,
                "reference": _record_view(reference_records[key]),
                "message": f"{key[0]}：只有参考 RTL 产出了这条检查记录",
            }
        )

    user_failed = sum(1 for record in user.records if not record.ok)
    reference_failed = sum(1 for record in reference.records if not record.ok)
    summary = {
        "user_checks": len(user.records),
        "reference_checks": len(reference.records),
        "shared_checks": len(shared),
        "user_failed": user_failed,
        "reference_failed": reference_failed,
        "mismatched_checks": len(mismatches),
        "user_status": user.status.value,
        "reference_status": reference.status.value,
    }
    return summary, mismatches


def _compare_waveforms(
    user: SimulationResult,
    reference: SimulationResult,
    *,
    clock_period_ns: float,
) -> dict[str, Any]:
    """比对两侧 VCD；缺任一侧就如实说明，不猜。"""

    user_path = (user.artifacts or {}).get("vcd", "")
    reference_path = (reference.artifacts or {}).get("vcd", "")
    if not user_path or not reference_path:
        return {"status": "not_available", "reason": "任一侧没有生成 VCD", "difference_count": 0}
    if not Path(user_path).is_file() or not Path(reference_path).is_file():
        return {"status": "not_available", "reason": "VCD 文件不存在", "difference_count": 0}
    try:
        user_analysis = analyze_vcd_file(user_path, max_changes=5000)
        reference_analysis = analyze_vcd_file(reference_path, max_changes=5000)
    except (OSError, ValueError) as exc:
        return {"status": "error", "error": str(exc), "difference_count": 0}
    comparison = compare_waveforms(reference_analysis, user_analysis, clock_period_ns=clock_period_ns)
    # 两侧顶层 testbench 同名（同一份 contract），因此信号名可以直接比较。
    reference_signals = {str(item.get("name", "")) for item in reference_analysis.get("signals", [])}
    user_signals = {str(item.get("name", "")) for item in user_analysis.get("signals", [])}
    comparison["signal_sets_match"] = reference_signals == user_signals
    comparison["reference_only_signals"] = sorted(reference_signals - user_signals)
    comparison["user_only_signals"] = sorted(user_signals - reference_signals)
    # 只保留 DUT 侧信号作为行为差异证据：testbench 记账信号（检查任务的
    # expected/actual 等）会被两侧记录差异本身带偏，不作为电路结论。
    comparison["dut_differences"] = [
        item for item in comparison.get("differences", []) if ".dut_i." in str(item.get("signal", ""))
    ]
    # 一侧多出的内部辅助变量（例如组合中间量 next_count）只是实现细节，
    # 不构成行为差异；共有信号全部一致时仍判 identical。
    comparison["extra_signals_are_internal_only"] = all(
        ".dut_i." in str(name) for name in comparison["reference_only_signals"] + comparison["user_only_signals"]
    )
    return comparison


def compare_pipeline_behavior(
    user: PipelineResult,
    reference: PipelineResult,
    *,
    module: str | None = None,
    clock_period_ns: float = 10.0,
) -> BehaviorCompareResult:
    """比对两次已完成流水线的结果（不再跑仿真）。"""

    summary, mismatches = _summarize_records(user.simulation, reference.simulation)
    waveform = _compare_waveforms(user.simulation, reference.simulation, clock_period_ns=clock_period_ns)
    dut_differences = waveform.get("dut_differences", []) if waveform.get("status") == "different" else []
    if mismatches or dut_differences:
        status = "different"
    elif waveform.get("status") in {"error", "not_available"}:
        status = "records_identical_waveform_unavailable"
    else:
        status = "identical"

    notes: list[str] = []
    if summary["user_status"] != summary["reference_status"]:
        notes.append(
            f"整体状态不同：用户 RTL `{summary['user_status']}`，参考 RTL `{summary['reference_status']}`"
        )
    if mismatches:
        notes.append(f"逐检查项比对发现 {len(mismatches)} 处结果差异")
    else:
        notes.append("两侧全部检查项结果一致")
    if waveform.get("status") == "different":
        notes.append(
            f"波形差异 {waveform.get('difference_count', 0)} 处"
            f"（其中 DUT 内部信号 {len(dut_differences)} 处，"
            f"testbench 记账信号 {waveform.get('difference_count', 0) - len(dut_differences)} 处）"
        )
    elif waveform.get("status") == "not_available":
        notes.append(f"波形未比对：{waveform.get('reason', '')}")
    elif waveform.get("status") == "error":
        notes.append(f"波形比对出错：{waveform.get('error', '')}")
    if not waveform.get("signal_sets_match", True) and not waveform.get("extra_signals_are_internal_only", False):
        notes.append(
            "两侧可观测信号集合不同：参考独有 "
            + (", ".join(waveform.get("reference_only_signals", [])) or "无")
            + "；用户独有 "
            + (", ".join(waveform.get("user_only_signals", [])) or "无")
            + "。端口层面的差异会直接影响可用性，请检查 contract。"
        )
    elif not waveform.get("signal_sets_match", True):
        notes.append(
            "用户 RTL 多出/缺少的内部信号："
            + (", ".join(waveform.get("reference_only_signals", []) + waveform.get("user_only_signals", [])))
            + "。属实现细节，不计入行为差异。"
        )
    if status == "identical":
        notes.append("在本测试计划覆盖的激励范围内，两份 RTL 的行为没有可观测差异")
        notes.append("注意：这只说明覆盖范围内的行为一致，不等于实现完全等价或代码质量相同")

    return BehaviorCompareResult(
        status=status,
        module=module or user.contract.module,
        user=user,
        reference=reference,
        record_summary=summary,
        mismatches=tuple(mismatches),
        waveform=waveform,
        notes=tuple(notes),
    )


def compare_rtl_behavior(
    plan: Any,
    contract: DutContract | Mapping[str, Any],
    user_rtl: str | Path,
    reference_rtl: str | Path,
    output_dir: str | Path,
    *,
    allowed_roots: Sequence[str | Path] | None = None,
    iverilog_path: str | Path | None = None,
    vvp_path: str | Path | None = None,
    include_dirs: Sequence[str | Path] = (),
    defines: Sequence[str] = (),
    timeout_seconds: float = 30.0,
    language: str = "2012",
    emit_vcd: bool = True,
    clock_period_ns: float | None = None,
) -> BehaviorCompareResult:
    """用同一份 TestPlan 分别仿真两份 RTL，再比对结果与波形。

    两个子目录 ``user/`` 与 ``reference/`` 各自独立，因此工件、日志、VCD 不会
    互相覆盖；两次运行使用完全相同的 plan 与 contract，测试台因此逐字节一致。
    """

    dut_contract = contract if isinstance(contract, DutContract) else DutContract.from_dict(dict(contract))
    period = float(clock_period_ns) if clock_period_ns else (
        dut_contract.clock.period_ns if dut_contract.clock is not None else 10.0
    )
    root = Path(output_dir)
    common: dict[str, Any] = {
        "allowed_roots": allowed_roots,
        "iverilog_path": iverilog_path,
        "vvp_path": vvp_path,
        "include_dirs": tuple(include_dirs),
        "defines": tuple(defines),
        "timeout_seconds": timeout_seconds,
        "language": language,
        "emit_vcd": emit_vcd,
    }
    reference_result = VerificationPipeline().run(plan, dut_contract, reference_rtl, root / "reference", **common)
    user_result = VerificationPipeline().run(plan, dut_contract, user_rtl, root / "user", **common)
    return compare_pipeline_behavior(
        user_result,
        reference_result,
        module=dut_contract.module,
        clock_period_ns=period,
    )
