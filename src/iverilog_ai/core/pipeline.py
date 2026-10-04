"""从严格 AI 测试计划到 Icarus 证据的确定性流水线。

本模块把三件事串起来：ai.schema.TestPlan、显式 DutContract 和既有
IcarusExecutor。流水线只创建 testbench/日志/result 工件，不修改 RTL，
也不调用网络或让 AI 输出进入 shell/Verilog 语句。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from ..ai.schema import TestPlan
from .config import ExecutionConfig, SafePathPolicy
from .contracts import ContractValidationError, DutContract
from .executor import IcarusExecutor
from .models import FailureRecord, SimulationResult, ResultStatus
from .testbench import DUT_INSTANCE, TestbenchGenerationError, TestbenchGenerator
from .reference_model import check_plan_consistency, override_plan_expectations, reference_expectations
from .assertions import build_assertion, evaluate_assertion, AssertionValidationError
from .coverage import analyze_signal_activity
from .observations import collect_observed_samples
from .synthesis import SynthConfig, YosysSynthRunner
from .vcd import analyze_vcd_file, analyze_failure_windows, waveform_insights


class PipelineValidationError(ValueError):
    """流水线输入不是受控 TestPlan/DUT 合约，或工件目录不安全。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_plan(plan: TestPlan | Mapping[str, Any]) -> TestPlan:
    if isinstance(plan, TestPlan):
        return plan
    if isinstance(plan, Mapping):
        try:
            return TestPlan.model_validate(plan)
        except Exception as exc:
            raise PipelineValidationError(f"invalid ai.schema.TestPlan: {exc}") from exc
    raise PipelineValidationError("plan must be an ai.schema.TestPlan or a JSON object")


def _coerce_contract(contract: DutContract | Mapping[str, Any]) -> DutContract:
    if isinstance(contract, DutContract):
        return contract
    try:
        return DutContract.from_dict(contract)
    except ContractValidationError as exc:
        raise PipelineValidationError(str(exc)) from exc


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return f"“{value}”"
    return _json_text(value)


def _evaluate_structured_assertions(plan: TestPlan, simulation: SimulationResult) -> dict[str, Any]:
    """Evaluate plan-level controlled assertions against observed records."""
    assertions = getattr(plan, "assertions", ()) or ()
    if not assertions:
        return {"status": "skipped", "checked": 0, "passed": 0, "failed": 0, "results": []}
    by_signal: dict[str, list[dict[str, Any]]] = {}
    timeline_map: dict[tuple[str, int | None], dict[str, Any]] = {}
    for record in simulation.records:
        if record.signal:
            by_signal.setdefault(record.signal, []).append({record.signal: record.actual})
            timeline_map.setdefault((record.test_id or "", record.cycle), {})[record.signal] = record.actual
    timeline = list(timeline_map.values())
    results = []
    for raw in assertions:
        try:
            assertion = build_assertion(raw)
            samples = timeline if assertion.kind == "signal_implies" else by_signal.get(assertion.signal, [])
            check = evaluate_assertion(assertion, samples)
            results.append({**assertion.to_dict(), "passed": check.passed, "checked_samples": check.checked_samples, "observed": check.observed, "message": check.message})
        except AssertionValidationError as exc:
            results.append({"passed": False, "message": str(exc), "assertion": raw})
    passed = sum(bool(item.get("passed")) for item in results)
    return {"status": "passed" if passed == len(results) else "warn", "checked": len(results), "passed": passed, "failed": len(results) - passed, "results": results, "evidence_level": "structured_assertion"}


def _failure_fingerprint(failure: FailureRecord) -> str:
    payload = {
        "test_id": failure.test_id,
        "cycle": failure.cycle,
        "signal": failure.signal,
        "expected": failure.expected,
        "actual": failure.actual,
        "message": failure.message,
        "severity": failure.severity,
    }
    return hashlib.sha256(_json_text(payload).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class FailureExplanation:
    """确定性、可复现的单条失败中文摘要。"""

    failure: FailureRecord
    summary: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "summary": self.summary,
            "failure": self.failure.to_dict(),
        }


def _make_failure_explanation(failure: FailureRecord) -> FailureExplanation:
    test = failure.test_id or "未命名测试"
    when = "未知周期" if failure.cycle is None else f"第 {failure.cycle} 周期"
    signal = f"信号 {failure.signal}" if failure.signal else "未标注信号"
    expected = _value_text(failure.expected)
    actual = _value_text(failure.actual)
    detail = failure.message.strip() if failure.message.strip() else "testbench 断言失败"
    fingerprint = _failure_fingerprint(failure)
    summary = (
        f"测试“{test}”在{when}检查{signal}失败：期望 {expected}，实际 {actual}。"
        f"断言信息：{detail}。失败指纹 {fingerprint}；"
        "可用相同 DUT、TestPlan 和 Icarus 工具重新运行复现。"
    )
    return FailureExplanation(failure=failure, summary=summary, fingerprint=fingerprint)


def explain_failure(failure: FailureRecord) -> str:
    """根据 FailureRecord 生成稳定中文摘要，不调用 AI。"""

    if not isinstance(failure, FailureRecord):
        raise TypeError("failure must be a FailureRecord")
    return _make_failure_explanation(failure).summary


def explain_failure_record(failure: FailureRecord) -> FailureExplanation:
    """返回带稳定指纹的结构化失败解释。"""

    if not isinstance(failure, FailureRecord):
        raise TypeError("failure must be a FailureRecord")
    return _make_failure_explanation(failure)


def explain_failures(failures: Sequence[FailureRecord]) -> tuple[str, ...]:
    """按输入顺序解释失败，空输入返回空元组。"""

    return tuple(explain_failure(item) for item in failures)


summarize_failure = explain_failure


#: 输入可以是新的扁平格式（`ai.schema.TestPlan`，用 `vectors`），也可以是旧的内部
#: 格式（`core.models.TestPlan`，用 `cases/steps`）。两种格式字段名不同，写死任一种
#: 都会让另一条路径失去支持，因此按 `Any` 处理并在运行时用 `getattr` 分辨。
def coverage_summary(plan: Any, simulation: SimulationResult) -> dict[str, Any]:
    """计算测试计划的执行摘要（不是 RTL 代码覆盖率）。

    vector coverage 按 test case id 统计；check coverage 按带 expected 的
    step 数量与实际产生的结构化记录统计；per-signal coverage 统计每个
    expected 信号至少被检查一次的比例。
    """
    # Current AI schema uses flat vectors; older internal plans used cases.
    raw_vectors = getattr(plan, "vectors", None)
    if raw_vectors is not None:
        vectors = [vector.name for vector in raw_vectors]
    else:
        vectors = [case.id for case in plan.cases]
    expected_checks: list[tuple[str, str]] = []
    if raw_vectors is not None:
        for vector in raw_vectors:
            for signal in vector.expected:
                expected_checks.append((vector.name, signal))
    else:
        for case in plan.cases:
            for step in case.steps:
                for signal in step.expected:
                    expected_checks.append((case.id, signal))
    executed_ids = {r.test_id for r in simulation.records if r.test_id}
    from collections import Counter
    expected_counts = Counter(expected_checks)
    actual_counts = Counter((r.test_id, r.signal) for r in simulation.records if r.test_id and r.signal)
    signal_names = sorted({signal for _, signal in expected_checks})
    covered_vectors = sum(1 for item in vectors if item in executed_ids)
    covered_checks = sum(min(expected_counts[pair], actual_counts[pair]) for pair in expected_counts)
    per_signal = {}
    for signal in signal_names:
        total = sum(1 for _, s in expected_checks if s == signal)
        covered = sum(min(expected_counts[(case_id, signal)], actual_counts[(case_id, signal)]) for case_id, s in expected_counts if s == signal)
        per_signal[signal] = {"covered": covered, "total": total, "percent": round(100 * covered / total, 2) if total else 0.0}
    return {
        "definition": "测试计划执行覆盖率；不代表 RTL 代码覆盖率",
        "vectors": {"covered": covered_vectors, "total": len(vectors), "percent": round(100 * covered_vectors / len(vectors), 2) if vectors else 0.0},
        "checks": {"covered": covered_checks, "total": len(expected_checks), "percent": round(100 * covered_checks / len(expected_checks), 2) if expected_checks else 0.0},
        "per_signal": per_signal,
    }


@dataclass(frozen=True)
class PipelineResult:
    """生成工件、Icarus 结果和可复现失败解释。"""

    plan: TestPlan
    contract: DutContract
    testbench_path: Path
    simulation: SimulationResult
    failure_explanations: tuple[FailureExplanation, ...] = ()
    artifacts: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    synthesis: dict[str, Any] = field(default_factory=dict)

    @property
    def result(self) -> SimulationResult:
        """兼容调用方将流水线返回值视作 SimulationResult 的便捷属性。"""

        return self.simulation

    @property
    def status(self):
        return self.simulation.status

    @property
    def records(self):
        return self.simulation.records

    @property
    def failures(self):
        return self.simulation.failures

    @property
    def verdict(self) -> str:
        """三层口径里的**结论层**：这份设计到底对不对。

        直接透传仿真的单一结论词。之所以在流水线结果上也暴露它：页面与报告需要
        同时显示"运行状态"与"设计结果"，如果这里没有同名属性，调用方就会退回用
        ``status`` 一个字段讲两件事——那正是被读错的根源（见 ``core/labels.py``）。
        """

        return self.simulation.verdict

    @property
    def failure_summaries(self) -> tuple[str, ...]:
        return tuple(item.summary for item in self.failure_explanations)

    @property
    def passed(self) -> bool:
        return self.simulation.passed

    @property
    def coverage(self) -> dict[str, Any]:
        return coverage_summary(self.plan, self.simulation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "created_at": self.created_at,
            "testbench_path": str(self.testbench_path),
            "artifacts": dict(self.artifacts),
            "failure_explanations": [item.to_dict() for item in self.failure_explanations],
            "coverage": self.coverage,
            "plan": self.plan.model_dump(mode="json"),
            "contract": self.contract.to_dict(),
            "simulation": self.simulation.to_dict(),
            "synthesis": dict(self.synthesis),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


class VerificationPipeline:
    """在显式工件目录中执行一次受控 TestPlan 验证。"""

    def __init__(
        self,
        *,
        generator: TestbenchGenerator | None = None,
        executor_factory: type[IcarusExecutor] = IcarusExecutor,
        phase_pairs: Sequence[Mapping[str, Any]] = (),
        run_synthesis: bool = False,
        yosys_path: str | None = None,
        synthesis_timeout_s: float = 180.0,
        reference_policy: Literal["builtin", "disabled"] = "builtin",
    ) -> None:
        if reference_policy not in {"builtin", "disabled"}:
            raise PipelineValidationError("reference_policy must be builtin or disabled")
        self.reference_policy = reference_policy
        self.generator = generator or TestbenchGenerator()
        self.executor_factory = executor_factory
        # 相位检查的期望延迟由调用方（contract/规格）显式给出，不从波形反推。
        self.phase_pairs = tuple(phase_pairs)
        # 综合证据层是可选的：没装 Yosys 时给出 unavailable，绝不影响仿真裁决。
        self.run_synthesis = run_synthesis
        self.yosys_path = yosys_path
        self.synthesis_timeout_s = synthesis_timeout_s

    def run(
        self,
        plan: TestPlan | Mapping[str, Any],
        contract: DutContract | Mapping[str, Any],
        rtl_path: str | Path,
        output_dir: str | Path,
        *,
        allowed_roots: Sequence[str | Path] | None = None,
        iverilog_path: str | Path | None = None,
        vvp_path: str | Path | None = None,
        include_dirs: Sequence[str | Path] = (),
        defines: Sequence[str] = (),
        timeout_seconds: float = 30.0,
        max_output_chars: int = 200_000,
        language: str = "2012",
        testbench_filename: str | None = None,
        emit_vcd: bool = True,
        vcd_filename: str = "waveform.vcd",
        capture_observations: bool = False,
    ) -> PipelineResult:
        if not isinstance(capture_observations, bool):
            raise PipelineValidationError("capture_observations must be a boolean")
        ai_plan = _coerce_plan(plan)
        dut_contract = _coerce_contract(contract)
        raw_output = Path(output_dir).expanduser()
        if raw_output.exists() and raw_output.is_symlink():
            raise PipelineValidationError("output_dir must not be a symbolic link")
        artifact_dir = raw_output.resolve(strict=False)
        if artifact_dir.exists() and not artifact_dir.is_dir():
            raise PipelineValidationError(f"output_dir is not a directory: {artifact_dir}")

        # Explicit roots are honored exactly. With no roots, the source parent
        # and the nearest existing parent of the chosen artifact directory are
        # deliberate trust roots. Crucially, all checks happen before mkdir so
        # an out-of-scope output can never be created as a side effect.
        source_parent = Path(rtl_path).expanduser().resolve(strict=False).parent
        if allowed_roots:
            roots = tuple(allowed_roots)
        else:
            artifact_root = artifact_dir
            while not artifact_root.exists() and artifact_root != artifact_root.parent:
                artifact_root = artifact_root.parent
            roots = (source_parent, artifact_root)
        try:
            policy = SafePathPolicy.from_roots(roots)
            rtl = policy.input_file(rtl_path)
            artifact_dir = policy.output_dir(artifact_dir)
        except Exception as exc:
            raise PipelineValidationError(str(exc)) from exc
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # Re-resolve after creation to reject a directory replaced by a link
        # between the preflight check and this write.
        artifact_dir = policy.output_dir(artifact_dir)

        # Validate the generated filename before touching any artifact.
        #
        # 权威预言机：内置案例的期望值由参考模型独立复算后覆盖 AI 给出的数字。
        # 这样 AI 无法通过猜错期望值来"制造"失败（假误报）或"掩盖"失败，而
        # 仿真裁决权仍然只属于 Icarus。AI 原始计划保留在 testplan.json 中，
        # 差异在 oracle 诊断里单独记录。
        oracle_expectations = (reference_expectations(ai_plan, ai_plan.design, dut_contract)
                               if self.reference_policy == "builtin" else {})
        generation_plan = override_plan_expectations(ai_plan, oracle_expectations) if oracle_expectations else ai_plan
        try:
            testbench_path = self.generator.generate(
                generation_plan,
                dut_contract,
                artifact_dir,
                filename=testbench_filename,
                emit_vcd=emit_vcd,
                vcd_filename=vcd_filename,
                **({"capture_observations": True} if capture_observations else {}),
            )
        except TestbenchGenerationError:
            raise
        plan_path = artifact_dir / "testplan.json"
        contract_path = artifact_dir / "dut_contract.json"
        pipeline_result_path = artifact_dir / "pipeline_result.json"
        authoritative_plan_path = artifact_dir / "authoritative_plan.json"
        planned_artifacts = [plan_path, contract_path, pipeline_result_path]
        if oracle_expectations:
            planned_artifacts.append(authoritative_plan_path)
        for artifact in planned_artifacts:
            if artifact.exists() and artifact.is_symlink():
                raise PipelineValidationError(f"artifact path must not be a symbolic link: {artifact}")
            policy.check(artifact, must_exist=False)
        plan_path.write_text(ai_plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        contract_path.write_text(dut_contract.to_json() + "\n", encoding="utf-8")
        if oracle_expectations:
            authoritative_plan_path.write_text(generation_plan.model_dump_json(indent=2) + "\n", encoding="utf-8")

        run_dir = artifact_dir / "runs"
        config = ExecutionConfig(
            rtl_path=rtl,
            testbench_path=testbench_path,
            top_module=f"tb_{dut_contract.module}",
            output_dir=run_dir,
            iverilog_path=iverilog_path,
            vvp_path=vvp_path,
            timeout_seconds=timeout_seconds,
            allowed_roots=tuple(policy.allowed_roots),
            include_dirs=tuple(include_dirs),
            defines=tuple(defines),
            max_output_chars=max_output_chars,
            language=language,
            keep_artifacts=True,
        )
        simulation = self.executor_factory(config).run()
        observations_path: Path | None = None
        if capture_observations:
            observations_path = artifact_dir / "observed_samples.json"
            if observations_path.is_symlink():
                raise PipelineValidationError("observed_samples artifact must not be a symbolic link")
            policy.check(observations_path, must_exist=False)
            # Bind observations to this execution's captured output. A later
            # change to the saved stdout must not change the measured evidence.
            stdout = simulation.run.stdout if simulation.run is not None else ""
            provenance = {"rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest(),
                          "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                          "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                          "testbench_sha256": hashlib.sha256(testbench_path.read_bytes()).hexdigest()}
            observations = collect_observed_samples(
                stdout, ai_plan, dut_contract, provenance=provenance,
                execution_complete=bool(simulation.run and simulation.run.status.value == "passed"),
                output_truncated=bool(simulation.run and simulation.run.output_truncated),
            )
            observations_path.write_text(json.dumps(observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            observation_metadata = {k: value for k, value in observations.items() if k != "samples"}
            observation_metadata["sha256"] = hashlib.sha256(observations_path.read_bytes()).hexdigest()
            simulation = replace(simulation, config={**simulation.config,
                "observed_samples": observation_metadata})
        vcd_analysis: dict[str, Any] = {"status": "not_available"}
        vcd_path_for_analysis = simulation.artifacts.get("vcd", "")
        if vcd_path_for_analysis:
            try:
                vcd_analysis = analyze_vcd_file(vcd_path_for_analysis, max_changes=5000)
                vcd_analysis["status"] = "parsed"
                period = dut_contract.clock.period_ns if dut_contract.clock is not None else 10.0
                failure_cycles = [item.cycle for item in simulation.failures if isinstance(item.cycle, int)]
                if failure_cycles:
                    vcd_analysis["failure_windows"] = analyze_failure_windows(
                        vcd_path_for_analysis, failure_cycles, clock_period_ns=period
                    )
                # 波形语义结论：边沿统计、信号稳定性与相位检查。稳定性检查
                # 排除时钟与复位：时钟每个周期必然翻转两次、复位在复位窗口内
                # 也会连续跳变，把它们算作"不稳定"只会淹没有用的结论。
                excluded = (".clk", ".clock", ".rst", ".rst_n", ".reset", ".reset_n", ".arst")
                data_signals = [
                    item["name"]
                    for item in vcd_analysis.get("signals", [])
                    if not item["name"].lower().endswith(excluded)
                ][:12]
                # 生成的 testbench 顶层是 tb_<module>，DUT 实例名固定为 DUT_INSTANCE，
                # 因此 DUT 内部信号的完整层次前缀是 tb_<module>.dut_i。测试平台自己的
                # 记账信号（检查任务的 expected/actual 等）不在此前缀下。
                dut_scope = f"tb_{dut_contract.module}.{DUT_INSTANCE}"
                vcd_analysis["insights"] = waveform_insights(
                    vcd_analysis,
                    clock_period_ns=float(period),
                    phase_pairs=self.phase_pairs,
                    stability_signals=data_signals,
                    dut_scopes=(dut_scope,),
                )
                # 信号活动覆盖率：由 VCD 事件推导"激励让设计里哪些信号动过、
                # 到达过多少种取值"。它是**激励质量**的指标，不是代码覆盖率——
                # 口径与边界见 core/coverage.py 的模块说明。
                try:
                    vcd_analysis["coverage"] = analyze_signal_activity(
                        rtl.read_text(encoding="utf-8"),
                        vcd_analysis,
                        top=f"tb_{dut_contract.module}",
                        instance=DUT_INSTANCE,
                    )
                except (OSError, ValueError, AttributeError) as exc:
                    vcd_analysis["coverage"] = {"status": "error", "error": str(exc)}
            except (OSError, ValueError, AttributeError) as exc:
                # AttributeError 也要接住：畸形 failure 记录（例如缺少 cycle）
                # 不应该让整条流水线崩掉，而应留下一份可审计的错误说明。
                vcd_analysis = {"status": "error", "error": str(exc)}
        # Reference checks explain the plan; the authoritative expectations above
        # already constrained the generated testbench. This block only records
        # how far the AI's own numbers were from the deterministic model, and it
        # never overrides the real Icarus status as the PASS/FAIL authority.
        consistency = (check_plan_consistency(ai_plan, ai_plan.design, dut_contract)
                       if self.reference_policy == "builtin" else {
                           "status": "skipped", "warnings": [],
                           "reason": "builtin reference lookup explicitly disabled",
                       })
        consistency["reference_policy"] = self.reference_policy
        # 期望值的**证据等级**必须如实标注，因为它决定了结论的可信度：
        #
        #   reference_model —— 确定性参考模型复算并覆盖了 AI 数字（内置且已逐拍对齐的案例）
        #   ai_generated    —— 没有参考模型，检查用的是 AI 给出的期望值
        #   none_given      —— 计划和参考模型都没给期望值，本轮没有功能层证据
        #
        # 早期版本用 `"reference_model" if oracle_expectations else "ai_generated"`
        # 两分支覆盖，于是"AI 也没给期望值"的自定义 RTL 会被标成 ai_generated ——
        # 把"没有期望值"误报成"有 AI 期望值"，读者会高估结论的可信度。
        plan_expectation_vectors = [
            str(vector.name)
            for vector in ai_plan.vectors
            if vector.expected
        ]
        if oracle_expectations:
            evidence_level = "reference_model"
        elif plan_expectation_vectors:
            evidence_level = "ai_generated"
        else:
            evidence_level = "none_given"
        consistency["expectation_source"] = evidence_level
        consistency["expectation_evidence_level"] = evidence_level
        consistency["plans_with_expectations"] = len(plan_expectation_vectors)
        consistency["ai_expectations_used_for_checking"] = evidence_level == "ai_generated"
        consistency["authoritative_vectors"] = len(oracle_expectations)
        if evidence_level == "none_given":
            consistency["advice"] = (
                "本轮既没有参考模型也没有 AI 期望值，因此只有激励与结构化断言在起作用；"
                "结论的期望值证据等级为 none_given，不要据此认为功能行为已被验证。"
            )
        elif evidence_level == "ai_generated":
            consistency["advice"] = (
                "本轮检查用的是 AI 给出的期望值：AI 猜错数字会直接表现为失败或漏检。"
                "该设计尚未纳入权威参考模型，如需更高可信度请先完成逐拍对齐。"
            )
        consistency_warnings = consistency.get("warnings", [])
        # AI 期望值偏差是**诊断**，不是裁决：当参考模型已经提供了权威期望值时，
        # 检查用的是参考值，AI 猜错数字不再推翻「通过」结论，只记为
        # ``ai_expected_mismatch`` 供实验统计。没有参考模型时才保留
        # ``plan_inconsistent`` 这一更严格的证据结论。
        ai_expected_mismatch = bool(consistency_warnings) and bool(oracle_expectations)
        if consistency_warnings:
            prefix = "ai_expected_mismatch: " if ai_expected_mismatch else "plan_inconsistent: "
            advisory = tuple(
                prefix + str(item.get("vector", "")) + "." + str(item.get("signal", ""))
                for item in consistency_warnings
            )
            simulation = replace(simulation, diagnostics=tuple(simulation.diagnostics) + advisory)
        # Embed the plan-execution coverage in the machine-readable simulation
        # result so standalone report renderers and the UI can consume it.
        assertion_result = _evaluate_structured_assertions(ai_plan, simulation)
        cross_validation = {
            "sources": ["iverilog"] + (["reference_model"] if consistency.get("status") != "skipped" else []) + (["structured_assertion"] if assertion_result.get("status") != "skipped" else []),
            "independent_sources": int(consistency.get("status") != "skipped") + int(assertion_result.get("status") != "skipped"),
            "status": "consistent" if not (consistency.get("warnings") and not ai_expected_mismatch) and assertion_result.get("status") in {"skipped", "passed"} else "inconsistent",
            "ai_expected_mismatch": ai_expected_mismatch,
        }
        # Keep the raw Icarus status unchanged, but expose a stricter evidence
        # conclusion for callers that need to distinguish mere simulation PASS
        # from an independently corroborated result.
        if simulation.status not in {ResultStatus.PASSED, ResultStatus.PASSED_WITH_WARNINGS}:
            verification_status = simulation.status.value
        elif consistency.get("warnings") and not ai_expected_mismatch:
            verification_status = "plan_inconsistent"
        elif assertion_result.get("status") == "warn":
            verification_status = "assertion_failed"
        elif consistency.get("status") != "skipped" or assertion_result.get("status") == "passed":
            verification_status = "verified"
        else:
            verification_status = "passed_unverified"
        simulation = replace(
            simulation,
            config={**simulation.config, "coverage": coverage_summary(ai_plan, simulation), "oracle": consistency, "structured_assertions": assertion_result, "cross_validation": cross_validation, "verification_status": verification_status, "vcd_analysis": vcd_analysis},
        )
        explanations = tuple(explain_failure_record(failure) for failure in simulation.failures)
        # 综合证据层：可选、不参与 PASS/FAIL 裁决。它只回答"这份 RTL 能不能被
        # 综合"，并显式标出时序/比特流/上板三个未做的层级。
        synthesis: dict[str, Any] = {
            "status": "not_run",
            "skipped_reason": "未启用综合证据层（run_synthesis=False）",
        }
        artifacts_synth: dict[str, str] = {}
        if self.run_synthesis:
            synth_result = YosysSynthRunner(
                SynthConfig(
                    rtl_path=rtl,
                    top=dut_contract.module,
                    work_dir=artifact_dir / "synthesis",
                    yosys_path=self.yosys_path,
                    timeout_s=self.synthesis_timeout_s,
                )
            ).run()
            synthesis = synth_result.to_dict()
            if synth_result.log_path:
                artifacts_synth["synthesis_log"] = synth_result.log_path
            if synth_result.stat_path:
                artifacts_synth["synthesis_stat"] = synth_result.stat_path
        # 放进 simulation.config，这样任何只拿到 SimulationResult 的渲染器
        # （report.py / CLI / 网页）都能直接展示，不必额外传参。
        simulation = replace(simulation, config={**simulation.config, "synthesis": synthesis})
        artifacts = {
            "output_dir": str(artifact_dir),
            "testbench": str(testbench_path),
            "testplan": str(plan_path),
            "dut_contract": str(contract_path),
            "run_dir": simulation.artifacts.get("run_dir", str(run_dir)),
            "result_json": simulation.artifacts.get("result_json", ""),
            "vcd": simulation.artifacts.get("vcd", ""),
        }
        artifacts.update(artifacts_synth)
        if observations_path is not None:
            artifacts["observed_samples"] = str(observations_path)
        if oracle_expectations:
            artifacts["authoritative_plan"] = str(authoritative_plan_path)
        result = PipelineResult(
            plan=ai_plan,
            contract=dut_contract,
            testbench_path=testbench_path,
            simulation=simulation,
            failure_explanations=explanations,
            artifacts=artifacts,
            synthesis=synthesis,
        )
        artifacts["pipeline_result"] = str(pipeline_result_path)
        result = PipelineResult(
            plan=result.plan,
            contract=result.contract,
            testbench_path=result.testbench_path,
            simulation=result.simulation,
            failure_explanations=result.failure_explanations,
            artifacts=artifacts,
            created_at=result.created_at,
            synthesis=synthesis,
        )
        pipeline_result_path.write_text(result.to_json() + "\n", encoding="utf-8")
        return result

    execute = run


def run_test_plan(
    plan: TestPlan | Mapping[str, Any],
    contract: DutContract | Mapping[str, Any],
    rtl_path: str | Path,
    output_dir: str | Path,
    **kwargs: Any,
) -> PipelineResult:
    """函数式流水线 API。"""

    return VerificationPipeline().run(plan, contract, rtl_path, output_dir, **kwargs)


execute_test_plan = run_test_plan
run_plan = run_test_plan


__all__ = [
    "FailureExplanation",
    "PipelineResult",
    "PipelineValidationError",
    "VerificationPipeline",
    "execute_test_plan",
    "explain_failure",
    "explain_failure_record",
    "explain_failures",
    "run_test_plan",
    "run_plan",
    "summarize_failure",
]
