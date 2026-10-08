"""Tool detection must reach real UI execution entry points on another machine."""
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from iverilog_ai.core.toolchain import ToolPaths

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tool_ui(monkeypatch, tmp_path):
    # Files are only used to model a different installation, never executed.
    binary_dir = tmp_path / "other-installation" / "bin"
    binary_dir.mkdir(parents=True)
    for name in ("iverilog.exe", "vvp.exe"):
        (binary_dir / name).write_bytes(b"not-an-executable; UI test fixture")
    detected = {"tools": ToolPaths(iverilog=str(binary_dir / "iverilog.exe"),
                                   vvp=str(binary_dir / "vvp.exe"))}
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "0")
    monkeypatch.delenv("IVERILOG_PATH", raising=False)
    monkeypatch.delenv("VVP_PATH", raising=False)
    monkeypatch.setattr("iverilog_ai.ai.local_api_profile.load_local_api_profile", lambda _: None)
    monkeypatch.setattr("iverilog_ai.core.toolchain.locate_tools", lambda: detected["tools"])
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=120)
    app.session_state["planner_setup_complete"] = True
    app.session_state["planner_mode"] = "离线确定性规划器（无需密钥、进程内）"
    app.session_state["case_name"] = "模十计数器"
    yield app, detected
    st.cache_data.clear()


@pytest.mark.parametrize("button", ["run_generated_plan", "run_handwritten_tb"])
def test_detected_foreign_installation_reaches_simulation(tool_ui, monkeypatch, button):
    app, detected = tool_ui
    calls = []

    def pipeline_probe(self, *args, **kwargs):
        calls.append((kwargs["iverilog_path"], kwargs["vvp_path"]))
        raise RuntimeError("UI tool dispatch probe: no simulation executed")

    def executor_probe(self):
        calls.append((self.config.iverilog_path, self.config.vvp_path))
        raise RuntimeError("UI tool dispatch probe: no simulation executed")

    monkeypatch.setattr("iverilog_ai.core.pipeline.VerificationPipeline.run", pipeline_probe)
    monkeypatch.setattr("iverilog_ai.core.executor.IcarusExecutor.run", executor_probe)
    app.run()
    if button == "run_generated_plan":
        app.button(key="generate_plan").click().run()
    app.button(key=button).click().run()
    assert not app.exception
    assert calls == [(detected["tools"].iverilog, detected["tools"].vvp)]
    assert any("UI tool dispatch probe" in item.value for item in app.error)


def test_missing_compiler_stops_before_pipeline_with_actionable_message(tool_ui, monkeypatch):
    app, detected = tool_ui
    detected["tools"] = ToolPaths(vvp=detected["tools"].vvp)
    calls = []
    monkeypatch.setattr("iverilog_ai.core.pipeline.VerificationPipeline.run",
                        lambda *args, **kwargs: calls.append(kwargs))
    app.run()
    app.button(key="generate_plan").click().run()
    app.button(key="run_generated_plan").click().run()
    assert not app.exception
    assert not calls
    assert any("未检测到 Icarus" in item.value and "重新检测工具" in item.value for item in app.error)


def test_refresh_updates_detection_without_discarding_input_or_plan(tool_ui):
    app, detected = tool_ui
    available = detected["tools"]
    detected["tools"] = ToolPaths()
    app.run()
    app.text_area(key="objective_text").set_value("复现电脑检查使能保持与回绕").run()
    app.button(key="generate_plan").click().run()
    plan = app.session_state["ai_plan"].model_dump(mode="json")
    app.radio(key="workspace_page").set_value("工具设置").run()
    assert any("iverilog=未找到" in item.value for item in app.caption)
    detected["tools"] = available
    app.button(key="detect_toolchain").click().run()
    assert not app.exception
    assert any(f"iverilog={available.iverilog}" in item.value for item in app.caption)
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.text_area(key="objective_text").value == "复现电脑检查使能保持与回绕"
    assert app.session_state["ai_plan"].model_dump(mode="json") == plan
