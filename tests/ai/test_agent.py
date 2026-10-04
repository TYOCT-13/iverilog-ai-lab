"""合成 Provider 用于测试控制流；真实 Icarus 测试只读取仓库现有 RTL。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentDecision, AgentLimits, AgentObservation, run_verification_agent
from iverilog_ai.ai.debug_provider import offline_provider
from iverilog_ai.ai.planner import plan_tests
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        answer = self.responses.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def append(cycles=1, **extra):
    return {"action": "append_vectors", "reason": "boundary", "vectors": [
        {"name": "next", "inputs": {"enable": 1}, "cycles": cycles, **extra}]}


class Pipeline:
    def __init__(self, *, failures=0, source="reference_model", status="passed"):
        self.failures = failures
        self.source = source
        self.status = status
        self.plans = []

    def run(self, plan, contract, rtl, output, **kwargs):
        self.plans.append(plan.model_dump(mode="json"))
        sim = SimpleNamespace(run_id=f"run-{len(self.plans)}", status=SimpleNamespace(value=self.status),
                              verdict="failed_checks" if self.failures else "passed", records=[1, 2],
                              config={"oracle": {"expectation_source": self.source}},
                              failures=[SimpleNamespace(to_dict=lambda: {"cycle": 1, "signal": "count", "actual": 9})] * self.failures)
        return SimpleNamespace(simulation=sim, artifacts={"pipeline_result": str(output.resolve() / "pipeline_result.json")}, plan=plan)


def run(tmp_path, provider, pipeline=None, **kwargs):
    return run_verification_agent(
        provider=provider, contract=DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text())),
        rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "agent", objective="find boundaries",
        pipeline=pipeline or Pipeline(), **kwargs)


def test_iterates_and_keeps_old_vectors_and_round_artifacts(tmp_path):
    provider = Scripted(append(1), append(2), {"action": "stop", "reason": "enough", "vectors": []})
    pipeline = Pipeline()
    result = run(tmp_path, provider, pipeline)
    assert len(pipeline.plans) == 2
    assert pipeline.plans[1]["vectors"][:1] == pipeline.plans[0]["vectors"]
    assert result.stop_reason == "model_stopped"
    assert result.trajectory["stimulus_cycles_executed"] == 4
    assert "observation" in provider.prompts[1]
    assert result.trajectory["record_kind"] == "test_provider"
    assert json.loads(result.trajectory_path.read_text())["requests_attempted"] == 3


@pytest.mark.parametrize("decision", [append(expected={"count": 4}), {"action": "shell", "reason": "x", "vectors": []},
                                      {"action": "stop", "reason": "x", "vectors": [], "command": "calc"}])
def test_rejects_model_judges_commands_and_unknown_fields(tmp_path, decision):
    pipeline = Pipeline()
    result = run(tmp_path, Scripted(decision), pipeline)
    assert result.stop_reason == "policy_error"
    assert not pipeline.plans


@pytest.mark.parametrize("budget,expected", [
    ({"max_requests": 1}, "request_budget"), ({"max_rounds": 1}, "round_budget"),
    ({"max_total_cycles": 1}, "cycle_budget"), ({"max_vectors": 1}, "vector_budget")])
def test_resource_budgets_bound_calls_and_replayed_cycles(tmp_path, budget, expected):
    provider = Scripted(append(1), append(2), append(3))
    pipeline = Pipeline()
    result = run(tmp_path, provider, pipeline, limits=AgentLimits(**budget))
    assert result.stop_reason == expected
    assert len(pipeline.plans) == 1
    assert len(provider.prompts) <= 2


def test_confirmed_failure_stops_without_trying_to_make_it_pass(tmp_path):
    provider = Scripted(append())
    result = run(tmp_path, provider, Pipeline(failures=1, status="passed_with_warnings"))
    assert result.stop_reason == "counterexample_found"
    assert len(provider.prompts) == 1


@pytest.mark.parametrize("source", ["ai_generated", "none_given", "unknown"])
def test_untrusted_or_missing_oracle_never_claims_confirmed_defect(tmp_path, source):
    result = run(tmp_path, Scripted(append()), Pipeline(failures=1, source=source))
    assert result.stop_reason == "insufficient_evidence"


def test_compile_failure_is_not_a_detected_functional_defect(tmp_path):
    result = run(tmp_path, Scripted(append()), Pipeline(status="compile_failed"))
    assert result.stop_reason == "execution_error"


def test_repeated_inputs_terminate_even_when_names_change(tmp_path):
    result = run(tmp_path, Scripted(append(), append()))
    assert result.stop_reason == "repeated_action"
    assert len(result.trajectory["rounds"]) == 1


def test_errors_do_not_retry_or_leak_exception_details(tmp_path):
    result = run(tmp_path, Scripted(RuntimeError("secret-token-value")))
    assert result.stop_reason == "policy_error"
    assert result.trajectory["requests_attempted"] == 1
    assert "secret-token-value" not in result.trajectory_path.read_text()


def test_credential_in_response_is_not_saved(tmp_path):
    provider = Scripted('{"action":"stop","reason":"secret-key","vectors":[]}')
    provider.api_key = "secret-key"
    result = run(tmp_path, provider)
    assert result.stop_reason == "policy_error"
    assert "secret-key" not in result.trajectory_path.read_text()


def test_existing_output_is_never_overwritten(tmp_path):
    (tmp_path / "agent").mkdir()
    with pytest.raises(ValueError, match="must be new"):
        run(tmp_path, Scripted())


def test_initial_plan_is_retained_without_extra_generation_call(tmp_path):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    plan = plan_tests("test", contract.module, offline_provider(contract, vector_count=2))
    original = plan.model_dump(mode="json")
    result = run(tmp_path, Scripted(), Pipeline(failures=1), initial_plan=plan)
    assert plan.model_dump(mode="json") == original
    assert result.trajectory["requests_attempted"] == 0
    assert result.trajectory["initial_plan_source"] == "provided"


def test_interruption_preserves_completed_rounds(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, Scripted(append(), KeyboardInterrupt()))
    trace = json.loads((tmp_path / "agent/agent_trajectory.json").read_text())
    assert len(trace["rounds"]) == 1
    assert trace["stop_reason"] == "interrupted"


def test_http_transport_budget_and_output_cap_are_enforced(tmp_path, monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(append())}}]}).encode()
    def request(req, timeout):
        calls.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    provider = OpenAICompatibleProvider(endpoint="https://api.example/v1", model="test", api_key="secret", allow_network=True, wire_api="chat_completions")
    result = run(tmp_path, provider, limits=AgentLimits(max_requests=1, max_output_tokens=256))
    assert result.stop_reason == "request_budget"
    assert len(calls) == 1
    assert calls[0].get("max_tokens", calls[0].get("max_completion_tokens")) == 256
    assert "secret" not in result.trajectory_path.read_text()


@pytest.mark.parametrize("rtl,expected", [("mod10_counter.v", "round_budget"), ("mod10_counter_bug_wrap9.v", "counterexample_found")])
def test_real_icarus_existing_rtl(tmp_path, rtl, expected):
    compiler = Path(r"D:\iverilog\bin\iverilog.exe")
    runtime = Path(r"D:\iverilog\bin\vvp.exe")
    if not compiler.is_file():
        pytest.skip("Icarus unavailable in this test environment")
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    result = run_verification_agent(provider=Scripted(append(16)), contract=contract,
        rtl_path=ROOT / "rtl" / rtl, output_dir=tmp_path / "real", objective="counter wraparound",
        limits=AgentLimits(max_rounds=1), execution_options={"allowed_roots": (ROOT, tmp_path),
        "iverilog_path": compiler, "vvp_path": runtime})
    assert result.stop_reason == expected
    assert result.last_result is not None
    assert result.last_result.simulation.records
    assert result.last_result.testbench_path.is_file()


def test_limits_reject_bools_and_out_of_bounds():
    for kwargs in [{"max_rounds": True}, {"max_requests": 0}, {"max_total_cycles": -1}]:
        with pytest.raises(ValueError):
            AgentLimits(**kwargs)


def test_invalid_response_keeps_usage_and_safe_diagnostic_codes(tmp_path):
    provider = Scripted('{"action": "append_vectors", "reason": "brief", "vectors": [], "private-field": 1}')
    provider.last_usage = {"prompt_tokens": 23, "completion_tokens": 5}
    result = run(tmp_path, provider)
    decision = result.trajectory["decisions"][0]
    assert result.stop_reason == "policy_error"
    assert decision["usage"] == {"prompt_tokens": 23, "completion_tokens": 5}
    assert "extra_forbidden" in decision["validation_error_types"]
    assert "private-field" not in result.trajectory_path.read_text()


def test_truncated_response_is_never_executed_even_if_json_parses(tmp_path):
    provider = Scripted(append())
    provider.last_finish_reason = "length"
    provider.last_usage = {"completion_tokens": 4096}
    pipeline = Pipeline()
    result = run(tmp_path, provider, pipeline)
    assert result.stop_reason == "output_truncated"
    assert result.trajectory["decisions"][0]["usage"]["completion_tokens"] == 4096
    assert not pipeline.plans


def test_no_feedback_ablation_hides_observations_but_preserves_actual_evidence(tmp_path):
    for enabled in (True, False):
        provider = Scripted(append(1), append(2))
        result = run(tmp_path / str(enabled), provider, limits=AgentLimits(max_rounds=2), include_feedback=enabled)
        state = json.loads(provider.prompts[1].split("STATE_JSON:\n", 1)[1])
        assert bool(state["observation"]) is enabled
        assert state["current_plan"]["vectors"]
        assert len(result.trajectory["rounds"]) == 2
        assert result.trajectory["rounds"][0]["observation"]["checks"] == 2
        assert result.trajectory["feedback_enabled"] is enabled


def differential_observer(*, differences=0, samples=2, source="qualified_baseline_differential",
                          outputs=None):
    """Synthetic observations exercise the gate; these are not external evidence."""
    import hashlib
    candidate = hashlib.sha256((ROOT / "rtl/mod10_counter.v").read_bytes()).hexdigest()
    def observe(result):
        return AgentObservation(
            status="passed", verdict="behavior_difference" if differences else "no_observed_difference",
            expectation_source=source, verification_status="qualified_baseline_differential",
            compared_samples=samples, differences=differences,
            qualified_outputs=["count"] if outputs is None else outputs,
            qualification_sha256="a" * 64, baseline_sha256="b" * 64, candidate_sha256=candidate)
    return observe


def test_qualified_output_difference_has_its_own_verdict_and_paired_budget(tmp_path):
    result = run(tmp_path, Scripted(append()), Pipeline(source="none_given"),
                 round_observer=differential_observer(differences=1), simulation_multiplier=2)
    assert result.stop_reason == "behavior_difference"
    row = result.trajectory["rounds"][0]
    assert row["observation"]["checks"] == row["observation"]["failures"] == 0
    assert row["observation"]["differences"] == 1
    assert row["stimulus_cycles"] == 2
    assert result.trajectory["candidate_stimulus_cycles_executed"] == 1
    assert result.trajectory["baseline_stimulus_cycles_executed"] == 1


@pytest.mark.parametrize("kwargs", [{"samples": 0}, {"source": "ai_generated"}, {"outputs": ["internal_state"]}])
def test_unqualified_differential_observation_stops_without_confirmed_defect(tmp_path, kwargs):
    result = run(tmp_path, Scripted(append()), round_observer=differential_observer(**kwargs),
                 simulation_multiplier=2)
    assert result.stop_reason == "insufficient_evidence"


def test_paired_replay_budget_is_charged_before_another_api_request(tmp_path):
    provider = Scripted(append(), append(2))
    result = run(tmp_path, provider, round_observer=differential_observer(), simulation_multiplier=2,
                 limits=AgentLimits(max_total_cycles=2))
    assert result.stop_reason == "cycle_budget"
    assert result.trajectory["stimulus_cycles_executed"] == 2
    assert len(provider.prompts) == 1


def test_differential_observation_cannot_relabel_samples_as_assertions():
    with pytest.raises(ValueError, match="not assertion checks"):
        AgentObservation(status="passed", verdict="behavior_difference",
                         expectation_source="qualified_baseline_differential", checks=10)


def test_unsupported_clocked_sampling_is_reported_as_missing_evidence(tmp_path):
    compiler = Path(r"D:\iverilog\bin\iverilog.exe")
    runtime = Path(r"D:\iverilog\bin\vvp.exe")
    if not compiler.is_file():
        pytest.skip("Icarus unavailable in this test environment")
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    provider = Scripted(append(2, sample_phase="before"))
    result = run_verification_agent(provider=provider, contract=contract,
        rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "real-before", objective="sampling gate",
        execution_options={"allowed_roots": (ROOT, tmp_path), "iverilog_path": compiler, "vvp_path": runtime})
    assert result.stop_reason == "insufficient_evidence"
    assert result.last_result.simulation.check_count == 0
    assert result.trajectory["rounds"][0]["observation"]["expectation_source"] == "none_given"
    state = json.loads(provider.prompts[0].split("STATE_JSON:\n", 1)[1])
    assert state["supported_sample_phases"] == ["after"]


def test_real_counter_holds_omitted_enable_input(tmp_path):
    compiler = Path(r"D:\iverilog\bin\iverilog.exe")
    runtime = Path(r"D:\iverilog\bin\vvp.exe")
    if not compiler.is_file():
        pytest.skip("Icarus unavailable in this test environment")
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text()))
    plan = Plan.model_validate({
        "design": contract.module, "objective": "hold input", "vectors": [
            {"name": "enable", "inputs": {"enable": 1}, "cycles": 1},
            {"name": "hold", "inputs": {}, "cycles": 2}]})
    result = run_verification_agent(provider=Scripted(), contract=contract,
        rtl_path=ROOT / "rtl/mod10_counter.v", output_dir=tmp_path / "held-input", objective="hold input",
        initial_plan=plan, limits=AgentLimits(max_rounds=1),
        execution_options={"allowed_roots": (ROOT, tmp_path), "iverilog_path": compiler, "vvp_path": runtime})
    assert result.stop_reason == "round_budget"
    assert result.last_result.simulation.check_count == 2
    assert not result.last_result.simulation.failures


def test_real_functional_feedback_ablation_keeps_sampling_and_trace_without_leaks(tmp_path):
    compiler = Path("D:/iverilog/bin/iverilog.exe")
    runtime = Path("D:/iverilog/bin/vvp.exe")
    if not compiler.is_file() or not runtime.is_file():
        pytest.skip("Icarus unavailable")
    contract = DutContract.from_dict(json.loads((ROOT / "examples/uart_tx_contract.json").read_text()))
    first = {"action": "append_vectors", "reason": "start an observed frame", "vectors": [
        {"name": "idle", "inputs": {}, "cycles": 1},
        {"name": "start", "inputs": {"start": 1, "data_in": 150}, "cycles": 1},
        {"name": "short", "inputs": {"start": 0}, "cycles": 2}]}
    follow = {"action": "append_vectors", "reason": "observe terminal symbol", "vectors": [
        {"name": "long", "inputs": {}, "cycles": 41}]}
    providers = []
    for feedback, coverage in ((True, True), (True, False), (False, False)):
        provider = Scripted(first, follow)
        providers.append(provider)
        result = run_verification_agent(provider=provider, contract=contract,
            rtl_path=ROOT / "rtl/uart_tx.v", output_dir=tmp_path / f"feedback-{feedback}-{coverage}",
            objective="observe a UART frame", limits=AgentLimits(max_rounds=2, max_total_cycles=128),
            include_feedback=feedback, include_functional_coverage=coverage,
            execution_options={"allowed_roots": (ROOT, tmp_path), "iverilog_path": compiler,
                               "vvp_path": runtime, "max_output_chars": 2_000_000})
        assert result.stop_reason == "round_budget"
        rows = result.trajectory["rounds"]
        assert rows[0]["functional_coverage"]["status"] == "measured"
        assert "uart.complete_frame" in rows[0]["functional_coverage"]["unknown"]
        assert "uart.complete_frame" in rows[1]["functional_coverage"]["observed"]
        assert rows[0]["observation"]["functional_coverage"] == rows[0]["functional_coverage"]
        state = json.loads(provider.prompts[1].split("STATE_JSON:\n", 1)[1])
        assert bool(state["observation"]) is feedback
        if feedback:
            assert ("functional_coverage" in state["observation"]) is coverage
            if coverage:
                compact = state["observation"]["functional_coverage"]
                assert compact == rows[0]["functional_coverage"]["compact_model_feedback"]
                assert "first_evidence" not in json.dumps(compact)
                assert "samples" not in json.dumps(compact)
                assert compact["observed"]
                assert any(b["first_cycle"] is not None for b in compact["bins"])
        else:
            assert state["observation"] is None
        # Correctness checks remain endpoint checks; these are not the 45 observed samples.
        assert rows[1]["observation"]["checks"] == 8
        assert rows[1]["functional_coverage"]["observed_cycles"] == 45
        assert result.trajectory["stimulus_cycles_executed"] == 49
        assert result.trajectory["functional_coverage_feedback_enabled"] is coverage
    assert providers[0].prompts[0] == providers[1].prompts[0] == providers[2].prompts[0]


@pytest.mark.parametrize("value", [1, "false", None])
def test_functional_feedback_switch_rejects_non_booleans_before_execution(tmp_path, value):
    with pytest.raises(ValueError, match="include_functional_coverage must be a boolean"):
        run(tmp_path, Scripted(), include_functional_coverage=value)
    assert not (tmp_path / "agent").exists()


def test_typed_external_observer_is_not_augmented_with_builtin_coverage(tmp_path):
    provider = Scripted(append(), append(2))
    result = run(tmp_path, provider, round_observer=differential_observer(), simulation_multiplier=2,
                 limits=AgentLimits(max_rounds=2))
    row = result.trajectory["rounds"][0]
    assert "functional_coverage" not in row["observation"]
    assert row["functional_coverage"]["status"] == "unsupported"
    state = json.loads(provider.prompts[1].split("STATE_JSON:\n", 1)[1])
    assert "functional_coverage" not in state["observation"]
