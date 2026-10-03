"""DUT replacement must invalidate evidence without resetting provider settings."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "ui" / "app.py"


class State(dict):
    def __getattr__(self, key: str) -> Any:
        return self[key]

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def _helpers():
    """Load side-effect-free lifecycle helpers, without mounting the whole app."""
    names = {
        "_content_fingerprint", "_uploaded_files_key", "_clear_input_evidence",
        "_invalidate_custom_contract", "_sync_workspace_input", "_sync_comparison_input",
        "_set_contract_editor", "_replace_custom_contract_draft", "_clear_custom_upload",
        "_compile_options", "_sync_vcd_input",
    }
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    state = State()
    scope = {"Path": Path, "ROOT": ROOT, "Any": Any, "hashlib": hashlib,
             "json": json, "st": SimpleNamespace(session_state=state)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), scope)
    return state, scope


def _contract(module="alpha", input_name="a", width=1):
    return {"module": module, "ports": [
        {"name": input_name, "direction": "input", "width": width},
        {"name": "y", "direction": "output", "width": 1},
    ]}


def test_same_filename_and_length_do_not_hide_changed_upload():
    _, helpers = _helpers()
    original = SimpleNamespace(name="dut.v", getvalue=lambda: b"assign y=a;")
    changed = SimpleNamespace(name="dut.v", getvalue=lambda: b"assign y=b;")
    assert len(original.getvalue()) == len(changed.getvalue())
    assert helpers["_uploaded_files_key"]([original]) != helpers["_uploaded_files_key"]([changed])
    assert helpers["_uploaded_files_key"]([original]) == helpers["_uploaded_files_key"]([original])


def test_replacing_draft_refreshes_editor_and_revokes_evidence():
    state, helpers = _helpers()
    state.update(custom_contract=DutContract.from_dict(_contract()),
                 custom_contract_json_text=json.dumps(_contract()),
                 custom_contract_editor_ports=_contract()["ports"],
                 contract_clock_signal="old_clock", contract_editor_gen=2,
                 ai_plan=object(), last_pipeline_result=object(), static_rtl_review=object(),
                 behavior_comparison=object(), workspace_evidence_pack=object(),
                 workspace_vcd_window_data=object(), planner_mode="offline", api_key="test-value")
    replacement = _contract("beta", "b", 32)
    helpers["_replace_custom_contract_draft"](json.dumps(replacement))
    assert state.custom_contract is None and state.ai_plan is None
    assert json.loads(state.custom_contract_json_text) == replacement
    assert state.custom_contract_editor_ports == replacement["ports"]
    assert state.contract_editor_gen == 3
    assert "contract_clock_signal" not in state
    for key in ("last_pipeline_result", "static_rtl_review", "behavior_comparison",
                "workspace_evidence_pack", "workspace_vcd_window_data"):
        assert key not in state
    assert state.planner_mode == "offline" and state.api_key == "test-value"


@pytest.mark.parametrize("change", ["contents", "module", "contract"])
def test_current_input_change_invalidates_plan_results_and_review(tmp_path, change):
    state, helpers = _helpers()
    path = tmp_path / "dut.v"
    path.write_text("module alpha; endmodule", encoding="utf-8")
    state.update(custom_selected_module="alpha", custom_contract=DutContract.from_dict(_contract()))
    case = {"rtl": str(path)}
    sync = helpers["_sync_workspace_input"]
    sync("自定义 RTL", case, True)
    token = object()
    state.update(ai_plan=token, last_pipeline_result=token, static_rtl_review=token,
                 rtl_comparison=token, behavior_comparison=token)
    sync("自定义 RTL", case, True)
    assert state.ai_plan is token and state.last_pipeline_result is token
    if change == "contents":
        path.write_text("module beta; endmodule", encoding="utf-8")
    elif change == "module":
        state.custom_selected_module = "beta"
    else:
        state.custom_contract = DutContract.from_dict(_contract(width=32))
    sync("自定义 RTL", case, True)
    assert state.ai_plan is None
    for key in ("last_pipeline_result", "static_rtl_review", "rtl_comparison", "behavior_comparison"):
        assert key not in state


def test_separate_comparison_is_bound_to_both_input_contents():
    state, helpers = _helpers()
    sync = helpers["_sync_comparison_input"]
    sync(("baseline-a", "candidate-a"))
    token = object()
    state.last_verify_diff = token
    sync(("baseline-a", "candidate-a"))
    assert state.last_verify_diff is token
    sync(("baseline-a", "candidate-b"))
    assert "last_verify_diff" not in state


@pytest.mark.parametrize("setting", ["compile_defines", "compile_includes"])
def test_compile_setting_changes_invalidate_evidence_but_spacing_does_not(tmp_path, setting):
    state, helpers = _helpers()
    path = tmp_path / "dut.v"
    path.write_text("module alpha; endmodule", encoding="utf-8")
    state[setting] = " FIRST ; SECOND, "
    sync = helpers["_sync_workspace_input"]
    sync("case", {"rtl": str(path)}, False)
    token = object()
    state.update(ai_plan=token, last_pipeline_result=token, static_rtl_review=token)
    state[setting] = "FIRST,SECOND"
    sync("case", {"rtl": str(path)}, False)
    assert state.last_pipeline_result is token
    state[setting] = "FIRST,THIRD"
    sync("case", {"rtl": str(path)}, False)
    assert state.ai_plan is None
    assert "last_pipeline_result" not in state and "static_rtl_review" not in state


def test_vcd_window_survives_navigation_but_clears_for_the_next_run():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from iverilog_ai.core.toolchain import locate_tools

    if not locate_tools().can_simulate:
        pytest.skip("需要本机 Icarus/vvp")
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "简单 ALU"
    app.run()
    app.button(key="generate_plan").click().run()
    app.button(key="run_generated_plan").click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    first = app.session_state["last_pipeline_result"].artifacts["output_dir"]
    app.button(key="workspace_vcd_analyze").click().run()
    app.button(key="workspace_vcd_read").click().run()
    old_window = app.session_state["workspace_vcd_window_data"]
    assert old_window["total_changes"] > 0
    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert app.session_state["workspace_vcd_window_data"] == old_window
    app.button(key="run_generated_plan").click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["last_pipeline_result"].artifacts["output_dir"] != first
    for key in ("workspace_vcd_window_data", "workspace_vcd_window", "workspace_vcd_start", "workspace_vcd_end"):
        assert key not in app.session_state.filtered_state


def test_overwritten_vcd_resets_only_its_own_cached_analysis(tmp_path):
    state, helpers = _helpers()
    path = tmp_path / "wave.vcd"
    path.write_text("first", encoding="utf-8")
    sync = helpers["_sync_vcd_input"]
    sync(path, key_prefix="workspace_vcd")
    token = object()
    state.update(workspace_vcd_window_data=token, workspace_vcd_start=5.0,
                 other_vcd_window_data=token)
    sync(path, key_prefix="workspace_vcd")
    assert state.workspace_vcd_window_data is token
    path.write_text("replacement", encoding="utf-8")
    sync(path, key_prefix="workspace_vcd")
    assert "workspace_vcd_window_data" not in state and "workspace_vcd_start" not in state
    assert state.other_vcd_window_data is token


def _custom_app():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=120)
    draft = _contract()
    app.session_state["case_name"] = "自定义 RTL"
    app.session_state["custom_rtl_path"] = ""
    app.session_state["custom_contract_text"] = json.dumps(draft)
    app.session_state["custom_contract"] = DutContract.from_dict(draft)
    app.session_state["custom_selected_module"] = "alpha"
    app.session_state["custom_modules"] = ("alpha", "beta")
    app.session_state["custom_rtl_source"] = (
        "module alpha(input a, output y); assign y=a; endmodule\n"
        "module beta(input [31:0] b, output y); assign y=b[0]; endmodule\n"
    )
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    app.button(key="generate_plan").click().run()
    assert app.session_state["ai_plan"].design == "alpha"
    return app


def test_top_module_switch_replaces_visible_contract_and_disables_old_plan():
    app = _custom_app()
    top = next(item for item in app.selectbox if list(item.options) == ["alpha", "beta"])
    top.set_value("beta").run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["custom_selected_module"] == "beta"
    assert json.loads(app.session_state["custom_contract_json_text"])["module"] == "beta"
    assert [port["name"] for port in app.session_state["custom_contract_editor_ports"]] == ["b", "y"]
    assert app.session_state["custom_contract"] is None
    assert app.session_state["ai_plan"] is None
    assert app.button(key="run_generated_plan").disabled


def test_confirmed_custom_input_and_plan_survive_navigation():
    """导航不能清空已确认的自定义接口、RTL 文本或可运行的计划。"""
    app = _custom_app()
    original_source = app.session_state["custom_rtl_source"]
    original_contract = app.session_state["custom_contract"].to_json()
    original_editor = app.text_area(key="custom_contract_json_text").value
    original_plan = app.session_state["ai_plan"].model_dump(mode="json")

    for page in ("工具设置", "规则审查", "运行档案", "使用手册", "项目概览", "工作台"):
        app.radio(key="workspace_page").set_value(page).run()
        assert not app.exception, [str(item.value) for item in app.exception]
        assert app.session_state["case_name"] == "自定义 RTL"
        assert app.session_state["custom_selected_module"] == "alpha"
        assert app.session_state["custom_rtl_source"] == original_source
        assert app.session_state["custom_contract"].to_json() == original_contract
        assert app.session_state["ai_plan"].model_dump(mode="json") == original_plan

    assert app.text_area(key="custom_contract_json_text").value == original_editor
    assert not app.button(key="run_generated_plan").disabled


def test_editing_contract_clears_prior_result_before_the_page_can_display_it():
    app = _custom_app()
    # A sentinel would crash rendering if the old result reached the result panel.
    app.session_state["last_pipeline_result"] = object()
    app.session_state["last_pipeline_case"] = "自定义 RTL"
    app.session_state["static_rtl_review"] = object()
    app.text_area(key="custom_contract_json_text").set_value(json.dumps(_contract(width=32))).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["custom_contract"] is None
    assert app.session_state["ai_plan"] is None
    assert app.session_state.filtered_state.get("last_pipeline_result") is None
    assert app.session_state.filtered_state.get("static_rtl_review") is None
    assert app.button(key="run_generated_plan").disabled


@pytest.mark.parametrize("stale_contract_type", [False, True])
def test_fresh_upload_can_be_validated_and_planned_without_preseeded_contract(monkeypatch, stale_contract_type):
    st = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    original_uploader = st.file_uploader
    uploaded = SimpleNamespace(name="dut.v", getvalue=lambda: (ROOT / "rtl/simple_alu.v").read_bytes())

    def upload(label, *args, **kwargs):
        if kwargs.get("accept_multiple_files") is True:
            return [uploaded]
        return original_uploader(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", upload)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "自定义 RTL"
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["custom_contract"] is None
    app.button(key="validate_custom_contract").click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["custom_contract"].module == "simple_alu"
    assert any("校验通过" in str(item.value) for item in app.success)
    app.button(key="generate_plan").click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["ai_error"] is None
    assert app.session_state["ai_plan"].design == "simple_alu"
    assert app.session_state["custom_contract"].module == "simple_alu"
    from iverilog_ai.core.toolchain import locate_tools

    if locate_tools().can_simulate:
        if stale_contract_type:
            # A hot reload can leave a validated object from the preceding
            # module class in session state. Its confirmed JSON is unchanged.
            confirmed_json = app.session_state["custom_contract"].to_json()
            app.session_state["custom_contract"] = SimpleNamespace(to_json=lambda: confirmed_json)
        app.button(key="run_generated_plan").click().run()
        assert not app.exception, [str(item.value) for item in app.exception]
        assert not app.error, [str(item.value) for item in app.error]
        assert app.session_state["last_pipeline_result"].simulation.status == "passed"
