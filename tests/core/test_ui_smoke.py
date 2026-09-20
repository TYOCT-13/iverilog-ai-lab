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
import re
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


def test_offline_mode_generates_a_plan_that_matches_the_selected_case():
    """离线模式必须按**所选案例的合约**生成计划，而不是回放一份写死的演示计划。

    真实反馈："选离线 mock，简单 alu，执行 AI 计划并生成 tb 时报
    `vectors[0].inputs contains unknown port 'rst_n'`；执行真实 Icarus 仿真却是 pass"。
    根因是离线分支接了 `MockProvider()` 的默认返回值（design=demo，向量固定驱动
    `rst_n`），而 `simple_alu` 是组合逻辑、合约里既没有时钟也没有复位。
    """

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.session_state["case_name"] = "简单 ALU"
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]

    buttons = [item for item in app.button if getattr(item, "key", None) == "generate_plan"]
    assert buttons, [getattr(item, "label", None) for item in app.button]
    buttons[0].click()
    app.run()

    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["ai_error"] is None, app.session_state["ai_error"]
    plan = app.session_state["ai_plan"]
    assert plan is not None and plan.design == "simple_alu", plan
    used = sorted({name for vector in plan.vectors for name in vector.inputs})
    assert used == ["a", "b", "op"], used


def test_offline_branches_use_the_contract_aware_provider():
    """把"离线分支必须用 `_offline_provider`"钉在源码上。

    行为用例（上一条）只覆盖默认案例；这条不依赖任何具体案例，任何一次把离线分支
    改回 `MockProvider()` 都会在这里被拦下。
    """

    source = APP.read_text(encoding="utf-8")
    plan_region = source.split('key="generate_plan"')[1].split("if st.session_state.ai_error")[0]
    assert "_offline_provider(contract)" in plan_region, plan_region
    assert "MockProvider()" not in plan_region, "离线生成计划的分支又用回了写死的演示 Provider"
    assert "_offline_provider(contract, vector_count=2)" in source, "离线补充向量分支没有走合约驱动路径"


def _ui_function(name: str):
    """把 ui/app.py 里的某个纯函数单独取出来执行（不启动 Streamlit）。

    与 `_ui_test_counter` 同一手法：页面脚本没法 import，但纯函数可以按 AST 摘出来跑。
    """

    return _ui_functions(name)[name]


def _ui_functions(*names: str) -> dict:
    """一次摘出多个函数（互相调用的辅助函数必须一起摘，否则会 NameError）。

    命名空间里补上这些函数用到的标准库模块（`ui/app.py` 顶部 import 的东西在摘出来的
    模块里并不存在），否则一调用就 `NameError`。
    """

    import os
    import shutil
    import subprocess
    import time as _time

    tree = ast.parse(APP.read_text(encoding="utf-8"))
    wanted = set(names)
    nodes = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in wanted
    ]
    assert len(nodes) == len(wanted), (sorted(wanted), [node.name for node in nodes])
    namespace: dict = {
        "Any": object, "Path": Path, "os": os, "shutil": shutil,
        "subprocess": subprocess, "time": _time,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui/app.py", "exec"), namespace)
    return namespace


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


def _custom_rtl_app(*, json_text: str = "") -> AppTest:
    """渲染"自定义 RTL"分支（contract 编辑区就在这里），可按需预置 JSON 文本框内容。"""

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.session_state["case_name"] = "自定义 RTL"
    # 该分支在 `custom_rtl_path` 缺席时会初始化并清空 contract 文本，因此必须先占位
    app.session_state["custom_rtl_path"] = ""
    app.session_state["custom_contract_text"] = json.dumps(
        {"module": "pwm", "ports": [{"name": "clk", "direction": "input", "width": 1}]}
    )
    app.session_state["custom_rtl_source"] = "module pwm(input wire clk); endmodule\n"
    app.session_state["custom_selected_module"] = "pwm"
    if json_text:
        app.session_state["custom_contract_json_text"] = json_text
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    return app


def _click(app: AppTest, key: str) -> None:
    target = next(item for item in app.button if getattr(item, "key", None) == key)
    target.click()
    app.run()


def test_validate_contract_button_works_when_the_json_box_is_filled():
    """真实事故：点「校验 contract」报
    ``contract 无效：st.session_state.custom_contract_json_text cannot be modified after the
    widget with key `custom_contract_json_text` is instantiated``。

    Streamlit 禁止在**本次运行**创建过 `key=X` 的控件之后再写 `st.session_state.X`。
    原来 JSON 文本框带 `key`，"校验通过后把规范格式写回文本框"这一步就必然抛错——
    于是「校验 contract」这个按钮在填过 JSON 之后完全不可用。
    现在文本框不带 `key`（`value=` 显示 + 手动回写普通 session key），任何时刻都能回写。
    """

    app = _custom_rtl_app(
        json_text='{"module":"pwm","ports":[{"name":"clk","direction":"input","width":1}]}'
    )
    _click(app, "validate_custom_contract")
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not [item.value for item in app.error], [item.value for item in app.error]
    assert any("校验通过" in item.value for item in app.success), [item.value for item in app.success]
    contract = app.session_state["custom_contract"]
    assert contract is not None
    # 规范化后的 JSON 必须真的回到文本框（显示值）与 session key
    assert app.session_state["custom_contract_json_text"] == contract.to_json()
    boxes = [item for item in app.text_area if "DUT contract JSON" in str(item.label)]
    assert boxes and boxes[0].value == contract.to_json(), [getattr(item, "value", None) for item in boxes]


def test_contract_editor_buttons_walk_through_the_documented_flow():
    """三个按钮按用户实际顺序走一遍：生成 JSON → 刷新表格 → 校验 contract。

    这条覆盖的是"点得到、点了不炸、结果对"：早期实现在「校验 contract」上必然抛
    StreamlitAPIException（见上一条用例），而「用 JSON 刷新表格」靠
    `st.rerun(scope="fragment")`——整页运行时 Streamlit 会拒绝该 scope。现在两个按钮都走
    `on_click` 回调，逻辑在 fragment 主体**之前**执行，因此既不需要重跑，也不受上下文限制。
    """

    app = _custom_rtl_app()
    _click(app, "FormSubmitter:contract_form-从表格生成 JSON")
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not [item.value for item in app.error], [item.value for item in app.error]
    generated = json.loads(app.session_state["custom_contract_json_text"])
    assert generated["module"] == "pwm", generated  # 模块名取自所选顶层 module，而不是字面量 dut

    _click(app, "contract_json_to_editor")
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not [item.value for item in app.error], [item.value for item in app.error]
    assert any("刷新表格" in item.value for item in app.success), [item.value for item in app.success]
    assert app.session_state["custom_contract_editor_ports"], "JSON 里的端口没有回到表格"

    _click(app, "validate_custom_contract")
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not [item.value for item in app.error], [item.value for item in app.error]
    assert app.session_state["custom_contract"].module == "pwm"


def test_validate_contract_reports_invalid_json_without_breaking_the_page():
    """校验失败必须报"contract 无效：<原因>"，并且不留下半份合约。

    回调里抛出的解析错误在旧实现里会被写成"Streamlit 内部错误"（那条 `cannot be modified…`），
    真正的原因（JSON 语法错在哪）反而看不到；这里钉住错误信息仍然是给人看的那种。
    """

    app = _custom_rtl_app(json_text='{"module": "pwm", "ports": [}')
    _click(app, "validate_custom_contract")
    assert not app.exception, [str(item.value) for item in app.exception]
    assert app.session_state["custom_contract"] is None
    messages = [item.value for item in app.error]
    assert messages and "contract 无效" in messages[0], messages


#: Streamlit 的控件函数（带 `key` 参数的那些）。
_WIDGET_FUNCS = frozenset(
    {
        "button", "download_button", "form_submit_button", "text_area", "text_input", "number_input",
        "selectbox", "multiselect", "radio", "checkbox", "toggle", "slider", "select_slider",
        "data_editor", "file_uploader", "color_picker", "date_input", "time_input", "camera_input",
        "chat_input", "pills", "segmented_control", "audio_input", "link_button", "form",
    }
)


def _literal_widget_key(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "key" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _session_state_target(node: ast.AST) -> str | None:
    """取出 `st.session_state.X = ...` / `st.session_state["X"] = ...` 里的 X。"""

    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    for target in targets:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute):
            if target.value.attr == "session_state":
                return target.attr
        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute):
            if target.value.attr == "session_state" and isinstance(target.slice, ast.Constant):
                if isinstance(target.slice.value, str):
                    return target.slice.value
    return None


def _write_after_widget_findings(path: Path) -> list[str]:
    """保守的 AST 检查：同一作用域内，控件创建之后又去写它的 session_state key。

    只报"同一函数/模块作用域、创建在前、赋值在后"的确定情况（跨函数调用顺序不推断），
    因此不会有误报，但能拦住这类事故的典型形态。
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings: list[str] = []

    def walk_scope(body: list[ast.stmt], scope: str) -> None:
        created: dict[str, int] = {}

        def visit(node: ast.AST) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return  # 各自作为独立作用域单独扫描
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _WIDGET_FUNCS:
                    key = _literal_widget_key(node)
                    if key:
                        created.setdefault(key, node.lineno)
            key = _session_state_target(node)
            if key and key in created:
                findings.append(
                    f"{path.name}:{node.lineno} 在 {scope} 里写 session_state['{key}']，"
                    f"而该 key 的控件已在第 {created[key]} 行创建（同一次运行内必抛 StreamlitAPIException）"
                )
            for child in ast.iter_child_nodes(node):
                visit(child)

        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk_scope(statement.body, f"{scope}::{statement.name}")
                continue
            if isinstance(statement, ast.ClassDef):
                continue
            visit(statement)

    walk_scope(tree.body, "module")
    return findings


def test_no_session_state_write_after_widget_instantiation():
    """把上面那类事故做成静态门禁：整份页面脚本都不允许"控件建好之后再写它的 key"。

    这类 bug 只在**用户点到那个按钮**时才炸，而且报错信息是 Streamlit 的内部话术，
    渲染测试默认覆盖不到（页面照样能打开）。
    """

    findings = _write_after_widget_findings(APP)
    assert not findings, "发现「控件创建后回写 session_state」的代码：\n" + "\n".join(findings)


def test_static_review_table_is_chinese_and_explains_itself():
    """静态审查表格：表头与正文都要中文，并说明这一节到底在说什么。

    真实反馈两条："RTL 静态质量审查里有什么信息"、"像图片里面的 message 能够改成中文吗"。
    规则 ID 与严重度保持英文标识（可检索），问题描述与建议必须中文。
    """

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.session_state["case_name"] = "模十计数器"
    app.run()
    _click(app, "run_static_rtl_review")
    assert not app.exception, [str(item.value) for item in app.exception]

    review = app.session_state["static_rtl_review"]
    assert review["finding_count"] >= 1, "参考设计至少会命中 `timescale 之类的提示"
    frames = []
    for element in app.dataframe:
        try:
            frames.append(element.value)
        except Exception:
            continue
    columns = [list(frame.columns) for frame in frames]
    assert any("问题" in item and "建议" in item and "严重度" in item for item in columns), columns
    body = next(frame for frame in frames if "问题" in list(frame.columns))
    assert set(body["严重度"]).issubset({"错误", "警告", "提示"}), set(body["严重度"])
    assert re.search(r"[\u4e00-\u9fff]", str(body.iloc[0]["问题"])), body.iloc[0]["问题"]

    captions = "\n".join(item.value for item in app.caption)
    assert "只**读 RTL 文本**" in captions or "只读 RTL 文本" in captions, captions[:400]


def test_vcd_section_is_a_fragment_so_clicks_do_not_reload_the_page():
    """VCD 相关按钮必须在 fragment 里，点击只重跑这一段。

    真实反馈："用 GTKWave 自动打开、读取窗口波形、分析 VCD 时间窗口都是无效的"——
    功能其实跑通，但每次点击重跑整页，页面回到顶部、结果落在视口外，看起来就像没反应。
    """

    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_show_vcd_analysis"),
        None,
    )
    assert target is not None, "未找到 _show_vcd_analysis"
    decorators = [ast.unparse(item) for item in target.decorator_list]
    assert any("fragment" in item for item in decorators), decorators
    # GTKWave 按钮与提示都在这个 fragment 内（不再由调用方渲染，否则又会整页重跑）
    region = source.split("def _show_vcd_analysis")[1].split("\nCASES: dict")[0]
    assert "用 GTKWave 打开" in region and "_open_vcd_with_gtkwave" in region, region[-400:]
    assert "_gtkwave_search_summary" in source, "失败时应说明找过哪些位置"


def test_gtkwave_path_can_be_set_manually_and_is_detected_automatically():
    """设置页必须能自动检测 GTKWave，也能手填路径（用户明确要求的功能）。"""

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    labels = [item.label for item in app.text_input]
    assert any("GTKWave" in label for label in labels), labels
    assert any("自动检测" in item.label for item in app.button), [item.label for item in app.button]
    captions = "\n".join(item.value for item in app.caption)
    assert "工具探测结果" in captions, captions[:400]


def test_gtkwave_launcher_reports_what_it_searched():
    """GTKWave 启动失败时，提示必须说清原因，并且**列出找过哪些位置**。

    真实反馈是"点了没反应、也不知道是不是没找到路径"。只说一句"未找到"没法行动：
    用户不知道去哪儿填路径。所以三种失败都要有具体信息。
    """

    namespace = _ui_functions(
        "_configured_gtkwave", "_gtkwave_search_summary", "_open_vcd_with_gtkwave",
    )
    namespace["st"] = type("Stub", (), {"session_state": {}})()
    open_vcd = namespace["_open_vcd_with_gtkwave"]

    # ① 路径存在性：显式给一个不存在的可执行文件
    ok, message = open_vcd(Path("Z:/nope/waveform.vcd"), executable="Z:/nope/gtkwave.exe")
    assert ok is False and "不存在" in message and "gtkwave.exe" in message, message

    # ② 根本没有 GTKWave：提示要包含"找过哪些位置"
    namespace["_configured_gtkwave"] = lambda: None
    ok, message = open_vcd(Path("Z:/nope/waveform.vcd"))
    assert ok is False, message
    assert "未找到 GTKWave" in message and "设置" in message, message
    assert "PATH" in message or "gtkwave" in message.lower(), message

    # ③ 有 GTKWave 但波形文件不存在：要说清是波形的问题，而不是"未找到工具"
    namespace["_configured_gtkwave"] = lambda: sys.executable  # 任何存在的可执行文件都行
    ok, message = open_vcd(Path("Z:/nope/waveform.vcd"))
    assert ok is False and "波形文件不存在" in message, message


def test_every_content_box_has_a_bounded_height():
    """长内容必须有固定可视范围，超出用滚轮（用户明确要求）。

    三类：
    1. `st.dataframe(...)` 必须显式给 `height=`（否则表格会按行数一直长下去）；
    2. `st.code(...)` / `st.json(...)` 要么套 `st.container(height=...)`，要么被 CSS 包住；
    3. `st.text_area(...)` 必须给 `height=`。
    """

    tree = ast.parse(APP.read_text(encoding="utf-8"))
    missing: list[str] = []
    code_json = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "st"):
            continue
        method = node.func.attr
        has_height = any(keyword.arg == "height" for keyword in node.keywords)
        if method in {"dataframe", "text_area"} and not has_height:
            missing.append(f"{method} @ line {node.lineno}")
        if method in {"code", "json"}:
            code_json += 1
    assert not missing, "以下内容框没有固定高度：\n" + "\n".join(missing)
    assert code_json > 0

    source = APP.read_text(encoding="utf-8")
    # CSS 兜底：code/json 的 pre 与 textarea 都要有 max-height + overflow
    for needle in ("max-height:260px", "max-height:300px", "max-height:320px"):
        assert needle in source, needle


def test_running_state_does_not_dim_the_whole_page():
    """运行中不得把整页调淡，进度反馈由按钮旁的 LOADING 提示承担。

    Streamlit 默认给手上的旧元素加 `data-stale="true"` 并施加 opacity .33——用户看到的
    就是"点了按钮整个网页被调白"。这里钉住覆盖规则存在，并钉住 `_busy` 被用在了
    所有耗时动作上（少于 10 处就说明有人漏包了）。
    """

    source = APP.read_text(encoding="utf-8")
    assert '[data-stale="true"]{opacity:1 !important' in source
    assert "_busy(" in source and "def _busy(" in source
    assert "st.spinner(" in source
    assert source.count("with _busy(") >= 10, source.count("with _busy(")


def test_page_rerun_is_fast_enough_to_be_usable():
    """换个案例不该等半天：第二次重跑必须有明确的速度上限。

    真实反馈："我从自定义 RTL 换到简单 ALU 都要加载半天"。根因是每次重跑都在扫整个仓库
    数测试函数（实测 ~10 秒 ×2），修好后是 0.2 秒级。这里给一个宽松上限（5 秒）：
    正常远低于它，而任何"又把全仓库扫一遍"的改动都会立刻超限。
    """

    import time

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.run()  # 首次渲染含解释器/模块导入，不计入
    started = time.perf_counter()
    app.session_state["case_name"] = "简单 ALU"
    app.run()
    elapsed = time.perf_counter() - started
    assert not app.exception, [str(item.value) for item in app.exception]
    assert elapsed < 5.0, f"切换案例后重跑用了 {elapsed:.2f}s，又变慢了"


def test_scenario_selector_ships_three_scenarios(rendered: AppTest):
    """页面必须按"你要做什么"给入口，而不是只按功能分页签。

    真实试用反馈里最常见的一句就是"我不知道从哪开始"：六个页签按功能命名，
    用户得自己把功能拼成流程。场景选择不改变任何裁决逻辑，只决定显示哪些控件。
    """

    radios = [item for item in rendered.radio if item.key == "ui_scenario"]
    assert radios, [item.key for item in rendered.radio]
    options = list(radios[0].options)
    assert len(options) == 3, options
    assert any("对比两份 RTL" in item for item in options)
    assert any("学习模式" in item for item in options)
    # 默认必须是"先跑起来"这条最普通的路径
    assert "验证一份 RTL" in radios[0].value


def test_diff_scenario_offers_baseline_and_candidate_without_contract():
    """对比场景要给"选基线 + 上传候选"，且**不得**要求先准备合约与计划。"""

    app = _run_app()
    app.radio(key="ui_scenario").set_value("对比两份 RTL（AI 改写验收 / 开源行为回归）").run()
    assert not app.exception, [str(item.value) for item in app.exception]
    keys = {item.key for item in app.selectbox}
    assert "diff_baseline" in keys, keys
    source = APP.read_text(encoding="utf-8")
    # 面板必须直说"不需要合约与计划"，且按钮文案不能出现"合约"这类前置要求
    assert "对比行为（不需要合约与计划）" in source
    assert "合约由基线 RTL 自动提取**草稿**" in source
    # 草稿与计划回退都必须如实告知，不能静默降级
    assert "st.warning(caveat" in source or "st.warning(caveat," in source


def test_learn_mode_collapses_advanced_options():
    """学习模式：高级选项收起，但功能一个不少（收起 ≠ 删除）。"""

    app = _run_app()
    app.radio(key="ui_scenario").set_value("学习模式（只要三个按钮）").run()
    assert not app.exception, [str(item.value) for item in app.exception]
    labels = [item.label for item in app.expander]
    assert any("高级选项" in item for item in labels), labels
    assert any("学习模式" in item.value for item in app.info), [item.value for item in app.info]
    # 折叠块里的控件仍然存在于页面上（AppTest 会渲染 expander 内容）
    source = APP.read_text(encoding="utf-8")
    assert 'st.expander("高级选项' in source


def test_failure_guides_say_they_are_hints_not_verdicts(rendered: AppTest):
    """白话失败解读必须声明"给的行号不代表那一行就是错的"。"""

    source = APP.read_text(encoding="utf-8")
    assert "def _render_failure_guides(" in source
    assert "不代表那一行就是错的" in source
    assert "这些失败是什么意思" in source


def test_evidence_cache_is_wired_and_test_count_stays_in_tests():
    """顶部实证面板必须走缓存，且测试计数不得再扫整个仓库。"""

    source = APP.read_text(encoding="utf-8")
    assert "@st.cache_data" in source, "没有使用缓存"
    assert "def _project_evidence()" in source
    # 计数函数的默认目录必须是 tests/
    tree = ast.parse(source)
    counter = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_count_test_cases"
    )
    unparsed = ast.unparse(counter)
    # ast.unparse 会把字符串统一成单引号，两种写法都认
    assert "ROOT / 'tests'" in unparsed or 'ROOT / "tests"' in unparsed, "测试计数又回到扫整个仓库了"
    # 缓存装饰器要落在 _project_evidence 与 _tools 上
    decorated = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any("cache_data" in ast.unparse(item) for item in node.decorator_list)
    }
    assert {"_project_evidence", "_tools"} <= decorated, decorated


def test_record_stats_separate_checks_from_observations():
    """`ok=true` 的观察记录不能算进"通过"的检查数。

    没有 `expected` 的向量，testbench 仍会打一条 `ok=true, has_signal=false` 的观察记录
    （`core/testbench.py::_result_display(ok=True, has_signal=False)`），于是页面上的
    `35/35 通过` 在"没有期望值"的那一轮里其实一次比对都没有——数字比证据强。
    这里钉住拆分口径：只有带 `signal` 的记录才算检查。
    """

    stats = _ui_function("_record_stats")

    class Record:
        def __init__(self, ok, signal=None):
            self.ok = ok
            self.signal = signal

    records = [Record(True, "count"), Record(False, "count"), Record(True), Record(True)]
    passed, checked, observed = stats(records)
    assert (passed, checked, observed) == (1, 2, 2)

    # 全是观察记录时，检查数为 0（页面据此显示"0 项比对"而不是"2/2 通过"）
    assert stats([Record(True), Record(True)]) == (0, 0, 2)
    assert stats([]) == (0, 0, 0)


def test_expectation_source_none_given_tells_you_how_to_improve():
    """证据等级为 none_given 时，不能只说"未验证"，还要给出可执行的下一步。"""

    source = APP.read_text(encoding="utf-8")
    assert 'source == "none_given"' in source
    assert "怎么把证据等级提上去" in source
    for hint in ("reference_model", "ai_generated", "结构化断言", "reference_model.py"):
        assert hint in source, hint
    # 观察记录的口径说明也要在页面上
    assert "不构成检查" in source


def test_overview_metrics_read_keys_that_evidence_actually_provides():
    """页面读的 evidence 键必须真的被 `_project_evidence()` 写入。

    真实事故：概览页写的是 `_ev.get('aligned', [])`，而 `_project_evidence()` 给的是
    `models_aligned` —— 于是"参考模型对齐"永远显示 **0 / 15**，把满分说成了零分。
    """

    import re

    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_project_evidence"
    )
    written = set(re.findall(r"evidence\[['\"]([a-z_]+)['\"]\]", ast.unparse(function)))
    read = set(re.findall(r"_ev\.get\(['\"]([a-z_]+)['\"]", source))
    assert read, "没有找到任何 _ev.get(...) 读取"
    assert not (read - written), f"页面读了未定义的键：{sorted(read - written)}"


def test_static_review_separates_fact_layer_from_ai_advice_layer():
    """静态审查必须是"事实层 + 建议层"两层，且默认不外发源码。

    规则命中是确定性的、参与评分，由正反例用例钉住；AI 只在其上给建议。
    真实需求是"为了凸显主题，让 AI 根据规则去比对然后给建议"——但**不能**让 AI 的建议
    混进事实层，否则可复现性与"AI 不参与判分"的承诺同时失效。
    """

    app = AppTest.from_file(str(APP), default_timeout=180)
    app.session_state["case_name"] = "模十计数器"
    app.run()
    _click(app, "run_static_rtl_review")
    assert not app.exception, [str(item.value) for item in app.exception]

    captions = "\n".join(item.value for item in app.caption)
    assert "事实层" in captions and "建议层" in captions, captions[:400]

    # 默认不把命中行代码发给模型（披露口径：不上传 RTL 源码）
    opt_in = [item for item in app.checkbox if getattr(item, "key", None) == "static_review_send_snippets"]
    assert opt_in, [getattr(item, "key", None) for item in app.checkbox]
    assert opt_in[0].value is False, "代码片段外发必须默认关闭"

    # 离线模式（默认规划器）点复核按钮：给出确定性的"非 AI"建议
    _click(app, "run_static_review_advice")
    assert not app.exception, [str(item.value) for item in app.exception]
    meta = app.session_state["static_review_advice_meta"]
    advice = app.session_state["static_review_advice"]
    assert meta["source"] == "offline_rules"
    assert meta["included_code_snippets"] is False
    assert advice["priorities"], advice
    notes = [str(item.value) for item in app.info]
    assert any("离线规则建议" in text and "非 AI" in text for text in notes), notes
    # 建议必须绑定到具体的审查版本，避免"代码换了、建议还是旧的"
    assert app.session_state["static_review_advice_hash"] == app.session_state["static_rtl_review"]["source_sha256"]


def test_static_review_advice_never_touches_the_fact_layer():
    """源码门禁：建议层不得写回命中/评分，且必须记录来源与发送内容。"""

    source = APP.read_text(encoding="utf-8")
    assert "advise_on_static_review" in source and "offline_review_advice" in source
    assert "不修改任何命中，也不参与评分" in source
    assert "不含任何源码文本" in source
    assert "幻觉防护" in source
    # 导出时事实层与建议层分开放，不能覆盖 review 字典
    assert "def _advice_export_payload" in source
    assert '"ai_advice"' in source


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
