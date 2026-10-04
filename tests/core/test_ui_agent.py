"""真实 Streamlit 控件 + HTTP 替身 + 真实 Icarus；不联系外部服务。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
import iverilog_ai.ai.agent as agent
from iverilog_ai.ai.local_api_profile import LocalApiProfile

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("file_credential", [False, True])
def test_api_agent_survives_navigation_and_invalidates_on_input_change(monkeypatch, tmp_path, file_credential):
    if not Path(r"D:\iverilog\bin\iverilog.exe").is_file():
        pytest.skip("local Icarus unavailable")
    actual_run = agent.run_verification_agent
    calls = []
    key_path = tmp_path / "key.txt"
    key_path.write_text("fixture-not-a-real-key", encoding="utf-8")
    profile = LocalApiProfile(endpoint="https://api.example/v1", model="ui-agent-test-fixture",
                              api_key_file=str(key_path), max_output_tokens=8192) if file_credential else None
    monkeypatch.setattr("iverilog_ai.ai.local_api_profile.load_local_api_profile", lambda _: profile)

    def isolated_run(**kwargs):
        kwargs["output_dir"] = tmp_path / "ui-agent"
        kwargs["execution_options"]["allowed_roots"] = (ROOT, tmp_path)
        result = actual_run(**kwargs)
        result.trajectory["record_kind"] = "test_provider"
        result.trajectory_path.write_text(json.dumps(result.trajectory), encoding="utf-8")
        return result

    class Response:
        def __init__(self, answer): self.answer = answer
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(self.answer)}}]}).encode()

    def request(req, timeout):
        body = json.loads(req.data)
        calls.append(body)
        if len(calls) <= 2:
            return Response({"action": "append_vectors", "reason": "test fixture", "vectors": [{"name": "boundary", "inputs": {"enable": 1}, "cycles": 2 if len(calls) == 1 else 13}]})
        return Response({"action": "stop", "reason": "test fixture", "vectors": []})

    monkeypatch.setattr(agent, "run_verification_agent", isolated_run)
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    app = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=120)
    app.session_state["case_name"] = "模十计数器"
    app.run()
    assert app.button(key="run_verification_agent").disabled
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="planner_mode").set_value(app.radio(key="planner_mode").options[2])
    app.text_input(key="provider_api_base").set_value("https://api.example/v1")
    app.text_input(key="provider_api_model").set_value("ui-agent-test-fixture")
    app.selectbox(key="provider_thinking_mode").set_value("关闭")
    if not file_credential:
        app.text_input(key="provider_api_key").set_value("fixture-not-a-real-key")
    else:
        assert app.text_input(key="provider_api_key").value == ""
    app.run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.selectbox(key="agent_plan_mode").value == "independent"
    assert app.checkbox(key="agent_per_cycle_checks").value is True
    app.text_area(key="objective_text").set_value("检查使能保持与回绕").run()
    app.button(key="run_verification_agent").click().run()
    assert not app.exception, [str(x.value) for x in app.exception]
    assert not app.error, [str(x.value) for x in app.error]
    result = app.session_state["workspace_agent_result"]
    assert result.stop_reason == "model_stopped"
    assert len(result.trajectory["rounds"]) == 2
    assert result.trajectory["requests_attempted"] == 3
    assert result.trajectory["objective"] == "检查使能保持与回绕"
    assert result.trajectory["agent_plan_mode"] == "independent"
    assert result.trajectory["reference_sampling"] == "per_cycle"
    assert [sum(v["cycles"] for v in row["plan"]["vectors"]) for row in result.trajectory["rounds"]] == [2, 13]
    assert result.trajectory["stimulus_cycles_executed"] == 15
    assert result.trajectory["limits"]["max_output_tokens"] == (8192 if file_credential else 4096)
    assert all(request["max_tokens"] == (8192 if file_credential else 4096) for request in calls)
    assert all(request["thinking"] == {"type": "disabled"} for request in calls)
    assert result.trajectory["thinking_mode"] == "disabled"
    original_id = app.session_state["last_pipeline_result"].simulation.run_id
    app.radio(key="workspace_page").set_value("运行档案").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.session_state["last_pipeline_result"].simulation.run_id == original_id
    assert app.session_state["workspace_agent_result"].trajectory_path.is_file()
    assert len(calls) == 3
    assert app.selectbox(key="agent_plan_mode").value == "independent"
    assert app.checkbox(key="agent_per_cycle_checks").value is True
    app.selectbox(key="agent_plan_mode").set_value("append").run()
    app.checkbox(key="agent_per_cycle_checks").set_value(False).run()
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.selectbox(key="agent_plan_mode").value == "append"
    assert app.checkbox(key="agent_per_cycle_checks").value is False
    assert app.session_state["last_pipeline_result"].simulation.run_id == original_id
    app.selectbox(key="case_name").set_value("简单 ALU").run()
    assert app.session_state.filtered_state.get("workspace_agent_result") is None
    assert not app.exception


@pytest.mark.parametrize("coverage_feedback", [True, False])
def test_uart_coverage_is_measured_visible_and_feedback_can_be_disabled(monkeypatch, tmp_path, coverage_feedback):
    if not Path(r"D:\iverilog\bin\iverilog.exe").is_file():
        pytest.skip("local Icarus unavailable")
    monkeypatch.setattr("iverilog_ai.ai.local_api_profile.load_local_api_profile", lambda _: None)
    actual_run = agent.run_verification_agent
    states = []

    def isolated_run(**kwargs):
        kwargs["output_dir"] = tmp_path / "ui-uart-agent"
        kwargs["execution_options"]["allowed_roots"] = (ROOT, tmp_path)
        result = actual_run(**kwargs)
        result.trajectory["record_kind"] = "test_provider"
        result.trajectory_path.write_text(json.dumps(result.trajectory), encoding="utf-8")
        return result

    class Response:
        def __init__(self, answer): self.answer = answer
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(self.answer)}}]}).encode()

    def request(req, timeout):
        body = json.loads(req.data)
        state_text = body["messages"][-1]["content"].split("STATE_JSON:")[-1].strip()
        states.append(json.loads(state_text))
        if len(states) == 1:
            return Response({"action": "append_vectors", "reason": "fixture idle", "vectors": [{"name": "idle", "inputs": {"start": 0}, "cycles": 1}]})
        if len(states) == 2:
            return Response({"action": "append_vectors", "reason": "fixture full frame", "vectors": [
                # The new episode starts from reset; coverage needs a measured
                # idle predecessor and never borrows the previous run's sample.
                {"name": "episode_idle", "inputs": {"start": 0}, "cycles": 1},
                {"name": "request", "inputs": {"start": 1, "data_in": 150}, "cycles": 1},
                {"name": "finish", "inputs": {"start": 0}, "cycles": 40}]})
        return Response({"action": "stop", "reason": "fixture complete", "vectors": []})

    monkeypatch.setattr(agent, "run_verification_agent", isolated_run)
    monkeypatch.setattr("iverilog_ai.ai.provider.build_opener", lambda *args: SimpleNamespace(open=request))
    app = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=120)
    app.session_state["case_name"] = "UART 发送器"
    app.run()
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="planner_mode").set_value(app.radio(key="planner_mode").options[2])
    app.text_input(key="provider_api_base").set_value("https://api.example/v1")
    app.text_input(key="provider_api_model").set_value("ui-uart-fixture")
    app.text_input(key="provider_api_key").set_value("fixture-not-a-real-key")
    app.run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert not app.checkbox(key="agent_coverage_feedback").disabled
    app.checkbox(key="agent_coverage_feedback").set_value(coverage_feedback).run()
    app.button(key="run_verification_agent").click().run()
    assert not app.exception and not app.error
    result = app.session_state["workspace_agent_result"]
    coverage = result.trajectory["rounds"][-1]["functional_coverage"]
    assert coverage["status"] == "measured" and "uart.complete_frame" in coverage["observed"]
    assert any(item.value == "功能场景" or "功能场景" in item.value for item in app.markdown)
    assert "functional_coverage" in states[1]["observation"] if coverage_feedback else "functional_coverage" not in states[1]["observation"]
    app.radio(key="workspace_page").set_value("运行档案").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.checkbox(key="agent_coverage_feedback").value == coverage_feedback
    assert app.session_state["workspace_agent_result"].trajectory["rounds"][-1]["functional_coverage"] == coverage
    assert len(states) == 3
