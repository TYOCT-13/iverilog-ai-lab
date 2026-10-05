"""Independent, non-DUT mechanical audit; all writes stay in this review tree.

The caller must first receive the root's stable-source/FROZEN notice. Real API
requests, credential reads and DUT/toolchain execution are prohibited here.
Synthetic providers and pipeline stubs test control flow only, never detection.
Each --attempt directory is exclusive and is retained even when checks fail.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import traceback
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

AGENT_REVISION = "a96933786c17986a739fc2da515db3294d6e8044"
PINNED = {
    "src/iverilog_ai/ai/agent.py": "bf8422840a97ed3360f0dac0ee0621fd605970d658521ce7bec0d57f3c8016ff",
    "src/iverilog_ai/core/observation_feedback.py": "3586fa13bd2ab82668188dac48b1a3055a935ff87d66d6accd600938e1b621d6",
}
SYSTEM_SHA = "3dd3f86f6f15b2367dc8f0913c5f3c7fe646782258093a148170f60200d6a26a"
CASES = ("valid_data_pipeline", "event_accumulator")
STRATEGIES = ("fixed", "random", "protocol_random", "single", "feedback", "no_feedback")
OLD_BATCHES = ("agent-study-1m-live-20261005", "agent-recovery-study-live-20261005",
              "agent-holdout-study-live-20261005", "agent-budget-study-live-20261005",
              "agent-feedback-study-live-20261005")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def refused(callback, expected=(ValueError,)) -> str:
    try:
        callback()
    except expected as exc:
        return str(exc)
    raise AssertionError("the invalid input was accepted")


def forbidden(*args, **kwargs):
    raise AssertionError("forbidden live credential/provider/DUT boundary reached")


def process_guard(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo"}:
        raise AssertionError("network operation prohibited by independent audit")
    if event == "subprocess.Popen":
        executable = Path(str(args[0])).name.lower()
        if executable not in {"git", "git.exe"}:
            raise AssertionError("only read-only Git subprocesses are allowed in this audit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    require(args.attempt.replace("_", "").replace("-", "").isalnum(), "safe attempt name required")
    folder = REVIEW / args.attempt
    folder.mkdir(exist_ok=False)
    began = datetime.now(timezone.utc).isoformat()
    checks = []
    detail = {}
    started_hashes = {}

    def check(name, callback):
        require(name not in {item["name"] for item in checks}, "duplicate mechanical check identity")
        try:
            value = callback()
            checks.append({"name": name, "kind": "non_DUT_mechanical", "status": "passed"})
            if value is not None:
                detail[name] = value
        except Exception as exc:
            checks.append({"name": name, "kind": "non_DUT_mechanical", "status": "failed",
                           "error_type": type(exc).__name__, "error": str(exc),
                           "traceback": traceback.format_exc()})
        print(f"{checks[-1]['status']}: {name}", flush=True)

    try:
        config_path = ROOT / "spec/agent_new_holdout_study_1m_v8.json"
        actual_config = json.loads(config_path.read_bytes())
        require(actual_config.get("freeze_status") == "FROZEN", "audit requires the final FROZEN configuration")
        sys.addaudithook(process_guard)
        entry = importlib.import_module("scripts.run_agent_new_holdout_study")
        comparison = importlib.import_module("scripts.run_agent_comparison")
        agent = importlib.import_module("iverilog_ai.ai.agent")
        transport = importlib.import_module("iverilog_ai.ai.provider")
        references = importlib.import_module("iverilog_ai.core.reference_model")
        baseline = importlib.import_module("benchmarks.agent_new_holdout_20261005.baselines")
        private_accounting = importlib.import_module("scripts.agent_token_budget")
        contracts = importlib.import_module("iverilog_ai.core.contracts")
        Plan = importlib.import_module("iverilog_ai.ai.schema").TestPlan
        with ExitStack() as guard:
            guard.enter_context(patch.object(entry, "read_key_file", forbidden))
            guard.enter_context(patch.object(comparison, "read_key_file", forbidden))
            guard.enter_context(patch("iverilog_ai.ai.local_api_profile.read_key_file", forbidden))
            guard.enter_context(patch("iverilog_ai.core.pipeline.VerificationPipeline.run", forbidden))
            guard.enter_context(patch.object(transport.OpenAICompatibleProvider, "_request", forbidden))
            registration = entry.preregister_new_holdout(require_frozen=True)
            save_new(folder / "registration.json", registration)
            manifest = json.loads(entry.MANIFEST.read_bytes())
            started_hashes = {name: {"sha256": digest((ROOT / name).read_bytes()), "size_bytes": (ROOT / name).stat().st_size}
                              for name in registration["code_and_input_sha256"]}
            save_new(folder / "audited-artifacts.json", started_hashes)
            typed = {case: contracts.DutContract.from_json((ROOT / manifest["cases"][case]["contract_path"]).read_bytes())
                     for case in CASES}

            def anchors():
                entry.validate_frozen_agent()
                for name, expected in PINNED.items():
                    require(digest((ROOT / name).read_bytes()) == expected, "current pinned bytes differ")
                    blob = subprocess.check_output(["git", "show", AGENT_REVISION + ":" + name], cwd=ROOT)
                    require(digest(blob) == expected, "anchored Git blob differs")
                require(digest(agent.SYSTEM_PROMPT.encode("utf-8")) == SYSTEM_SHA, "imported SYSTEM_PROMPT differs")
                require(agent.PROMPT_VERSION == "verification-agent-v8-bounded-port-feedback", "prompt version differs")
            check("anchors.current_and_git_blobs_and_imported_system", anchors)
            for pin_name in PINNED:
                def bad_anchor(pin_name=pin_name):
                    good_sha = entry.sha
                    def changed_sha(path):
                        return "0" * 64 if path == ROOT / pin_name else good_sha(path)
                    with patch.object(entry, "sha", changed_sha):
                        refused(entry.validate_frozen_agent)
                check("anchors.reject_current_drift." + pin_name, bad_anchor)
            check("anchors.reject_system_drift", lambda: _reject_system(entry))

            def geometry():
                rows = registration["rows"]
                identities = [(row["case"], row["variant"], row["seed"], row["strategy"]) for row in rows]
                require(len(rows) == len(set(identities)) == 108, "task identities or denominator differ")
                for strategy in STRATEGIES:
                    selected = [row for row in rows if row["strategy"] == strategy]
                    require(len(selected) == 18, "strategy task denominator differs")
                    require(sum(row["variant"] != "reference" for row in selected) == 12, "defect denominator differs")
                    require(sum(row["variant"] == "reference" for row in selected) == 6, "correct-control denominator differs")
                require(sum(0 if row["strategy"] in STRATEGIES[:3] else 1 if row["strategy"] == "single" else 3 for row in rows) == 126,
                        "shared theoretical request cap differs")
                require(all(row["status"] == "not_started" and row["requests"] == 0 and row["budget_cycles"] == 24 for row in rows),
                        "registration has pre-existing scores or wrong cycle scope")
                for group_start in range(0, 108, 6):
                    group = rows[group_start:group_start + 6]
                    row = group[0]
                    rotation = (row["seed"] + ("reference", "mutation_b", "mutation_c").index(row["variant"]) + CASES.index(row["case"])) % 6
                    require([item["strategy"] for item in group] == list(STRATEGIES[rotation:] + STRATEGIES[:rotation]), "rotation differs")
                return {"unique_rows": 108, "defect_tasks_per_strategy": 12, "correct_tasks_per_strategy": 6, "theoretical_requests": 126}
            check("registration.denominators_request_cap_and_rotation", geometry)
            check("registration.internal_holdout_limits", lambda: _truthful_scope(registration, manifest))
            check("registration.snapshot_set_complete", lambda: _registered_set(ROOT, entry, registration, manifest))
            check("registration.dry_run_has_no_external_access", lambda: _dry_run(entry, folder))

            config_changes = [(field, value) for field, value in {
                "schema": "other", "round_name": "other", "token_cap": 999999,
                "max_output_tokens_per_request": 2048, "max_vectors_per_proposal": 13,
                "max_accepted_vectors_total": 65, "repeats": 2, "registered_rows": 107,
                "theoretical_request_cap": 127, "agent_frozen_from_revision": "0" * 40,
                "agent_prompt_version": "other", "agent_sha256": "0" * 64,
                "observation_feedback_sha256": "0" * 64, "system_prompt_sha256": "0" * 64,
                "strategies": list(STRATEGIES[:-1]), "cycle_budgets": {case: 25 for case in CASES},
                "token_scope": "", "freeze_status": "UNKNOWN", "manifest_sha256": None,
            }.items()]
            config_changes += [("token_cap", True), ("repeats", True), ("max_vectors_per_proposal", 12.0)]
            for index, (field, value) in enumerate(config_changes):
                def invalid_config(index=index, field=field, value=value):
                    data = deepcopy(actual_config)
                    data[field] = value
                    path = folder / "fixtures" / f"config-{index:02d}.json"
                    save_new(path, data)
                    with patch.object(entry, "CONFIG", path):
                        refused(lambda: entry._load_config(require_frozen=True))
                check(f"config.reject.{index:02d}.{field}", invalid_config)
            for field, value in {"endpoint": "https://other.invalid", "model": "other", "wire_api": "responses",
                                 "thinking_mode": "enabled", "stream": True, "store": True,
                                 "timeout_seconds": 61, "automatic_transport_retry": True}.items():
                def invalid_transport(field=field, value=value):
                    data = deepcopy(actual_config)
                    data["transport"][field] = value
                    path = folder / "fixtures" / f"transport-{field}.json"
                    save_new(path, data)
                    with patch.object(entry, "CONFIG", path):
                        refused(lambda: entry._load_config(require_frozen=True))
                check("config.reject_transport." + field, invalid_transport)
            check("config.unfrozen_rejects_before_anchor_credential_output", lambda: _unfrozen(entry, actual_config, folder))

            mutations = {
                "schema": lambda data: data.update(schema="other"),
                "missing_case": lambda data: data["cases"].pop(CASES[1]),
                "extra_case": lambda data: data["cases"].update(extra=deepcopy(data["cases"][CASES[0]])),
                "missing_member": lambda data: data["members"].pop(next(iter(data["members"]))),
                "extra_member": lambda data: data["members"].update({"unexpected.txt": "0" * 64}),
                "bad_member_sha": lambda data: data["members"].update({next(iter(data["members"])): "0" * 64}),
                "bad_member_sha_shape": lambda data: data["members"].update({next(iter(data["members"])): "invalid"}),
                "private_metadata_api_visible": lambda data: data["private_metadata"][0].update(API_visible=True),
                "baseline_path": lambda data: data.update(baseline_factory_path="other.py"),
                "baseline_sha": lambda data: data.update(baseline_factory_sha256="0" * 64),
                "references_sha": lambda data: data.update(reference_functions_sha256="0" * 64),
                "prior_membership_sha": lambda data: data.update(prior_membership_sha256="0" * 64),
            }
            for case in CASES:
                for field, value in {"reference_rtl": "other.v", "contract_path": "other.json", "spec_path": "other.md",
                                     "default_parameters": {"WIDTH": 8}, "cycle_budget": 25,
                                     "max_vectors_per_proposal": 13, "max_accepted_vectors_total": 65,
                                     "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
                                     "reset": {"signal": "i_rstn", "active_level": 1, "synchronous": False, "assert_cycles": 2},
                                     "sampling": "before", "episodes": "continued", "contract_sha256": "0" * 64}.items():
                    mutations[case + "." + field] = lambda data, case=case, field=field, value=value: data["cases"][case].update({field: value})
                mutations[case + ".missing_target"] = lambda data, case=case: data["cases"][case]["targets"].pop()
                mutations[case + ".target_order"] = lambda data, case=case: data["cases"][case]["targets"].reverse()
                mutations[case + ".target_path"] = lambda data, case=case: data["cases"][case]["targets"][1].update(rtl="other.v")
                mutations[case + ".target_sha"] = lambda data, case=case: data["cases"][case]["targets"][1].update(sha256="0" * 64)
            check("manifest.complete_raw_asset_members", lambda: _closed_assets(ROOT, entry, manifest))
            for name, mutate in mutations.items():
                def invalid_manifest(name=name, mutate=mutate):
                    data = deepcopy(manifest)
                    mutate(data)
                    path = folder / "fixtures" / ("manifest-" + name + ".json")
                    save_new(path, data)
                    config = deepcopy(actual_config)
                    config["manifest_sha256"] = digest(path.read_bytes())
                    with patch.object(entry, "MANIFEST", path):
                        refused(lambda: entry._load_manifest(config))
                check("manifest.reject." + name, invalid_manifest)
            check("manifest.identical_json_changed_bytes_rejected", lambda: _manifest_raw_drift(entry, actual_config, manifest, folder))

            for case in CASES:
                for strategy in STRATEGIES[:3]:
                    for seed in range(3):
                        check(f"baseline.public_only_geometry_determinism.{case}.{strategy}.{seed}",
                              lambda case=case, strategy=strategy, seed=seed: _baseline_check(baseline, entry, typed[case], case, strategy, seed, ROOT))
                for mismatch in ("width", "signed", "extra_port", "direction", "parameter", "clock_alias", "clock_period", "clock_edge",
                                 "reset_alias", "reset_polarity", "reset_sync", "reset_length", "initial", "no_clock", "no_reset"):
                    check(f"oracle.reject_fixed_contract.{case}.{mismatch}",
                          lambda case=case, mismatch=mismatch: _contract_reject(references, typed[case], mismatch, Plan, contracts))
                check("oracle.reject_before_x_z_clock_and_unknown_port." + case,
                      lambda case=case: _bad_plans(references, typed[case], Plan))
                check("oracle.name_or_raw_contract_never_authoritative." + case,
                      lambda case=case: _name_only(references, typed[case], Plan))
            check("oracle.manual_pipeline_capture_bubble_flush_reset", lambda: _manual_pipeline(references, typed[CASES[0]], Plan))
            check("oracle.manual_event_permission_clear_wrap_reset", lambda: _manual_event(references, typed[CASES[1]], Plan))
            check("oracle.prior_17_pure_models_anchored_compatibility", lambda: _old_models(ROOT, references, contracts, Plan))

            check("history.five_original_preregs_and_accounting_only", lambda: _actual_history(ROOT, entry, registration))
            for violation in ("unfrozen", "existing_output", "no_explicit_key", "dirty_git", "untracked_input", "revision_drift", "byte_drift", "unfinished_history"):
                check("admission.refuses_before_credentials_provider_output." + violation,
                      lambda violation=violation: _admission(entry, registration, folder, violation))
            for violation in ("absent", "pending", "unfinished", "false_totals"):
                check("history.synthetic_refusal." + violation,
                      lambda violation=violation: _synthetic_history(entry, private_accounting, folder, violation))
            check("history.synthetic_unknown_keeps_full_reservation", lambda: _synthetic_history(entry, private_accounting, folder, "unknown"))
            check("snapshot.all_registered_original_bytes", lambda: _snapshot(comparison, registration, folder))
            check("snapshot.changed_hash_refused_before_new_output", lambda: _snapshot_refusal(comparison, registration, folder))
            check("transport.entry_factory_and_execute_pins", lambda: _entry_transport(entry, registration, folder))
            check("transport.payload_and_attributes", lambda: _payload(transport))
            for error in (transport.ProviderConnectionError("closed without response"), TimeoutError("audit timeout"),
                          transport.ProviderHTTPError(429), ValueError("provider final output text is empty")):
                check("transport.no_auto_retry." + type(error).__name__, lambda error=error: _no_retry(transport, error))
            check("budget.paid_rejection_unknown_and_cap", lambda: _budget(private_accounting, transport, folder))

            scenarios = ("format_recover", "plan_recover", "all_format_rejected", "three_rounds", "early_failure")
            for case in CASES:
                for strategy in STRATEGIES[3:]:
                    for scenario in scenarios:
                        check(f"agent.shared_limits_and_payload.{case}.{strategy}.{scenario}",
                              lambda case=case, strategy=strategy, scenario=scenario: _agent_flow(agent, typed[case], strategy, scenario, ROOT, manifest, folder))
            check("final.registered_bytes_unchanged_after_non_DUT_checks", lambda: _unchanged(ROOT, started_hashes))
            real_git_status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode("utf-8")
            detail["actual_execute_precondition"] = {
                "git_worktree_clean_now": not bool(real_git_status),
                "registered_inputs_committed_and_clean_required_before_API": True,
                "fresh_live_output_exists": entry.OUTPUT.exists(),
                "credential_not_supplied_to_audit": True,
                "API_execution_performed": False,
            }
    except Exception as exc:
        checks.append({"name": "audit.infrastructure_or_final_freeze_precondition", "kind": "non_DUT_mechanical",
                       "status": "failed", "error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()})
    finally:
        counts = Counter(item["status"] for item in checks)
        receipt = {"schema": "independent-internal-new-holdout-prereg-audit-v1", "attempt": args.attempt,
                   "started_at": began, "finished_at": datetime.now(timezone.utc).isoformat(),
                   "auditor_role": "non-implementer same-team machine reviewer; not human/H02", "tool_sha256": digest(Path(__file__).read_bytes()),
                   "unique_checks": len({item["name"] for item in checks}), "non_DUT_checks": len(checks),
                   "passed": counts["passed"], "failed": counts["failed"], "skipped": 0,
                   "actual_API_calls": 0, "real_credential_reads": 0, "actual_DUT_runs": 0,
                   "other_agents_tests_counted": False, "mock_execution_is_functional_evidence": False,
                   "checks": checks, "details": detail}
        save_new(folder / "receipt.json", receipt)
        output_bindings = {path.relative_to(folder).as_posix(): {"sha256": digest(path.read_bytes()), "size_bytes": path.stat().st_size}
                           for path in folder.rglob("*") if path.is_file()}
        save_new(folder / "attempt-artifacts-sha256.json", output_bindings)
        print(json.dumps({key: receipt[key] for key in ("attempt", "unique_checks", "non_DUT_checks", "passed", "failed", "skipped")}), flush=True)
    return 0 if counts["failed"] == 0 else 1


def _reject_system(entry):
    with patch.object(entry, "SYSTEM_PROMPT", "changed"):
        refused(entry.validate_frozen_agent)


def _truthful_scope(reg, manifest):
    require(reg["independent_holdout"] is True and reg["external_independent_holdout"] is False, "holdout booleans differ")
    study = reg["study"]
    require(study["external_blind_holdout"] is False and study["independent_human_review"] is False, "external/human scope overstated")
    require("internal" in study["holdout_level"] and "pretraining" in study["holdout_level"], "meaning of internal holdout not disclosed")
    require(manifest["human_trial"] is False and manifest["independent_human_review"] is False, "asset origin overstated")
    require(manifest["preparation_API_calls"] == 0 and manifest["preparation_is_agent_score"] is False, "preparation conflated with Agent results")
    require(manifest["style_ready"] is False and manifest["WaveDrom_svg_ready"] is False, "failed delivery/rendering misrepresented")


def _registered_set(root, entry, reg, manifest):
    names = set(reg["code_and_input_sha256"])
    required = set(manifest["members"]) | {".gitattributes", entry.CONFIG.relative_to(root).as_posix(), entry.MANIFEST.relative_to(root).as_posix(), entry.PLAN.relative_to(root).as_posix(),
        "scripts/run_agent_new_holdout_study.py", "scripts/run_agent_comparison.py", "scripts/summarize_agent_comparison.py", "scripts/agent_token_budget.py", "scripts/run_strategy_experiment.py",
        "tests/core/test_agent_new_holdout_study.py", "tests/core/test_agent_new_holdout_assets.py", "tests/core/test_agent_new_holdout_oracles.py"}
    required.update(path.relative_to(root).as_posix() for path in (root / "src").rglob("*.py"))
    require(names == required, "source snapshot closure differs")
    require(all(digest((root / name).read_bytes()) == sha for name, sha in reg["code_and_input_sha256"].items()), "registered original digest differs")
    return {"source_and_input_count": len(names), "manifest_member_count": len(manifest["members"])}


def _dry_run(entry, folder):
    output = folder / "dry-run-live-output-must-not-exist"
    with patch.object(entry, "OUTPUT", output), patch.object(entry, "previous_batch_accounting", forbidden), patch.object(entry, "BudgetedProvider", forbidden):
        captured = io.StringIO()
        with redirect_stdout(captured):
            require(entry.main([]) == 0, "dry-run failed")
        require(not output.exists(), "dry-run created the output directory")
        return json.loads(captured.getvalue())


def _unfrozen(entry, actual, folder):
    data = deepcopy(actual)
    data.update(freeze_status="UNFROZEN", manifest_sha256=None)
    path = folder / "fixtures/unfrozen-main.json"
    save_new(path, data)
    output = folder / "unfrozen-output-must-not-exist"
    with patch.object(entry, "CONFIG", path), patch.object(entry, "OUTPUT", output), patch.object(entry, "validate_frozen_agent", forbidden), patch.object(entry, "BudgetedProvider", forbidden):
        captured = io.StringIO()
        with redirect_stdout(captured):
            require(entry.main(["--execute", "--api-key-file", str(folder / "never-open-this-fake-key.txt")]) == 2, "unfrozen execute admitted")
        require("UNFROZEN" in captured.getvalue() and not output.exists(), "refusal did not precede external access")


def _closed_assets(root, entry, manifest):
    actual = entry._asset_files()
    require(set(manifest["members"]) == actual, "manifest omitted or added a formal file")
    require(all(digest((root / name).read_bytes()) == sha for name, sha in manifest["members"].items()), "asset raw-byte mismatch")
    return {"closed_member_count": len(actual)}


def _manifest_raw_drift(entry, actual, manifest, folder):
    path = folder / "fixtures/manifest-same-semantics-different-bytes.json"
    with path.open("xb") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    require(path.read_bytes() != entry.MANIFEST.read_bytes(), "test fixture needs different original bytes")
    with patch.object(entry, "MANIFEST", path):
        require("original bytes" in refused(lambda: entry._load_manifest(actual)), "manifest byte admission missing")


def _baseline_check(baseline, entry, contract, case, strategy, seed, root):
    allowed = (root / f"spec/agent_new_holdout_20261005/{case}_spec.md").resolve()
    original = Path.read_text
    reads = []
    def read_text(path, *args, **kwargs):
        require(path.resolve() == allowed, "baseline read a resource outside the correct public specification")
        reads.append(path.resolve())
        return original(path, *args, **kwargs)
    with patch.object(Path, "read_text", read_text):
        first = entry.holdout_baseline(case, strategy, seed, contract, 24)
        second = entry.holdout_baseline(case, strategy, seed, contract, 24)
    require(reads == [allowed, allowed], "public spec read differs")
    require(first.model_dump() == second.model_dump(), "baseline not seed deterministic")
    require(first.design == case and len(first.vectors) <= 12 and sum(v.cycles for v in first.vectors) == 24, "baseline geometry differs")
    require(all(v.expected == {} and v.sample_phase == "after" for v in first.vectors), "baseline sent expectation/private hint or before sampling")
    if strategy == "random":
        require(len(first.vectors) == 12 and all(v.cycles == 2 for v in first.vectors), "random segment geometry differs")


def _changed_contract(contract, kind, types):
    if kind == "width": return replace(contract, ports=(*contract.ports[:-1], replace(contract.ports[-1], width=2)))
    if kind == "signed": return replace(contract, ports=(*contract.ports[:-1], replace(contract.ports[-1], signed=True)))
    if kind == "extra_port": return replace(contract, ports=(*contract.ports, replace(contract.ports[-1], name="extra")))
    if kind == "direction": return replace(contract, ports=(*contract.ports[:-1], replace(contract.ports[-1], direction=types.PortDirection.INOUT)))
    if kind == "parameter": return replace(contract, parameters={"WIDTH": 8})
    if kind == "clock_alias": return replace(contract, ports=(replace(contract.ports[0], name="clk"), *contract.ports[1:]), clock=replace(contract.clock, signal="clk"))
    if kind == "clock_period": return replace(contract, clock=replace(contract.clock, period_ns=20))
    if kind == "clock_edge": return replace(contract, clock=replace(contract.clock, edge="negedge"))
    if kind == "reset_alias": return replace(contract, ports=(contract.ports[0], replace(contract.ports[1], name="rst_n"), *contract.ports[2:]), reset=replace(contract.reset, signal="rst_n"))
    if kind == "reset_polarity": return replace(contract, reset=replace(contract.reset, active_level=1))
    if kind == "reset_sync": return replace(contract, reset=replace(contract.reset, synchronous=True))
    if kind == "reset_length": return replace(contract, reset=replace(contract.reset, assert_cycles=1))
    if kind == "initial": return replace(contract, ports=(*contract.ports[:-1], replace(contract.ports[-1], initial=0)))
    if kind == "no_clock": return replace(contract, clock=None)
    if kind == "no_reset": return replace(contract, reset=None)
    raise AssertionError("unknown mismatch")


def _make_plan(Plan, case, vectors):
    return Plan.model_validate({"design": case, "objective": "independent non-DUT mechanical audit", "clock_period_ns": 10, "vectors": vectors})


def _contract_reject(ref, contract, mismatch, Plan, types):
    changed = _changed_contract(contract, mismatch, types)
    plan = _make_plan(Plan, contract.module, [{"name": "observe", "inputs": {}, "cycles": 2}])
    require(ref.reference_sampling_profile(changed) is None, "wrong fixed contract became authoritative")
    require(ref.reference_expectations(plan, contract=changed) == {}, "wrong fixed contract returned authority")
    refused(lambda: ref.reference_cycle_expectations(plan, changed), (ref.ReferenceSamplingError,))


def _bad_plans(ref, contract, Plan):
    signal = "i_valid" if contract.module == CASES[0] else "i_event"
    vectors = [{"name": "before", "inputs": {}, "sample_phase": "before"}]
    inputs = ({signal: "1'bx"}, {signal: "1'bz"}, {signal: 2}, {"i_clk": 0}, {"unknown_port": 0})
    bad = [_make_plan(Plan, contract.module, vectors)] + [_make_plan(Plan, contract.module, [{"name": "bad", "inputs": row}]) for row in inputs]
    for plan in bad:
        require(ref.reference_expectations(plan, contract=contract) == {}, "invalid sample returned authority")
        refused(lambda plan=plan: ref.reference_cycle_expectations(plan, contract), (ref.ReferenceSamplingError,))


def _name_only(ref, contract, Plan):
    plan = _make_plan(Plan, contract.module, [{"name": "observe", "inputs": {}}])
    require(ref.reference_expectations(plan) == {}, "name-only call got new authority")
    require(ref.reference_expectations(plan, contract=contract.to_dict()) == {}, "raw contract got new authority")
    require(ref.reference_expectations(plan.model_dump(), contract=contract) == {}, "raw plan got new authority")


def _flatten(table):
    return [row for values in table.values() for row in values]


def _manual_pipeline(ref, contract, Plan):
    plan = _make_plan(Plan, contract.module, [
        {"name": "capture", "inputs": {"i_valid": 1, "i_data": 165}},
        {"name": "deliver", "inputs": {"i_valid": 0}},
        {"name": "bubble", "inputs": {}},
        {"name": "capture_again", "inputs": {"i_valid": 1, "i_data": 60}},
        {"name": "flush", "inputs": {"i_flush": 1}},
        {"name": "release", "inputs": {"i_flush": 0, "i_valid": 0}},
        {"name": "reset", "inputs": {"i_rstn": 0}},
        {"name": "restart", "inputs": {"i_rstn": 1, "i_valid": 1, "i_data": 126}},
        {"name": "drain", "inputs": {"i_valid": 0}}])
    actual = _flatten(ref.reference_cycle_expectations(plan, contract))
    expected = [{"o_valid": valid, "o_data": data} for valid, data in [(0, 0), (1, 165), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (1, 126)]]
    require(actual == expected, "manual pipeline output table differs")


def _manual_event(ref, contract, Plan):
    plan = _make_plan(Plan, contract.module, [
        {"name": "count", "inputs": {"i_enable": 1, "i_event": 1}, "cycles": 17},
        {"name": "permission_off", "inputs": {"i_enable": 0}, "cycles": 2},
        {"name": "clear", "inputs": {"i_clear": 1}},
        {"name": "clear_still", "inputs": {"i_enable": 1}},
        {"name": "resume", "inputs": {"i_clear": 0}, "cycles": 2},
        {"name": "reset", "inputs": {"i_rstn": 0}},
        {"name": "restart", "inputs": {"i_rstn": 1}}])
    actual = [row["o_count"] for row in _flatten(ref.reference_cycle_expectations(plan, contract))]
    require(actual == list(range(1, 16)) + [0, 1, 1, 1, 0, 0, 1, 2, 0, 1], "manual event output table differs")


def _old_models(root, current, types, Plan):
    raw = subprocess.check_output(["git", "show", AGENT_REVISION + ":src/iverilog_ai/core/reference_model.py"], cwd=root)
    old = ModuleType("iverilog_ai.core._audit_anchored_reference")
    old.__package__ = "iverilog_ai.core"
    exec(compile(raw, "<anchored_reference_model>", "exec"), old.__dict__)
    require(set(old.AUTHORITATIVE) == set(current.AUTHORITATIVE) - set(CASES) and len(old.AUTHORITATIVE) == 17, "existing authoritative membership differs")
    for case in sorted(old.AUTHORITATIVE):
        contract = types.DutContract.from_json((root / "examples" / f"{case}_contract.json").read_bytes())
        require(current.INPUT_DEFAULTS[case] == old.INPUT_DEFAULTS[case], "old defaults changed: " + case)
        require(current.reference_sampling_profile(contract) == old.reference_sampling_profile(contract), "old profile changed: " + case)
        rng = random.Random(97031)
        business = [port for port in contract.inputs if not contract.clock or port.name != contract.clock.signal]
        vectors = []
        for index in range(60):
            row = {port.name: rng.randrange(1 << port.width) for port in business}
            if contract.reset: row[contract.reset.signal] = int(index not in {0, 13, 37})
            vectors.append({"name": f"row_{index}", "inputs": row, "cycles": 1 + index % 3})
        plan = _make_plan(Plan, case, vectors)
        require(current.reference_cycle_expectations(plan, contract) == old.reference_cycle_expectations(plan, contract), "old per-cycle model changed: " + case)
        for view in (contract, contract.to_dict(), None):
            require(current.reference_expectations(plan, contract=view) == old.reference_expectations(plan, contract=view), "old vector-end compatibility changed: " + case)
    return {"old_modules_compared": 17, "vectors_per_module": 60, "sampling_modes": ["per_cycle", "vector_end"], "DUT_runs": 0}


def _actual_history(root, entry, reg):
    membership = []
    selected = set(CASES)
    for batch in OLD_BATCHES:
        public_folder = batch.replace("20261005", "2026-10-05")
        path = root / "docs/experiment" / public_folder / "preregistration.json"
        raw = path.read_bytes()
        data = json.loads(raw)
        modules = sorted({row["case"] for row in data["rows"]})
        require(selected.isdisjoint(modules), "new modules overlap a previous registered batch")
        membership.append({"batch": batch, "public_prereg_path": path.relative_to(root).as_posix(), "sha256": digest(raw), "module_set": modules})
    records = entry.previous_batch_accounting()
    require([item["batch"] for item in records] == list(OLD_BATCHES), "historical accounting inventory differs")
    require(all(item["pending_requests"] == 0 and item["finished_at"] and item["historical_usage_charged_to_this_batch"] is False for item in records), "old accounting is not closed")
    require(reg["study"]["limits"]["token_cap"] == 1_000_000, "old usage deducted from new cap")
    return {"old_prereg_module_membership_only": membership, "accounting_only": records,
            "old_scores_used_for_selection": False, "old_score_fields_output": False}


def _admission(entry, registration, folder, violation):
    reg = deepcopy(registration)
    output = folder / ("admission-" + violation + "-new-output")
    key = folder / "never-read-fake-key.txt"
    if violation == "unfrozen": reg["study"]["limits"]["freeze_status"] = "UNFROZEN"
    if violation == "existing_output": output.mkdir()
    if violation == "no_explicit_key": key = None
    if violation == "byte_drift": reg["code_and_input_sha256"]["scripts/run_agent_new_holdout_study.py"] = "0" * 64
    def git(*args):
        if args == ("status", "--porcelain"): return b" M source.py\n" if violation == "dirty_git" else b""
        if args == ("ls-files", "-z"):
            tracked = list(reg["code_and_input_sha256"])
            if violation == "untracked_input": tracked.pop()
            return "\0".join(tracked).encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            return ("0" * 40 if violation == "revision_drift" else reg["study"]["source_revision"]).encode()
        raise AssertionError("unexpected git operation")
    history = lambda: (_ for _ in ()).throw(ValueError("previous registered batch is pending or unfinished"))
    with patch.object(entry, "OUTPUT", output), patch.object(entry, "_git", git), patch.object(entry, "previous_batch_accounting", history if violation == "unfinished_history" else forbidden):
        refused(lambda: entry.execution_admission(reg, key))
    require(output.exists() is (violation == "existing_output"), "invalid admission created the live output")


def _synthetic_history(entry, accounting, folder, violation):
    root = folder / ("history-fixture-" + violation)
    root.mkdir()
    if violation != "absent":
        for batch in OLD_BATCHES:
            work = root / ".iverilog-ai" / batch
            work.mkdir(parents=True)
            journal = work / "token_budget.json"
            budget = accounting.TokenBudget(1_000_000, journal)
            body = {"model": "local-audit", "messages": [{"role": "user", "content": "fixture"}], "stream": False, "thinking": {"type": "disabled"}, "max_tokens": 4096}
            identifier = budget.reserve(body)
            if violation != "pending": budget.settle(identifier, None, attempted=True)
            report = {"finished_at": "" if violation == "unfinished" else "2026-10-05T00:00:00+00:00"}
            save_new(work / "results.json", report)
            if violation == "false_totals":
                data = json.loads(journal.read_bytes())
                data["totals"]["unknown_reserved_tokens"] = 0
                journal.write_bytes((json.dumps(data) + "\n").encode())
    with patch.object(entry, "ROOT", root):
        if violation == "unknown":
            actual = entry.previous_batch_accounting()
            require(len(actual) == 5 and all(item["unknown_usage_requests"] == 1 and item["tokens"]["unknown_reserved_tokens"] > 0
                    and item["unknown_usage_records"][0]["reserved_tokens"] == item["tokens"]["unknown_reserved_tokens"]
                    and item["historical_usage_charged_to_this_batch"] is False for item in actual), "unknown history became zero or deducted new budget")
        else:
            refused(entry.previous_batch_accounting)


def _snapshot(comparison, reg, folder):
    output = folder / "byte-snapshot"
    output.mkdir()
    info = comparison.freeze_registered_inputs(reg, output)
    manifest = json.loads((output / info["path"]).read_bytes())
    require(len(manifest["files"]) == len(reg["code_and_input_sha256"]), "snapshot omitted a registered input")
    require(digest((output / info["path"]).read_bytes()) == info["sha256"], "snapshot manifest receipt differs")
    for item in manifest["files"]:
        require((output / item["copy"]).read_bytes() == (ROOT / item["path"]).read_bytes(), "snapshot newline/raw-byte drift")
    return info


def _snapshot_refusal(comparison, registration, folder):
    reg = deepcopy(registration)
    reg["code_and_input_sha256"]["scripts/run_agent_new_holdout_study.py"] = "0" * 64
    output = folder / "changed-source-must-not-exist"
    with patch.object(comparison, "VerificationPipeline", forbidden):
        refused(lambda: comparison.execute(reg, output))
    require(not output.exists(), "changed hash created execution output")


def _entry_transport(entry, registration, folder):
    calls = {}
    def factory(**kwargs):
        calls["provider"] = kwargs
        return SimpleNamespace()
    def execute(reg, output, **kwargs):
        calls["execute"] = kwargs
        kwargs["provider_factory"](3)
        return {}
    class Budget:
        def __init__(self, limit, journal): calls["budget"] = {"limit": limit, "journal": str(journal)}
        def save(self): pass
    output = folder / "factory-live-output-must-not-exist"
    with (patch.object(entry, "preregister_new_holdout", lambda **kwargs: deepcopy(registration)), patch.object(entry, "execution_admission", lambda *args: []),
         patch.object(entry, "read_key_file", lambda path: "fabricated-local-audit-token"), patch.object(entry, "OUTPUT", output),
         patch.object(entry, "TokenBudget", Budget), patch.object(entry, "BudgetedProvider", factory), patch.object(entry, "execute", execute),
         patch.object(entry, "write", lambda *args: None), patch.object(entry, "build_summary", lambda *args, **kwargs: {})):
        with redirect_stdout(io.StringIO()):
            require(entry.main(["--execute", "--api-key-file", str(folder / "not-a-real-key-file")]) == 0, "synthetic factory route failed")
    provider = calls["provider"]
    expected = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash", "wire_api": "chat_completions", "thinking_mode": "disabled",
                "stream": False, "store": False, "timeout": 60, "max_output_tokens": 4096, "force_output_limit": True,
                "request_limit": 3, "allow_network": True, "reasoning_effort": None}
    require(all(provider.get(key) == value for key, value in expected.items()), "entry provider transport pins differ")
    require(calls["budget"]["limit"] == 1_000_000 and calls["execute"]["request_cap"] == 126, "shared entry budgets differ")
    require(calls["execute"]["baseline_factory"] is entry.holdout_baseline and calls["execute"]["provider_factory_record_kind"] == "api_and_local_simulation", "executor provenance or baseline route differs")
    require(not output.exists(), "stubbed execute unexpectedly created live output")
    return {"provider_pins": expected, "credential_boundary": "fabricated callback only; no file/environment credential read", "execute_boundary": "stub only; no API/DUT execution"}


def _provider(transport):
    return transport.OpenAICompatibleProvider(endpoint="https://api.deepseek.com", model="deepseek-flash", api_key="fabricated-local-audit-token",
        wire_api="chat_completions", thinking_mode="disabled", stream=False, store=False, timeout=60,
        max_output_tokens=4096, force_output_limit=True, request_limit=3, reasoning_effort=None, allow_network=False)


def _payload(transport):
    provider = _provider(transport)
    body = provider._build_body("", streaming=False, messages=[transport.ProviderMessage("system", "fixed-system"), transport.ProviderMessage("user", "public-state")])
    require(body["model"] == "deepseek-flash" and body["stream"] is False and body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 4096, "final transport body differs")
    require(provider.store is False and body.get("store", False) is False and provider.timeout == 60 and provider._endpoint_path() == "/chat/completions", "endpoint/store/timeout differs")
    require("reasoning" not in body and "Authorization" not in body, "payload has inappropriate fields")
    return body


def _no_retry(transport, error):
    provider = _provider(transport)
    with patch.object(provider, "_request", side_effect=error) as request:
        refused(lambda: provider.generate_messages([transport.ProviderMessage("user", "public local fixture")]), (type(error),))
        require(request.call_count == 1 and provider.last_stream_fallback is False, "automatic transport retry occurred")


def _budget(accounting, transport, folder):
    budget = accounting.TokenBudget(1_000_000, folder / "budget-local.json")
    body = _provider(transport)._build_body("", streaming=False, messages=[transport.ProviderMessage("user", "paid rejection fixture")])
    first = budget.reserve(body)
    budget.settle(first, {"prompt_tokens": 101, "completion_tokens": 7, "total_tokens": 108, "prompt_cache_hit_tokens": 99}, attempted=True)
    require(budget.totals()["reported_tokens"] == 108, "paid rejection omitted or cache counted twice")
    second = budget.reserve(body)
    budget.settle(second, None, attempted=True)
    totals = budget.totals()
    require(totals["unknown_reserved_tokens"] == budget.data["records"][second]["reserved_tokens"] > 0, "missing usage became zero")
    require(totals["remaining_tokens"] == 1_000_000 - totals["conservative_total"], "shared budget closure differs")
    small = accounting.TokenBudget(100, folder / "budget-too-small-must-not-exist.json")
    refused(lambda: small.reserve(body), (accounting.TokenBudgetExceeded,))
    require(not small.journal.exists(), "unreservable request wrote a journal")


def _agent_flow(agent, contract, strategy, scenario, root, manifest, folder):
    case = contract.module
    single = strategy == "single"
    feedback = strategy != "no_feedback"
    cap = 1 if single else 3
    inputs = {"i_valid": 1, "i_data": 165} if case == CASES[0] else {"i_enable": 1, "i_event": 1}
    valid = {"action": "append_vectors", "vectors": [{"name": "public", "inputs": inputs, "cycles": 2}], "reason": "public fixture"}
    stop = {"action": "stop", "vectors": [], "reason": "public fixture complete"}
    invalid = {"action": "invalid-action", "vectors": [], "reason": "public fixture"}
    over = deepcopy(valid)
    over["vectors"][0]["cycles"] = 25
    if scenario == "format_recover": actions = [invalid, valid, stop]
    elif scenario == "plan_recover": actions = [over, valid, stop]
    elif scenario == "all_format_rejected": actions = [invalid, invalid, invalid, valid]
    elif scenario == "three_rounds":
        actions = []
        for index in range(3):
            action = deepcopy(valid)
            action["vectors"][0]["inputs"]["i_data" if case == CASES[0] else "i_event"] = index + 1 if case == CASES[0] else index % 2
            action["vectors"][0]["cycles"] = index + 1
            actions.append(action)
    else: actions = [valid, valid, stop]
    class Provider:
        def __init__(self): self.states = []
        def generate(self, prompt):
            state = json.loads(prompt[prompt.index("\nSTATE_JSON:\n") + len("\nSTATE_JSON:\n"):])
            self.states.append(state)
            require(len(self.states) <= cap, "shared request cap exceeded")
            return json.dumps(actions[len(self.states) - 1])
    class Pipeline:
        reference_policy = "builtin"
        def __init__(self): self.plans = []
        def run(self, plan, contract, source, output, **kwargs):
            self.plans.append(plan.model_dump(mode="json"))
            return SimpleNamespace(artifacts={"pipeline_result": str((output / "synthetic-pipeline.json").resolve())})
    provider, pipeline = Provider(), Pipeline()
    output = folder / "synthetic-agent" / f"{case}-{strategy}-{scenario}"
    summary = {"run_id": "synthetic-control-flow-only", "status": "passed", "verdict": "passed", "expectation_source": "reference_model",
               "verification_status": "reference_model", "checks": 2, "failures": int(scenario == "early_failure"), "failure_samples": []}
    coverage = {"status": "unsupported", "compact_model_feedback": {"status": "unsupported", "coverage": None}}
    with (patch.object(agent, "_summary", lambda actual: deepcopy(summary)), patch.object(agent, "analyze_functional_coverage", lambda *args, **kwargs: deepcopy(coverage)),
         patch.object(agent, "build_observation_feedback", lambda *args, **kwargs: {"synthetic_observation": True, "samples": [{"cycle": 0}]})):
        result = agent.run_verification_agent(provider=provider, pipeline=pipeline, contract=contract, rtl_path=root / manifest["cases"][case]["reference_rtl"],
            output_dir=output, objective="independent mechanical control-flow fixture", specification=(root / manifest["cases"][case]["spec_path"]).read_text(encoding="utf-8"),
            limits=agent.AgentLimits(max_rounds=cap, max_requests=cap, max_total_cycles=24, max_vectors=64, max_output_tokens=4096),
            include_feedback=feedback, include_functional_coverage=feedback, agent_plan_mode="independent", execution_options={"reference_sampling": "per_cycle"})
    trace = result.trajectory
    require(trace["requests_attempted"] == len(provider.states) <= cap and len(trace["rounds"]) <= cap, "request/actual round limits differ")
    require(trace["stimulus_cycles_executed"] <= 24 and trace["accepted_vectors"] <= 64, "cumulative cycle/vector limit exceeded")
    for state in provider.states:
        if not feedback:
            require(all(state[key] is None for key in ("observation", "plan_error", "latest_decision_error")), "no_feedback leaked one of its three feedback fields")
        text = json.dumps(state)
        require(not any(token in text for token in ("mutation_b", "mutation_c", "private_metadata", "witness", "benchmarks/", "targets/", "rtl_sha256", "source_revision")), "private resources leaked into API state")
        require(state["contract"] == contract.to_dict() and state["auto_driven_inputs"] == ["i_clk"] and state["supported_sample_phases"] == ["after"], "public contract or driving constraints differ")
        require(state["next_execution"]["fresh_dut_instance"] is True and state["next_execution"]["circuit_state_continues"] is False and state["next_execution"]["automatic_reset"] == contract.reset.to_dict(), "independent episode/reset disclosure differs")
        require(state["max_new_vectors"] <= 12, "proposal vector limit differs")
    if scenario == "all_format_rejected": require(len(provider.states) == cap and not pipeline.plans, "format requests did not share the request cap")
    if scenario in {"format_recover", "plan_recover"}:
        require(len(provider.states) == cap and len(pipeline.plans) == (0 if single else 1), "rejected proposal request not charged to shared cap")
        if feedback and not single:
            field = "latest_decision_error" if scenario == "format_recover" else "plan_error"
            require(provider.states[1][field] is not None and provider.states[2]["observation"] is not None, "positive feedback control did not expose trusted diagnostics")
    if scenario == "three_rounds": require(len(pipeline.plans) == cap and len(provider.states) == cap, "actual round cap differs")
    if scenario == "early_failure": require(len(pipeline.plans) == 1 and len(provider.states) == 1 and trace["stop_reason"] == "counterexample_found", "executor early stop changed in ablation")
    return {"mock_requests": len(provider.states), "stub_pipeline_calls": len(pipeline.plans), "actual_DUT_runs": 0,
            "feedback_fields_None_on_every_no_feedback_state": not feedback, "stop_reason": trace["stop_reason"]}


def _unchanged(root, original):
    require(all((root / name).is_file() and digest((root / name).read_bytes()) == item["sha256"] for name, item in original.items()), "registered artifacts changed during audit")


if __name__ == "__main__":
    raise SystemExit(main())
