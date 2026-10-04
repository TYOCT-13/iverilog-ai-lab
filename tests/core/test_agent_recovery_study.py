"""New full recovery registration; public fixtures only, no real key or API."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_agent_recovery_study as study
from scripts import run_agent_study_1m as parent
from scripts.agent_token_budget import BudgetedProvider


@pytest.fixture
def registration():
    return study.preregister_recovery_study()


def test_full_membership_order_and_spec_bytes_are_identical_to_public_parent(registration):
    reg, generated = registration
    prior, prior_generated = parent.preregister_study()
    assert reg["rows"] == prior["rows"]
    assert len(reg["rows"]) == 216 and reg["theoretical_requests"] == 252
    assert not reg["independent_holdout"]
    assert set(generated) == {study.INPUTS / f"{case}_spec.md" for case in study.CASES}
    for strategy in study.STRATEGIES:
        rows = [row for row in reg["rows"] if row["strategy"] == strategy]
        assert len(rows) == 36 and sum(row["variant"] != "reference" for row in rows) == 24
        assert sum(row["variant"] == "reference" for row in rows) == 12
        assert {row["seed"] for row in rows} == {0, 1, 2}
        assert all(row["requests"] == 0 and row["rounds"] == [] for row in rows)
    for case in study.CASES:
        content = generated[study.INPUTS / f"{case}_spec.md"]
        assert content == prior_generated[parent.INPUTS / f"{case}_spec.md"]
        item = reg["protocol_config"]["cases"][case]
        relative = (study.INPUTS / f"{case}_spec.md").relative_to(study.ROOT).as_posix()
        assert item["spec_path"] == relative
        assert reg["code_and_input_sha256"][relative] == hashlib.sha256(content).hexdigest()
        assert (parent.INPUTS / f"{case}_spec.md").relative_to(study.ROOT).as_posix() not in reg["code_and_input_sha256"]
        assert all(row["budget_cycles"] == {"sync_fifo": 16, "uart_tx": 48, "spi_master": 20,
                                            "handshake_stage": 8}[case]
                   for row in reg["rows"] if row["case"] == case)
    assert not any(path.startswith(parent.INPUTS.relative_to(study.ROOT).as_posix() + "/")
                   for path in reg["code_and_input_sha256"])


def test_deterministic_rotation_and_prompt_disclosure_are_registered(registration):
    reg, _ = registration
    again, _ = study.preregister_recovery_study()
    assert reg["rows"] == again["rows"]
    ranks = {}
    for row in reg["rows"]:
        ranks.setdefault(row["case"], {})
        ranks[row["case"]].setdefault(row["variant"], len(ranks[row["case"]]))
    order = []
    for row in reg["rows"]:
        case = study.CASES.index(row["case"])
        rank = ranks[row["case"]][row["variant"]]
        rotation = (row["seed"] + rank + case) % len(study.STRATEGIES)
        order.append((row["seed"], rank, case, (study.STRATEGIES.index(row["strategy"])-rotation) % 6))
    assert order == sorted(order)
    disclosure = reg["study"]["prompt_change_disclosure"]
    assert disclosure["current"] == {key: reg["prompt_profile"][key]
                                      for key in ("agent_prompt_version", "system_prompt_sha256")}
    assert disclosure["changed"] is (disclosure["current"] != disclosure["parent"])
    assert "not a single-factor" in disclosure["interpretation"]
    caveat = reg["study"]["feedback_caveat"]
    assert "ordinary-format diagnostics" in caveat and "plan_error" in caveat
    assert "without rejection details" in caveat and "early stopping remains" in caveat
    assert reg["protocol"]["no_feedback"] == caveat
    for name in ("scripts/run_agent_recovery_study.py", "spec/agent_recovery_study_1m.json",
                 "docs/experiment/agent_recovery_study_plan_2026-10-05.md",
                 "scripts/agent_token_budget.py", "src/iverilog_ai/ai/agent.py",
                 "src/iverilog_ai/core/pipeline.py", "scripts/summarize_agent_comparison.py"):
        assert name in reg["code_and_input_sha256"]


@pytest.mark.parametrize("semantic", [False, True])
def test_parent_config_drift_is_rejected_before_delegation(tmp_path, monkeypatch, semantic):
    copied = tmp_path / "parent-config.json"
    raw = parent.CONFIG.read_bytes()
    if semantic:
        data = json.loads(raw)
        data["cycle_budgets"]["uart_tx"] = 49
        raw = json.dumps(data).encode()
    else:
        raw += b"\n"
    copied.write_bytes(raw)
    monkeypatch.setattr(parent, "CONFIG", copied)
    monkeypatch.setattr(parent, "preregister_study", lambda: pytest.fail("drift delegated"))
    with pytest.raises(ValueError, match="parent configuration drift"):
        study.preregister_recovery_study()


@pytest.mark.parametrize("field,value", [("token_cap", 1000001), ("theoretical_request_cap", 253),
                                         ("repeats", 1), ("max_output_tokens_per_request", 8192)])
def test_new_config_cannot_expand_registered_limits(tmp_path, monkeypatch, field, value):
    data = json.loads(study.CONFIG.read_text())
    data[field] = value
    copied = tmp_path / "recovery-config.json"
    copied.write_text(json.dumps(data))
    monkeypatch.setattr(study, "CONFIG", copied)
    with pytest.raises(ValueError, match="invalid recovery study scope"):
        study.preregister_recovery_study()


def test_transport_false_must_be_boolean_not_numeric(tmp_path, monkeypatch):
    data = json.loads(study.CONFIG.read_text())
    data["transport"]["stream"] = 0
    copied = tmp_path / "recovery-config.json"
    copied.write_text(json.dumps(data))
    monkeypatch.setattr(study, "CONFIG", copied)
    with pytest.raises(ValueError, match="invalid recovery study scope"):
        study.preregister_recovery_study()


def test_generated_spec_drift_is_rejected_without_mutating_parent_registration(monkeypatch):
    original_reg, original_generated = parent.preregister_study()
    saved = deepcopy(original_reg)
    altered = dict(original_generated)
    altered[parent.INPUTS / "uart_tx_spec.md"] += b"\n"
    monkeypatch.setattr(parent, "preregister_study", lambda: (original_reg, altered))
    with pytest.raises(ValueError, match="parent generated specification drift"):
        study.preregister_recovery_study()
    assert original_reg == saved


def test_default_dry_run_has_no_key_directory_budget_or_execution_effects(monkeypatch, capsys):
    before = study.INPUTS.exists(), study.OUTPUT.exists()
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dry-run read key"))
    monkeypatch.setattr(study, "execute", lambda *a, **k: pytest.fail("dry-run executed"))
    monkeypatch.setattr(study, "TokenBudget", lambda *a, **k: pytest.fail("dry-run created journal"))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("dry-run created directory"))
    assert study.main(["--api-key-file", "missing-unread-fixture"]) == 0
    assert before == (study.INPUTS.exists(), study.OUTPUT.exists())
    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "dry_run" and preview["rows"] == 216
    assert preview["theoretical_requests"] == 252 and preview["round_token_cap"] == 1000000


def arrange_main_paths(tmp_path, monkeypatch, registration):
    reg, generated = registration
    inputs, output = tmp_path / "inputs", tmp_path / "output"
    copied = {inputs / path.name: content for path, content in generated.items()}
    monkeypatch.setattr(study, "INPUTS", inputs)
    monkeypatch.setattr(study, "OUTPUT", output)
    monkeypatch.setattr(study, "preregister_recovery_study", lambda: (deepcopy(reg), copied))
    return inputs, output


@pytest.mark.parametrize("which,kind", [("inputs", "directory"), ("output", "directory"),
                                       ("inputs", "file"), ("output", "file")])
def test_existing_target_refuses_execution_before_key_read(tmp_path, monkeypatch, registration, which, kind):
    inputs, output = arrange_main_paths(tmp_path, monkeypatch, registration)
    target = inputs if which == "inputs" else output
    if kind == "directory":
        target.mkdir()
        (target / "sentinel").write_text("preserve")
    else:
        target.write_text("preserve")
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("existing target read key"))
    monkeypatch.setattr(study, "execute", lambda *a, **k: pytest.fail("existing target executed"))
    assert study.main(["--execute", "--api-key-file", "unread-fixture"]) == 2
    assert (target / "sentinel").read_text() == "preserve" if kind == "directory" else target.read_text() == "preserve"


def test_dangling_input_link_is_rejected_even_when_exists_is_false(tmp_path, monkeypatch, registration):
    inputs, _ = arrange_main_paths(tmp_path, monkeypatch, registration)
    original_link_check = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == inputs or original_link_check(self))
    monkeypatch.setattr(study, "read_key_file", lambda _: pytest.fail("dangling link read key"))
    assert not inputs.exists()
    assert study.main(["--execute", "--api-key-file", "unread-fixture"]) == 2
    assert not inputs.exists()


def test_official_factory_is_lazy_shares_one_book_and_freezes_transport(tmp_path, monkeypatch, registration):
    inputs, output = arrange_main_paths(tmp_path, monkeypatch, registration)
    monkeypatch.setattr(study, "read_key_file", lambda _: "synthetic-unit-fixture")
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *a: pytest.fail("real transport"))
    captured = {}
    def execute(reg, actual_output, **options):
        captured.update(options)
        assert actual_output == output and inputs.is_dir()
        actual_output.mkdir()
        # Provider construction is lazy and does not itself count a request.
        providers = [options["provider_factory"](count) for count in (1, 3)]
        assert all(isinstance(provider, BudgetedProvider) for provider in providers)
        assert providers[0].token_budget is providers[1].token_budget
        for provider, count in zip(providers, (1, 3)):
            assert provider.request_limit == count and provider.request_count == 0
            assert provider.max_output_tokens == 4096 and provider.force_output_limit
            assert provider.thinking_mode == "disabled" and provider.stream is False
            assert provider.timeout == 60 and provider.wire_api == "chat_completions"
            assert provider.base_url == "https://api.deepseek.com"
        assert reg["study"]["limits"]["token_cap"] == 1000000
    monkeypatch.setattr(study, "execute", execute)
    assert study.main(["--execute", "--api-key-file", "synthetic-unread-fixture"]) == 0
    assert captured["provider_factory_record_kind"] == "api_and_local_simulation"
    assert captured["request_cap"] == 252
    assert captured["model"] == "deepseek-flash" and captured["max_output_tokens"] == 4096
    assert captured["thinking_mode"] == "disabled" and captured["wire_api"] == "chat_completions"
    ledger = json.loads((output / "token_budget.json").read_text())
    assert ledger["limit"] == 1000000 and ledger["records"] == []
    assert ledger["totals"]["reported_tokens"] == 0
    assert len(list(inputs.iterdir())) == 4
