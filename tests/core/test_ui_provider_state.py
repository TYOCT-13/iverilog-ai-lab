"""规则审查先于设置面板执行，也必须使用当前会话的规划器配置。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit", reason="未安装 streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402
import iverilog_ai.ai as ai  # noqa: E402


APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"


@pytest.mark.parametrize(
    "mode_index,wire_label,endpoint,picked_model,expected_wire,expected_reasoning",
    [
        (0, "Chat Completions API", "https://audit.invalid/v1", None, None, None),
        (1, "Responses API", "https://audit.invalid/v1", None, "chat_completions", None),
        (2, "Chat Completions API", "https://audit.invalid/v1", None, "chat_completions", None),
        (2, "Responses API", "https://audit.invalid/v1", None, "responses", "high"),
        (2, "Responses API", "https://api.deepseek.com", None, "chat_completions", None),
        (2, "Responses API", "https://audit.invalid/v1", "listed-audit-model", "responses", "high"),
    ],
)
def test_static_advice_uses_current_provider_settings_before_settings_render(
    monkeypatch, mode_index, wire_label, endpoint, picked_model, expected_wire, expected_reasoning,
):
    """通过真实控件设置配置、跨页后调用；构造与建议均替身，不发网络请求。"""

    created = []
    advised = []

    def provider_factory(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(model=kwargs["model"], last_usage=None)

    def review_advice(provider, review, **kwargs):
        advised.append(provider)
        return ai.offline_review_advice(review), {
            "source": "online_model",
            "attempts": 1,
            "included_code_snippets": kwargs["include_snippets"],
            "review_sha256": review["source_sha256"],
            "dropped_unknown_rule_ids": [],
        }

    monkeypatch.setattr(ai, "OpenAICompatibleProvider", provider_factory)
    monkeypatch.setattr(ai, "advise_on_static_review", review_advice)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "模十计数器"
    if picked_model:
        app.session_state["available_models"] = [picked_model]
    app.run()
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="planner_mode").set_value(app.radio(key="planner_mode").options[mode_index])
    app.text_input(key="provider_debug_endpoint").set_value("http://127.0.0.1:19191/v1")
    app.text_input(key="provider_api_base").set_value(endpoint)
    app.text_input(key="provider_api_model").set_value("typed-audit-model")
    app.text_input(key="provider_api_key").set_value("audit-placeholder-not-a-real-secret")
    app.slider(key="provider_api_timeout").set_value(190)
    app.slider(key="provider_api_output_tokens").set_value(5120)
    app.selectbox(key="provider_wire_api").set_value(wire_label)
    app.selectbox(key="provider_reasoning").set_value("high")
    if picked_model:
        app.selectbox(key="picked_model_from_list").set_value(picked_model)
    app.run()
    app.radio(key="workspace_page").set_value("规则审查").run()
    app.button(key="run_static_rtl_review").click().run()
    app.button(key="run_static_review_advice").click().run()

    assert not app.exception, [str(item.value) for item in app.exception]
    assert not app.error, [str(item.value) for item in app.error]
    assert app.session_state["static_review_advice"]["priorities"]
    if mode_index == 0:
        assert not created and not advised
        assert app.session_state["static_review_advice_meta"]["source"] == "offline_rules"
        return

    assert len(created) == len(advised) == 1
    configuration = created[0]
    assert configuration["wire_api"] == expected_wire
    assert configuration["reasoning_effort"] == expected_reasoning
    assert configuration["store"] is False
    if mode_index == 1:
        assert configuration["endpoint"] == "http://127.0.0.1:19191/v1"
        assert configuration["model"] == "debug-local"
        assert configuration["allow_network"] is False
        assert "api_key" not in configuration
    else:
        assert configuration["endpoint"] == endpoint
        assert configuration["model"] == (picked_model or "typed-audit-model")
        assert configuration["api_key"] == "audit-placeholder-not-a-real-secret"
        assert configuration["timeout"] == 190
        assert configuration["max_output_tokens"] == 5120
        assert configuration["allow_network"] is True

    app.radio(key="workspace_page").set_value("工具设置").run()
    assert app.text_input(key="provider_api_base").value == endpoint
    assert app.selectbox(key="provider_wire_api").value == wire_label
