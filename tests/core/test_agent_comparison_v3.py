"""New sampling comparisons retain every row and freeze exact input bytes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_agent_comparison import ROOT, execute, main, preregister
from scripts.summarize_agent_comparison import build_summary, freeze_pipeline_evidence, verify_frozen_inputs


STRATEGIES = ("fixed", "random", "protocol_random", "feedback", "no_feedback")


def test_v3_explicit_scope_and_modes_before_any_request(tmp_path):
    reg = preregister(strategies=STRATEGIES, profile="v3")
    assert len(reg["rows"]) == 60
    assert reg["theoretical_requests"] == 72
    assert len(preregister(profile="v3")["rows"]) == 60
    assert reg["prompt_profile"]["reference_sampling"] == "per_cycle"
    assert reg["prompt_profile"]["agent_plan_mode"] == "independent"
    assert len(reg["contract_profile_sha256"]) == 4
    assert "docs/experiment/agent_comparison_v5_plan_2026-10-05.md" in reg["code_and_input_sha256"]
    output = tmp_path / "absent"
    assert main(["--profile", "v3", "--strategies", *STRATEGIES, "--api-key-file", str(tmp_path / "missing"),
                 "--output-dir", str(output)]) == 0
    assert not output.exists()


def test_v3_zero_budget_keeps_original_bytes_and_all_denominators(tmp_path):
    reg = preregister(cases=["handshake_stage"], strategies=["feedback"], profile="v3")
    output = tmp_path / "frozen"
    def forbidden(_):
        pytest.fail("zero budget created a provider")
    report = execute(reg, output, provider_factory=forbidden)
    assert report["requests_attempted"] == 0
    assert len(report["rows"]) == 3
    assert report["summary"]["feedback"]["registered_defect_samples"] == 2
    assert verify_frozen_inputs(report, reg, output)
    manifest = json.loads((output / "registered-inputs/manifest.json").read_text())
    for item in manifest["files"]:
        assert (output / item["copy"]).read_bytes() == (ROOT / item["path"]).read_bytes()
    target = output / manifest["files"][0]["copy"]
    target.write_bytes(target.read_bytes() + b"\n")
    assert not verify_frozen_inputs(report, reg, output)


@pytest.mark.parametrize("relative", ["../outside.txt", "C:/outside.txt", "C:outside.txt"])
def test_invalid_registered_path_is_rejected_before_hashing(monkeypatch, tmp_path, relative):
    reg = preregister(cases=["handshake_stage"], strategies=["fixed"], profile="v3")
    reg["code_and_input_sha256"] = {relative: "0" * 64}
    monkeypatch.setattr("scripts.run_agent_comparison.sha", lambda _: pytest.fail("unsafe path hashed"))
    with pytest.raises(ValueError, match="escapes"):
        execute(reg, tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


def test_v3_api_strategies_forward_independent_per_cycle(monkeypatch, tmp_path):
    calls = []
    def fake_agent(**kwargs):
        calls.append(kwargs)
        kwargs["provider"].request_count += 1
        return SimpleNamespace(stop_reason="model_stopped", trajectory_path=kwargs["output_dir"] / "agent_trajectory.json",
            trajectory={"record_kind": "test_provider", "stimulus_cycles_executed": 0,
                        "decisions": [{"usage": None}], "requests_attempted": 1})
    monkeypatch.setattr("scripts.run_agent_comparison.run_verification_agent", fake_agent)
    reg = preregister(cases=["handshake_stage"], strategies=["feedback", "no_feedback"],
                     defects_per_case=1, profile="v3")
    report = execute(reg, tmp_path / "profiles", request_cap=4,
                     provider_factory=lambda count: SimpleNamespace(request_count=0))
    assert report["requests_attempted"] == 4
    assert all(c["agent_plan_mode"] == "independent" for c in calls)
    assert all(c["execution_options"]["reference_sampling"] == "per_cycle" for c in calls)
    assert [(c["include_feedback"], c["include_functional_coverage"]) for c in calls[:2]] == [(True, True), (False, False)]


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_v3_real_baselines_use_equal_per_cycle_checks_and_verified_bindings(tmp_path):
    reg = preregister(cases=["handshake_stage"], strategies=["fixed", "random", "protocol_random"],
                     defects_per_case=1, profile="v3")
    output = tmp_path / "real"
    report = execute(reg, output, iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    summary = build_summary(report, reg, evidence_root=output)
    assert summary["eligible_for_frozen_comparison"], [(r["status"], r.get("evidence_error")) for r in summary["rows"]]
    assert report["requests_attempted"] == 0
    checks = set()
    for row in report["rows"]:
        entry = row["rounds"][0]
        checks.add(entry["actual"]["checks"])
        assert entry["cycles"] == 160
        assert entry["reference"]["failures"] == 0
        assert len(entry["plan"]["vectors"]) <= 200
        raw = json.loads(Path(entry["actual"]["pipeline_result"]).read_text())
        assert raw["simulation"]["config"]["reference_sampling"] == "per_cycle"
        packet = Path(raw["artifacts"]["reference_samples"])
        assert hashlib.sha256(packet.read_bytes()).hexdigest() == raw["simulation"]["config"]["oracle"]["reference_samples"]["sha256"]
    assert len(checks) == 1
    assert not build_summary(report, reg)["eligible_for_frozen_comparison"]
    damaged = json.loads(json.dumps(report))
    observed = damaged["rows"][0]["rounds"][0]["actual"]
    raw = json.loads(Path(observed["pipeline_result"]).read_text())
    raw["simulation"]["failures"].append({"test_id": "invented", "cycle": 0, "signal": "out_valid",
        "expected": "0", "actual": "1", "message": "must not count without a real RESULT", "severity": "warn"})
    fake = output / "tampered-pipeline-result.json"
    fake.write_text(json.dumps(raw), encoding="utf-8")
    observed.update(pipeline_result=str(fake), failures=1, failure_cycles=[0],
                    evidence_files=freeze_pipeline_evidence(str(fake)))
    checked = build_summary(damaged, reg, evidence_root=output)
    assert checked["rows"][0]["evidence_error"] == "failures_disagree_with_actual_records"
    assert not checked["rows"][0]["detected"]
    assert not checked["eligible_for_frozen_comparison"]
