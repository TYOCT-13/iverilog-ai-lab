"""Historical v7 assets/executor fixtures; no frozen v7 API experiment rerun."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from iverilog_ai.core.contracts import DutContract
from scripts import run_agent_budget_study as study
from scripts.run_agent_comparison import execute
from scripts.summarize_agent_comparison import build_summary


@pytest.fixture
def isolated_registration(monkeypatch):
    """Only the registration guard sees v7; execute binds real current bytes."""
    relative = "src/iverilog_ai/ai/agent.py"
    revision = "b9f7a6ed57b215208b790c3be32980862267aa49"
    config = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    original_sha, original_prompt, original_version = study.sha, study.SYSTEM_PROMPT, study.PROMPT_VERSION
    source = subprocess.check_output(["git", "show", revision + ":" + relative], cwd=study.ROOT)
    assignments = {target.id: ast.literal_eval(node.value)
        for node in ast.parse(source.decode("utf-8")).body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
        and target.id in {"SYSTEM_PROMPT", "PROMPT_VERSION"}}
    historical_sha = hashlib.sha256(source).hexdigest()
    assert historical_sha == config["agent_sha256"]
    assert hashlib.sha256(assignments["SYSTEM_PROMPT"].encode()).hexdigest() == config["system_prompt_sha256"]
    with monkeypatch.context() as guard:
        guard.setattr(study, "sha", lambda path: historical_sha if path == study.ROOT / relative else original_sha(path))
        guard.setattr(study, "SYSTEM_PROMPT", assignments["SYSTEM_PROMPT"])
        guard.setattr(study, "PROMPT_VERSION", assignments["PROMPT_VERSION"])
        reg = study.preregister_budget_study()
    assert study.sha is original_sha and study.SYSTEM_PROMPT == original_prompt and study.PROMPT_VERSION == original_version
    reg["code_and_input_sha256"] = {path: original_sha(study.registered_source_path(path))
                                   for path in reg["code_and_input_sha256"]}
    reg["study"]["test_fixture"] = {"purpose": "historical registration/assets/executor unit tests only",
        "historical_experiment_rerun": False, "guard_only_revision": revision,
        "execution_source": "real current worktree bytes; no hash mocking during execute"}
    reg["prompt_profile"]["agent_prompt_version"] = original_version
    reg["prompt_profile"]["system_prompt_sha256"] = hashlib.sha256(original_prompt.encode()).hexdigest()
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    return reg


def contract(case):
    if case in study.MODULE_HOLDOUT_CASES:
        path = study.ROOT / f"benchmarks/agent_module_holdout_20261005_v7/contracts/{case}_contract.json"
    else:
        path = study.ROOT / f"examples/{case}_contract.json"
    return DutContract.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_registration_keeps_all_three_cohorts_and_shared_cap(isolated_registration):
    reg = isolated_registration
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


def test_dry_run_does_not_read_credentials_or_initialize_provider(monkeypatch, tmp_path, isolated_registration):
    monkeypatch.setattr(study, "preregister_budget_study", lambda: isolated_registration)
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


def test_no_api_budget_preserves_all_216_agent_tasks(tmp_path, isolated_registration):
    reg = isolated_registration
    reg["rows"] = [r for r in reg["rows"] if r["strategy"] in ("single", "feedback", "no_feedback")]
    destination = tmp_path / "zero_api"
    def forbidden(_):
        pytest.fail("zero budget opened provider")
    result = execute(reg, destination, request_cap=0, provider_factory=forbidden)
    summary = build_summary(result, reg, evidence_root=destination)
    assert len(result["rows"]) == 216 and result["requests_attempted"] == 0
    assert summary["frozen_input_snapshot_verified"] and not summary["eligible_for_frozen_comparison"]
    assert all(summary["strategies"][s]["registered_defect_samples"] == 48 for s in ("single", "feedback", "no_feedback"))


def test_changed_target_and_unregistered_resource_refused_before_any_output(tmp_path, isolated_registration):
    reg = isolated_registration
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
def test_all_public_baselines_have_real_per_cycle_reference_evidence(tmp_path, isolated_registration):
    reg = isolated_registration
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


def test_production_v7_registration_rejects_current_v8_without_guard_patch():
    with pytest.raises(ValueError, match="frozen v7"):
        study.preregister_budget_study()


def test_historical_v7_agent_hash_cannot_bypass_real_execution_snapshot(tmp_path, isolated_registration):
    reg = copy.deepcopy(isolated_registration)
    reg["code_and_input_sha256"]["src/iverilog_ai/ai/agent.py"] = reg["study"]["limits"]["agent_sha256"]
    with pytest.raises(ValueError, match="registered source/input changed before execution"):
        execute(reg, tmp_path / "must-not-exist", provider_factory=lambda _: pytest.fail("opened API"))
    assert not (tmp_path / "must-not-exist").exists()
