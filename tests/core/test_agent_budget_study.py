"""Fair proposal limits, intact denominators and genuine reference execution."""
import copy
import json
from pathlib import Path

import pytest

from iverilog_ai.core.contracts import DutContract
from scripts import run_agent_budget_study as study
from scripts.run_agent_comparison import execute
from scripts.summarize_agent_comparison import build_summary


def contract(case):
    if case in study.MODULE_HOLDOUT_CASES:
        path = study.ROOT / f"benchmarks/agent_module_holdout_20261005_v7/contracts/{case}_contract.json"
    else:
        path = study.ROOT / f"examples/{case}_contract.json"
    return DutContract.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_registration_keeps_all_three_cohorts_and_shared_cap():
    reg = study.preregister_budget_study()
    assert len(reg["rows"]) == 432 and reg["theoretical_requests"] == 504
    assert reg["independent_holdout"] is False and reg["external_independent_holdout"] is False
    for strategy in study.STRATEGIES:
        rows = [r for r in reg["rows"] if r["strategy"] == strategy]
        assert len(rows) == 72 and sum(r["variant"] != "reference" for r in rows) == 48
        for cohort, cases in study.COHORTS.items():
            selected = [r for r in rows if r["cohort"] == cohort]
            assert len(selected) == len(cases) * 9
            assert {r["case"] for r in selected} == set(cases)
        assert all(r["budget_cycles"] == study.CYCLE_BUDGETS[r["case"]] for r in rows)
    assert reg["study"]["limits"]["token_cap"] == 1_000_000
    assert reg["prompt_profile"]["agent_plan_mode"] == "independent"
    assert reg["prompt_profile"]["reference_sampling"] == "per_cycle"
    assert all(not p.startswith(".iverilog-ai/") for p in reg["code_and_input_sha256"])
    assert "scripts/run_agent_holdout_study.py" in reg["code_and_input_sha256"]


def test_dry_run_does_not_read_credentials_or_initialize_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "absent")
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dry run read a credential"))
    monkeypatch.setattr(study, "BudgetedProvider", lambda **_: pytest.fail("dry run created provider"))
    assert study.main(["--api-key-file", str(tmp_path / "missing")]) == 0
    assert not study.OUTPUT.exists()


@pytest.mark.parametrize("field,value", [("token_cap", True), ("registered_rows", 432.0),
    ("theoretical_request_cap", 505), ("max_vectors_per_proposal", 13), ("repeats", 2)])
def test_limit_drift_is_rejected_before_execution(monkeypatch, tmp_path, field, value):
    config = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="scope"):
        study.preregister_budget_study()


@pytest.mark.parametrize("case", study.CASES)
@pytest.mark.parametrize("strategy", ("fixed", "random", "protocol_random"))
def test_every_baseline_has_equal_proposal_limits_without_expected_or_target_data(case, strategy):
    dut = contract(case)
    for seed in range(3):
        plan = study.budget_baseline(case, strategy, seed, dut, study.CYCLE_BUDGETS[case])
        assert plan == study.budget_baseline(case, strategy, seed, dut, study.CYCLE_BUDGETS[case])
        assert plan.design == case and 1 <= len(plan.vectors) <= 12
        assert sum(v.cycles for v in plan.vectors) == study.CYCLE_BUDGETS[case]
        allowed = {p.name for p in dut.inputs} - {dut.clock.signal, dut.reset.signal}
        assert all(set(v.inputs) - {dut.reset.signal} == allowed
            and v.inputs.get(dut.reset.signal, 1) == 1
            and not v.expected and v.sample_phase == "after" for v in plan.vectors)


def test_no_api_budget_preserves_all_216_agent_tasks(tmp_path):
    reg = study.preregister_budget_study()
    reg["rows"] = [r for r in reg["rows"] if r["strategy"] in ("single", "feedback", "no_feedback")]
    destination = tmp_path / "zero_api"
    def forbidden(_):
        pytest.fail("zero budget opened provider")
    result = execute(reg, destination, request_cap=0, provider_factory=forbidden)
    summary = build_summary(result, reg, evidence_root=destination)
    assert len(result["rows"]) == 216 and result["requests_attempted"] == 0
    assert summary["frozen_input_snapshot_verified"] and not summary["eligible_for_frozen_comparison"]
    assert all(summary["strategies"][s]["registered_defect_samples"] == 48 for s in ("single", "feedback", "no_feedback"))


def test_changed_target_and_unregistered_resource_refused_before_any_output(tmp_path):
    reg = study.preregister_budget_study()
    changed = copy.deepcopy(reg)
    changed["rows"][0]["reference_rtl"] = "../outside.v"
    with pytest.raises(ValueError, match="not registered"):
        execute(changed, tmp_path / "override")
    assert not (tmp_path / "override").exists()
    changed = copy.deepcopy(reg)
    changed["code_and_input_sha256"][changed["rows"][0]["rtl"]] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        execute(changed, tmp_path / "drift")
    assert not (tmp_path / "drift").exists()


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_all_public_baselines_have_real_per_cycle_reference_evidence(tmp_path):
    reg = study.preregister_budget_study()
    reg["rows"] = [r for r in reg["rows"] if r["variant"] == "reference" and r["strategy"] in ("fixed", "random", "protocol_random")]
    destination = tmp_path / "correct_controls"
    result = execute(reg, destination, request_cap=0, provider_factory=lambda _: pytest.fail("baseline opened API"),
        baseline_factory=study.budget_baseline, iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    summary = build_summary(result, reg, evidence_root=destination)
    assert result["requests_attempted"] == 0 and len(summary["rows"]) == 72
    assert summary["eligible_for_frozen_comparison"], [(r["case"], r["strategy"], r.get("evidence_error")) for r in summary["rows"] if not r["evidence_verified"]]
    for row in summary["rows"]:
        assert row["status"] == "not_detected" and row["search_cycles"] == study.CYCLE_BUDGETS[row["case"]]
        assert row["evidence_verified"] and row["rounds"][0]["reference"]["failures"] == 0
        assert row["rounds"][0]["actual"]["checks"] == row["search_cycles"] * len(contract(row["case"]).outputs)
