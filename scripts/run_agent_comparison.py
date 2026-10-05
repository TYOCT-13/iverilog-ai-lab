"""Pre-registered bounded Agent pilot. Dry-run by default; never discard failures."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from iverilog_ai.ai.agent import AgentLimits, PROMPT_VERSION, SYSTEM_PROMPT, run_verification_agent
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.strategy_scoring import budget_for, normalize_vectors, plan_cycles, classify_undecidable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_strategy_experiment import _fixed, _plan_with_vectors
from scripts.summarize_agent_comparison import classify, summarize_rows, freeze_pipeline_evidence
CASES = ("sync_fifo", "uart_tx", "spi_master", "handshake_stage")
STRATEGIES = ("fixed", "random", "single", "feedback", "no_feedback")
V2_STRATEGIES = (*STRATEGIES, "protocol_random", "feedback_no_coverage")
V3_STRATEGIES = ("fixed", "random", "protocol_random", "feedback", "no_feedback")
BASELINES = {"fixed", "random", "protocol_random"}
PROTOCOLS_PATH = ROOT / "spec/agent_protocols.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def registered_source_path(relative: str) -> Path:
    """Validate a registered path before opening it, including Windows drives."""
    path = Path(relative)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ValueError("registered input escapes repository")
    source = (ROOT / path).resolve(strict=True)
    if not source.is_relative_to(ROOT.resolve()) or not source.is_file():
        raise ValueError("registered input escapes repository")
    return source


def freeze_registered_inputs(registration: dict, output: Path) -> dict:
    """Keep the registered bytes before the first request, not just their hashes."""
    files = []
    for relative, digest in registration["code_and_input_sha256"].items():
        source = registered_source_path(relative)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("registered input changed during snapshot")
        target = output / "registered-inputs" / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(raw)
        files.append({"path": relative, "copy": str(target.relative_to(output)).replace("\\", "/"),
                      "sha256": digest, "size_bytes": len(raw)})
    manifest = {"schema": "registered-input-bytes-v1", "files": files,
                "purpose": "exact bytes frozen before API execution; no newline conversion"}
    write(output / "registered-inputs" / "manifest.json", manifest)
    return {"path": "registered-inputs/manifest.json",
            "sha256": sha(output / "registered-inputs" / "manifest.json"), "file_count": len(files)}


def protocol_config(path: Path = PROTOCOLS_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "agent-protocols-v1":
        raise ValueError("unsupported protocol profile schema")
    for case in CASES:
        item = payload["cases"][case]
        if not isinstance(item["cycle_budget"], int) or not 1 <= item["cycle_budget"] <= 100000:
            raise ValueError("invalid protocol cycle budget")
        spec = (ROOT / item["spec_path"]).resolve(strict=True)
        if not spec.is_relative_to(ROOT) or not spec.is_file():
            raise ValueError("protocol specification escapes repository")
        text = spec.read_text(encoding="utf-8")
        if not text.strip() or len(text) > 16000:
            raise ValueError("protocol specification must fit the agent context")
    return payload


def preregister(cases=CASES, strategies=None, repeats=None, defects_per_case=2, *, profile="legacy") -> dict:
    if profile not in {"legacy", "v2", "v3"}:
        raise ValueError("unknown comparison profile")
    strategies = tuple(strategies if strategies is not None else V3_STRATEGIES if profile == "v3"
                       else V2_STRATEGIES if profile == "v2" else STRATEGIES)
    repeats = repeats if repeats is not None else 3 if profile == "v2" else 1
    if len(set(cases)) != len(cases) or len(set(strategies)) != len(strategies):
        raise ValueError("duplicate cases or strategies")
    if not cases or not strategies or not 1 <= repeats <= 5 or not 1 <= defects_per_case <= 3:
        raise ValueError("invalid registered sample selection")
    if set(strategies) - set(V2_STRATEGIES if profile in {"v2", "v3"} else STRATEGIES):
        raise ValueError("strategy requires v2 profile")
    protocols = protocol_config() if profile in {"v2", "v3"} else None
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text(encoding="utf-8"))
    mutation_profile = None
    if protocols:
        mutation_profile = json.loads((ROOT / "benchmarks/agent_v2/mutation_manifest.json").read_text(encoding="utf-8"))
        if mutation_profile.get("schema_version") != "agent-v2-mutations-v1":
            raise ValueError("unsupported v2 mutation manifest")
        baseline = mutation_profile["baseline"]
        if any(sha(ROOT / baseline[key]) != baseline["sha256"] for key in ("path", "snapshot_path")):
            raise ValueError("v2 mutation baseline hash mismatch")
        for defect in mutation_profile["defects"]:
            if sha(ROOT / defect["file"]) != defect["sha256"] or defect["baseline_sha256"] != baseline["sha256"]:
                raise ValueError("v2 mutation hash mismatch")
    targets = []
    contract_profiles = {}
    for case in cases:
        if case not in CASES:
            raise ValueError("case outside registered development families")
        if protocols:
            contract_data = json.loads((ROOT / f"examples/{case}_contract.json").read_text(encoding="utf-8"))
            contract_profiles[case] = hashlib.sha256(json.dumps(DutContract.from_dict(contract_data).to_dict(),
                                                               ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if contract_data.get("parameters", {}) != protocols["cases"][case]["default_parameters"]:
                raise ValueError("protocol timing profile does not match contract parameters")
        targets.append({"case": case, "variant": "reference", "rtl": f"rtl/{case}.v"})
        source_defects = mutation_profile["defects"] if mutation_profile and case == "sync_fifo" else manifest["defects"]
        defects = [d for d in source_defects if d["type"] == case][:defects_per_case]
        if len(defects) != defects_per_case:
            raise ValueError("insufficient registered defects")
        targets.extend({"case": case, "variant": d["id"], "rtl": d["file"]} for d in defects)
    rows = [{**target, "strategy": strategy, "seed": seed,
             "budget_cycles": protocols["cases"][target["case"]]["cycle_budget"] if protocols else budget_for(target["case"]).cycles,
             "status": "not_started", "detected": False, "requests": 0, "rounds": [],
             "first_detection_cycle": None, "first_detection_search_budget": None, "first_detection_elapsed_seconds": None}
            for target in targets for seed in range(repeats) for strategy in strategies]
    inputs = {"benchmarks/manifest.json", "scripts/run_agent_comparison.py", "scripts/run_strategy_experiment.py",
              "scripts/summarize_agent_comparison.py", "docs/experiment/agent_comparison_protocol.md"}
    inputs.update(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "src/iverilog_ai").rglob("*.py"))
    for target in targets:
        inputs.update([target["rtl"], f"rtl/{target['case']}.v", f"examples/{target['case']}_contract.json"])
        inputs.add(protocols["cases"][target["case"]]["spec_path"] if protocols else "spec/common_cases.md")
    if protocols:
        assert mutation_profile is not None
        inputs.add("spec/agent_protocols.json")
        inputs.add("docs/experiment/agent_comparison_v5_plan_2026-10-05.md" if profile == "v3"
                   else "docs/experiment/agent_comparison_v2_plan_2026-10-04.md")
        inputs.add("benchmarks/agent_v2/mutation_manifest.json")
        inputs.add(mutation_profile["baseline"]["snapshot_path"])
    prompt_profile = {"agent_prompt_version": PROMPT_VERSION,
                      "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                      "profile": profile, "strategies": list(strategies), "repeats": repeats,
                      "functional_coverage": "available to single/feedback; no_feedback and feedback_no_coverage hidden" if protocols else "disabled legacy",
                      "max_rounds": 3, "api_request_limit_per_sample": {"single": 1, "feedback": 3, "no_feedback": 3, "feedback_no_coverage": 3}}
    if profile == "v3":
        prompt_profile.update(reference_sampling="per_cycle", agent_plan_mode="independent")
    return {"schema": "agent-comparison-v3" if profile == "v3" else "agent-comparison-v2" if protocols else "agent-comparison-v1", "profile": profile,
            **({"contract_profile_sha256": contract_profiles} if profile == "v3" else {}),
            "scope": "development_repeated_not_human_trial" if protocols else "pilot_not_human_trial", "rows": rows,
            "independent_holdout": False, "protocol_config": protocols,
            "prompt_profile": prompt_profile,
            "prompt_profile_sha256": hashlib.sha256(json.dumps(prompt_profile, sort_keys=True).encode()).hexdigest(),
            "theoretical_requests": sum(0 if r["strategy"] in BASELINES else 1 if r["strategy"] == "single" else 3 for r in rows),
            "code_and_input_sha256": {p: sha(ROOT / p) for p in sorted(inputs)},
            "protocol": {"reference_replay": "every executed plan; any alarm invalidates target sample",
                         "cycles": ("independent reset episodes; sum of all executed stimulus, excluding reset and separately reported reference audit"
                                    if profile == "v3" else "cumulative reruns, excluding reset and separately reported reference audit"),
                         "denominator": "all registered defects per repeat including incomplete samples",
                         "single": "same decision schema and prompt, one API proposal and one simulation",
                         "no_feedback": "same loop and budget, observation withheld; failure stop retained",
                         "selection": "first N manifest defects, selected before execution"}}


def protocol_random_vectors(case: str, seed: int, contract: DutContract, cycles: int, protocol: dict) -> list[dict]:
    """Seeded protocol transactions; never reads target RTL, variants or failure labels."""
    rng = random.Random(seed)
    vectors: list[dict] = []
    ports = {p.name: p for p in contract.ports if p.direction.value == "input"}
    clock = contract.clock.signal if contract.clock else None
    reset = contract.reset.signal if contract.reset else None
    defaults = {name: 0 for name in ports if name not in {clock, reset}}
    defaults.update({k: v for k, v in protocol.get("input_defaults", {}).items() if k in defaults})
    used = 0

    def emit(inputs: dict, count: int = 1) -> None:
        nonlocal used
        if count <= 0 or used + count > cycles:
            raise ValueError("protocol generator exceeded registered budget")
        values = {**defaults, **inputs}
        if any(name not in ports or not isinstance(value, int) or not 0 <= value < 1 << ports[name].width
               for name, value in values.items()):
            raise ValueError("protocol input outside contract")
        vectors.append({"name": f"protocol_{len(vectors)}", "inputs": values, "cycles": count,
                        "sample_phase": "after", "expected": {}})
        used += count

    if case in {"uart_tx", "spi_master"}:
        timing = protocol["timing"]
        # Acceptance edge plus all busy edges and a post-completion idle edge.
        busy = int(timing["busy_cycles_after_accept"])
        block = busy + 2
        if case == "uart_tx":
            bit_period = int(timing["clks_per_bit"])
            if bit_period < 2:
                raise ValueError("registered UART random profile needs at least two clocks per bit")
            frame_vectors = int(timing["data_bits"]) + 5 + int(bit_period > 2)
        else:
            frame_vectors = block
        while cycles - used >= block and len(vectors) + frame_vectors + 1 <= 200:
            data = rng.randrange(1 << ports["data_in"].width)
            emit({"start": 1, "data_in": data})
            # Boundary attempt during busy is ignored by the documented protocol.
            emit({"start": 1, "data_in": rng.randrange(1 << ports["data_in"].width)})
            if case == "uart_tx":
                if bit_period > 2:
                    emit({"start": 0, "data_in": data}, bit_period - 2)
                # Observe each data bit and stop bit, not just idle after a frame.
                for _ in range(int(timing["data_bits"]) + 1):
                    emit({"start": 0, "data_in": data}, bit_period)
                emit({"start": 0, "data_in": data})
            else:
                for _ in range(busy - 1):
                    emit({"start": 0, "data_in": data})
            emit({"start": 0, "data_in": data})
        if used < cycles:
            emit({"start": 0}, cycles - used)
    elif case == "sync_fifo":
        depth = int(protocol["timing"]["depth"])
        # Empty read, fill, overflow attempt, full simultaneous read/write, drain.
        prefix = [(0, 1)] + [(1, 0)] * depth + [(1, 0), (1, 1)] + [(0, 1)] * depth
        for step in range(cycles):
            wr, rd = prefix[step] if step < len(prefix) else rng.choice([(1, 0), (0, 1), (1, 1), (0, 0)])
            emit({"wr_en": wr, "rd_en": rd, "wr_data": rng.randrange(1 << ports["wr_data"].width)})
    elif case == "handshake_stage":
        valid = False
        pending = False
        payload = 0
        for step in range(cycles):
            ready = step % 8 >= 3 if step < 16 else bool(rng.randrange(2))
            if not pending:
                pending = True if step < 16 else bool(rng.randrange(2))
                payload = rng.randrange(1 << ports["in_data"].width)
            accepted = pending and (not valid or ready)
            emit({"in_valid": int(pending), "in_data": payload, "out_ready": int(ready)})
            if not valid or ready:
                valid = pending
            if accepted:
                pending = False
    else:
        raise ValueError("no registered protocol generator")
    if len(vectors) > 200:
        raise ValueError("protocol generator exceeded vector limit")
    return vectors


def baseline_plan(case: str, strategy: str, seed: int, contract: DutContract, cycles: int, *, profile="legacy", protocol=None) -> TestPlan:
    if strategy == "protocol_random":
        if profile not in {"v2", "v3"} or protocol is None:
            raise ValueError("protocol random requires explicit v2 specification")
        vectors = protocol_random_vectors(case, seed, contract, cycles, protocol)
    elif strategy == "fixed":
        vectors = [{**v, "expected": {}} for v in _fixed(case)]
    else:
        rng = random.Random(seed)
        excluded = {contract.clock.signal if contract.clock else "", contract.reset.signal if contract.reset else ""}
        inputs = [p for p in contract.ports if p.direction.value == "input" and p.name not in excluded]
        segments = min(cycles, 200) if profile in {"v2", "v3"} else cycles
        vectors = [{"name": f"random_{i}", "inputs": {p.name: rng.randrange(1 << p.width) for p in inputs},
                    "cycles": cycles // segments + int(i < cycles % segments), "expected": {}} for i in range(segments)]
    plan = TestPlan.model_validate({"design": case, "objective": "Check contract behavior and protocol boundaries", "vectors": vectors,
                                    "reset": contract.reset.to_dict() if contract.reset else {}})
    return _plan_with_vectors(plan, normalize_vectors(vectors, cycles).vectors)


def observation(result, *, capture_coverage=False, rtl_sha256="") -> dict:
    sim = result.simulation
    data = {"status": sim.status.value, "checks": sim.check_count if sim.check_count is not None else 0,
            "records": len(sim.records), "failures": len(sim.failures),
            "failure_cycles": [f.cycle for f in sim.failures if isinstance(f.cycle, int)],
            "expectation_source": sim.config.get("oracle", {}).get("expectation_source"),
            "pipeline_result": str(result.artifacts.get("pipeline_result", ""))}
    if capture_coverage:
        from iverilog_ai.core.functional_coverage import analyze_functional_coverage
        data["functional_coverage"] = analyze_functional_coverage(result, rtl_sha256=rtl_sha256, builtin_profile=True)
    return data



def summarize(rows: list[dict]) -> dict:
    return summarize_rows(rows)


def decision_records(index: int, trace: dict) -> list[dict]:
    safe_fields = {"status", "schema_validation_status", "error_type", "validation_error_types", "http_status", "finish_reason", "executed_round",
                   "plan_validation_status", "plan_error", "retry_eligible", "decision_error", "policy_error_code",
                   "parse_status", "untrusted_response_status", "untrusted_response", "response_chars",
                   "response_bytes", "response_sha256"}
    return [{"request_id": f"{index}:{n}", "usage": decision.get("usage"),
             **{key: value for key, value in decision.items() if key in safe_fields}}
            for n, decision in enumerate(trace.get("decisions", []))]


def execute(registration: dict, output: Path, *, endpoint="", model="", key="", request_cap=0,
            max_output_tokens=4096, wire_api: Literal["chat_completions", "responses"] = "chat_completions",
            thinking_mode: Literal["enabled", "disabled"] | None = None,
            iverilog="iverilog", vvp="vvp", provider_factory=None,
            provider_factory_record_kind="test_provider",
            baseline_factory: Callable[[str, str, int, DutContract, int], TestPlan] | None = None) -> dict:
    if provider_factory_record_kind not in {"test_provider", "api_and_local_simulation"}:
        raise ValueError("invalid provider factory provenance")
    if thinking_mode not in {None, "enabled", "disabled"}:
        raise ValueError("invalid thinking mode")
    if wire_api == "responses" and thinking_mode is not None:
        raise ValueError("explicit thinking mode requires chat_completions")
    if any(sha(registered_source_path(p)) != digest
           for p, digest in registration["code_and_input_sha256"].items()):
        raise ValueError("registered source/input changed before execution")
    # Custom module resources remain part of the same frozen registration.
    for registered in registration["rows"]:
        resources = (registered["rtl"],
                     registered.get("contract_path", f"examples/{registered['case']}_contract.json"),
                     registered.get("reference_rtl", f"rtl/{registered['case']}.v"))
        for resource in resources:
            if resource not in registration["code_and_input_sha256"]:
                raise ValueError("sample resource is not registered")
            registered_source_path(resource)
    profile = registration.get("profile", "legacy")
    protocols = registration.get("protocol_config")
    output.mkdir(parents=True, exist_ok=False)
    write(output / "preregistration.json", registration)
    frozen_inputs = freeze_registered_inputs(registration, output) if profile == "v3" else None
    settings = {"preregistration_sha256": sha(output / "preregistration.json"), "wire_api": wire_api,
                "thinking_mode": thinking_mode,
                "thinking_mode_meaning": "unspecified_provider_default" if thinking_mode is None else "explicit_request",
                "endpoint_host": urlsplit(endpoint).hostname, "model": model,
                "max_output_tokens": max_output_tokens, "total_request_cap": request_cap,
                "request_timeout_seconds": 60, "stream": False, "iverilog": iverilog, "vvp": vvp,
                "profile": profile, "max_output_chars": 2_000_000 if profile in {"v2", "v3"} else 200_000,
                "prompt_profile_sha256": registration.get("prompt_profile_sha256")}
    settings["baseline_factory"] = (baseline_factory.__module__ + "." + baseline_factory.__qualname__
                                    if baseline_factory else "scripts.run_agent_comparison.baseline_plan")
    if profile == "v3":
        settings.update(reference_sampling="per_cycle", agent_plan_mode="independent", frozen_inputs=frozen_inputs)
    write(output / "run_settings.json", settings)
    report = {"preregistration_sha256": sha(output / "preregistration.json"),
              "run_settings_sha256": sha(output / "run_settings.json"), "wire_api": wire_api, "profile": profile,
              "thinking_mode": thinking_mode,
              "started_at": datetime.now(timezone.utc).isoformat(), "endpoint_host": urlsplit(endpoint).hostname,
              "model": model, "total_request_cap": request_cap, "max_output_tokens": max_output_tokens,
              "cost_currency": None, "cost_missing_reason": "provider billing not supplied; usage is not currency",
              "rows": json.loads(json.dumps(registration["rows"])), "requests_attempted": 0,
              "record_kind": provider_factory_record_kind if provider_factory else "api_and_local_simulation"}
    if frozen_inputs:
        report["frozen_inputs"] = frozen_inputs
    def save():
        report["summary"] = summarize(report["rows"])
        write(output / "results.json", report)
    save()
    runner = VerificationPipeline()
    options = {"allowed_roots": (ROOT, output.resolve()), "iverilog_path": iverilog, "vvp_path": vvp, "timeout_seconds": 30}
    if profile in {"v2", "v3"}:
        options["capture_observations"] = True
        options["max_output_chars"] = 2_000_000
    if profile == "v3":
        options["reference_sampling"] = "per_cycle"
    try:
        for index, row in enumerate(report["rows"]):
            started = time.monotonic()
            row["started_at"] = datetime.now(timezone.utc).isoformat()
            provider = None
            work = output / f"sample-{index:03d}"
            work.mkdir()
            try:
                case = row["case"]
                contract_path = registered_source_path(row.get("contract_path", f"examples/{case}_contract.json"))
                reference_rtl = registered_source_path(row.get("reference_rtl", f"rtl/{case}.v"))
                contract = DutContract.from_dict(json.loads(contract_path.read_text(encoding="utf-8")))
                def audit(round_row):
                    plan = TestPlan.model_validate(round_row["plan"])
                    cycles = plan_cycles(plan.model_dump(mode="json")["vectors"])
                    actual_observation = dict(round_row["observation"])
                    pipeline_path = actual_observation.get("pipeline_result")
                    if not pipeline_path and round_row.get("pipeline_result"):
                        pipeline_path = str(work / "agent" / round_row["pipeline_result"])
                    if pipeline_path:
                        raw_result = json.loads(Path(pipeline_path).read_text(encoding="utf-8"))["simulation"]
                        actual_observation["checks"] = raw_result.get("summary", {}).get("checks", 0)
                        actual_observation["records"] = len(raw_result.get("records", []))
                        actual_observation["failure_cycles"] = [f["cycle"] for f in raw_result.get("failures", [])
                                                                 if isinstance(f.get("cycle"), int)]
                        actual_observation["pipeline_result"] = pipeline_path
                    if round_row.get("functional_coverage"):
                        actual_observation["functional_coverage"] = round_row["functional_coverage"]
                    if pipeline_path:
                        actual_observation["evidence_files"] = freeze_pipeline_evidence(pipeline_path)
                    previous_cycles = sum(r["cycles"] for r in row["rounds"])
                    entry = {"round": round_row["round"], "plan": plan.model_dump(mode="json"),
                             "actual": actual_observation, "cycles": cycles,
                             "cumulative_search_cycles": previous_cycles + cycles,
                             "remaining_search_cycles": row["budget_cycles"] - previous_cycles - cycles,
                             "vector_count": len(plan.vectors),
                             "checks_per_stimulus_cycle": (actual_observation.get("checks") or 0) / cycles,
                             "result_available_elapsed_seconds": round(time.monotonic() - started, 6),
                             "reference": {"status": "not_completed", "checks": 0, "failures": 0,
                                           "expectation_source": None}}
                    row["rounds"].append(entry)
                    row["reference_audit_cycles_attempted"] = row.get("reference_audit_cycles_attempted", 0) + cycles
                    save()
                    audit_started = time.monotonic()
                    try:
                        reference = runner.run(plan, contract, reference_rtl, work / f"audit-{round_row['round']}", **options)
                        entry["reference"] = observation(reference, capture_coverage=profile in {"v2", "v3"},
                                                         rtl_sha256=sha(reference_rtl))
                        entry["reference"]["evidence_files"] = freeze_pipeline_evidence(entry["reference"]["pipeline_result"])
                    finally:
                        entry["reference_audit_elapsed_seconds"] = round(time.monotonic() - audit_started, 6)
                    row["reference_audit_cycles"] = row.get("reference_audit_cycles", 0) + cycles
                    save()
                if row["strategy"] in BASELINES:
                    plan = (baseline_factory(case, row["strategy"], row["seed"], contract, row["budget_cycles"])
                            if baseline_factory else baseline_plan(case, row["strategy"], row["seed"], contract, row["budget_cycles"],
                                         profile=profile, protocol=protocols["cases"][case] if protocols else None))
                    vector_cap = registration.get("study", {}).get("limits", {}).get("max_vectors_per_proposal", 200)
                    if (not isinstance(plan, TestPlan) or plan.design != contract.module
                            or len(plan.vectors) > vector_cap
                            or plan_cycles(plan.model_dump(mode="json")["vectors"]) > row["budget_cycles"]):
                        raise ValueError("baseline proposal exceeds the registered contract or budget")
                    row["baseline_cycles_attempted"] = plan_cycles(plan.model_dump(mode="json")["vectors"])
                    save()
                    actual = runner.run(plan, contract, ROOT / row["rtl"], work / "run", **options)
                    audit({"round": 1, "plan": plan.model_dump(mode="json"),
                           "observation": observation(actual, capture_coverage=profile in {"v2", "v3"}, rtl_sha256=sha(ROOT / row["rtl"]))})
                    row["stop_reason"] = "single_run"
                else:
                    remaining = request_cap - report["requests_attempted"]
                    if remaining <= 0:
                        row["status"] = "global_request_budget"
                        continue
                    count = min(1 if row["strategy"] == "single" else 3, remaining)
                    provider = provider_factory(count) if provider_factory else OpenAICompatibleProvider(
                        endpoint=endpoint, model=model, api_key=key, allow_network=True, store=False,
                        reasoning_effort=None, thinking_mode=thinking_mode, timeout=60, stream=False, request_limit=count, wire_api=wire_api,
                        max_output_tokens=max_output_tokens, force_output_limit=True)
                    result = run_verification_agent(provider=provider, contract=contract, rtl_path=ROOT / row["rtl"],
                        output_dir=work / "agent", objective="Check contract behavior and protocol boundaries",
                        specification=(ROOT / protocols["cases"][case]["spec_path"]).read_text(encoding="utf-8") if protocols else "\n".join(line for line in (ROOT / "spec/common_cases.md").read_text(encoding="utf-8").splitlines() if f"`{case}.v`" in line),
                        include_feedback=row["strategy"] != "no_feedback",
                        include_functional_coverage=profile in {"v2", "v3"} and row["strategy"] not in {"no_feedback", "feedback_no_coverage"},
                        agent_plan_mode="independent" if profile == "v3" else "append",
                        limits=AgentLimits(max_rounds=1 if row["strategy"] == "single" else 3, max_requests=count,
                                           max_total_cycles=row["budget_cycles"], max_output_tokens=max_output_tokens),
                        execution_options=options, on_round=audit)
                    row["stop_reason"] = result.stop_reason
                    row["record_kind"] = result.trajectory["record_kind"]
                    row["agent_stimulus_cycles"] = result.trajectory["stimulus_cycles_executed"]
                    row["trajectory"] = str(result.trajectory_path)
                    row["usage_by_decision"] = decision_records(index, result.trajectory)
                    row["requests"] = result.trajectory["requests_attempted"]
                row["status"], row["detected"] = classify(row)
                if row["detected"]:
                    previous = 0
                    for entry in row["rounds"]:
                        if entry["actual"]["failures"]:
                            failure_cycles = entry["actual"].get("failure_cycles", [])
                            cycle = min(failure_cycles) if failure_cycles else None
                            row["first_detection_cycle"] = cycle
                            row["first_detection_search_budget"] = previous + cycle + 1 if cycle is not None else None
                            row["first_detection_available_elapsed_seconds"] = entry["result_available_elapsed_seconds"]
                            row["first_detection_round"] = entry["round"]
                            break
                        previous += entry["cycles"]
            except KeyboardInterrupt:
                row["status"] = "interrupted"
                raise
            except Exception as exc:
                row["status"] = "execution_error"
                row["error_type"] = type(exc).__name__
            finally:
                trace_path = work / "agent/agent_trajectory.json"
                if trace_path.is_file():
                    try:
                        trace = json.loads(trace_path.read_text(encoding="utf-8"))
                        row["agent_stimulus_cycles"] = trace["stimulus_cycles_executed"]
                        row["trajectory"] = str(trace_path)
                        row["trajectory_sha256"] = sha(trace_path)
                        row["requests"] = trace["requests_attempted"]
                        row["stop_reason"] = trace["stop_reason"]
                        row["usage_by_decision"] = decision_records(index, trace)
                    except (OSError, ValueError, KeyError) as exc:
                        row["trace_recovery_error_type"] = type(exc).__name__
                if provider is not None:
                    row["requests"] = int(getattr(provider, "request_count", row["requests"]))
                report["requests_attempted"] += row["requests"]
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                row["finished_at"] = datetime.now(timezone.utc).isoformat()
                row["audited_round_search_cycles"] = sum(r["cycles"] for r in row["rounds"])
                row["search_cycles"] = row.get("agent_stimulus_cycles", row["audited_round_search_cycles"])
                row["search_cycle_accounting_gap"] = row["search_cycles"] - row["audited_round_search_cycles"]
                row.setdefault("reference_audit_cycles", 0)
                row["requests_without_usage"] = max(0, row["requests"] - sum(bool(d["usage"]) for d in row.get("usage_by_decision", [])))
                save()
                print(json.dumps({k: row[k] for k in ("case", "variant", "strategy", "status", "requests")}), flush=True)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["changed_inputs_at_finish"] = [p for p, digest in registration["code_and_input_sha256"].items()
                                               if not (ROOT / p).is_file() or sha(ROOT / p) != digest]
        save()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--profile", choices=["legacy", "v2", "v3"], default="legacy")
    parser.add_argument("--strategies", nargs="+", choices=V2_STRATEGIES)
    parser.add_argument("--repeats", type=int, choices=range(1, 6))
    parser.add_argument("--defects-per-case", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--total-request-cap", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, choices=range(256, 8193), default=4096)
    parser.add_argument("--endpoint", default=os.getenv("IVERILOG_AI_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("IVERILOG_AI_MODEL", ""))
    parser.add_argument("--wire-api", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--thinking-mode", choices=["enabled", "disabled"], default=None)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--iverilog", default="D:/iverilog/bin/iverilog.exe")
    parser.add_argument("--vvp", default="D:/iverilog/bin/vvp.exe")
    args = parser.parse_args(argv)
    try:
        if args.wire_api == "responses" and args.thinking_mode is not None:
            raise ValueError("explicit thinking mode requires chat_completions")
        if args.total_request_cap < 0:
            raise ValueError("negative request cap")
        reg = preregister(args.cases, args.strategies, args.repeats, args.defects_per_case, profile=args.profile)
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "samples": len(reg["rows"]),
                          "theoretical_requests": reg["theoretical_requests"], "authorized_request_cap": args.total_request_cap,
                          "wire_api": args.wire_api, "thinking_mode": args.thinking_mode, "endpoint_host": urlsplit(args.endpoint).hostname,
                          "model": args.model, "max_output_tokens": args.max_output_tokens}))
        if not args.execute:
            return 0
        key = ""
        if reg["theoretical_requests"] and args.total_request_cap:
            url = urlsplit(args.endpoint)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or not args.model:
                raise ValueError("HTTPS endpoint and model required")
            key = read_key_file(args.api_key_file) if args.api_key_file else os.getenv("IVERILOG_AI_API_KEY", "")
            if not key:
                raise ValueError("credential missing")
        execute(reg, args.output_dir or ROOT / (f".iverilog-ai/agent-comparison-{args.profile}" if args.profile in {"v2", "v3"} else ".iverilog-ai/agent-comparison-pilot"), endpoint=args.endpoint, model=args.model, key=key,
                request_cap=args.total_request_cap, max_output_tokens=args.max_output_tokens,
                wire_api=args.wire_api, thinking_mode=args.thinking_mode, iverilog=args.iverilog, vvp=args.vvp)
        return 0
    except Exception as exc:
        print(f"Comparison failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
