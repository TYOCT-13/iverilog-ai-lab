"""New-module comparison never selects tasks using model outcomes or drops failures."""
import copy
import json
from pathlib import Path

import pytest

from iverilog_ai.core.contracts import DutContract
from scripts import run_agent_holdout_study as study
from scripts.run_agent_comparison import execute
from scripts.summarize_agent_comparison import build_summary


def contract(case):
    return DutContract.from_dict(json.loads((study.ROOT / f"examples/{case}_contract.json").read_text(encoding="utf-8")))


def test_registration_is_disjoint_full_and_prompt_frozen():
    reg = study.preregister_holdout()
    assert len(reg["rows"]) == 108 and reg["theoretical_requests"] == 126
    assert {row["case"] for row in reg["rows"]} == set(study.CASES)
    assert reg["scope"] == "post_freeze_new_synthetic_modules_internal_holdout"
    assert reg["external_independent_holdout"] is False
    for strategy in study.STRATEGIES:
        rows = [row for row in reg["rows"] if row["strategy"] == strategy]
        assert len(rows) == 18 and sum(row["variant"] != "reference" for row in rows) == 12
        assert {row["seed"] for row in rows} == {0, 1, 2}
        assert all(row["budget_cycles"] == 16 for row in rows)
    assert "src/iverilog_ai/ai/agent.py" in reg["code_and_input_sha256"]
    assert reg["code_and_input_sha256"]["src/iverilog_ai/ai/agent.py"] == reg["study"]["limits"]["agent_sha256"]
    assert reg["prompt_profile"]["reference_sampling"] == "per_cycle"


def test_dry_run_never_reads_key_or_creates_output(monkeypatch, tmp_path):
    destination = tmp_path / "absent"
    monkeypatch.setattr(study, "OUTPUT", destination)
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dry run read credentials"))
    assert study.main(["--api-key-file", str(tmp_path / "missing")]) == 0
    assert not destination.exists()


@pytest.mark.parametrize("case", study.CASES)
@pytest.mark.parametrize("strategy", ["fixed", "random", "protocol_random"])
def test_baselines_are_deterministic_bounded_and_expectation_free(case, strategy):
    dut = contract(case)
    for seed in (0, 1, 2):
        first = study.holdout_baseline(case, strategy, seed, dut, 16)
        assert first == study.holdout_baseline(case, strategy, seed, dut, 16)
        assert sum(vector.cycles for vector in first.vectors) == 16
        assert 1 <= len(first.vectors) <= 12
        allowed = {port.name for port in dut.inputs} - {"clk", "rst_n"}
        for vector in first.vectors:
            assert set(vector.inputs) == allowed and not vector.expected
            assert vector.sample_phase == "after"


@pytest.mark.parametrize("cycles", [0, 15, 17, 100000])
def test_baselines_cannot_silently_use_a_different_budget(cycles):
    with pytest.raises(ValueError, match="scope"):
        study.holdout_baseline("credit_guard", "fixed", 0, contract("credit_guard"), cycles)


@pytest.mark.parametrize("field,value", [("repeats", 3.0), ("registered_rows", 108.0),
                                        ("token_cap", True), ("max_output_tokens_per_request", 4096.0)])
def test_configuration_types_cannot_change_frozen_limits(monkeypatch, tmp_path, field, value):
    config = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    config[field] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="scope"):
        study.preregister_holdout()


def test_unregistered_override_is_rejected_before_any_output(tmp_path):
    reg = study.preregister_holdout()
    for field in ("contract_path", "reference_rtl"):
        changed = copy.deepcopy(reg)
        changed["rows"][0][field] = "../outside.txt"
        destination = tmp_path / field
        with pytest.raises(ValueError, match="not registered"):
            execute(changed, destination)
        assert not destination.exists()


def test_zero_api_budget_preserves_all_new_module_denominators(tmp_path):
    reg = study.preregister_holdout()
    reg["rows"] = [row for row in reg["rows"] if row["strategy"] not in {"fixed", "random", "protocol_random"}]
    destination = tmp_path / "zero"
    def forbidden(_):
        pytest.fail("zero request cap initialized provider")
    report = execute(reg, destination, request_cap=0, provider_factory=forbidden)
    summary = build_summary(report, reg, evidence_root=destination)
    assert report["requests_attempted"] == 0 and len(report["rows"]) == 54
    assert summary["frozen_input_snapshot_verified"]
    assert not summary["eligible_for_frozen_comparison"]
    assert all(summary["strategies"][key]["registered_defect_samples"] == 12
               for key in ("single", "feedback", "no_feedback"))
    assert summary["scope"] == reg["scope"]


@pytest.mark.parametrize("violation", ["cycles", "vectors", "design"])
def test_custom_baseline_budget_violations_never_reach_dut(monkeypatch, tmp_path, violation):
    reg = study.preregister_holdout()
    reg["rows"] = [next(row for row in reg["rows"] if row["strategy"] == "fixed")]
    def forbidden(*args, **kwargs):
        pytest.fail("invalid baseline executed the DUT")
    monkeypatch.setattr("scripts.run_agent_comparison.VerificationPipeline.run", forbidden)
    def invalid(case, strategy, seed, dut, cycles):
        payload = study.holdout_baseline(case, strategy, seed, dut, cycles).model_dump(mode="json")
        if violation == "cycles":
            payload["vectors"][0]["cycles"] += 1
        elif violation == "vectors":
            payload["vectors"] = [{"name": f"v{i}", "inputs": {"acquire": 0, "release_req": 0},
                                  "cycles": 1, "expected": {}} for i in range(13)]
        else:
            payload["design"] = "another_design"
        return study.TestPlan.model_validate(payload)
    report = execute(reg, tmp_path / violation, baseline_factory=invalid)
    assert report["requests_attempted"] == 0
    assert report["rows"][0]["status"] == "execution_error" and not report["rows"][0]["rounds"]


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_new_resource_paths_and_baseline_factory_have_real_verified_evidence(tmp_path):
    reg = study.preregister_holdout()
    reg["rows"] = [row for row in reg["rows"] if row["seed"] == 0 and row["strategy"] == "fixed"]
    destination = tmp_path / "all_fixed"
    report = execute(reg, destination, baseline_factory=study.holdout_baseline,
                     iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    summary = build_summary(report, reg, evidence_root=destination)
    assert len(summary["rows"]) == 6 and report["requests_attempted"] == 0
    assert summary["eligible_for_frozen_comparison"], [(row["status"], row.get("evidence_error")) for row in summary["rows"]]
    for row in summary["rows"]:
        assert row["evidence_verified"] and row["search_cycles"] == 16
        assert row["rounds"][0]["reference"]["failures"] == 0
        assert row["rounds"][0]["actual"]["checks"] == 16
