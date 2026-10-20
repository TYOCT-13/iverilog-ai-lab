"""Uploaded headers retain include semantics through preflight and real simulation."""
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace

import pytest

from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rtl_import import RTLImportError, import_rtl_project
from iverilog_ai.core.rtl_preflight import check_rtl_syntax
from iverilog_ai.core.toolchain import locate_tools


TOOLS = locate_tools()
HEADER = b"`ifndef TEST_DEFS\n`define TEST_DEFS\n`define W 8\n`endif\n"
CHILD = b'`include "defs.vh"\nmodule child(input [`W-1:0] a, output [`W-1:0] y); assign y=a; endmodule\n'
TOP = b'`include "defs.vh"\nmodule dut(input [`W-1:0] a, output [`W-1:0] y); child u(a,y); endmodule\n'


def _check(project, root):
    return check_rtl_syntax(project.entry_path, project_root=root, top_module="dut",
        source_files=project.source_files, include_dirs=tuple(map(str, project.include_dirs)),
        iverilog_path=TOOLS.iverilog)


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("order", list(permutations(("defs.vh", "child.v", "top.v"))))
def test_header_and_source_upload_order_preserves_width_and_actual_output(tmp_path, order):
    bodies = {"defs.vh": HEADER, "child.v": CHILD, "top.v": TOP}
    project = import_rtl_project([(n, bodies[n]) for n in order if n.endswith(".v")], tmp_path,
        include_files=[(n, bodies[n]) for n in order if n.endswith(".vh")])
    result = _check(project, tmp_path)
    assert result.returncode == 0 and result.error is None and not result.stderr
    assert all(str(path) in result.command for path in project.source_files)
    assert not any(arg.endswith("defs.vh") for arg in result.command)
    contract = DutContract.from_dict({"module": "dut", "ports": [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "y", "direction": "output", "width": 8}]})
    run = VerificationPipeline(reference_policy="disabled").run(
        {"design": "dut", "objective": "preserve included macro width",
         "vectors": [{"name": "high_bits", "inputs": {"a": 165}, "expected": {"y": 165}}]},
        contract, project.entry_path, tmp_path / "run", allowed_roots=(tmp_path,),
        include_dirs=tuple(map(str, project.include_dirs)),
        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    assert run.simulation.check_count == 1 and not run.simulation.failures
    assert not run.simulation.compile.stderr


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_undefined_macro_is_rejected_even_if_compiler_returns_zero(tmp_path):
    source = tmp_path / "dut.v"
    source.write_text("module dut(input [`UNDEFINED+1:0] a, output y); assign y=a[0]; endmodule", encoding="ascii")
    result = check_rtl_syntax(source, project_root=tmp_path, top_module="dut", iverilog_path=TOOLS.iverilog)
    assert result.returncode == 0  # Preserve the actual compiler exit code.
    assert result.error and "undefined macro" in result.error
    assert "undefined" in result.stderr and result.status.value == "failed"


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_missing_or_changed_header_fails_and_source_files_stay_inside_policy(tmp_path):
    project = import_rtl_project({"child.v": CHILD, "top.v": TOP}, tmp_path, include_files={"defs.vh": HEADER})
    assert _check(project, tmp_path).error is None
    header = project.project_dir / "include/defs.vh"
    header.write_text("`define W ;\n", encoding="ascii")
    assert _check(project, tmp_path).returncode != 0
    header.unlink()
    assert _check(project, tmp_path).returncode != 0
    with pytest.raises(ValueError):
        check_rtl_syntax(project.entry_path, project_root=tmp_path, top_module="dut",
            source_files=(tmp_path.parent / "outside.v",), iverilog_path=TOOLS.iverilog)


def test_duplicate_names_are_rejected_and_generated_entry_never_overwrites_upload(tmp_path):
    with pytest.raises(RTLImportError, match="duplicate"):
        import_rtl_project([("dut.v", TOP), ("DUT.v", CHILD)], tmp_path)
    project = import_rtl_project({"__icarus_project__.sv": TOP, "child.v": CHILD}, tmp_path)
    assert project.entry_path.name != "__icarus_project__.sv"
    assert (project.project_dir / "__icarus_project__.sv").read_bytes() == TOP


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
@pytest.mark.parametrize("two_files", [False, True])
def test_source_only_uploads_keep_standalone_evidence_replay(tmp_path, two_files):
    from scripts.create_evidence_pack import create_evidence_pack

    child = b"module child(input [7:0] a, output [7:0] y); assign y=a; endmodule\n"
    top = b"module dut(input [7:0] a, output [7:0] y); child u(a,y); endmodule\n"
    files = [("child.v", child), ("top.v", top)] if two_files else [("dut.v", top.replace(b"child u(a,y);", b"assign y=a;"))]
    project = import_rtl_project(files, tmp_path)
    assert project.include_dirs == ()
    result = VerificationPipeline(reference_policy="disabled").run(
        {"design": "dut", "objective": "standalone export", "vectors": [
            {"name": "one", "inputs": {"a": 165}, "expected": {"y": 165}}]},
        {"module": "dut", "ports": [{"name": "a", "direction": "input", "width": 8},
                                    {"name": "y", "direction": "output", "width": 8}]},
        project.entry_path, tmp_path / "run", allowed_roots=(tmp_path,),
        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    assert result.simulation.check_count == 1 and not result.simulation.failures
    manifest = create_evidence_pack(result.artifacts["pipeline_result"], tmp_path / "pack")
    assert manifest["replay"]["status"] == "available"


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_web_header_first_uses_project_sources_and_auto_include_dirs(monkeypatch):
    st = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    original = st.file_uploader
    uploads = [SimpleNamespace(name=n, getvalue=lambda body=b: body)
               for n, b in (("defs.vh", HEADER), ("top.v", TOP), ("child.v", CHILD))]
    def upload(label, *args, **kwargs):
        return uploads if label == "上传 RTL 文件" else original(label, *args, **kwargs)
    monkeypatch.setattr(st, "file_uploader", upload)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "ui/app.py"), default_timeout=120)
    app.session_state["planner_setup_complete"] = True
    app.session_state["planner_mode"] = "离线确定性规划器（无需密钥、进程内）"
    app.session_state["case_name"] = "自定义 RTL"
    app.run()
    assert not app.exception and not app.error
    paths = app.session_state["custom_source_files"]
    assert [Path(p).name for p in paths] == ["top.v", "child.v"]
    assert len(app.session_state["custom_include_dirs"]) == 2
    assert any("预检查通过" in str(item.value) for item in app.success)
    # Header bytes replacing an input invalidate an existing plan and evidence.
    from iverilog_ai.ai.schema import TestPlan as Plan
    app.session_state["ai_plan"] = Plan.model_validate({"design": "dut", "objective": "old",
        "vectors": [{"name": "old", "inputs": {"a": 1}}]})
    uploads[0] = SimpleNamespace(name="defs.vh", getvalue=lambda: b"`define W ;\n")
    app.run()
    assert not app.exception and app.session_state["ai_plan"] is None
    assert app.button(key="run_generated_plan").disabled
    assert any("预检查未通过" in str(item.value) for item in app.error)
