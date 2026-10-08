"""Fresh sessions choose a planner; configuration and task navigation stay local."""
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "ui/app.py"


@pytest.fixture(autouse=True)
def no_external_requests(monkeypatch):
    monkeypatch.setattr("iverilog_ai.ai.local_api_profile.load_local_api_profile", lambda _: None)
    monkeypatch.setenv("IVERILOG_AI_ALLOW_NETWORK", "0")

    def forbidden(*args, **kwargs):
        raise AssertionError("Opening or configuring a page must not request a model")

    monkeypatch.setattr("iverilog_ai.ai.provider.OpenAICompatibleProvider.generate", forbidden)
    monkeypatch.setattr("iverilog_ai.ai.provider.OpenAICompatibleProvider.list_models", forbidden)


def fresh_app():
    return AppTest.from_file(str(APP), default_timeout=120).run()


def open_config(index=2):
    app = fresh_app()
    selector = app.radio(key="startup_planner_mode")
    selector.set_value(selector.options[index])
    app.button(key="complete_planner_setup").click().run()
    assert not app.exception
    return app


def test_fresh_session_defaults_online_and_prompts_once():
    app = fresh_app()
    assert app.radio(key="startup_planner_mode").value.startswith("在线")
    assert not any(item.key == "workspace_page" for item in app.radio)
    app.button(key="complete_planner_setup").click().run()
    assert not app.exception
    assert app.radio(key="workspace_page").value == "工具设置"
    assert app.radio(key="planner_mode").value.startswith("在线")
    app.run()
    assert not any(item.key == "startup_planner_mode" for item in app.radio)
    other = fresh_app()
    assert other.radio(key="startup_planner_mode").value.startswith("在线")


@pytest.mark.parametrize("index", [0, 1, 2])
def test_selected_mode_opens_only_its_configuration(index):
    app = open_config(index)
    keys = {item.key for item in app.text_input}
    api_keys = {"provider_api_base", "provider_api_model", "provider_api_key"}
    assert (api_keys <= keys) if index == 2 else api_keys.isdisjoint(keys)
    assert ("provider_debug_endpoint" in keys) == (index == 1)
    if index != 2:
        assert not any(item.label in {"检查配置", "读取模型列表"} for item in app.button)
        assert not any(str(item.key).startswith("provider_api") for item in app.slider)
    app.button(key="planner_settings_to_workspace").click().run()
    assert not app.exception
    assert app.radio(key="workspace_page").value == "工作台"


def test_api_and_debug_values_survive_mode_and_page_changes():
    app = open_config()
    app.text_input(key="provider_api_base").set_value("https://test.invalid/v1")
    app.text_input(key="provider_api_model").set_value("fixture-model")
    app.text_input(key="provider_api_key").set_value("fixture-only-no-real-key")
    app.slider(key="provider_api_timeout").set_value(190)
    app.run()
    modes = app.radio(key="planner_mode").options
    app.radio(key="planner_mode").set_value(modes[0]).run()
    assert not any(item.key == "provider_api_key" for item in app.text_input)
    app.radio(key="planner_mode").set_value(modes[1]).run()
    app.text_input(key="provider_debug_endpoint").set_value("http://127.0.0.1:19191/v1").run()
    app.radio(key="workspace_page").set_value("规则审查").run()
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="planner_mode").set_value(modes[2]).run()
    assert not app.exception
    assert app.text_input(key="provider_api_base").value == "https://test.invalid/v1"
    assert app.text_input(key="provider_api_model").value == "fixture-model"
    assert app.text_input(key="provider_api_key").value == "fixture-only-no-real-key"
    assert app.slider(key="provider_api_timeout").value == 190
    app.radio(key="planner_mode").set_value(modes[1]).run()
    assert app.text_input(key="provider_debug_endpoint").value == "http://127.0.0.1:19191/v1"


def test_task_selector_only_exists_in_workbench_and_keeps_selection():
    app = open_config(0)
    app.button(key="planner_settings_to_workspace").click().run()
    scenario = app.radio(key="ui_scenario")
    picked = "对比两份 RTL（AI 改写验收 / 开源行为回归）"
    scenario.set_value(picked).run()
    for page in ["规则审查", "运行档案", "工具设置", "使用手册", "项目概览"]:
        app.radio(key="workspace_page").set_value(page).run()
        assert not app.exception
        assert not any(item.key == "ui_scenario" for item in app.radio)
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.radio(key="ui_scenario").value == picked
