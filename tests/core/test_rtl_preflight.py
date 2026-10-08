"""真实 Icarus 预检查和网页阻断：不能把未检查或旧源码当作通过。"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.core.rtl_preflight import check_rtl_syntax
from iverilog_ai.core.toolchain import locate_tools
from iverilog_ai.ai.schema import TestPlan as Plan


@pytest.fixture
def compiler():
    tool = locate_tools().iverilog
    if tool is None:
        pytest.skip("actual Icarus compiler unavailable")
    return tool


def check(path, compiler, **options):
    return check_rtl_syntax(path, project_root=path.parent, top_module="dut",
                            iverilog_path=compiler, **options)


def test_real_preflight_does_not_execute_initial_blocks(tmp_path, compiler):
    rtl = tmp_path / "dut.v"
    marker = tmp_path / "must-not-execute.txt"
    rtl.write_text(f'module dut; integer f; initial f=$fopen("{marker.as_posix()}","w"); endmodule')
    result = check(rtl, compiler)
    assert result.returncode == 0 and not marker.exists()


@pytest.mark.parametrize("source", [
    "module dut(input wire a; output wire y); endmodule",
    "module dut; localparam X 1; endmodule",
    "module dut(output wire y); assign y=; endmodule",
    "module dut; absent_child child(); endmodule",
])
def test_real_preflight_rejects_syntax_and_missing_dependencies(tmp_path, compiler, source):
    rtl = tmp_path / "dut.v"
    rtl.write_text(source)
    result = check(rtl, compiler)
    assert result.returncode != 0 and result.stderr


def test_replacement_and_include_changes_are_rechecked(tmp_path, compiler):
    rtl, header = tmp_path / "dut.v", tmp_path / "values.vh"
    rtl.write_text('`include "values.vh"\nmodule dut(output wire y); assign y=`VALUE; endmodule')
    header.write_text("`define VALUE 1'b0\n")
    assert check(rtl, compiler, include_dirs=(str(tmp_path),)).returncode == 0
    header.write_text("`define VALUE ;\n")
    assert check(rtl, compiler, include_dirs=(str(tmp_path),)).returncode != 0
    rtl.write_text("module dut(output wire y); assign y=; endmodule")
    assert check(rtl, compiler).returncode != 0


def test_current_macros_are_used(tmp_path, compiler):
    rtl = tmp_path / "dut.v"
    rtl.write_text("module dut(output wire y); assign y=`VALUE; endmodule")
    assert check(rtl, compiler).returncode != 0
    assert check(rtl, compiler, defines=("VALUE=1'b0",)).returncode == 0


def test_missing_compiler_and_unsafe_includes_fail_closed(tmp_path, compiler):
    rtl = tmp_path / "dut.v"
    rtl.write_text("module dut; endmodule")
    with pytest.raises(ValueError, match="cannot find"):
        check(rtl, str(tmp_path / "missing" / "iverilog.exe"))
    with pytest.raises(ValueError, match="outside allowed"):
        check(rtl, compiler, include_dirs=(str(tmp_path.parent),))


def test_ui_blocks_existing_plan_and_recovers_after_new_upload(monkeypatch, compiler):
    st = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from iverilog_ai.core.pipeline import VerificationPipeline

    current = {"bytes": b"module dut(input wire clk, output wire y); assign y=; endmodule"}
    uploaded = SimpleNamespace(name="dut.v", getvalue=lambda: current["bytes"])
    original = st.file_uploader

    def upload(label, *args, **options):
        return [uploaded] if label == "上传 RTL 文件" else original(label, *args, **options)

    def forbidden_run(*args, **options):
        pytest.fail("invalid RTL must not reach the simulation pipeline")

    monkeypatch.setattr(st, "file_uploader", upload)
    monkeypatch.setattr(VerificationPipeline, "run", forbidden_run)
    root = Path(__file__).resolve().parents[2]
    app = AppTest.from_file(str(root / "ui/app.py"), default_timeout=120)
    app.session_state["planner_setup_complete"] = True
    app.session_state["planner_mode"] = "离线确定性规划器（无需密钥、进程内）"
    app.session_state["case_name"] = "自定义 RTL"
    app.run()
    assert not app.exception
    plan = Plan.model_validate({"design": "dut", "objective": "gate regression", "vectors": [{"name": "sample", "inputs": {}, "expected": {"y": 0}}]})
    app.session_state["ai_plan"] = plan
    app.run()
    assert not app.exception
    assert app.button(key="run_generated_plan").disabled
    assert any("预检查未通过" in str(item.value) for item in app.error)
    # Even a synthetic click cannot bypass the handler guard.
    app.button(key="run_generated_plan").click().run()
    assert not app.exception and app.session_state.filtered_state.get("last_pipeline_result") is None
    current["bytes"] = b"module dut(input wire clk, output wire y); assign y=1'b0; endmodule"
    app.run()
    app.session_state["ai_plan"] = plan
    app.run()
    assert not app.exception and not app.button(key="run_generated_plan").disabled
    assert not app.error


@pytest.mark.parametrize("failure", ["timeout", "unavailable"])
def test_ui_blocks_when_preflight_cannot_complete(monkeypatch, failure):
    st = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from iverilog_ai.core.models import ProcessResult, ProcessStatus
    import iverilog_ai.core.rtl_preflight as preflight

    uploaded = SimpleNamespace(name="dut.v", getvalue=lambda: b"module dut(input clk, output y); assign y=1'b0; endmodule")
    original = st.file_uploader

    def upload(label, *args, **options):
        return [uploaded] if label == "上传 RTL 文件" else original(label, *args, **options)

    def incomplete(*args, **options):
        if failure == "unavailable":
            raise ValueError("Icarus unavailable")
        return ProcessResult(status=ProcessStatus.TIMEOUT, returncode=None,
                             command=("iverilog",), timed_out=True)

    monkeypatch.setattr(st, "file_uploader", upload)
    monkeypatch.setattr(preflight, "check_rtl_syntax", incomplete)
    root = Path(__file__).resolve().parents[2]
    app = AppTest.from_file(str(root / "ui/app.py"), default_timeout=120)
    app.session_state["planner_setup_complete"] = True
    app.session_state["case_name"] = "自定义 RTL"
    app.run()
    app.session_state["ai_plan"] = Plan.model_validate({"design": "dut", "objective": "gate regression", "vectors": [{"name": "sample", "inputs": {}, "expected": {"y": 0}}]})
    app.run()
    assert not app.exception and app.error
    assert app.button(key="run_generated_plan").disabled
    assert app.button(key="run_verification_agent").disabled
