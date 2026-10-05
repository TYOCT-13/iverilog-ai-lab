"""Historical holdout assets/executor fixtures; never rerun the frozen v6 API batch."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from iverilog_ai.core.contracts import DutContract
from scripts import run_agent_holdout_study as study
from scripts.run_agent_comparison import execute
from scripts.summarize_agent_comparison import build_summary


def contract(case):
    return DutContract.from_dict(json.loads((study.ROOT / f"examples/{case}_contract.json").read_text(encoding="utf-8")))


def forbidden_provider(_):
    pytest.fail("historical holdout test fixture initialized an API provider")


@pytest.fixture
def isolated_registration(monkeypatch):
    """Exercise the historical guard in isolation, then freeze real current bytes.

    Only registration sees the historical Agent hash/prompt. No old module is
    executed, no source/config is written, and execute gets no hash patches.
    The returned object is explicitly a unit-test fixture, not a v6 rerun.
    """
    config = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    relative = "src/iverilog_ai/ai/agent.py"
    agent_path = study.ROOT / relative
    real_sha, real_prompt, real_version = study.sha, study.SYSTEM_PROMPT, study.PROMPT_VERSION
    current_agent_sha = real_sha(agent_path)
    historical = subprocess.check_output(
        ["git", "show", config["agent_frozen_from_revision"] + ":" + relative], cwd=study.ROOT)
    assignments = {target.id: ast.literal_eval(node.value)
                   for node in ast.parse(historical.decode("utf-8")).body
                   if isinstance(node, ast.Assign)
                   for target in node.targets
                   if isinstance(target, ast.Name) and target.id in {"SYSTEM_PROMPT", "PROMPT_VERSION"}}
    assert isinstance(assignments["SYSTEM_PROMPT"], str) and isinstance(assignments["PROMPT_VERSION"], str)
    historical_sha = hashlib.sha256(historical).hexdigest()
    historical_prompt_sha = hashlib.sha256(assignments["SYSTEM_PROMPT"].encode()).hexdigest()
    assert historical_sha == config["agent_sha256"]
    assert historical_prompt_sha == config["system_prompt_sha256"]
    with monkeypatch.context() as guard_only:
        guard_only.setattr(study, "sha", lambda path: historical_sha if path == agent_path else real_sha(path))
        guard_only.setattr(study, "SYSTEM_PROMPT", assignments["SYSTEM_PROMPT"])
        guard_only.setattr(study, "PROMPT_VERSION", assignments["PROMPT_VERSION"])
        reg = study.preregister_holdout()
    assert study.sha is real_sha and study.SYSTEM_PROMPT == real_prompt and study.PROMPT_VERSION == real_version
    assert real_sha(agent_path) == current_agent_sha
    reg["code_and_input_sha256"] = {
        path: real_sha(study.registered_source_path(path)) for path in reg["code_and_input_sha256"]}
    reg["study"]["test_fixture"] = {
        "purpose": "historical holdout registration/assets/executor unit tests only",
        "historical_experiment_rerun": False,
        "guard_only_revision": config["agent_frozen_from_revision"],
        "guard_only_agent_sha256": historical_sha,
        "guard_only_system_prompt_sha256": historical_prompt_sha,
        "execution_source": "real current worktree bytes; no hash mocking during execute",
        "execution_agent_sha256": current_agent_sha,
        "execution_prompt_version": real_version,
        "execution_system_prompt_sha256": hashlib.sha256(real_prompt.encode()).hexdigest(),
    }
    reg["prompt_profile"]["agent_prompt_version"] = real_version
    reg["prompt_profile"]["system_prompt_sha256"] = hashlib.sha256(real_prompt.encode()).hexdigest()
    reg["prompt_profile_sha256"] = hashlib.sha256(json.dumps(reg["prompt_profile"], sort_keys=True).encode()).hexdigest()
    return reg


def test_registration_fixture_preserves_disjoint_membership_and_freezes_current_bytes(isolated_registration):
    reg = isolated_registration
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
    assert all(study.sha(study.registered_source_path(path)) == digest
               for path, digest in reg["code_and_input_sha256"].items())
    fixture = reg["study"]["test_fixture"]
    assert fixture["historical_experiment_rerun"] is False
    assert fixture["guard_only_agent_sha256"] == reg["study"]["limits"]["agent_sha256"]
    assert fixture["execution_agent_sha256"] == reg["code_and_input_sha256"]["src/iverilog_ai/ai/agent.py"]
    assert fixture["execution_agent_sha256"] != fixture["guard_only_agent_sha256"]
    assert reg["prompt_profile"]["agent_prompt_version"] == fixture["execution_prompt_version"] == study.PROMPT_VERSION
    assert reg["prompt_profile"]["system_prompt_sha256"] == fixture["execution_system_prompt_sha256"]
    assert reg["prompt_profile"]["reference_sampling"] == "per_cycle"


def test_current_agent_without_fixture_is_rejected_by_frozen_v6_guard(monkeypatch):
    config = json.loads(study.CONFIG.read_text(encoding="utf-8"))
    assert study.sha(study.ROOT / "src/iverilog_ai/ai/agent.py") != config["agent_sha256"]
    assert hashlib.sha256(study.SYSTEM_PROMPT.encode()).hexdigest() != config["system_prompt_sha256"]
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("guard read credentials"))
    with pytest.raises(ValueError, match="frozen Agent or system prompt changed"):
        study.preregister_holdout()


def test_isolated_dry_run_never_reads_key_or_creates_output(monkeypatch, tmp_path, isolated_registration):
    destination = tmp_path / "absent"
    monkeypatch.setattr(study, "OUTPUT", destination)
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dry run read credentials"))
    monkeypatch.setattr(study, "preregister_holdout", lambda: copy.deepcopy(isolated_registration))
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


def test_unregistered_override_is_rejected_before_any_output(tmp_path, isolated_registration):
    reg = isolated_registration
    for field in ("contract_path", "reference_rtl"):
        changed = copy.deepcopy(reg)
        changed["rows"][0][field] = "../outside.txt"
        destination = tmp_path / field
        with pytest.raises(ValueError, match="not registered"):
            execute(changed, destination, provider_factory=forbidden_provider)
        assert not destination.exists()


def test_historical_agent_hash_cannot_bypass_actual_execution_snapshot(tmp_path, isolated_registration):
    reg = copy.deepcopy(isolated_registration)
    reg["code_and_input_sha256"]["src/iverilog_ai/ai/agent.py"] = reg["study"]["limits"]["agent_sha256"]
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="registered source/input changed before execution"):
        execute(reg, destination, provider_factory=forbidden_provider)
    assert not destination.exists()


def test_zero_api_budget_preserves_all_new_module_denominators(tmp_path, isolated_registration):
    reg = isolated_registration
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
def test_custom_baseline_budget_violations_never_reach_dut(monkeypatch, tmp_path, violation, isolated_registration):
    reg = isolated_registration
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
    report = execute(reg, tmp_path / violation, baseline_factory=invalid, provider_factory=forbidden_provider)
    assert report["requests_attempted"] == 0
    assert report["rows"][0]["status"] == "execution_error" and not report["rows"][0]["rounds"]


@pytest.mark.skipif(not Path("D:/iverilog/bin/iverilog.exe").exists(), reason="Icarus unavailable")
def test_new_resource_paths_and_baseline_factory_have_real_verified_evidence(tmp_path, isolated_registration):
    reg = isolated_registration
    reg["rows"] = [row for row in reg["rows"] if row["seed"] == 0 and row["strategy"] == "fixed"]
    destination = tmp_path / "all_fixed"
    report = execute(reg, destination, baseline_factory=study.holdout_baseline, provider_factory=forbidden_provider,
                     iverilog="D:/iverilog/bin/iverilog.exe", vvp="D:/iverilog/bin/vvp.exe")
    summary = build_summary(report, reg, evidence_root=destination)
    assert len(summary["rows"]) == 6 and report["requests_attempted"] == 0
    assert report["record_kind"] == "test_provider"
    saved = json.loads((destination / "preregistration.json").read_text(encoding="utf-8"))
    assert saved["study"]["test_fixture"]["historical_experiment_rerun"] is False
    manifest = json.loads((destination / "registered-inputs/manifest.json").read_text(encoding="utf-8"))
    agent = next(item for item in manifest["files"] if item["path"] == "src/iverilog_ai/ai/agent.py")
    assert (destination / agent["copy"]).read_bytes() == (study.ROOT / agent["path"]).read_bytes()
    assert summary["eligible_for_frozen_comparison"], [(row["status"], row.get("evidence_error")) for row in summary["rows"]]
    for row in summary["rows"]:
        assert row["evidence_verified"] and row["search_cycles"] == 16
        assert row["rounds"][0]["reference"]["failures"] == 0
        assert row["rounds"][0]["actual"]["checks"] == 16
