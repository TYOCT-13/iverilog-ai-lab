import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_agent_comparison import (ROOT, baseline_plan, classify, execute, main, preregister, summarize)
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.strategy_scoring import plan_cycles


def test_default_preregistration_is_fixed_before_results():
    reg = preregister()
    assert len(reg["rows"]) == 60
    assert reg["theoretical_requests"] == 84
    assert all(r["status"] == "not_started" for r in reg["rows"])
    assert len({(r["case"], r["variant"]) for r in reg["rows"] if r["variant"] != "reference"}) == 8
    assert "src/iverilog_ai/ai/agent.py" in reg["code_and_input_sha256"]


def test_dry_run_does_not_read_key_or_create_output(tmp_path):
    output = tmp_path / "output"
    assert main(["--api-key-file", str(tmp_path / "missing"), "--output-dir", str(output)]) == 0
    assert not output.exists()


def test_responses_thinking_mode_rejected_before_output_or_key_read(tmp_path):
    folder = tmp_path / "absent"
    reg = preregister(cases=["handshake_stage"], strategies=["single"], defects_per_case=1)
    with pytest.raises(ValueError, match="chat_completions"):
        execute(reg, folder, wire_api="responses", thinking_mode="disabled")
    assert not folder.exists()
    assert main(["--wire-api", "responses", "--thinking-mode", "enabled",
                 "--api-key-file", str(tmp_path / "no-key"), "--output-dir", str(folder)]) == 2
    assert not folder.exists()


@pytest.mark.parametrize("wire_api,route,thinking_mode", [
    ("chat_completions", "/chat/completions", None),
    ("chat_completions", "/chat/completions", "enabled"),
    ("chat_completions", "/chat/completions", "disabled"),
    ("responses", "/responses", None)])
def test_real_provider_transport_uses_frozen_protocol(tmp_path, monkeypatch, wire_api, route, thinking_mode):
    calls = []
    output = tmp_path / wire_api
    stop = json.dumps({"action": "stop", "reason": "transport test", "vectors": []})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps({"choices": [{"message": {"content": stop}}], "output_text": stop,
                               "usage": {"prompt_tokens": 13, "completion_tokens": 5}}).encode()
    def request(req, timeout):
        settings = json.loads((output / "run_settings.json").read_text())
        assert settings["wire_api"] == wire_api
        assert settings["endpoint_host"] == "api.example"
        assert settings["model"] == "transport-test"
        assert settings["total_request_cap"] == 1
        assert settings["max_output_tokens"] == 256
        assert settings["thinking_mode"] == thinking_mode
        assert settings["thinking_mode_meaning"] == ("unspecified_provider_default" if thinking_mode is None else "explicit_request")
        calls.append((req.full_url, json.loads(req.data)))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    reg = preregister(cases=["handshake_stage"], strategies=["single"], defects_per_case=1)
    kwargs = {} if wire_api == "chat_completions" else {"wire_api": wire_api}
    report = execute(reg, output, endpoint="https://api.example/v1", model="transport-test", key="fake-credential",
                     request_cap=1, max_output_tokens=256, thinking_mode=thinking_mode, **kwargs)
    assert len(calls) == 1 and calls[0][0].endswith(route)
    assert report["wire_api"] == wire_api
    assert report["thinking_mode"] == thinking_mode
    if thinking_mode is None:
        assert "thinking" not in calls[0][1]
    else:
        assert calls[0][1]["thinking"] == {"type": thinking_mode}
    assert report["run_settings_sha256"] == hashlib.sha256((output / "run_settings.json").read_bytes()).hexdigest()
    assert report["requests_attempted"] == 1
    assert report["rows"][0]["requests_without_usage"] == 0
    assert "fake-credential" not in (output / "run_settings.json").read_text()


def test_interrupted_engine_recovers_trace_costs(tmp_path, monkeypatch):
    def interrupted(**kwargs):
        folder = kwargs["output_dir"]
        folder.mkdir()
        (folder / "agent_trajectory.json").write_text(json.dumps({"stimulus_cycles_executed": 7,
            "requests_attempted": 1, "stop_reason": "interrupted", "decisions": [{"usage": {"total_tokens": 42}}]}))
        raise KeyboardInterrupt
    monkeypatch.setattr("scripts.run_agent_comparison.run_verification_agent", interrupted)
    reg = preregister(cases=["handshake_stage"], strategies=["single"], defects_per_case=1)
    output = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        execute(reg, output, request_cap=1, provider_factory=lambda count: SimpleNamespace(request_count=1))
    report = json.loads((output / "results.json").read_text())
    assert report["requests_attempted"] == 1
    row = report["rows"][0]
    assert row["status"] == "interrupted"
    assert row["search_cycles"] == 7 and row["search_cycle_accounting_gap"] == 7
    assert row["reference_audit_cycles"] == 0
    assert row["usage_by_decision"][0]["usage"]["total_tokens"] == 42
    assert report["rows"][1]["status"] == "not_started"


@pytest.mark.parametrize("case,cycles", [("sync_fifo", 40), ("uart_tx", 40), ("spi_master", 64), ("handshake_stage", 24)])
def test_baselines_have_same_budget_and_random_reproducible(case, cycles):
    contract = DutContract.from_dict(json.loads((ROOT / f"examples/{case}_contract.json").read_text()))
    for strategy in ("fixed", "random"):
        plan = baseline_plan(case, strategy, 7, contract, cycles)
        assert plan_cycles(plan.model_dump(mode="json")["vectors"]) == cycles
        assert plan == baseline_plan(case, strategy, 7, contract, cycles)
        assert all(not v.expected for v in plan.vectors)


def test_false_alarm_and_compile_failure_never_count_as_detection():
    good = {"status": "passed", "checks": 20, "failures": 0, "expectation_source": "reference_model"}
    row = {"variant": "bug", "rounds": [{"actual": {**good, "failures": 4}, "reference": good}]}
    assert classify(row) == ("detected", True)
    row["rounds"][0]["reference"] = {**good, "failures": 1}
    assert classify(row) == ("reference_false_alarm", False)
    row["rounds"][0] = {"actual": {**good, "status": "compile_failed"}, "reference": good}
    assert classify(row) == ("compile_failed", False)


def test_unique_defects_and_incomplete_denominator():
    reg = preregister(cases=["sync_fifo"], strategies=["fixed"], repeats=2)
    rows = reg["rows"]
    for r in rows:
        if r["variant"] != "reference":
            r["detected"] = True
            r["status"] = "detected"
            r["rounds"] = [{"actual": {"status": "passed", "checks": 1, "failures": 1, "expectation_source": "reference_model"},
                             "reference": {"status": "passed", "checks": 1, "failures": 0, "expectation_source": "reference_model"}}]
    rows[-1]["status"] = "not_started"
    rows[-1]["detected"] = False
    summary = summarize(rows)["fixed"]
    assert summary["registered_defect_samples"] == 4
    assert summary["unique_detected"] == 2
    assert summary["detected_samples"] == 3
    assert summary["incomplete_or_undecidable"] == 1


def test_zero_global_budget_preserves_missing_without_provider(tmp_path):
    reg = preregister(cases=["sync_fifo"], strategies=["feedback"])
    def forbidden(count):
        raise AssertionError("network must not run")
    report = execute(reg, tmp_path / "zero", request_cap=0, provider_factory=forbidden)
    assert all(r["status"] == "global_request_budget" for r in report["rows"])
    assert report["summary"]["feedback"]["registered_defect_samples"] == 2
    assert report["requests_attempted"] == 0
    assert (tmp_path / "zero/preregistration.json").exists()


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_scripted_agent_cap_and_no_feedback_are_recorded(tmp_path):
    class Scripted:
        request_count = 0
        def generate(self, prompt):
            self.request_count += 1
            return json.dumps({"action": "append_vectors", "reason": "test only", "vectors": [
                {"name": "one", "inputs": {"in_valid": 0, "out_ready": 0, "in_data": 0}, "cycles": 1}]})
    reg = preregister(cases=["handshake_stage"], strategies=["no_feedback"], defects_per_case=1)
    report = execute(reg, tmp_path / "mock", request_cap=1, provider_factory=lambda count: Scripted(),
                     iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    assert report["requests_attempted"] == 1
    assert report["record_kind"] == "test_provider"
    assert report["rows"][1]["status"] == "global_request_budget"
    trace = json.loads(Path(report["rows"][0]["trajectory"]).read_text(encoding="utf-8"))
    assert trace["feedback_enabled"] is False
    assert report["changed_inputs_at_finish"] == []


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_actual_icarus_baseline_audit_and_artifacts(tmp_path):
    reg = preregister(cases=["handshake_stage"], strategies=["fixed", "random"], defects_per_case=1)
    report = execute(reg, tmp_path / "real", iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    assert report["requests_attempted"] == 0
    assert all(r["status"] in {"detected", "not_detected"} for r in report["rows"])
    assert all(r["search_cycles"] == 24 and r["reference_audit_cycles"] == 24 for r in report["rows"])
    assert all(r["rounds"][0]["reference"]["failures"] == 0 for r in report["rows"])
    with pytest.raises(FileExistsError):
        execute(reg, tmp_path / "real")


def test_v2_registration_freezes_protocol_and_keeps_legacy_budget():
    old = preregister()
    new = preregister(profile="v2")
    assert len(old["rows"]) == 60 and old["theoretical_requests"] == 84
    assert len(new["rows"]) == 252 and new["theoretical_requests"] == 360
    assert new["independent_holdout"] is False
    assert {r["budget_cycles"] for r in old["rows"] if r["case"] == "uart_tx"} == {40}
    assert {r["budget_cycles"] for r in new["rows"] if r["case"] == "uart_tx"} == {512}
    assert "spec/agent_protocols.json" in new["code_and_input_sha256"]
    assert "spec/uart_tx_spec.md" in new["code_and_input_sha256"]
    assert len(new["prompt_profile_sha256"]) == 64
    assert "benchmarks/agent_v2/mutation_manifest.json" in new["code_and_input_sha256"]
    assert all(r["rtl"].startswith("benchmarks/agent_v2/") for r in new["rows"]
               if r["case"] == "sync_fifo" and r["variant"] != "reference")
    assert all(r["rtl"].startswith("rtl/") for r in old["rows"] if r["case"] == "sync_fifo")


def test_v2_dry_run_does_not_read_secret_or_create_directory(tmp_path):
    folder = tmp_path / "absent"
    assert main(["--profile", "v2", "--thinking-mode", "disabled", "--api-key-file", str(tmp_path / "no-key"), "--output-dir", str(folder)]) == 0
    assert not folder.exists()


@pytest.mark.parametrize("case", ["sync_fifo", "uart_tx", "spi_master", "handshake_stage"])
def test_v2_protocol_and_uniform_random_exact_budget(case):
    from scripts.run_agent_comparison import protocol_config
    config = protocol_config()["cases"][case]
    contract = DutContract.from_dict(json.loads((ROOT / f"examples/{case}_contract.json").read_text()))
    for strategy in ["protocol_random", "random"]:
        plan = baseline_plan(case, strategy, 2, contract, config["cycle_budget"], profile="v2", protocol=config)
        assert sum(v.cycles for v in plan.vectors) == config["cycle_budget"]
        assert len(plan.vectors) <= 200
        assert all(v.sample_phase == "after" and not v.expected for v in plan.vectors)
        assert plan == baseline_plan(case, strategy, 2, contract, config["cycle_budget"], profile="v2", protocol=config)


def test_protocol_uart_preserves_complete_frames_and_has_no_labels():
    from scripts.run_agent_comparison import protocol_config, protocol_random_vectors
    config = protocol_config()["cases"]["uart_tx"]
    contract = DutContract.from_dict(json.loads((ROOT / "examples/uart_tx_contract.json").read_text()))
    vectors = protocol_random_vectors("uart_tx", 0, contract, 512, config)
    # Every data bit and stop bit is sampled; don't only check final idle.
    frame_vectors = 14
    blocks = (len(vectors) - 1) // frame_vectors
    assert blocks >= 2
    for offset in range(0, blocks * frame_vectors, frame_vectors):
        frame = vectors[offset:offset + frame_vectors]
        assert [v["cycles"] for v in frame] == [1, 1, 2] + [4] * 9 + [1, 1]
        assert [v["inputs"]["start"] for v in frame] == [1, 1] + [0] * 12
    assert vectors[-1]["inputs"]["start"] == 0


def test_changed_registration_refused_before_directory_or_provider(tmp_path):
    reg = preregister(cases=["handshake_stage"], strategies=["single"])
    reg["code_and_input_sha256"]["scripts/run_agent_comparison.py"] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        execute(reg, tmp_path / "no-create", request_cap=1)
    assert not (tmp_path / "no-create").exists()


def test_v2_api_profiles_forward_full_spec_and_coverage_ablation(tmp_path, monkeypatch):
    calls = []
    def fake_agent(**kwargs):
        calls.append(kwargs)
        kwargs["provider"].request_count += 1
        return SimpleNamespace(stop_reason="model_stopped", trajectory_path=kwargs["output_dir"] / "agent_trajectory.json",
            trajectory={"record_kind": "test_provider", "stimulus_cycles_executed": 0,
                        "decisions": [{"usage": None}], "requests_attempted": 1})
    monkeypatch.setattr("scripts.run_agent_comparison.run_verification_agent", fake_agent)
    reg = preregister(cases=["handshake_stage"], strategies=["single", "feedback", "no_feedback", "feedback_no_coverage"],
                     repeats=1, defects_per_case=1, profile="v2")
    result = execute(reg, tmp_path / "profiles", request_cap=8,
                     provider_factory=lambda count: SimpleNamespace(request_count=0))
    assert result["requests_attempted"] == 8
    assert [(c["include_feedback"], c["include_functional_coverage"]) for c in calls[:4]] == [
        (True, True), (True, True), (False, False), (True, False)]
    full_spec = (ROOT / "spec/handshake_stage_spec.md").read_text(encoding="utf-8")
    assert all(c["specification"] == full_spec for c in calls)
    assert all(c["execution_options"]["capture_observations"] for c in calls)
    assert all(c["limits"].max_total_cycles == 160 for c in calls)


def test_v2_missing_profile_never_silently_uses_legacy(monkeypatch):
    def missing():
        raise FileNotFoundError("test missing configuration")
    monkeypatch.setattr("scripts.run_agent_comparison.protocol_config", missing)
    with pytest.raises(FileNotFoundError):
        preregister(profile="v2")
    assert len(preregister()["rows"]) == 60

@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
@pytest.mark.parametrize("case", ["sync_fifo", "uart_tx", "spi_master", "handshake_stage"])
def test_v2_real_protocol_baseline_has_measured_coverage(tmp_path, case):
    from scripts.summarize_agent_comparison import build_summary
    reg = preregister(cases=[case], strategies=["protocol_random"], repeats=1, defects_per_case=1, profile="v2")
    report = execute(reg, tmp_path / case, iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    assert report["requests_attempted"] == 0
    assert report["changed_inputs_at_finish"] == []
    summary = build_summary(report, reg)
    assert summary["eligible_for_frozen_comparison"]
    assert all(r["evidence_verified"] for r in summary["rows"])
    for row in report["rows"]:
        assert row["status"] in {"detected", "not_detected"}
        assert row["search_cycles"] == row["budget_cycles"]
        entry = row["rounds"][0]
        assert entry["reference"]["failures"] == 0
        assert entry["reference"]["functional_coverage"]["status"] == "measured"
        assert entry["actual"]["functional_coverage"]["status"] == "measured"
        assert entry["actual"]["checks"] > 0
        if row["detected"]:
            assert row["first_detection_cycle"] >= 0
            assert row["first_detection_search_budget"] == row["first_detection_cycle"] + 1
            detection = summary["strategies"]["protocol_random"]["first_detection"][0]
            assert detection["elapsed_seconds"] is None
            assert detection["result_available_elapsed_seconds"] == row["first_detection_available_elapsed_seconds"]
    damaged = json.loads(json.dumps(report))
    damaged["rows"][-1]["rounds"][0]["actual"]["failures"] += 1
    assert not build_summary(damaged, reg)["eligible_for_frozen_comparison"]
    assert not build_summary(damaged, reg)["rows"][-1]["detected"]
    conflicting = json.loads(json.dumps(report))
    conflicting["rows"][-1].update(status="compile_failed", detected=True)
    assert not build_summary(conflicting, reg)["rows"][-1]["detected"]
    assert not build_summary(conflicting, reg)["eligible_for_frozen_comparison"]
    evidence = Path(report["rows"][-1]["rounds"][0]["actual"]["pipeline_result"])
    evidence.write_bytes(evidence.read_bytes() + b" ")
    assert not build_summary(report, reg)["eligible_for_frozen_comparison"]
