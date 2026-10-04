"""API-agent adapter for frozen external RTL with separately qualified baselines.

No reference-model or assertion result is fabricated. Offline replay is the default;
--execute uses the same bounded agent loop once its observation hook is available.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, cast
from urllib.parse import urlsplit

from iverilog_ai.ai.agent import AgentLimits, AgentObservation, run_verification_agent
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import PipelineResult, VerificationPipeline
from iverilog_ai.core.testbench import TestbenchGenerator, TestbenchGenerationError

# Support both direct script execution and import by tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_external_module as harness

QUALIFIED_OUTPUTS = {
    "uart_rx": ("m_axis_tdata", "m_axis_tvalid", "frame_error", "busy"),
    "uart_tx": ("txd", "busy"),
    "priority_encoder": ("output_valid", "output_encoded", "output_unencoded"),
}
EVIDENCE_KIND = "qualified_baseline_differential"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SnapshotGenerator(TestbenchGenerator):
    """Add observation-only displays at a validated generator sampling anchor."""
    def generate(self, plan: Any, contract: Any, output_dir: Any, **options: Any) -> Path:
        if any(v.expected for v in plan.vectors) or plan.assertions or plan.pre_reset_expected:
            raise TestbenchGenerationError("snapshot instrumentation requires stimulus-only plans")
        path = super().generate(plan, contract, output_dir, **options)
        source = path.read_text(encoding="utf-8")
        anchor = "    cycle = cycle + 1;"
        count = sum(vector.cycles for vector in plan.vectors)
        lines = source.splitlines()
        locations = [i for i, line in enumerate(lines) if line == anchor]
        if len(locations) != count or any(i == 0 or not lines[i - 1].startswith('    $display("IVERILOG_AI_RESULT ') for i in locations):
            raise TestbenchGenerationError("sampling anchor contract changed; refuse instrumentation")
        names = QUALIFIED_OUTPUTS[contract.module]
        if not all(contract.port_map[name].direction.value == "output" for name in names):
            raise TestbenchGenerationError("snapshot can only read qualified outputs")
        statement = ('    $display("ICARUS_EXTERNAL_SAMPLE %0d %.3f ' + " ".join(["%b"] * len(names))
                     + '", cycle, $realtime, ' + ", ".join(names) + ');')
        patched = source.replace(anchor, statement + "\n" + anchor)
        original = path.with_name(path.stem + "_uninstrumented.v")
        if original.exists():
            raise TestbenchGenerationError("uninstrumented evidence already exists")
        original.write_text(source, encoding="utf-8")
        path.write_text(patched, encoding="utf-8")
        generator_source = Path(inspect.getfile(TestbenchGenerator))
        save(path.parent / "snapshot_instrumentation.json", {
            "kind": "read_only_sampling_display", "anchor": anchor, "anchor_count": count,
            "original_sha256": sha(original), "instrumented_sha256": sha(path),
            "generator_source_sha256": sha(generator_source), "adapter_sha256": sha(Path(__file__)),
            "outputs": list(names), "time_unit": "ns", "time_precision": "1ps",
            "assertions_added": 0, "stimulus_or_rtl_changed": False})
        return path


def samples_from_log(path: Path, contract: DutContract, count: int) -> list[dict[str, Any]]:
    """Read statement-time snapshots; final VCD timestamp values are not an oracle."""
    if count < 1 or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("insufficient or excessive output log")
    outputs = QUALIFIED_OUTPUTS[contract.module]
    snapshots: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("ICARUS_EXTERNAL_SAMPLE "):
            continue
        fields = line.split()
        if len(fields) != 3 + len(outputs) or not fields[1].isdigit() or not re.fullmatch(r"[0-9]+\.[0-9]{3}", fields[2]):
            raise ValueError("malformed snapshot")
        cycle, time_ns = int(fields[1]), float(fields[2])
        if cycle != len(snapshots) or (snapshots and time_ns <= snapshots[-1]["time_ns"]):
            raise ValueError("missing, duplicated or unordered sample")
        if not all(re.fullmatch("[01]+", value) for value in fields[3:]):
            raise ValueError("unknown output at sample")
        observed = {name: int(value, 2) for name, value in zip(outputs, fields[3:])}
        snapshots.append({"cycle": cycle, "time_ns": time_ns, "outputs": observed})
    if len(snapshots) != count:
        raise ValueError("sample count differs from plan")
    return snapshots


def compare_samples(reference: list[dict[str, Any]], candidate: list[dict[str, Any]], module: str) -> dict[str, Any]:
    if not reference or len(reference) != len(candidate):
        raise ValueError("incomplete samples")
    differences = []
    compared = 0
    for left, right in zip(reference, candidate):
        if (left["cycle"], left["time_ns"]) != (right["cycle"], right["time_ns"]):
            raise ValueError("sampling points differ")
        for signal in QUALIFIED_OUTPUTS[module]:
            # Do not compare unspecified payload/encoding while reference valid is low.
            if module == "uart_rx" and signal == "m_axis_tdata" and not left["outputs"]["m_axis_tvalid"]:
                continue
            if module == "priority_encoder" and signal != "output_valid" and not left["outputs"]["output_valid"]:
                continue
            compared += 1
            a, b = left["outputs"][signal], right["outputs"][signal]
            if a != b:
                differences.append({"cycle": left["cycle"], "time_ns": left["time_ns"],
                                    "signal": signal, "baseline": a, "candidate": b})
    return {"compared_samples": compared, "differences": len(differences),
            "difference_samples": differences[:8]}


class FrozenExternalRunner:
    """Trusted Python adapter; models cannot choose or change its oracle."""
    def __init__(self, *, manifest: Path, candidate: Path, module: str, output_dir: Path,
                 iverilog: str, vvp: str) -> None:
        if module not in QUALIFIED_OUTPUTS:
            raise ValueError("unsupported external qualification")
        self.root = output_dir.resolve()
        self.records = harness.freeze_inputs(manifest, self.root)
        self.module = module
        self.contract = DutContract.from_dict(harness.MODULES[module]["contract"])
        self.baseline = self.root / self.records[module]["local"]
        self.candidate = self.root / "candidate.v"
        self.candidate.write_bytes(candidate.read_bytes())
        self.iverilog, self.vvp = iverilog, vvp
        self.hashes = {str(self.root / record["local"]): record["sha256"] for record in self.records.values()}
        self.hashes[str(self.candidate)] = sha(self.candidate)
        self.qualification_path = self.root / "qualification.json"
        self.qualification = self._qualify()
        save(self.qualification_path, self.qualification)
        self.qualification_hash = sha(self.qualification_path)
        self.last: PipelineResult | None = None
        self.observation: dict[str, Any] = {}

    def _unchanged(self) -> bool:
        return all(sha(Path(path)) == digest for path, digest in self.hashes.items())

    def _qualify(self) -> dict[str, Any]:
        tb = self.root / "qualification_tb.v"
        tb.write_text(harness.MODULES[self.module]["spec_tb"], encoding="utf-8")
        executable = self.root / "qualification.vvp"
        deps = [self.root / self.records["uart_rx"]["local"]] if self.module == "uart_tx" else []
        command = [self.iverilog, "-g2012", "-s", f"tb_{self.module}", "-o", str(executable),
                   str(self.baseline), *map(str, deps), str(tb)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=30, errors="replace")
        (self.root / "qualification_compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
        result: dict[str, Any] = {"record_kind": "machine_spec_qualification", "independent_human_review": False,
            "baseline_sha256": sha(self.baseline), "testbench_sha256": sha(tb), "compile_command": command,
            "dependency_sha256": {p.name: sha(p) for p in deps}, "qualified_outputs": list(QUALIFIED_OUTPUTS[self.module]),
            "status": "inconclusive", "checks": 0, "failures": None,
            "scope": "limited existing hand-written specification tests; no full functional proof"}
        if compiled.returncode:
            return result
        run = subprocess.run([self.vvp, str(executable)], capture_output=True, text=True, timeout=30, errors="replace")
        output = run.stdout + run.stderr
        (self.root / "qualification_simulation.log").write_text(output, encoding="utf-8")
        summary = re.search(r"^SPEC_SUMMARY checks=(\d+) failures=(\d+)$", output, re.M)
        if summary:
            result.update(checks=int(summary[1]), failures=int(summary[2]))
        if run.returncode == 0 and result["checks"] > 0 and result["failures"] == 0 and self._unchanged():
            result["status"] = "qualified"
        return result

    def run(self, plan: TestPlan, contract: DutContract, rtl_path: Path, output_dir: Path, **options: Any) -> PipelineResult:
        if self.qualification["status"] != "qualified" or not self._unchanged() or sha(self.qualification_path) != self.qualification_hash:
            raise ValueError("baseline not qualified or frozen inputs changed")
        if contract.to_dict() != self.contract.to_dict() or Path(rtl_path).resolve() != self.candidate:
            raise ValueError("cannot change frozen candidate or qualified contract")
        if plan.design != self.module or any(v.expected for v in plan.vectors) or plan.assertions or plan.pre_reset_expected:
            raise ValueError("external comparison accepts stimulus only")
        options = {**options, "iverilog_path": self.iverilog, "vvp_path": self.vvp, "emit_vcd": True}
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=False)
        pipeline = VerificationPipeline(reference_policy="disabled", generator=SnapshotGenerator())
        reference = pipeline.run(plan, contract, self.baseline, output_dir / "baseline", **options)
        candidate = pipeline.run(plan, contract, self.candidate, output_dir / "candidate", **options)
        self.last = candidate
        observation: dict[str, Any] = {"run_id": candidate.simulation.run_id, "status": "inconclusive",
            "verdict": "inconclusive", "expectation_source": EVIDENCE_KIND, "verification_status": "inconclusive",
            "checks": 0, "failures": 0, "compared_samples": 0, "differences": 0, "difference_samples": [],
            "qualification_sha256": self.qualification_hash, "baseline_sha256": sha(self.baseline),
            "candidate_sha256": sha(self.candidate), "qualified_outputs": list(QUALIFIED_OUTPUTS[self.module]),
            "evidence_path": str(output_dir / "external_observation.json"),
            "baseline_pipeline_result": reference.artifacts["pipeline_result"],
            "candidate_pipeline_result": candidate.artifacts["pipeline_result"],
            "candidate_stimulus_cycles": sum(v.cycles for v in plan.vectors),
            "baseline_stimulus_cycles": sum(v.cycles for v in plan.vectors)}
        try:
            if not self._unchanged():
                raise ValueError("input changed")
            for actual in (reference, candidate):
                sim = actual.simulation
                if sim.compile.returncode != 0 or sim.run is None or sim.run.returncode != 0 or sim.run.timed_out or sim.run.output_truncated:
                    raise ValueError("simulation incomplete")
            count = sum(v.cycles for v in plan.vectors)
            baseline_samples = samples_from_log(Path(reference.simulation.artifacts["run_stdout"]), contract, count)
            candidate_samples = samples_from_log(Path(candidate.simulation.artifacts["run_stdout"]), contract, count)
            save(output_dir / "baseline_samples.json", baseline_samples)
            save(output_dir / "candidate_samples.json", candidate_samples)
            observation.update(compare_samples(baseline_samples, candidate_samples, self.module))
            observation.update(status="passed", verification_status=EVIDENCE_KIND,
                verdict="behavior_difference" if observation["differences"] else "no_observed_difference")
        except (ValueError, OSError, KeyError) as error:
            observation["error_type"] = type(error).__name__
        save(output_dir / "external_observation.json", observation)
        self.observation = observation
        return candidate

    def observe(self, result: PipelineResult) -> AgentObservation:
        if result is not self.last:
            raise ValueError("observation does not belong to this round")
        return AgentObservation.model_validate(self.observation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--module", required=True, choices=sorted(QUALIFIED_OUTPUTS))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--execute", action="store_true", help="send bounded API requests; default is offline replay")
    parser.add_argument("--endpoint", default=os.getenv("IVERILOG_AI_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("IVERILOG_AI_MODEL", ""))
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=2)
    parser.add_argument("--max-total-cycles", type=int, default=1200)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    args = parser.parse_args(argv)
    try:
        provider = None
        limits = AgentLimits(max_rounds=args.max_rounds, max_requests=args.max_requests,
                             max_total_cycles=args.max_total_cycles, max_output_tokens=args.max_output_tokens)
        if args.execute:
            if "round_observer" not in inspect.signature(run_verification_agent).parameters:
                raise ValueError("core observation hook is not available yet")
            url = urlsplit(args.endpoint)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or not args.model:
                raise ValueError("explicit HTTPS endpoint and model required")
            key = read_key_file(args.api_key_file) if args.api_key_file else os.getenv("IVERILOG_AI_API_KEY", "")
            if not key:
                raise ValueError("API key missing")
            provider = OpenAICompatibleProvider(endpoint=args.endpoint, model=args.model, api_key=key,
                wire_api="chat_completions", allow_network=True, store=False, stream=False, request_limit=limits.max_requests,
                max_output_tokens=limits.max_output_tokens, force_output_limit=True)
        if args.output_dir.exists():
            raise ValueError("output directory must be new")
        runner = FrozenExternalRunner(manifest=args.manifest, candidate=args.candidate, module=args.module,
            output_dir=args.output_dir / "qualification", iverilog=args.iverilog, vvp=args.vvp)
        plan = TestPlan.model_validate(harness.MODULES[args.module]["plan"]())
        if runner.qualification["status"] != "qualified":
            print("inconclusive: baseline qualification failed")
            return 1
        if not args.execute:
            actual = runner.run(plan, runner.contract, runner.candidate, args.output_dir / "offline-round")
            print(runner.observe(actual).model_dump_json())
            return 0 if runner.observation["status"] == "passed" else 1
        assert provider is not None
        result = run_verification_agent(provider=provider, contract=runner.contract, rtl_path=runner.candidate,
            output_dir=args.output_dir / "agent", objective="Append targeted UART/input tests to compare qualified outputs; report behavior differences only.",
            specification="Qualified baseline differential evidence only; never full functional correctness. Existing qualification is limited.",
            initial_plan=plan, limits=limits, pipeline=cast(VerificationPipeline, runner), round_observer=runner.observe, simulation_multiplier=2)
        print(result.stop_reason)
        return 0 if result.stop_reason in {"behavior_difference", "model_stopped", "round_budget", "cycle_budget", "request_budget"} else 1
    except Exception as error:
        print(f"External agent failed: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
