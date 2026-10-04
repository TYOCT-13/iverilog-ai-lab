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


@pytest.mark.parametrize("wire_api,route", [("chat_completions", "/chat/completions"), ("responses", "/responses")])
def test_real_provider_transport_uses_frozen_protocol(tmp_path, monkeypatch, wire_api, route):
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
        calls.append((req.full_url, json.loads(req.data)))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    reg = preregister(cases=["handshake_stage"], strategies=["single"], defects_per_case=1)
    kwargs = {} if wire_api == "chat_completions" else {"wire_api": wire_api}
    report = execute(reg, output, endpoint="https://api.example/v1", model="transport-test", key="fake-credential",
                     request_cap=1, max_output_tokens=256, **kwargs)
    assert len(calls) == 1 and calls[0][0].endswith(route)
    assert report["wire_api"] == wire_api
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
