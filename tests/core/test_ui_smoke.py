"""UI 冒烟测试：用 Streamlit 自带的 AppTest 真正把页面渲染一遍。

为什么需要它：`ui/app.py` 是一个"模块级脚本"，很多语句只在渲染时才执行。
静态解析（AST）能检查表与路径，但**检查不出一段永远不执行的代码**——真实事故：
`_build_provider` 在 `return` 之后还留着"检查配置"和"读取模型列表"两个按钮块，
于是这两个功能从来没在页面上出现过，而所有静态测试都是绿的。
AppTest 会把脚本跑一遍：语法/名字错误、组件 API 误用、以及被移动后的分支是否
真的可渲染，都能在这里暴露。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="未安装 streamlit（UI 冒烟测试跳过）")

from streamlit.testing.v1 import AppTest  # noqa: E402
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "ui" / "app.py"


def _run_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.run()
    return app


@pytest.fixture(scope="module")
def rendered() -> AppTest:
    return _run_app()


def test_page_renders_without_exception(rendered: AppTest):
    assert not rendered.exception, [str(item.value) for item in rendered.exception]


def test_navigation_tabs_cover_every_section(rendered: AppTest):
    """顶部导航栏必须把功能分开，而不是全挤在一页里。"""

    labels = [tab.label for tab in rendered.tabs]
    for expected in ("概览", "验证", "质量与对比", "手册", "设置", "历史"):
        assert expected in labels, labels


def test_theme_is_injected(rendered: AppTest):
    """风格主题（临床白 + 青色强调 + 导航栏样式）必须真的注入页面。"""

    html = "\n".join(getattr(item, "value", "") for item in rendered.markdown)
    assert "--rl-cyan" in html and "stTabs" in html, html[:400]


def test_manual_has_four_audiences(rendered: AppTest):
    """网页内的使用手册必须覆盖入门 / 进阶 / 深度 / 按目的四类读者。"""

    manuals = sorted((ROOT / "docs" / "manual").glob("*.md"))
    assert len(manuals) == 4, [path.name for path in manuals]
    for path in manuals:
        text = path.read_text(encoding="utf-8")
        assert len(text) > 1200, f"{path.name} 内容过短，像是占位"
        assert "```" in text, f"{path.name} 缺少可执行命令"

    body = "\n".join(getattr(item, "value", "") for item in rendered.markdown)
    assert "入门" in body and "按目的" in body, "手册内容没有渲染到页面上"


def test_default_case_is_selectable_and_labelled(rendered: AppTest):
    assert rendered.selectbox, "页面至少应有一个案例选择框"
    labels = [item.label for item in rendered.selectbox]
    assert any("案例" in label for label in labels), labels


def test_evidence_panel_shows_measured_numbers(rendered: AppTest):
    """实证状态面板必须显示现算的数字，而不是一排占位符。"""

    captions = "\n".join(item.value for item in rendered.caption)
    assert "基准矩阵" in captions or "案例" in captions, captions[:400]


def test_provider_settings_expander_contains_model_list_controls(rendered: AppTest):
    """AI 接口设置里必须真的有这两个按钮（它们曾被写在 return 之后而从未渲染）。"""

    labels = [item.label for item in rendered.button]
    assert any("检查配置" in label for label in labels), labels
    assert any("读取模型列表" in label for label in labels), labels


def test_page_survives_a_generated_plan():
    """生成计划之后，整页必须继续渲染。

    真实事故：计划渲染分支里调用了一个**不存在的函数名**（`rules_manifest`，
    实际导入的是 `rule_manifest`）。它抛的是 `NameError`，而那里的 `except` 只接
    `ValueError`——于是"生成计划"之后页面直接中断：计划 JSON、执行按钮、结果区
    全都看不到。默认的空状态渲染不会触发这条分支，所以必须显式构造这个状态。
    """

    from iverilog_ai.ai.schema import TestPlan

    app = AppTest.from_file(str(APP), default_timeout=120)
    app.run()
    app.session_state["ai_plan"] = TestPlan.model_validate(
        {
            "design": "pwm",
            "objective": "smoke",
            "vectors": [{"name": "v1", "inputs": {"rst_n": 1, "duty": 0}, "cycles": 1, "expected": {}}],
        }
    )
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    # 计划区与规则集指纹都应该渲染出来
    assert any("TestPlan" in str(item.value) for item in app.subheader), [item.value for item in app.subheader]
    assert any("规则集" in item.value for item in app.caption), [item.value for item in app.caption]


def _ui_function(name: str):
    """把 ui/app.py 里的某个纯函数单独取出来执行（不启动 Streamlit）。

    与 `_ui_test_counter` 同一手法：页面脚本没法 import，但纯函数可以按 AST 摘出来跑。
    """

    tree = ast.parse(APP.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    namespace: dict = {"Any": object}
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"ui/app.py:{name}", "exec"), namespace)
    return namespace[name]


def test_contract_payload_builder_matches_the_contract_schema():
    """表格 → contract 的转换必须产出可校验的合约（含时钟/复位/参数）。"""

    build = _ui_function("_contract_payload")
    payload = build(
        module="my_dut",
        ports=[
            {"name": "clk", "direction": "input", "width": 1, "signed": False},
            {"name": "rst_n", "direction": "input", "width": 1, "signed": False},
        ],
        parameters={"WIDTH": 8},
        clock_signal=" clk ",
        clock_period=10.0,
        clock_edge="posedge",
        reset_signal="rst_n",
        reset_active=0,
        reset_sync=False,
        reset_cycles=2,
    )
    contract = DutContract.from_dict(payload)
    assert contract.module == "my_dut"
    assert contract.parameters == {"WIDTH": 8}
    assert contract.clock and contract.clock.signal == "clk"  # 首尾空格被去掉
    assert contract.reset and contract.reset.signal == "rst_n"

    # 不填时钟/复位时不应凭空造出这两个字段
    bare = build(
        module="bare",
        ports=[{"name": "a", "direction": "input", "width": 1, "signed": False}],
        parameters=None,
        clock_signal="",
        clock_period=10.0,
        clock_edge="posedge",
        reset_signal="",
        reset_active=0,
        reset_sync=False,
        reset_cycles=2,
    )
    assert "clock" not in bare and "reset" not in bare


def test_contract_editor_is_a_fragment_and_survives_render():
    """自定义 RTL 的 contract 编辑区必须独立重跑（而不是刷新整页）。

    这条用例对应真实反馈："点『从表格生成 JSON』整个页面刷新了"。修法是把这一段装进
    `@st.fragment`，并把原来靠 `st.rerun()` 生效的隐式双向同步改成两个显式动作。
    这里钉住：源码里确实是 fragment、里面不再有整页重跑、且自定义 RTL 分支能渲染。
    """

    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    editors = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_contract_editor"
    ]
    assert editors, "未找到 _contract_editor"
    decorators = [ast.unparse(item) for item in editors[0].decorator_list]
    assert any("fragment" in item for item in decorators), decorators

    region = source.split("def _contract_editor")[1].split("def _build_provider")[0]
    full_page_reruns = [
        line.strip() for line in region.splitlines() if line.strip().startswith("st.rerun()")
    ]
    assert not full_page_reruns, f"contract 编辑区里不应再有整页重跑：{full_page_reruns}"

    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "自定义 RTL"
    # 该分支在 `custom_rtl_path` 缺席时会初始化并清空 contract 文本，因此必须先占位
    app.session_state["custom_rtl_path"] = ""
    app.session_state["custom_contract_text"] = json.dumps(
        {"module": "pwm", "ports": [{"name": "clk", "direction": "input", "width": 1}]}
    )
    app.session_state["custom_rtl_source"] = "module pwm(input wire clk); endmodule\n"
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_contract_editor_survives_stale_widget_state():
    """会话里残留旧形状的编辑状态时，页面必须自愈而不是整页崩掉。

    真实事故：`session_state["custom_ports_editor"]` 里存的是 Streamlit 自己的**编辑状态**
    （`{edited_rows, added_rows, deleted_rows}`），不是端口数据。早期实现把它当数据喂回
    `st.data_editor`，pandas 抛 "Mixing dicts with non-Series…"，整页打成 500。
    现在数据只从影子列表来，任何残留的编辑状态都不影响渲染。
    """

    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["case_name"] = "自定义 RTL"
    # 该分支在 `custom_rtl_path` 缺席时会初始化并清空 contract 文本，因此必须先占位
    app.session_state["custom_rtl_path"] = ""
    app.session_state["custom_contract_text"] = json.dumps(
        {"module": "pwm", "ports": [{"name": "clk", "direction": "input", "width": 1}]}
    )
    app.session_state["custom_rtl_source"] = "module pwm(input wire clk); endmodule\n"
    # 模拟旧会话残留的"编辑事件字典"
    app.session_state["custom_ports_editor"] = {"edited_rows": {}, "added_rows": [], "deleted_rows": []}
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert isinstance(app.session_state["custom_contract_editor_ports"], list)


def test_no_python_file_has_unreachable_code():
    """把未可达代码检查作为测试跑一遍，保证门禁在 `pytest` 里也生效。"""

    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import check_dead_code  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    findings: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if {".git", ".iverilog-ai", ".dsh-tmp", "__pycache__"} & set(path.parts):
            continue
        if path.resolve() == Path(check_dead_code.__file__).resolve():
            continue
        findings.extend(check_dead_code.scan_file(path))
    assert not findings, "发现不可达代码：\n" + "\n".join(findings)
