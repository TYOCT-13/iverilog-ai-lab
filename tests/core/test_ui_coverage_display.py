"""原计划无 expected 时，参考模型产生的真实检查不能被显示成零覆盖。"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="未安装 streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402
from iverilog_ai.core.toolchain import locate_tools  # noqa: E402


APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"


def test_oracle_checks_are_distinct_from_empty_explicit_plan_coverage():
    if not locate_tools().can_simulate:
        pytest.skip("需要本机 Icarus/vvp")
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "简单 ALU"
    app.run()
    app.button(key="generate_plan").click().run()
    app.button(key="run_generated_plan").click().run()

    assert not app.exception, [str(item.value) for item in app.exception]
    result = app.session_state["last_pipeline_result"]
    assert result.coverage["checks"]["total"] == 0
    checked = [item for item in result.records if item.signal]
    assert checked, "本例必须真正执行参考模型提供的比对，不能用观察记录代替"
    metrics = {item.label: item for item in app.metric}
    actual = metrics["实际仿真比对"]
    assert actual.value == f"{sum(item.ok for item in checked)}/{len(checked)} 条比对一致"
    explicit = metrics["计划显式检查覆盖"]
    assert explicit.value == "—"
    assert explicit.delta in ("", None), "无显式检查不能显示0%或虚构的覆盖率"
    assert any("计划未写入预期值" in item.value and "参考模型" in item.value and "实际比对" in item.value for item in app.caption)

    app.radio(key="workspace_page").set_value("运行档案").run()
    app.radio(key="workspace_page").set_value("工作台").run()
    assert not app.exception
    retained = {item.label: item for item in app.metric}
    assert retained["计划显式检查覆盖"].value == "—"
    assert retained["实际仿真比对"].value == actual.value
