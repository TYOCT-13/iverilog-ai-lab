"""合成 Provider 用于测试控制流；真实 Icarus 测试只读取仓库现有 RTL。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.ai.agent import AgentDecision, AgentLimits, run_verification_agent
from iverilog_ai.ai.debug_provider import offline_provider
from iverilog_ai.ai.planner import plan_tests
from iverilog_ai.ai.provider import OpenAICompatibleProvider
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
