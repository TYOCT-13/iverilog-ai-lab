"""两份 RTL 上传、输入失效与对比结论的界面回归；不调用模型。"""

from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

st = pytest.importorskip("streamlit", reason="未安装 streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402


APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"
BASELINE = b"module audit_dual(input wire a, input wire b, output wire y); assign y=a; endmodule\n"
CANDIDATE = BASELINE.replace(b"assign y=a", b"assign y=b")


def _upload(name: str, content: bytes):
    return SimpleNamespace(name=name, getvalue=lambda: content)


@pytest.fixture
def comparison_app(monkeypatch):
    """保留真实导入路径，只替换上传控件与仿真服务，观察 UI 交给服务的输入。"""
    uploads = {
        "diff_baseline_upload": _upload("audit-baseline.v", BASELINE),
        "diff_candidate": _upload("audit-candidate.v", CANDIDATE),
    }
    calls = []
    behavior = {"status": "identical"}
    real_uploader = st.file_uploader

    def upload_widget(*args, **kwargs):
        key = kwargs.get("key")
        if key in uploads:
            return uploads[key]
        return real_uploader(*args, **kwargs)

    def compare(baseline, candidate, output_dir, **kwargs):
        baseline_path, candidate_path = Path(baseline), Path(candidate)
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        markdown = output / "comparison.md"
        markdown.write_text(f"audit comparison run {len(calls) + 1}", encoding="utf-8")
        calls.append({
            "baseline": baseline_path,
            "candidate": candidate_path,
            "baseline_bytes": baseline_path.read_bytes(),
            "candidate_bytes": candidate_path.read_bytes(),
            "output_dir": output,
            "markdown": markdown,
        })
        status = behavior["status"]
        return SimpleNamespace(
            status=status,
            label="两侧一致" if status == "identical" else "未取得可比证据",
            comparable_checks=1 if status == "identical" else 0,
            waveform_compared=status == "identical",
            contract_source="draft-from-baseline",
            differences=(),
            caveats=() if status == "identical" else ("测试替身：候选编译失败",),
            artifacts={"markdown": str(markdown)},
            to_dict=lambda: {"status": status, "markdown": str(markdown)},
        )

    monkeypatch.setattr(st, "file_uploader", upload_widget)
    monkeypatch.setattr(import_module("iverilog_ai.core.verify_diff"), "verify_diff", compare)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "简单 ALU"
    app.run()
    app.radio(key="ui_scenario").set_value("对比两份 RTL（AI 改写验收 / 开源行为回归）").run()
    app.selectbox(key="diff_baseline").set_value("上传基线 RTL").run()
    assert not app.exception, [str(item.value) for item in app.exception]
    return app, uploads, calls, behavior


def test_uploaded_baseline_and_candidate_reach_comparison_and_preserve_prior_report(comparison_app):
    app, _, calls, _ = comparison_app
    app.button(key="run_verify_diff").click().run()
    assert not app.exception and not app.error
    assert len(calls) == 1
    first = calls[0]
    assert first["baseline_bytes"] == BASELINE
    assert first["candidate_bytes"] == CANDIDATE
    assert first["baseline"] != first["candidate"]
    first_bytes = first["markdown"].read_bytes()
    assert any("未发现行为差异" in item.value and "不等于形式等价" in item.value for item in app.success)
    assert any(item.proto.id.endswith("-download_verify_diff_md") for item in app.get("download_button"))
    assert any(item.label == "接口信息" and item.value == "自动草稿" for item in app.metric)

    app.radio(key="workspace_page").set_value("工具设置").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert not app.exception and not app.error
    assert len(calls) == 1, "仅切换导航不得重新运行对比"
    assert app.session_state["last_verify_diff"].artifacts["markdown"] == str(first["markdown"])
    assert first["markdown"].read_bytes() == first_bytes
    assert any(item.proto.id.endswith("-download_verify_diff_md") for item in app.get("download_button"))

    app.button(key="run_verify_diff").click().run()
    assert not app.exception and not app.error
    assert len(calls) == 2
    assert calls[1]["output_dir"] != first["output_dir"]
    assert first["markdown"].read_bytes() == first_bytes
    assert calls[1]["markdown"].read_bytes() != first_bytes


@pytest.mark.parametrize("upload_key", ["diff_baseline_upload", "diff_candidate"])
def test_same_name_same_length_replacement_invalidates_comparison(comparison_app, upload_key):
    app, uploads, calls, _ = comparison_app
    app.button(key="run_verify_diff").click().run()
    assert "last_verify_diff" in app.session_state
    previous = uploads[upload_key]
    replacement = CANDIDATE if previous.getvalue() == BASELINE else BASELINE
    assert len(replacement) == len(previous.getvalue())
    uploads[upload_key] = _upload(previous.name, replacement)
    app.run()

    assert not app.exception and not app.error
    assert len(calls) == 1, "替换输入只清理旧结果，不自动执行"
    assert "last_verify_diff" not in app.session_state
    assert not any("对比结论：" in item.value for item in app.subheader)
    assert not any(item.proto.id.endswith("-download_verify_diff_md") for item in app.get("download_button"))


@pytest.mark.parametrize(
    "missing_key,message",
    [("diff_baseline_upload", "请先上传原版本 RTL。"), ("diff_candidate", "请先上传候选 RTL。")],
)
def test_missing_upload_gives_actionable_message_without_comparison(comparison_app, missing_key, message):
    app, uploads, calls, _ = comparison_app
    uploads[missing_key] = None
    app.run()
    app.button(key="run_verify_diff").click().run()
    assert not app.exception and not app.error
    assert not calls
    assert any(item.value == message for item in app.warning)
    assert "last_verify_diff" not in app.session_state


def test_inconclusive_comparison_never_shows_identical_success(comparison_app):
    app, _, calls, behavior = comparison_app
    behavior["status"] = "inconclusive"
    app.button(key="run_verify_diff").click().run()
    assert not app.exception and not app.error
    assert len(calls) == 1
    assert app.session_state["last_verify_diff"].status == "inconclusive"
    assert any("未取得可比证据" in item.value for item in app.subheader)
    assert any("可比证据不足" in item.value and "无法判断" in item.value for item in app.info)
    assert not any(any(term in item.value for term in ("行为差异", "一致", "等价")) for item in app.success)
    assert any("候选编译失败" in item.value for item in app.warning)
