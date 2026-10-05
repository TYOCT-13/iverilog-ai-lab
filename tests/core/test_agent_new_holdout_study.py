"""Mechanical new-holdout admission tests: zero API, zero DUT, zero real key."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random

import pytest

from scripts import run_agent_new_holdout_study as study
from scripts.run_agent_comparison import execute, freeze_registered_inputs
from scripts.summarize_agent_comparison import build_summary, verify_frozen_inputs


def forbidden(*args, **kwargs):
    pytest.fail("mechanical test attempted credentials, provider, DUT or historical writes")


@pytest.fixture(autouse=True)
def forbid_external_effects(monkeypatch):
    monkeypatch.setattr(study, "read_key_file", forbidden)
    monkeypatch.setattr(study, "BudgetedProvider", forbidden)
    monkeypatch.setattr("iverilog_ai.ai.provider.OpenAICompatibleProvider._request", forbidden)
    monkeypatch.setattr("scripts.run_agent_comparison.VerificationPipeline.run", forbidden)
    monkeypatch.setattr(study.TokenBudget, "save", forbidden)


@pytest.fixture
def registration():
    return study.preregister_new_holdout()


def load_config():
    return json.loads(study.CONFIG.read_text(encoding="utf-8"))


def frozen_fixture(registration):
    """A negative-admission fixture; never executes or claims a production freeze."""
    reg = copy.deepcopy(registration)
    reg["study"]["limits"]["freeze_status"] = "FROZEN"
    return reg


def clean_git_fixture(monkeypatch, registration):
    tracked = "\0".join(registration["code_and_input_sha256"]) + "\0"

    def git(*arguments):
        if arguments == ("status", "--porcelain"):
            return b""
        if arguments == ("ls-files", "-z"):
            return tracked.encode()
        if arguments == ("rev-parse", "HEAD"):
            return registration["study"]["source_revision"].encode()
        forbidden()

    monkeypatch.setattr(study, "_git", git)


def write_previous(root: Path, *, status="known_usage", finished=True):
    """Create five explicitly synthetic complete ledgers in an isolated directory."""
    for name in study.PREVIOUS_BATCHES:
        folder = root / ".iverilog-ai" / name
        folder.mkdir(parents=True)
        record = {"id": 0, "status": status, "reserved_tokens": 256,
            "charged_tokens": 30 if status == "known_usage" else 0,
            "request_sha256": "0" * 64, "request_bytes": 10, "output_cap": 4096}
        if status == "known_usage":
            record.update(prompt_tokens=20, completion_tokens=10)
        if status == "unknown_usage":
            record.update(uncertain_charge_tokens=300, usage_status="missing")
        reserved = 300 if status == "unknown_usage" else 256 if status == "pending" else 0
        known = 30 if status == "known_usage" else 0
        totals = {"reported_tokens": known, "unknown_reserved_tokens": reserved,
            "conservative_total": known + reserved, "remaining_tokens": 1_000_000 - known - reserved,
            "requests_known_usage": int(status == "known_usage"),
            "requests_unknown_usage": int(status in {"pending", "unknown_usage"})}
        data = {"schema": "agent-round-token-budget-v1", "limit": 1_000_000,
            "halted": False, "records": [record], "totals": totals, "unit_test_fixture": True}
        (folder / "token_budget.json").write_text(json.dumps(data), encoding="utf-8")
        result = {"finished_at": "unit-test-finished" if finished else None, "unit_test_fixture": True}
        (folder / "results.json").write_text(json.dumps(result), encoding="utf-8")


def test_full_geometry_and_truthful_new_internal_scope(registration):
    reg = registration
    assert len(reg["rows"]) == 108 and reg["theoretical_requests"] == 126
    assert reg["independent_holdout"] and not reg["external_independent_holdout"]
    assert reg["internal_controlled_module_set_holdout"]
    assert "same-team synthetic designs/mutations; no external blindness" in reg["independent_holdout_meaning"]
    assert reg["study"]["agent_frozen_from_revision"] == study.FROZEN_REVISION
    assert reg["study"]["new_holdout_modules"] == list(study.CASES)
    assert reg["study"]["created_after_v8_freeze"]
    assert not reg["study"]["all_modules_previously_agent_exposed"]
    assert not reg["study"]["external_blind_holdout"]
    assert not reg["study"]["independent_human_review"]
    assert reg["study"]["previous_failed_v8_tasks_not_retried"]
    identities = {(r["case"], r["variant"], r["strategy"], r["seed"]) for r in reg["rows"]}
    assert len(identities) == 108
    for strategy in study.STRATEGIES:
        rows = [r for r in reg["rows"] if r["strategy"] == strategy]
        assert len(rows) == 18 and sum(r["variant"] != "reference" for r in rows) == 12
        assert sum(r["variant"] == "reference" for r in rows) == 6
        assert {r["seed"] for r in rows} == {0, 1, 2}
        assert all(r["budget_cycles"] == 24 and r["status"] == "not_started" and not r["rounds"] for r in rows)
    for start in range(0, 108, 6):
        block = reg["rows"][start:start + 6]
        first = block[0]
        rotation = (first["seed"] + study.VARIANTS.index(first["variant"]) + study.CASES.index(first["case"])) % 6
        assert [row["strategy"] for row in block] == list(study.STRATEGIES[rotation:] + study.STRATEGIES[:rotation])
    prompt = reg["prompt_profile"]
    assert prompt["agent_plan_mode"] == "independent" and prompt["reference_sampling"] == "per_cycle"
    assert prompt["api_request_limit_per_sample"] == {"single": 1, "feedback": 3, "no_feedback": 3}
    assert reg["prompt_profile_sha256"] == hashlib.sha256(json.dumps(prompt, sort_keys=True).encode()).hexdigest()


def test_frozen_agent_uses_actual_import_and_both_original_git_blobs():
    study.validate_frozen_agent()
    assert study.PROMPT_VERSION == "verification-agent-v8-bounded-port-feedback"
    assert hashlib.sha256(study.SYSTEM_PROMPT.encode()).hexdigest() == study.SYSTEM_PROMPT_SHA256
    for relative, digest in study.FROZEN_SOURCES.items():
        assert study.sha(study.ROOT / relative) == digest
        assert hashlib.sha256(study._git("show", study.FROZEN_REVISION + ":" + relative)).hexdigest() == digest


def test_all_original_assets_sources_and_executor_dependencies_registered(registration):
    manifest = json.loads(study.MANIFEST.read_text(encoding="utf-8"))
    expected = set(manifest["members"]) | {study.MANIFEST.relative_to(study.ROOT).as_posix()}
    expected.update(path.relative_to(study.ROOT).as_posix() for path in (study.ROOT / "src").rglob("*.py"))
    expected.update({".gitattributes", "scripts/run_agent_new_holdout_study.py",
        "scripts/agent_token_budget.py", "scripts/run_agent_comparison.py", "scripts/run_strategy_experiment.py",
        "scripts/summarize_agent_comparison.py", "spec/agent_new_holdout_study_1m_v8.json",
        "docs/experiment/agent_new_holdout_study_plan_2026-10-05.md", "tests/core/test_agent_new_holdout_study.py",
        "tests/core/test_agent_new_holdout_assets.py", "tests/core/test_agent_new_holdout_oracles.py"})
    assert set(registration["code_and_input_sha256"]) == expected
    assert all(study.sha(study.registered_source_path(relative)) == digest
               for relative, digest in registration["code_and_input_sha256"].items())


def test_snapshot_preserves_exact_original_bytes_and_rejects_copy_drift(registration, tmp_path):
    entry = freeze_registered_inputs(registration, tmp_path)
    report = {"frozen_inputs": entry}
    assert verify_frozen_inputs(report, registration, tmp_path)
    saved = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
    for item in saved["files"]:
        assert (tmp_path / item["copy"]).read_bytes() == (study.ROOT / item["path"]).read_bytes()
    target = tmp_path / saved["files"][0]["copy"]
    target.write_bytes(target.read_bytes() + b"\n")
    assert not verify_frozen_inputs(report, registration, tmp_path)


def test_dry_run_does_not_read_credential_provider_history_or_create_output(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "absent")
    monkeypatch.setattr(study, "previous_batch_accounting", forbidden)
    assert study.main(["--api-key-file", str(tmp_path / "nonexistent-key")]) == 0
    assert not study.OUTPUT.exists()


def test_unfrozen_execute_refuses_before_git_assets_credentials_or_output(monkeypatch, tmp_path, capsys):
    config = load_config()
    config.update(freeze_status="UNFROZEN", manifest_sha256=None)
    path = tmp_path / "unfrozen.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "absent")
    monkeypatch.setattr(study, "_git", forbidden)
    monkeypatch.setattr(study, "_load_manifest", forbidden)
    assert study.main(["--execute", "--api-key-file", str(tmp_path / "nonexistent-key")]) == 2
    assert "UNFROZEN" in capsys.readouterr().out and not study.OUTPUT.exists()


@pytest.mark.parametrize("field,value", [("token_cap", True), ("registered_rows", 107), ("repeats", 3.0),
    ("max_vectors_per_proposal", 13), ("max_accepted_vectors_total", 65), ("max_output_tokens_per_request", 8192),
    ("theoretical_request_cap", 127), ("cycle_budgets", {case: 16 for case in study.CASES}),
    ("agent_frozen_from_revision", "2f124e7"), ("agent_sha256", "0" * 64),
    ("observation_feedback_sha256", "0" * 64), ("system_prompt_sha256", "0" * 64)])
def test_frozen_scope_and_agent_pin_drift_refused_before_external_access(monkeypatch, tmp_path, field, value):
    config = load_config()
    config[field] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="scope|pins"):
        study.preregister_new_holdout()


@pytest.mark.parametrize("status,digest", [("FROZEN", None), ("FROZEN", "bad"), ("UNFROZEN", "0" * 64), ("READY", None)])
def test_freeze_lifecycle_cannot_be_bypassed(monkeypatch, tmp_path, status, digest):
    config = load_config()
    config.update(freeze_status=status, manifest_sha256=digest)
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="lifecycle"):
        study._load_config()


@pytest.mark.parametrize("field,value", [("stream", True), ("store", True), ("automatic_transport_retry", True),
    ("timeout_seconds", 60.0), ("thinking_mode", "enabled"), ("model", "other-model")])
def test_transport_drift_refused(monkeypatch, tmp_path, field, value):
    config = load_config()
    config["transport"][field] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(study, "CONFIG", path)
    with pytest.raises(ValueError, match="scope"):
        study._load_config()


def test_frozen_manifest_rejects_semantically_identical_changed_bytes(monkeypatch, tmp_path):
    config = load_config()
    config.update(freeze_status="FROZEN", manifest_sha256=study.sha(study.MANIFEST))
    path = tmp_path / "manifest.json"
    path.write_bytes(study.MANIFEST.read_bytes() + b"\n")
    monkeypatch.setattr(study, "MANIFEST", path)
    with pytest.raises(ValueError, match="original bytes"):
        study._load_manifest(config)


@pytest.mark.parametrize("violation", ["missing_member", "member_bytes", "resource_binding", "target_count", "target_path"])
def test_closed_manifest_and_fixed_targets_reject_drift(monkeypatch, tmp_path, violation):
    manifest = json.loads(study.MANIFEST.read_text(encoding="utf-8"))
    item = manifest["cases"][study.CASES[0]]
    if violation == "missing_member":
        manifest["members"].pop(next(iter(manifest["members"])))
    elif violation == "member_bytes":
        manifest["members"][next(iter(manifest["members"]))] = "0" * 64
    elif violation == "resource_binding":
        item["contract_sha256"] = "0" * 64
    elif violation == "target_count":
        item["targets"].pop()
    else:
        item["targets"][1]["rtl"] = "../outside.v"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    config = load_config()
    config.update(freeze_status="UNFROZEN", manifest_sha256=None)
    monkeypatch.setattr(study, "MANIFEST", path)
    with pytest.raises(ValueError, match="members|bytes|denominator|target path"):
        study._load_manifest(config)


def test_missing_oracle_adapter_cannot_claim_valid_registration(monkeypatch):
    monkeypatch.setattr(study, "reference_sampling_profile", lambda contract: None)
    with pytest.raises(ValueError, match="Oracle.*complete fixed contract"):
        study.preregister_new_holdout()


@pytest.mark.parametrize("case", study.CASES)
@pytest.mark.parametrize("strategy", study.STRATEGIES[:3])
def test_public_baseline_geometry_is_24_cycles_and_expectation_free(case, strategy):
    contract = study.DutContract.from_dict(json.loads((study.ROOT / study.ASSETS / "contracts" / f"{case}_contract.json").read_text(encoding="utf-8")))
    for seed in (0, 1, 2):
        plan = study.holdout_baseline(case, strategy, seed, contract, 24)
        assert plan == study.holdout_baseline(case, strategy, seed, contract, 24)
        assert plan.design == case and 1 <= len(plan.vectors) <= 12
        assert sum(vector.cycles for vector in plan.vectors) == 24
        assert all(not vector.expected and vector.sample_phase == "after" for vector in plan.vectors)
        if strategy == "random":
            assert len(plan.vectors) == 12 and all(vector.cycles == 2 for vector in plan.vectors)
            rng = random.Random(seed)
            business = [port for port in contract.inputs if port.name not in {"i_clk", "i_rstn"}]
            for vector in plan.vectors:
                assert vector.inputs == {"i_rstn": 1, **{port.name: rng.randrange(1 << port.width) for port in business}}


def test_shared_executor_refuses_changed_original_hash_before_output_or_provider(registration, tmp_path):
    reg = copy.deepcopy(registration)
    reg["code_and_input_sha256"]["scripts/run_agent_new_holdout_study.py"] = "0" * 64
    destination = tmp_path / "absent"
    with pytest.raises(ValueError, match="changed before execution"):
        execute(reg, destination, provider_factory=forbidden, baseline_factory=study.holdout_baseline)
    assert not destination.exists()


def test_summary_preserves_all_failed_and_unexecuted_denominators_without_dut(registration):
    report = {"profile": "v3", "rows": [], "finished_at": None, "changed_inputs_at_finish": []}
    summary = build_summary(report, registration)
    assert summary["registered_rows"] == 108 and not summary["eligible_for_frozen_comparison"]
    for strategy in study.STRATEGIES:
        counts = summary["strategies"][strategy]
        assert counts["registered_defect_samples"] == 12 and counts["unique_defects"] == 4
        assert counts["detected_samples"] == 0 and counts["incomplete_or_undecidable"] == 12
        assert len(counts["per_repeat"]) == 3


@pytest.mark.parametrize("violation", ["output_exists", "missing_key", "dirty", "untracked", "source_bytes"])
def test_execution_admission_refuses_before_history_or_credentials(monkeypatch, tmp_path, registration, violation):
    reg = frozen_fixture(registration)
    clean_git_fixture(monkeypatch, reg)
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(study, "previous_batch_accounting", forbidden)
    key_file = tmp_path / "nonexistent-key"
    if violation == "output_exists":
        study.OUTPUT.mkdir()
    elif violation == "missing_key":
        key_file = None
    elif violation == "dirty":
        monkeypatch.setattr(study, "_git", lambda *args: b" M modified.py\n")
    elif violation == "untracked":
        monkeypatch.setattr(study, "_git", lambda *args: b"" if args != ("rev-parse", "HEAD") else reg["study"]["source_revision"].encode())
    else:
        reg["code_and_input_sha256"]["scripts/run_agent_new_holdout_study.py"] = "0" * 64
    with pytest.raises(ValueError, match="fresh output|committed|original bytes"):
        study.execution_admission(reg, key_file)
    if violation != "output_exists":
        assert not study.OUTPUT.exists()


def test_five_historical_prefixes_match_original_feedback_runner():
    assert study.PREVIOUS_BATCHES == ("agent-study-1m-live-20261005", "agent-recovery-study-live-20261005",
        "agent-holdout-study-live-20261005", "agent-budget-study-live-20261005", "agent-feedback-study-live-20261005")


@pytest.mark.parametrize("pending,finished", [(True, True), (False, False)])
def test_previous_pending_or_unfinished_batch_blocks_without_key_or_new_output(monkeypatch, tmp_path, pending, finished):
    write_previous(tmp_path, status="pending" if pending else "known_usage", finished=finished)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="pending or unfinished"):
        study.previous_batch_accounting()
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_missing_local_private_old_accounts_are_explicitly_absent_and_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="accounting absent; execution refused") as caught:
        study.previous_batch_accounting()
    assert all(name in str(caught.value) for name in study.PREVIOUS_BATCHES)
    assert not (tmp_path / ".iverilog-ai").exists()


def test_main_historical_pending_gate_precedes_key_provider_and_output(monkeypatch, tmp_path, registration, capsys):
    write_previous(tmp_path, status="pending")
    reg = frozen_fixture(registration)
    clean_git_fixture(monkeypatch, reg)
    monkeypatch.setattr(study, "preregister_new_holdout", lambda **kwargs: reg)
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "OUTPUT", tmp_path / "new-absent-output")
    monkeypatch.setattr(study, "execute", forbidden)
    assert study.main(["--execute", "--api-key-file", str(tmp_path / "nonexistent-key")]) == 2
    assert "pending or unfinished" in capsys.readouterr().out
    assert not study.OUTPUT.exists()


def test_unknown_historical_usage_preserves_reservations_and_does_not_charge_new_cap(monkeypatch, tmp_path):
    write_previous(tmp_path, status="unknown_usage")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    records = study.previous_batch_accounting()
    assert len(records) == 5
    for record in records:
        assert record["pending_requests"] == 0 and record["unknown_usage_requests"] == 1
        assert record["unknown_usage_records"][0]["uncertain_charge_tokens"] == 300
        assert record["tokens"]["reported_tokens"] == 0 and record["tokens"]["unknown_reserved_tokens"] == 300
        assert record["historical_usage_charged_to_this_batch"] is False
        assert len(record["journal_sha256"]) == 64 and len(record["results_sha256"]) == 64
    new_budget = study.TokenBudget(1_000_000, tmp_path / "new-nonexistent" / "token_budget.json")
    assert new_budget.totals()["remaining_tokens"] == 1_000_000 and not new_budget.data["records"]
    assert not new_budget.journal.parent.exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_historical_unknown_totals_cannot_be_reported_as_zero(monkeypatch, tmp_path):
    write_previous(tmp_path, status="unknown_usage")
    path = tmp_path / ".iverilog-ai" / study.PREVIOUS_BATCHES[-1] / "token_budget.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["totals"]["unknown_reserved_tokens"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="ledger totals"):
        study.previous_batch_accounting()
