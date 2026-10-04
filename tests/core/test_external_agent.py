"""External evidence adapter: synthetic parser checks and real local Icarus replay.

No live API, no new RTL defects, no human-trial evidence.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import json
import shutil
import pytest
from iverilog_ai.ai.schema import TestPlan

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("external_agent", ROOT / "scripts/run_external_verification_agent.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
MANIFEST = ROOT / ".iverilog-ai/external/frozen-20261004-ic/manifest.json"
HISTORY = ROOT / ".iverilog-ai/external/uart_rx_check"
IVERILOG = shutil.which("iverilog") or ("D:/iverilog/bin/iverilog.exe" if Path("D:/iverilog/bin/iverilog.exe").exists() else None)
VVP = shutil.which("vvp") or ("D:/iverilog/bin/vvp.exe" if Path("D:/iverilog/bin/vvp.exe").exists() else None)


def row(outputs, cycle=0, time=10):
    return {"cycle": cycle, "time_ns": time, "outputs": outputs}


def test_only_qualified_outputs_are_compared_and_invalid_payload_is_masked():
    left = row({"m_axis_tdata": 13, "m_axis_tvalid": 0, "frame_error": 0, "busy": 0, "internal": 10})
    right = row({**left["outputs"], "m_axis_tdata": 47, "internal": 99})
    result = adapter.compare_samples([left], [right], "uart_rx")
    assert result["differences"] == 0 and result["compared_samples"] == 3
    left["outputs"]["m_axis_tvalid"] = right["outputs"]["m_axis_tvalid"] = 1
    assert adapter.compare_samples([left], [right], "uart_rx")["differences"] == 1


@pytest.mark.parametrize("reference,candidate", [([], []), ([row({})], []), ([row({})], [row({}, time=11)])])
def test_missing_or_misaligned_samples_are_inconclusive(reference, candidate):
    with pytest.raises(ValueError):
        adapter.compare_samples(reference, candidate, "uart_rx")


@pytest.mark.parametrize("module,tag,verdict", [
    ("uart_rx", "baseline", "no_observed_difference"),
    ("uart_rx", "equivalent_rewrite", "no_observed_difference"),
    ("uart_rx", "mut_bit_order", "behavior_difference"),
    ("uart_rx", "broken_compile", "inconclusive"),
    ("uart_tx", "baseline", "no_observed_difference"),
    ("priority_encoder", "baseline", "no_observed_difference"),
])
def test_real_icarus_existing_sources(tmp_path, module, tag, verdict):
    if not MANIFEST.exists() or not IVERILOG or not VVP:
        pytest.skip("requires separately frozen historical inputs and local Icarus")
    candidate = HISTORY / f"{module}_{tag}.v"
    if not candidate.exists():
        pytest.skip("historical candidate unavailable")
    runner = adapter.FrozenExternalRunner(manifest=MANIFEST, candidate=candidate, module=module,
        output_dir=tmp_path / "qualification", iverilog=IVERILOG, vvp=VVP)
    assert runner.qualification["status"] == "qualified"
    plan = TestPlan.model_validate(adapter.harness.MODULES[module]["plan"]())
    actual = runner.run(plan, runner.contract, runner.candidate, tmp_path / "round")
    observation = runner.observe(actual).model_dump()
    assert observation["verdict"] == verdict
    assert observation["expectation_source"] == "qualified_baseline_differential"
    assert observation["checks"] == observation["failures"] == 0
    assert observation["candidate_stimulus_cycles"] == observation["baseline_stimulus_cycles"]
    # Original pipeline remains honest: no authoritative expected checks were supplied.
    assert actual.simulation.config.get("oracle", {}).get("expectation_source") != "reference_model"
    if verdict != "inconclusive":
        assert observation["compared_samples"] > 0
    if tag == "mut_bit_order":
        assert observation["difference_samples"][0]["signal"] == "m_axis_tdata"
        assert observation["difference_samples"][0]["baseline"] == 0x96
        assert observation["difference_samples"][0]["candidate"] == 0x69


def test_parser_rejects_missing_snapshot(tmp_path):
    log = tmp_path / "missing.log"
    log.write_text("no sample lines\n")
    contract = adapter.DutContract.from_dict(adapter.harness.CONTRACT)
    with pytest.raises(ValueError, match="sample count"):
        adapter.samples_from_log(log, contract, 1)


def test_existing_output_is_refused_before_api_or_simulation(tmp_path):
    output = tmp_path / "exists"
    output.mkdir()
    assert adapter.main(["--manifest", "missing.json", "--candidate", "missing.v", "--module", "uart_rx",
                         "--output-dir", str(output)]) == 2


@pytest.mark.parametrize("budget,expected_calls,stop", [(364, 0, "cycle_budget"), (1200, 1, "round_budget")])
def test_shared_agent_loop_with_mock_http_real_icarus(tmp_path, monkeypatch, budget, expected_calls, stop):
    """Mocked transport only: these records are not real provider performance evidence."""
    from types import SimpleNamespace
    if not MANIFEST.exists() or not IVERILOG or not VVP:
        pytest.skip("requires frozen historical inputs and local Icarus")
    calls = []
    action = {"action": "append_vectors", "reason": "offline mocked idle extension", "vectors": [
        {"name": "idle_more", "inputs": {"rxd": 1, "m_axis_tready": 1}, "cycles": 2, "sample_phase": "after"}]}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(action)}, "finish_reason": "stop"}]}).encode()
    def request(req, timeout):
        calls.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    provider = adapter.OpenAICompatibleProvider(endpoint="https://api.example/v1", model="mock-network",
        api_key="test-secret", allow_network=True, wire_api="chat_completions", stream=False)
    runner = adapter.FrozenExternalRunner(manifest=MANIFEST, candidate=HISTORY / "uart_rx_baseline.v", module="uart_rx",
        output_dir=tmp_path / "qualification", iverilog=IVERILOG, vvp=VVP)
    plan = TestPlan.model_validate(adapter.harness.build_plan())
    result = adapter.run_verification_agent(provider=provider, contract=runner.contract, rtl_path=runner.candidate,
        output_dir=tmp_path / "agent", objective="mock network integration; not live API evidence", initial_plan=plan,
        limits=adapter.AgentLimits(max_rounds=2, max_requests=1, max_total_cycles=budget), pipeline=runner,
        round_observer=runner.observe, simulation_multiplier=2)
    assert result.stop_reason == stop
    assert len(calls) == expected_calls
    assert result.trajectory["stimulus_cycles_executed"] == (732 if expected_calls else 364)
    assert result.trajectory["rounds"][0]["observation"]["expectation_source"] == adapter.EVIDENCE_KIND
    assert "test-secret" not in result.trajectory_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("output,expected_count,raises", [("1", 1, False), ("x", 1, True), ("1", 2, True)])
def test_exact_snapshot_parser_and_unknowns(tmp_path, output, expected_count, raises):
    log = tmp_path / "synthetic-parser-fixture.log"
    log.write_text("ICARUS_EXTERNAL_SAMPLE 0 16.000 " + output + " 0\n")
    contract = adapter.DutContract.from_dict(adapter.harness.TX_CONTRACT)
    if raises:
        with pytest.raises(ValueError):
            adapter.samples_from_log(log, contract, expected_count)
    else:
        samples = adapter.samples_from_log(log, contract, expected_count)
        assert samples == [{"cycle": 0, "time_ns": 16, "outputs": {"txd": 1, "busy": 0}}]


@pytest.mark.parametrize("tamper", ["candidate", "qualification"])
def test_changed_frozen_evidence_is_rejected_before_execution(tmp_path, monkeypatch, tamper):
    if not MANIFEST.exists() or not IVERILOG or not VVP:
        pytest.skip("requires frozen historical inputs and local Icarus")
    runner = adapter.FrozenExternalRunner(manifest=MANIFEST, candidate=HISTORY / "uart_rx_baseline.v", module="uart_rx",
        output_dir=tmp_path / "qualification", iverilog=IVERILOG, vvp=VVP)
    original_sha = adapter.sha
    target = runner.candidate if tamper == "candidate" else runner.qualification_path
    monkeypatch.setattr(adapter, "sha", lambda path: "0" * 64 if path == target else original_sha(path))
    plan = TestPlan.model_validate(adapter.harness.build_plan())
    with pytest.raises(ValueError, match="changed"):
        runner.run(plan, runner.contract, runner.candidate, tmp_path / "round")
    assert not (tmp_path / "round").exists()


def test_missing_qualification_summary_is_not_qualified(tmp_path, monkeypatch):
    from subprocess import CompletedProcess
    if not MANIFEST.exists():
        pytest.skip("requires frozen historical inputs")
    monkeypatch.setattr(adapter.subprocess, "run", lambda *a, **k: CompletedProcess([], 0, "", ""))
    runner = adapter.FrozenExternalRunner(manifest=MANIFEST, candidate=HISTORY / "uart_rx_baseline.v", module="uart_rx",
        output_dir=tmp_path / "qualification", iverilog="mock-compiler", vvp="mock-runtime")
    assert runner.qualification["status"] == "inconclusive"
    assert runner.qualification["checks"] == 0


@pytest.mark.parametrize("module,phase", [("priority_encoder", "after"), ("priority_encoder", "before"), ("uart_rx", "before")])
def test_real_snapshot_phase_and_consecutive_combination_inputs(tmp_path, module, phase):
    if not MANIFEST.exists() or not IVERILOG or not VVP:
        pytest.skip("requires frozen historical inputs and local Icarus")
    runner = adapter.FrozenExternalRunner(manifest=MANIFEST, candidate=HISTORY / f"{module}_baseline.v", module=module,
        output_dir=tmp_path / "qualification", iverilog=IVERILOG, vvp=VVP)
    data = adapter.harness.MODULES[module]["plan"]()
    for vector in data["vectors"]:
        vector["sample_phase"] = phase
    plan = TestPlan.model_validate(data)
    actual = runner.run(plan, runner.contract, runner.candidate, tmp_path / "round")
    assert runner.observe(actual).verdict == "no_observed_difference"
    samples = json.loads((tmp_path / "round/baseline_samples.json").read_text(encoding="utf-8"))
    assert len(samples) == sum(v.cycles for v in plan.vectors)
    if module == "priority_encoder":
        for value, sample in enumerate(samples):
            outputs = sample["outputs"]
            assert outputs["output_valid"] == bool(value)
            if value:
                winner = value.bit_length() - 1
                assert outputs["output_encoded"] == winner
                assert outputs["output_unencoded"] == 1 << winner
        assert samples[0]["outputs"]["output_valid"] == 0  # old final-VCD method returned 1
    else:
        assert samples[0]["time_ns"] == 28.0  # #1 before sampling, after reset release at 27ns
    evidence = json.loads((tmp_path / "round/baseline/snapshot_instrumentation.json").read_text(encoding="utf-8"))
    assert evidence["anchor_count"] == len(samples)
    assert evidence["assertions_added"] == 0


def test_instrumentation_fails_closed_when_anchor_changes(tmp_path, monkeypatch):
    original = adapter.TestbenchGenerator._render
    def changed(*args, **kwargs):
        return original(*args, **kwargs).replace("    cycle = cycle + 1;", "    cycle=cycle+1;")
    monkeypatch.setattr(adapter.TestbenchGenerator, "_render", changed)
    contract = adapter.DutContract.from_dict(adapter.harness.CONTRACT)
    plan = TestPlan.model_validate(adapter.harness.build_plan())
    with pytest.raises(adapter.TestbenchGenerationError, match="anchor"):
        adapter.SnapshotGenerator().generate(plan, contract, tmp_path)
