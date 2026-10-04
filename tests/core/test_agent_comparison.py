import json
from pathlib import Path

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
