"""安全的单页演示：案例来自代码内白名单，仿真交给 IcarusExecutor。"""
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Literal
import json
import sys
import streamlit as st

import os
import hashlib
import shutil
import subprocess
import time
import uuid
from iverilog_ai.ai import (
    DeterministicLocalProvider,
    MockProvider,
    OpenAICompatibleProvider,
    advise_on_static_review,
    offline_provider,
    offline_review_advice,
    plan_tests,
    supplement_tests,
)
from iverilog_ai.core.config import ExecutionConfig
from iverilog_ai.ai.agent import AgentLimits, STOP_LABELS, run_verification_agent
from iverilog_ai.ai.local_api_profile import load_local_api_profile
from iverilog_ai.core.executor import IcarusExecutor
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.labels import (
    COMPARE_LABELS,
    EVIDENCE_LABELS,
    run_status_label,
    verdict_label,
)
from iverilog_ai.core.failure_guide import render_failure_guides
from iverilog_ai.core.verify_diff import verify_diff
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.pipeline import explain_failure_record
from iverilog_ai.core.report import write_report
from iverilog_ai.core.toolchain import locate_tools
from iverilog_ai.core.rtl_import import import_rtl_bytes, extract_contract_draft, available_modules, RTLImportError
from iverilog_ai.core.repair_compare import safe_candidate_copy, compare_simulation_results
from iverilog_ai.core.rtl_compare import compare_rtl_sources
from iverilog_ai.core.behavior_compare import compare_rtl_behavior
from iverilog_ai.core.rules import rules_context, rule_manifest, rules_fingerprint
from iverilog_ai.core.rule_assertions import assertion_suggestions
# `scripts/` 不是安装包的一部分：从仓库外启动页面（`streamlit run E:\...\ui\app.py`）时
# `import scripts.create_evidence_pack` 会失败。把仓库根加进 sys.path 再导入，
# 页面因此不依赖"当前工作目录必须是仓库根"。
_ROOT_HINT = Path(__file__).resolve().parents[1]
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))
from scripts.create_evidence_pack import create_evidence_pack
# 注意：core.rules 与 core.static_review 各有一个 rule_manifest，签名不同
# （前者按案例返回规则文本，后者返回静态规则注册表）。必须用别名区分，否则
# 后导入的会覆盖先导入的：实证面板会静默退化成一排 "—"，而案例规则文本会报错。
from iverilog_ai.core.static_review import review_rtl_file, render_static_markdown
from iverilog_ai.core.static_review import rule_manifest as static_rule_manifest
from iverilog_ai.core.vcd import analyze_vcd_file

ROOT = Path(__file__).resolve().parents[1]
_local_api_error = ""
try:
    _local_api_profile = load_local_api_profile(ROOT / ".iverilog-ai/local-api.json")
except (OSError, ValueError) as _profile_exception:
    _local_api_profile = None
    _local_api_error = type(_profile_exception).__name__
_api_default_base = os.getenv("IVERILOG_AI_BASE_URL") or (_local_api_profile.endpoint if _local_api_profile else "https://api.deepseek.com")
_api_default_model = os.getenv("IVERILOG_AI_MODEL") or (_local_api_profile.model if _local_api_profile else "deepseek-flash")


def _configured_api_key(endpoint: str, entered_key: str) -> str:
    if entered_key.strip():
        return entered_key.strip()
    return _local_api_profile.key_for(endpoint) if _local_api_profile else ""


@contextmanager
def _busy(message: str):
    """在当前操作旁显示进度，结束后自动收起。"""

    with st.spinner(message):
        yield


def _count_test_cases(root: Path | None = None) -> int | None:
    """统计 `tests/` 下真实的测试用例数（函数级），而不是文件数。

    用 AST 数 `def test_*`：这是"测试函数数"，比文件数更接近读者理解的规模。
    注意它**小于** pytest 实际收集的用例数（`@pytest.mark.parametrize` 会在运行时
    展开成多条），因此 `tests/core/test_ui_assets.py` 会断言这里的口径与
    pytest 的收集结果一致，避免页面数字与实际跑的数量脱节。

    **默认只扫 `tests/`**：早先默认从仓库根 `rglob`，会把 `.iverilog-ai/` 下的历史运行
    目录、`.git`、临时脚本全都走一遍——实测**每次调用 ~10 秒**，而这个函数每次重跑要被
    调用两次（"换个案例要等半天"的真正原因）。测试目录本身只有几十个文件。
    """

    import ast

    base = Path(root) if root is not None else ROOT / "tests"
    total = 0
    try:
        for path in base.rglob("test_*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            total += sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
    except (OSError, SyntaxError):
        return None
    return total or None


@st.cache_data(ttl=300, show_spinner=False)
def _tools():
    """探测外部工具（缓存 5 分钟）。

    实测 `locate_tools()` 每次 ~0.4 秒（`shutil.which` 要遍历 PATH），而页面在一次重跑里
    会问它好几次（顶部状态条、设置页、GTKWave 按钮）。工具路径在一次会话里不会变，
    缓存它是安全的；需要重新探测时用「自动检测」按钮显式清缓存。
    """

    return locate_tools()


@st.cache_data(ttl=300, show_spinner=False)
def _project_evidence() -> dict:
    """读取仓库里的真实规模数据，用于页面顶部的"实证状态"面板。

    全部从磁盘现算（基准清单、规则注册表、测试函数数），不写死数字——写死的
    数字会随时间失真，而这个页面最重要的承诺就是"给的都是可核验的事实"。

    结果缓存 5 分钟：这些数字在一次会话里不会变，而每次重跑都为它们扫一遍磁盘、
    解析所有测试文件，是页面"点一下等半天"的另一半原因。
    """

    evidence: dict = {}
    try:
        manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
        evidence["cases"] = len(manifest.get("categories", []))
        evidence["defects"] = len(manifest.get("defects", []))
    except (OSError, json.JSONDecodeError):
        evidence["cases"] = evidence["defects"] = None
    try:
        rules = static_rule_manifest()
        evidence["rules"] = len(rules)
        evidence["rule_errors"] = sum(1 for item in rules if item.get("severity") == "error")
    except Exception:
        evidence["rules"] = evidence["rule_errors"] = None
    evidence["tests"] = _count_test_cases()
    try:
        tools = _tools()
        evidence["iverilog"] = tools.iverilog
        evidence["vvp"] = tools.vvp
        evidence["yosys"] = tools.yosys
        # GTKWave 只用于"打开波形看"，缺失不影响仿真判决，因此单独一栏、单独显示。
        evidence["gtkwave"] = tools.gtkwave
    except Exception:  # pragma: no cover - 探测失败不影响页面其它部分
        evidence["iverilog"] = evidence["vvp"] = evidence["yosys"] = evidence["gtkwave"] = None
    try:
        from iverilog_ai.core.reference_model import AUTHORITATIVE, SUPPORTED

        evidence["models_aligned"] = len(AUTHORITATIVE)
        evidence["models_total"] = len(SUPPORTED)
    except Exception:
        evidence["models_aligned"] = evidence["models_total"] = None
    return evidence


def _render_evidence_header() -> None:
    """先讲清"证据从哪来"，再讲功能——这是本项目与其他 AI 工具最主要的差别。"""

    evidence = _project_evidence()
    st.caption(
        "结果以本地仿真和检查记录为依据，AI 提供测试建议。"
    )
    columns = st.columns(5)
    pairs = (
        ("基准案例", evidence.get("cases")),
        ("可复现缺陷", evidence.get("defects")),
        ("静态规则", evidence.get("rules")),
        ("自动化测试", evidence.get("tests")),
        ("已校验参考模型", f"{evidence.get('models_aligned')}/{evidence.get('models_total')}"
         if evidence.get("models_total") else None),
    )
    for column, (label, value) in zip(columns, pairs):
        column.metric(label, "—" if value is None else value)
    st.caption(
        "统计来自当前本地项目；运行结果见 `docs/verification_report.md`。"
    )


def _record_stats(records) -> tuple[int, int, int]:
    """把结构化记录拆成"真的比对过的"与"只观察的"。

    为什么必须拆开：向量里没有 `expected` 时，生成的 testbench 仍会打一条
    `ok=true` 的**观察记录**（`core/testbench.py` 的 `_result_display(ok=True, has_signal=False)`）。
    于是 `35/35 通过` 在"没有期望值"的那一轮里其实一次比对都没有——数字看起来比
    实际证据强。这里按"记录里有没有 signal"区分：有 signal 的才是有比对的检查。

    返回 (通过的比对记录数, 比对记录总数, 观察记录数)。
    """

    checked = [item for item in records if getattr(item, "signal", None)]
    observed = len(records) - len(checked)
    return sum(1 for item in checked if item.ok), len(checked), observed


def _render_record_metric(label: str, records) -> None:
    """显示结构化记录：比对记录与观察记录分开，避免数字夸大证据。

    措辞刻意用"比对一致"而不是"通过"：这里的数字只说明**逐项检查对上了几条**，
    与"运行完成没有""设计对不对"是另外两层（见 ``core/labels.py`` 的三层措辞表）。
    """

    passed, checked, observed = _record_stats(records)
    if checked:
        st.metric(
            label,
            f"{passed}/{checked} 条比对一致",
            f"另有 {observed} 条观察记录（未比对）" if observed else None,
            delta_color="off",
        )
    else:
        st.metric(label, "0 项比对", f"{observed} 条观察记录（无期望值）", delta_color="off")


def _render_run_conclusion(prefix: str, status: Any, verdict: Any, failures) -> None:
    """把"运行层 / 比对层 / 结论层"三层分开显示，避免共用一个"通过"造成误读。

    为什么必须分开：``status`` 与 ``verdict`` 的取值同名（都可能是 ``passed``），
    而 ``passed`` 字段在"检出 3 个缺陷"的正常运行里仍是 ``true``。只显示一个
    原始枚举值，读者就会把"检出缺陷"读成"通过"。
    """

    run_text = run_status_label(status)
    design_text = verdict_label(verdict)
    mismatch = len(failures or ())
    st.subheader(f"{prefix}：{design_text}")
    left, middle, right = st.columns(3)
    left.metric("运行状态", run_text)
    middle.metric(
        COMPARE_LABELS["failures"],
        mismatch,
        "未记录差异" if mismatch == 0 else "查看下方详情",
        delta_color="off",
    )
    right.metric("本次结论", design_text)


# ---------------------------------------------------------------- 场景入口
#
# 为什么要有"场景"这一层：早先的页签是按**功能**分的（概览 / 验证 / 质量 / 手册 / 设置 /
# 历史），用户得自己把功能拼成一条流程。真实试用反馈里最常见的一句就是"我不知道从哪开始"。
# 场景选择只做一件事：按"你要完成什么"决定显示哪些控件，不改变任何裁决逻辑。
_SINGLE_SCENARIO = "验证一份 RTL（先跑起来）"
_DIFF_SCENARIO = "对比两份 RTL（AI 改写验收 / 开源行为回归）"
_LEARN_SCENARIO = "学习模式（只要三个按钮）"
_SCENARIOS = (_SINGLE_SCENARIO, _DIFF_SCENARIO, _LEARN_SCENARIO)


def _ui_scenario() -> str:
    """当前场景；未选过时按"验证一份 RTL"处理。"""

    value = str(st.session_state.get("ui_scenario") or _SINGLE_SCENARIO)
    return value if value in _SCENARIOS else _SINGLE_SCENARIO


def _builtin_rtl_choices() -> list[str]:
    """可作基线的仓库内 RTL 列表（相对路径，排序稳定）。"""

    root = ROOT / "rtl"
    return sorted(path.relative_to(ROOT).as_posix() for path in root.glob("*.v")) if root.is_dir() else []


def _content_fingerprint(path: str | Path | None) -> str:
    if not path:
        return ""
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    try:
        return hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        return "unavailable:" + str(source)


def _uploaded_files_key(files: Any) -> tuple[tuple[str, str], ...]:
    """Equal names and byte counts do not mean equal RTL contents."""
    return tuple((item.name, hashlib.sha256(item.getvalue()).hexdigest()) for item in files)


def _clear_input_evidence() -> bool:
    """Invalidate only derived evidence; preserve settings and saved disk artifacts."""
    keys = (
        "ai_plan", "ai_error", "ai_plan_case", "last_pipeline_result", "last_pipeline_case",
        "last_handwritten_result", "last_handwritten_case", "last_handwritten_report", "last_run_kind",
        "workspace_evidence_pack", "static_rtl_review", "static_review_advice",
        "static_review_advice_meta", "static_review_advice_hash", "rtl_comparison", "rtl_ai_review",
        "behavior_comparison", "candidate_repair_text", "custom_reference_fingerprint", "workspace_agent_result",
    )
    had_evidence = any(st.session_state.get(key) is not None for key in keys)
    for key in keys:
        st.session_state.pop(key, None)
    for state_key in list(st.session_state):
        if isinstance(state_key, str) and (state_key.startswith("workspace_vcd_") or state_key.endswith("_candidate_result")):
            st.session_state.pop(state_key, None)
    st.session_state.ai_plan = None
    st.session_state.ai_error = None
    st.session_state.ai_plan_case = None
    return had_evidence


def _invalidate_custom_contract() -> None:
    """An edited draft cannot keep using the previous validated contract."""
    st.session_state.custom_contract = None
    if _clear_input_evidence():
        st.session_state.workspace_refresh_pending = True


def _refresh_workspace_if_needed() -> None:
    # A contract fragment cannot erase its sibling result panel. Refresh the app
    # once when existing evidence was invalidated, not on ordinary table edits.
    if st.session_state.pop("workspace_refresh_pending", False):
        st.rerun()


def _sync_workspace_input(case_name: str, selected_case: dict, custom: bool) -> None:
    contract = st.session_state.get("custom_contract") if custom else None
    identity = (
        case_name,
        _content_fingerprint(selected_case.get("rtl")),
        st.session_state.get("custom_selected_module", "") if custom else "",
        contract.to_json() if contract is not None else (
            st.session_state.get("custom_contract_text", "") if custom
            else _content_fingerprint(selected_case.get("contract"))
        ),
        _compile_options(),
    )
    previous = st.session_state.get("workspace_input_identity")
    if previous is not None and previous != identity:
        _clear_input_evidence()
    st.session_state.workspace_input_identity = identity


def _sync_comparison_input(identity: Any) -> None:
    previous = st.session_state.get("diff_input_identity")
    if previous is not None and previous != identity:
        st.session_state.pop("last_verify_diff", None)
    st.session_state.diff_input_identity = identity


def _sync_vcd_input(vcd_path: Path, *, key_prefix: str) -> None:
    """Keep analysis for this VCD only; navigating within one run preserves it."""
    source = vcd_path.resolve()
    try:
        file_stat = source.stat()
        revision = (file_stat.st_mtime_ns, file_stat.st_size)
    except OSError:
        revision = None
    identity = (str(source), revision)
    identity_key = f"{key_prefix}_source_identity"
    if st.session_state.get(identity_key) != identity:
        for state_key in list(st.session_state):
            if isinstance(state_key, str) and state_key.startswith(f"{key_prefix}_"):
                st.session_state.pop(state_key, None)
        st.session_state.pop("gtkwave_message", None)
        st.session_state.pop("gtkwave_message_ok", None)
    st.session_state[identity_key] = identity


def _render_failure_guides(result: Any, *, prefix: str) -> None:
    """把失败翻成"下一步看哪里"，并明确这是**提示**不是结论。

    面向刚学 Verilog 的人，但默认对所有场景都显示——它只补充"手该往哪放"，
    不改变任何判定，因此不会让老用户误读结论。
    """

    failures = tuple(getattr(result, "failures", ()) or ())
    if not failures:
        return
    with st.expander(f"排查建议（{len(failures)} 条）", expanded=_ui_scenario() == _LEARN_SCENARIO):
        st.caption(
            "行号是排查线索，不一定是出错位置；请结合激励、复位和上游信号检查。"
        )
        for item in render_failure_guides(result, limit=5):
            st.markdown(item)


def _render_verify_diff_panel() -> None:
    """两份 RTL 的行为对比：**不需要用户先准备合约与测试计划**。

    这是本页最省事的入口，专为两类人设计：让 AI 重写过某个模块、想知道行为有没有变的人；
    以及要给一个 PR 补行为回归证据、但上游项目根本没有 testbench 的人。
    """

    st.caption(
        "上传两个版本，使用同一组测试比较输出。两份 RTL 的模块名须相同。"
    )
    choices = _builtin_rtl_choices()
    upload_baseline = "上传基线 RTL"
    baseline_file = None
    left, right = st.columns(2)
    with left:
        baseline = st.selectbox(
            "基线 RTL",
            choices + [upload_baseline],
            key="diff_baseline",
            help="选择内置设计，或上传自己的原版本。接口信息和测试计划会自动生成。",
        )
        if baseline == upload_baseline:
            baseline_file = st.file_uploader(
                "上传原版本 RTL", type=["v", "sv"], key="diff_baseline_upload",
            )
    with right:
        candidate_file = st.file_uploader(
            "候选 RTL",
            type=["v", "sv"],
            key="diff_candidate",
            help="上传修改后的版本，与左侧基线比较。",
        )

    _sync_comparison_input((
        str(baseline),
        _uploaded_files_key([baseline_file]) if baseline_file is not None else _content_fingerprint(baseline),
        _uploaded_files_key([candidate_file]) if candidate_file is not None else (),
    ))

    if st.button("开始对比", type="primary", key="run_verify_diff"):
        if baseline == upload_baseline and baseline_file is None:
            st.warning("请先上传原版本 RTL。")
        elif candidate_file is None:
            st.warning("请先上传候选 RTL。")
        else:
            try:
                with _busy("正在仿真并比较两个版本"):
                    baseline_path = (
                        import_rtl_bytes(baseline_file.name, baseline_file.getvalue(), ROOT).path
                        if baseline_file is not None else Path(str(baseline))
                    )
                    imported = import_rtl_bytes(candidate_file.name, candidate_file.getvalue(), ROOT)
                    outcome = verify_diff(
                        baseline_path,
                        imported.path,
                        ROOT / ".iverilog-ai" / "ui-verify-diff" / f"workspace-{uuid.uuid4().hex[:12]}",
                        allowed_roots=(ROOT,),
                        iverilog_path=_tools().iverilog,
                        vvp_path=_tools().vvp,
                    )
                st.session_state.last_verify_diff = outcome
            except Exception as exc:
                st.error(f"行为对比失败：{exc}")

    # 另起一个名字：`outcome` 在按钮块里是本次算出来的结果，这里是上一次留在会话里的，
    # 两者类型相同但语义不同，混用会让"点了没反应"和"看了旧结果"分不清。
    last: Any = st.session_state.get("last_verify_diff")
    if last is None:
        return
    outcome = last
    st.subheader(f"对比结论：{outcome.label}")
    columns = st.columns(4)
    columns[0].metric("可比检查项", outcome.comparable_checks, "两侧均有期望值", delta_color="off")
    columns[1].metric("逐拍波形", "已比对" if outcome.waveform_compared else "未比对", delta_color="off")
    columns[2].metric(
        "接口信息",
        "已确认" if outcome.contract_source == "provided" else "自动草稿",
        delta_color="off",
    )
    columns[3].metric("差异数量", len(outcome.differences), delta_color="off")

    if outcome.differences:
        st.dataframe(
            [
                {
                    "类型": item["kind"],
                    "位置": item["where"],
                    "基线": item["expected"],
                    "候选": item["actual"],
                    "说明": item["message"],
                }
                for item in outcome.differences
            ],
            use_container_width=True,
            hide_index=True,
            height=260,
        )
    elif outcome.status == "identical":
        st.success("当前测试未发现行为差异；这不等于形式等价证明。")
    else:
        st.info("可比证据不足，暂时无法判断两份 RTL 是否一致。原因见下方。")

    for caveat in outcome.caveats:
        st.warning(caveat, icon="⚠️")

    markdown = Path(outcome.artifacts["markdown"])
    if markdown.is_file():
        st.download_button(
            "下载对比报告",
            markdown.read_bytes(),
            file_name=markdown.name,
            mime="text/markdown",
            key="download_verify_diff_md",
        )
    with st.expander("原始结果 JSON"):
        st.json(outcome.to_dict())


def _render_expectation_source(config: dict) -> None:
    """把"这一轮期望值是谁给的"讲清楚——这是可信度的关键，也是最容易被忽略的信息。

    用中文说明期望值来源，并保留影响结果可信度的边界。
    """

    oracle = (config or {}).get("oracle") or {}
    if not oracle:
        return
    source = oracle.get("expectation_source", "unknown")
    grade = EVIDENCE_LABELS.get(str(source), f"未知来源（{source}）")
    if source == "reference_model":
        st.success(
            f"期望值：**{grade}**。本次采用参考模型结果，AI 数值不参与判定。"
        )
    elif source == "ai_generated":
        st.warning(
            f"期望值：**{grade}**。尚未经参考模型核验，AI 数值出错会影响结论。"
        )
    elif source == "none_given":
        st.error(
            "未给出期望值：本轮没有逐项比对，不能视为功能验证通过。"
        )
        _design = str(oracle.get("design") or "")
        _assertions = (config or {}).get("structured_assertions") or {}
        _assertion_note = (
            f"另检查了 {_assertions.get('checked', 0)} 条断言，通过 {_assertions.get('passed', 0)} 条。"
            if _assertions.get("checked")
            else "本轮也未设置断言；运行完成不代表功能正确。"
        )
        st.caption(
            (f"`{_design}` 暂无参考模型。" if _design else "")
            + _assertion_note
        )
        with st.expander("如何补充检查"):
            st.markdown(
                "- **补充期望值**：在线模型可以生成，但仍需人工核验。\n"
                "- **添加断言**：检查信号取值、稳定性或变化顺序，见手册「进阶用法」。\n"
                "- **使用参考模型**：内置案例已提供；自定义设计需编写并验证相应模型。"
            )
    else:
        st.info(f"期望值：**{grade}**")
    if oracle.get("advice"):
        st.caption(oracle["advice"])
    if oracle.get("ai_expected_mismatch"):
        st.caption(
            f"AI 期望值与参考模型有 {oracle.get('mismatched_expected', '若干')} 项不同；本次按参考模型判定。"
        )


def _configured_gtkwave() -> str | None:
    """按"页面里填的路径 → 环境变量 → 自动探测"的顺序取 GTKWave 可执行文件。"""

    manual = str(st.session_state.get("gtkwave_path", "") or "").strip()
    if manual:
        path = Path(manual)
        if path.is_file():
            return str(path)
    env_value = str(os.getenv("GTKWAVE_PATH", "") or "").strip()
    if env_value and Path(env_value).is_file():
        return env_value
    try:
        return _tools().gtkwave
    except Exception:
        return None


def _open_vcd_with_gtkwave(vcd_path: Path, *, executable: str | None = None) -> tuple[bool, str]:
    """用 GTKWave 打开 VCD（固定可执行文件 + 参数列表，绝不经过 shell）。

    路径来源见 :func:`_configured_gtkwave`：页面里手填的路径优先，其次是
    `GTKWAVE_PATH` 环境变量，最后是从 PATH / 常见目录 / iverilog 安装位置推断。
    真实反馈是"点了没反应、也不知道是不是没找到路径"，因此失败时把**找过哪些位置**
    一并带出来，而不是只说一句"未找到"。
    """

    resolved = executable or _configured_gtkwave()
    if not resolved:
        tried = _gtkwave_search_summary()
        return False, (
            "未找到 GTKWave。请在「设置 → 波形查看器（GTKWave）」里填写 gtkwave.exe 的完整路径，"
            "或设置环境变量 GTKWAVE_PATH。已查找：" + tried
        )
    target = Path(resolved)
    if not target.is_file():
        return False, f"GTKWave 路径不存在：{target}。请在「设置 → 波形查看器（GTKWave）」里更正。"
    if not Path(vcd_path).is_file():
        return False, f"波形文件不存在：{vcd_path}"
    try:
        # Keep the GUI process visible.  Some Windows GTKWave launchers exit
        # immediately when started with CREATE_NO_WINDOW.
        # Use the executable directory as cwd: GTKWave bundles DLLs and
        # launcher helpers next to the binary on Windows.
        process = subprocess.Popen(
            [str(target), str(vcd_path)],
            shell=False,
            close_fds=True,
            cwd=str(target.parent),
        )
    except OSError as exc:
        return False, f"GTKWave 启动失败：{exc}（路径：{target}）"
    # 启动后立刻退出通常意味着缺 DLL 或参数不被接受；这里等一下再确认，避免"看起来成功了"。
    time.sleep(0.4)
    if process.poll() is not None:
        return False, f"GTKWave 启动后立即退出（退出码 {process.returncode}）：{target}"
    return True, f"已用 GTKWave 打开：{vcd_path.name}（{target}，PID {process.pid}）"


def _gtkwave_search_summary() -> str:
    """列出 GTKWave 的查找位置，供失败提示使用（不猜测、只说实际找过的地方）。

    这里**故意用未缓存的 `locate_tools()`**：它只在"启动失败"这条路径上被调用，
    此刻需要的是"刚刚真的找过哪里"，而不是 5 分钟前的缓存结果。
    """

    from iverilog_ai.core.toolchain import gtkwave_candidates, locate_tools

    parts: list[str] = []
    manual = str(st.session_state.get("gtkwave_path", "") or "").strip()
    if manual:
        parts.append(f"页面填写的路径（不存在）：{manual}")
    if os.getenv("GTKWAVE_PATH"):
        parts.append(f"环境变量 GTKWAVE_PATH={os.getenv('GTKWAVE_PATH')}")
    if shutil.which("gtkwave"):
        parts.append(f"PATH：{shutil.which('gtkwave')}")
    else:
        parts.append("PATH 中没有 gtkwave")
    for candidate in gtkwave_candidates(locate_tools().iverilog):
        parts.append(candidate)
    return "；".join(parts)


def _show_behavior_comparison(data: dict) -> None:
    """展示行为级对比结论：逐检查项结果 + 波形差异 + 口径说明。"""

    st.subheader("行为对比结果")
    status = str(data.get("status", ""))
    summary = data.get("record_summary", {})
    if status == "identical":
        st.success("当前测试未发现行为差异；这不等于形式等价证明。")
    elif status == "different":
        st.warning("两份 RTL 存在行为差异。")
    else:
        st.info(f"对比结论：{status}")
    columns = st.columns(4)
    columns[0].metric("用户 RTL 状态", str(summary.get("user_status", "-")))
    columns[1].metric("参考 RTL 状态", str(summary.get("reference_status", "-")))
    columns[2].metric("检查项差异", summary.get("mismatched_checks", 0))
    columns[3].metric(
        "失败项（用户/参考）",
        f"{summary.get('user_failed', 0)}/{summary.get('reference_failed', 0)}",
    )
    mismatches = data.get("mismatches", [])
    if mismatches:
        with st.expander(f"逐检查项差异（{len(mismatches)} 处）", expanded=True):
            st.dataframe(
                [
                    {
                        "测试": item.get("test_id"),
                        "信号": item.get("signal"),
                        "类型": item.get("kind"),
                        "用户 RTL": (item.get("user") or {}).get("actual"),
                        "参考 RTL": (item.get("reference") or {}).get("actual"),
                    }
                    for item in mismatches
                ],
                use_container_width=True,
                hide_index=True,
                height=240,
            )
    waveform = data.get("waveform", {})
    st.markdown("**波形比对**")
    st.write(
        f"- 状态：`{waveform.get('status')}`；共有信号差异 {waveform.get('difference_count', 0)} 处"
        f"（其中 DUT 内部信号 {len(waveform.get('dut_differences', []))} 处）"
    )
    dut_differences = waveform.get("dut_differences", [])
    if dut_differences:
        for item in dut_differences[:10]:
            st.write(f"- {item.get('message', '')}")
    if waveform.get("reference_only_signals") or waveform.get("user_only_signals"):
        st.caption(
            "信号集合差异：参考独有 "
            + (", ".join(waveform.get("reference_only_signals", [])) or "无")
            + "；用户独有 "
            + (", ".join(waveform.get("user_only_signals", [])) or "无")
        )
    for note in data.get("notes", []):
        st.caption(note)
    st.caption(data.get("disclaimer", ""))
    st.download_button(
        "下载行为对比 JSON",
        json.dumps(data, ensure_ascii=False, indent=2),
        file_name="behavior-comparison.json",
        mime="application/json",
        key="download_behavior_comparison",
    )


def _show_synthesis(synthesis: dict | None) -> None:
    """展示分层证据：仿真/综合跑过，时序/比特流/上板显式标未运行。

    这张表刻意把"没做的事"写出来，避免把"综合通过"误读成"能上板"。
    """

    data = synthesis or {}
    stages = data.get("stages") or []
    if not stages:
        return
    st.subheader("验证进度")
    labels = {
        "provided_by_pipeline": "本次运行已提供",
        # 这一列说的是"这一层的工具跑完了没有"，刻意不用"通过"——"通过"是结论层的词，
        # 混用会让读者把"综合工具跑完了"读成"设计综合正确"。
        "passed": "已完成",
        "failed": "失败",
        "unavailable": "工具不可用",
        "timeout": "超时",
        "error": "执行错误",
        "not_run": "未运行",
    }
    st.dataframe(
        [
            {
                "层级": item.get("title", item.get("stage", "")),
                "状态": labels.get(str(item.get("status")), item.get("status")),
                "说明": item.get("detail", ""),
            }
            for item in stages
        ],
        use_container_width=True,
        hide_index=True,
        height=200,
    )
    status = str(data.get("status", "not_run"))
    if status == "passed":
        columns = st.columns(4)
        columns[0].metric("门级单元", data.get("cell_count") or 0)
        columns[1].metric("单元类型", data.get("cell_kinds") or 0)
        columns[2].metric("连线", data.get("wire_count") or 0)
        columns[3].metric("综合耗时", f"{data.get('duration_ms', 0)} ms")
        if data.get("cells"):
            with st.expander("门级单元明细"):
                st.dataframe(data["cells"], use_container_width=True, hide_index=True, height=240)
    elif status == "failed":
        st.error("综合失败：" + str(data.get("error") or "未知原因"))
        st.caption("仿真通过不代表可综合，请查看综合错误。")
    else:
        st.info("综合未执行：" + str(data.get("skipped_reason") or data.get("error") or "本次未启用综合"))
    if data.get("warnings"):
        st.caption(f"综合告警 {len(data['warnings'])} 条；首条：{data['warnings'][0]}")
    st.caption(data.get("disclaimer", ""))


# 注意：这个函数必须定义在**第一次调用之前**。ui/app.py 是线性脚本，模块级语句
# 按顺序执行——把它放在文件后半部分时，自定义 RTL 的行为级对比会在调用点抛
# NameError（被 except Exception 捕获成一句"行为级对比失败：name '_contract' is not defined"）。
def _compile_options() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """读取界面上填写的宏定义与 include 目录（逗号分隔）。

    这两项以前只有命令行支持（`--define` / `--include-dir`），网页上无法使用，
    于是"自定义 RTL 依赖宏或 include"的场景在演示时只能绕开。路径合法性不在这里
    判断：`SafePathPolicy` 会在执行前统一校验，越界会以明确错误返回。
    """

    raw_defines = str(st.session_state.get("compile_defines", "") or "")
    raw_includes = str(st.session_state.get("compile_includes", "") or "")
    defines = tuple(item.strip() for item in raw_defines.replace(";", ",").split(",") if item.strip())
    includes = tuple(item.strip() for item in raw_includes.replace(";", ",").split(",") if item.strip())
    return defines, includes


def _wire_api_for(label: str) -> Literal["responses", "chat_completions"]:
    """把界面上的接口格式标签映射成 provider 接受的**字面量**取值。

    原先三处各写一遍内联三元表达式，类型上退化成 `str`，静态检查无法确认
    传进去的一定是合法取值。集中成一个函数后，类型与实现都只有一份。
    """

    return "responses" if label.startswith("Responses") else "chat_completions"


def _contract() -> DutContract:
    if is_custom:
        if st.session_state.get("custom_contract") is None:
            raise ValueError("请先上传 RTL，再点击「校验接口」。")
        # Session state can outlive a source reload. Revalidate the confirmed
        # JSON instead of passing an instance of an obsolete module class.
        return DutContract.from_json(st.session_state.custom_contract.to_json())
    return DutContract.from_json((ROOT / case["contract"]).read_text(encoding="utf-8"))

def _verification_rules(case_name: str, contract: DutContract, spec_text: str) -> str:
    """Load bounded repository rules for model guidance; never executes them."""
    return rules_context(ROOT, RULE_CASE_NAMES.get(case_name, case_name), contract.to_json(), spec_text=spec_text)[0]


@st.fragment
def _show_vcd_analysis(vcd_path: Path, *, key_prefix: str, preset: dict | None = None) -> None:
    """显示 VCD 信号元数据、语义结论与时间窗分析。

    **整段是 fragment**：用户反馈"点『读取窗口波形』『分析 VCD 时间窗口』像是没反应"——
    功能其实跑通了，但每次点击都重跑**整个脚本**，页面回到顶部、结果落在视口之外，
    看起来就像没生效（"用 GTKWave 自动打开"同理）。放进 fragment 后，这几个按钮只重跑
    这一段，结果就地出现。
    """

    _sync_vcd_input(vcd_path, key_prefix=key_prefix)
    data = preset or {}
    if data.get("status") == "parsed":
        st.caption(f"波形范围：{data.get('start_ns')} ～ {data.get('end_ns')} ns · {data.get('signal_count', 0)} 个信号 · {data.get('total_changes', 0)} 次变化")
        if data.get("signals"):
            with st.expander("信号列表"):
                st.dataframe(data["signals"], use_container_width=True, hide_index=True, height=240)

        # 信号活动覆盖率：激励质量的指标，**不是**代码覆盖率（口径见 docs/coverage.md）
        activity = data.get("coverage") or {}
        if activity.get("status") == "measured":
            st.markdown("**信号活动**")
            columns = st.columns(3)
            columns[0].metric(
                "活动信号",
                f"{activity.get('changed_signals', 0)}/{activity.get('declared_signals', 0)}",
                f"{activity.get('ratio', 0) * 100:.0f}%",
            )
            value_coverage = activity.get("value_coverage")
            columns[1].metric("取值覆盖", "—" if value_coverage is None else f"{value_coverage * 100:.0f}%")
            columns[2].metric("未变化信号", activity.get("unchanged_signals", 0))
            if activity.get("unchanged"):
                st.info("未变化信号：" + "、".join(activity["unchanged"]))
            if activity.get("value_detail"):
                with st.expander("取值覆盖明细"):
                    st.dataframe(activity["value_detail"], use_container_width=True, hide_index=True, height=240)
            st.caption("这里只统计信号是否活动，不是代码覆盖率；信号有变化也不代表功能正确。")
            with st.expander("统计说明"):
                st.caption(activity.get("disclaimer", ""))
                if activity.get("note"):
                    st.caption(activity["note"])

        # 波形语义结论：边沿统计、稳定性与相位检查（来自流水线的 insights）
        insights = data.get("insights") or {}
        if insights.get("notes"):
            st.markdown("**波形分析**")
            for note in insights["notes"]:
                st.write(f"- {note}")
        if insights.get("unstable_signals"):
            st.warning("这些设计信号需检查稳定性：" + "、".join(insights["unstable_signals"]))
        if insights.get("unstable_auxiliary"):
            st.info(
                "以下测试辅助信号多次变化，不用于判断电路稳定性："
                + "、".join(insights["unstable_auxiliary"])
            )
        if insights.get("signal_edges"):
            with st.expander("信号边沿与稳定性"):
                rows = []
                stability = {item.get("signal"): item for item in insights.get("stability", [])}
                for item in insights["signal_edges"]:
                    entry = stability.get(item.get("signal"), {})
                    status = entry.get("status", "-")
                    if entry.get("status") == "unstable":
                        status = "不稳定（设计信号）" if entry.get("is_dut") else "不稳定（测试辅助信号）"
                    rows.append({**item, "归属": "DUT" if entry.get("is_dut") else "testbench", "稳定性": status})
                st.dataframe(rows, use_container_width=True, hide_index=True, height=240)
        if insights.get("phase_checks"):
            st.markdown("**输出时序（提前或延后一拍）**")
            st.dataframe(insights["phase_checks"], use_container_width=True, hide_index=True, height=200)

        # 失败周期对应的波形时间窗（流水线已算好，此前没有展示入口）
        windows = data.get("failure_windows") or {}
        if windows.get("status") == "parsed" and windows.get("windows"):
            with st.expander(f"失败附近的波形（{len(windows['windows'])} 处）"):
                st.caption(windows.get("disclaimer", ""))
                rows = [
                    {
                        "失败周期": item.get("cycle"),
                        "时间窗(ns)": f"{item.get('start_ns')} ～ {item.get('end_ns')}",
                        "窗口内信号数": (item.get("analysis") or {}).get("signal_count", 0),
                        "窗口内变化数": (item.get("analysis") or {}).get("total_changes", 0),
                    }
                    for item in windows["windows"]
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True, height=220)
                st.download_button(
                    "下载失败波形 JSON",
                    json.dumps(windows, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="failure-windows.json",
                    mime="application/json",
                    key=f"{key_prefix}_failure_windows",
                )
    if st.button("选择时间范围", key=f"{key_prefix}_analyze", help="展开起止时间，查看该范围内的信号变化，无需 GTKWave。"):
        if data.get("start_ns") is None or data.get("end_ns") is None:
            st.warning("波形没有可用的时间范围。")
        else:
            st.session_state[f"{key_prefix}_window"] = {"start": float(data["start_ns"]), "end": float(data["end_ns"])}
    window = st.session_state.get(f"{key_prefix}_window")
    if window is not None:
        st.caption("设置起止时间后，点击「读取波形」。")
        _win_cols = st.columns(2)
        start = _win_cols[0].number_input("起始时间 (ns)", min_value=0.0, value=float(window["start"]), key=f"{key_prefix}_start")
        end = _win_cols[1].number_input("结束时间 (ns)", min_value=float(start), value=max(float(start), float(window["end"])), key=f"{key_prefix}_end")
        if st.button("读取波形", key=f"{key_prefix}_read", type="primary"):
            try:
                with _busy("正在读取波形"):
                    st.session_state[f"{key_prefix}_window_data"] = analyze_vcd_file(vcd_path, start_ns=start, end_ns=end, max_changes=2000)
            except Exception as exc:
                st.error(f"波形读取失败：{exc}")
    window_data = st.session_state.get(f"{key_prefix}_window_data")
    if window_data:
        _win_total = window_data.get("total_changes", 0)
        _win_signals = window_data.get("signal_count", 0)
        st.success(
            f"已读取 {window_data.get('start_ns')} ～ {window_data.get('end_ns')} ns："
            f"{_win_signals} 个信号，{_win_total} 次变化"
            + ("（变化记录限 2000 条）" if window_data.get("truncated") else "")
        )
        if window_data.get("changes"):
            st.dataframe(window_data["changes"], use_container_width=True, hide_index=True, height=260)
        else:
            st.info("所选时间内没有信号变化，可扩大范围再试。")
        st.download_button("下载波形分析 JSON", json.dumps(window_data, ensure_ascii=False, indent=2).encode("utf-8"), file_name="vcd-analysis.json", mime="application/json", key=f"{key_prefix}_download")
    else:
        st.caption("选择时间范围可查看信号变化。")

    # 波形查看器：按钮放在 fragment 内，点击只重跑这一段（此前会整页重跑，看起来像没反应）。
    st.divider()
    _gv_col, _gv_info = st.columns([1, 3])
    with _gv_col:
        if st.button("用 GTKWave 打开", key=f"{key_prefix}_gtkwave_open"):
            with _busy("正在启动 GTKWave"):
                ok, message = _open_vcd_with_gtkwave(vcd_path)
            st.session_state.gtkwave_message = message
            st.session_state.gtkwave_message_ok = ok
    with _gv_info:
        _gv_path = _configured_gtkwave()
        if _gv_path:
            st.caption(f"GTKWave：{_gv_path}")
        else:
            st.caption("未找到 GTKWave，可在「工具设置」中填写安装路径。")
    if st.session_state.get("gtkwave_message"):
        renderer = st.success if st.session_state.get("gtkwave_message_ok") else st.warning
        renderer(st.session_state.gtkwave_message)


CASES: dict[str, dict[str, Any]] = {
    "交通灯·紧急模式": {"rtl": "rtl/traffic_light_emergency.v", "tb": "tb/tb_traffic_light_emergency.v", "top": "tb_traffic_light_emergency", "spec": "spec/traffic_light_emergency_spec.md", "contract": "examples/traffic_light_emergency_contract.json"},
    "模十计数器": {"rtl": "rtl/mod10_counter.v", "tb": "tb/tb_mod10_counter.v", "top": "tb_mod10_counter", "spec": "spec/mod10_counter_spec.md", "contract": "examples/mod10_counter_contract.json"},
    "简单 ALU": {"rtl": "rtl/simple_alu.v", "tb": "tb/tb_simple_alu.v", "top": "tb_simple_alu", "spec": "spec/simple_alu_spec.md", "contract": "examples/simple_alu_contract.json"},
    "101 序列检测（允许重叠）": {"rtl": "rtl/sequence_101_overlap.v", "tb": "tb/tb_sequence_101_overlap.v", "top": "tb_sequence_101_overlap", "spec": "spec/sequence_101_overlap_spec.md", "contract": "examples/sequence_101_overlap_contract.json"},
    "同步上升沿检测器": {"rtl": "rtl/edge_detector.v", "tb": "tb/tb_edge_detector.v", "top": "tb_edge_detector", "spec": "spec/edge_detector_spec.md", "contract": "examples/edge_detector_contract.json"},
    "脉冲展宽器": {"rtl": "rtl/pulse_stretcher.v", "tb": "tb/tb_pulse_stretcher.v", "top": "tb_pulse_stretcher", "spec": "spec/pulse_stretcher_spec.md", "contract": "examples/pulse_stretcher_contract.json"},
    "单时钟 FIFO": {"rtl": "rtl/sync_fifo.v", "tb": "tb/tb_sync_fifo.v", "top": "tb_sync_fifo", "spec": "spec/common_cases.md", "contract": "examples/sync_fifo_contract.json"},
    "UART 发送器": {"rtl": "rtl/uart_tx.v", "tb": "tb/tb_uart_tx.v", "top": "tb_uart_tx", "spec": "spec/common_cases.md", "contract": "examples/uart_tx_contract.json"},
    "SPI 主机": {"rtl": "rtl/spi_master.v", "tb": "tb/tb_spi_master.v", "top": "tb_spi_master", "spec": "spec/common_cases.md", "contract": "examples/spi_master_contract.json"},
    "Valid-Ready 握手级": {"rtl": "rtl/handshake_stage.v", "tb": "tb/tb_handshake_stage.v", "top": "tb_handshake_stage", "spec": "spec/common_cases.md", "contract": "examples/handshake_stage_contract.json"},
    "按键去抖": {"rtl": "rtl/debounce.v", "tb": "tb/tb_debounce.v", "top": "tb_debounce", "spec": "spec/common_cases.md", "contract": "examples/debounce_contract.json"},
    "PWM": {"rtl": "rtl/pwm.v", "tb": "tb/tb_pwm.v", "top": "tb_pwm", "spec": "spec/common_cases.md", "contract": "examples/pwm_contract.json"},
    "四选一多路选择器": {"rtl": "rtl/mux4.v", "tb": "tb/tb_mux4.v", "top": "tb_mux4", "spec": "spec/common_cases.md", "contract": "examples/mux4_contract.json"},
    "同步复位模块": {"rtl": "rtl/sync_reset.v", "tb": "tb/tb_sync_reset.v", "top": "tb_sync_reset", "spec": "spec/common_cases.md", "contract": "examples/sync_reset_contract.json"},
    "约翰逊计数器": {"rtl": "rtl/johnson_counter.v", "tb": "tb/tb_johnson_counter.v", "top": "tb_johnson_counter", "spec": "spec/johnson_counter_spec.md", "contract": "examples/johnson_counter_contract.json"},
}

RULE_CASE_NAMES = {
    "交通灯·紧急模式": "traffic_light_emergency", "模十计数器": "mod10_counter", "简单 ALU": "simple_alu", "101 序列检测（允许重叠）": "sequence_101_overlap", "同步上升沿检测器": "edge_detector", "脉冲展宽器": "pulse_stretcher", "单时钟 FIFO": "sync_fifo", "UART 发送器": "uart_tx", "SPI 主机": "spi_master", "Valid-Ready 握手级": "handshake_stage", "按键去抖": "debounce", "PWM": "pwm", "四选一多路选择器": "mux4", "同步复位模块": "sync_reset", "约翰逊计数器": "johnson_counter", "自定义 RTL": "custom_rtl",
}


def _show_failure_explanation(result, key):
    failures = getattr(result, "failures", ())
    if failures and st.button("解释失败原因", key=key):
        for failure in failures:
            item = explain_failure_record(failure)
            if getattr(failure, "severity", "warn") == "error":
                st.error(item.summary)
            else:
                st.warning(item.summary)
            st.caption(f"问题编号：{item.fingerprint}")


def _candidate_repair_text(result, rtl_path):
    """Create a review-only repair proposal; never mutates RTL or invokes a shell."""
    failures = tuple(getattr(result, "failures", ()) or ())
    source = Path(rtl_path)
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        digest = "unavailable"
    lines = [
        "# 候选 RTL 修复建议（待人工确认）", "",
        "> 这不是已应用的补丁。系统不会自动覆盖原始 RTL。请人工审查后在临时副本中验证。", "",
        f"- RTL 文件：`{source.name}`", f"- RTL SHA-256：`{digest}`",
        f"- 失败条数：{len(failures)}", "", "## 失败证据",
    ]
    for index, failure in enumerate(failures, 1):
        item = explain_failure_record(failure)
        lines.extend([f"{index}. {item.summary}", f"   - 指纹：`{item.fingerprint}`"])
    lines += ["", "## 建议检查方向"]
    for failure in failures:
        message = (failure.message or "").lower()
        if "timeout" in message or "超时" in message:
            suggestion = "检查 testbench 是否缺少 $finish、时钟/复位是否持续，以及 RTL 是否存在无法退出的状态循环。"
        elif failure.signal:
            suggestion = f"检查信号 `{failure.signal}` 的时序、复位极性和边界条件；以失败周期附近波形为证据。"
        else:
            suggestion = "根据失败周期和 VCD 波形定位状态转换或输出时序问题。"
        lines.append(f"- {suggestion}")
    lines += ["", "## 人工确认清单", "- [ ] 已阅读失败证据和 VCD 波形", "- [ ] 已在临时副本应用修改", "- [ ] 已使用相同回归集重新仿真", "- [ ] 回归通过后再决定是否手动合并"]
    return "\n".join(lines) + "\n"


def _show_candidate_repair(result, rtl_path, key):
    """Show/download a candidate proposal only after an explicit user action."""
    failures = tuple(getattr(result, "failures", ()) or ())
    if not failures:
        return
    st.subheader("修复建议")
    st.caption("按失败记录生成排查清单，需人工修改后重新验证。")
    if st.button("生成修复建议", key=key):
        st.session_state["candidate_repair_text"] = _candidate_repair_text(result, rtl_path)
    proposal = st.session_state.get("candidate_repair_text")
    if proposal:
        with st.container(height=260):
            st.code(proposal, language="markdown")
        st.download_button("下载修复建议", proposal.encode("utf-8"), file_name="candidate-repair.md", mime="text/markdown", key=f"{key}_download")


def _show_candidate_verify(before_result, rtl_path, contract, plan, key):
    """验证用户上传的候选 RTL 副本，并比较同一计划的前后结果。"""
    uploaded = st.file_uploader("上传修复后的 RTL", type=["v", "sv"], key=f"{key}_upload", help="支持 .v/.sv，使用副本验证，不覆盖原文件。")
    if uploaded is None:
        return
    if st.button("验证修复", key=f"{key}_run"):
        try:
            candidate = import_rtl_bytes(uploaded.name, uploaded.getvalue(), ROOT).path
            output = ROOT / ".iverilog-ai" / "repair-candidates" / candidate.stem
            after = VerificationPipeline().run(plan, contract.to_dict(), candidate, output, allowed_roots=(ROOT,),
                iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe", emit_vcd=True)
            comparison = compare_simulation_results(before_result, after.simulation)
            st.subheader("修复前后对比")
            st.json(comparison.__dict__)
            st.session_state[f"{key}_candidate_result"] = comparison.__dict__
            if comparison.verdict == "candidate_verified": st.success("修复版本通过本次测试，仍需完整回归。")
            elif comparison.verdict == "improved": st.warning("结果有所改善，仍有问题待检查。")
            else: st.error("修复版本未通过本次验证。")
        except Exception as exc:
            st.error(f"候选修复验证失败：{exc}")


def _set_contract_editor(raw: str) -> None:
    """将 JSON contract 拆分到表格编辑器的 session 状态。"""
    try:
        value = json.loads(raw)
        st.session_state.custom_contract_editor_ports = list(value.get("ports", []))
        clock = value.get("clock") or {}
        reset = value.get("reset") or {}
        st.session_state.custom_contract_editor_parameters = dict(value.get("parameters") or {})
        st.session_state.custom_contract_editor_clock = {
            "signal": clock.get("signal", ""), "period_ns": float(clock.get("period_ns", 10.0)),
            "edge": clock.get("edge", "posedge"),
        }
        st.session_state.custom_contract_editor_reset = {
            "signal": reset.get("signal", ""), "active_level": int(reset.get("active_level", 0)),
            "synchronous": bool(reset.get("synchronous", False)), "assert_cycles": int(reset.get("assert_cycles", 2)),
        }
    except Exception:
        pass


def _replace_custom_contract_draft(raw: str) -> None:
    """Install a different DUT draft before its editor widgets are mounted."""
    _clear_input_evidence()
    st.session_state.custom_contract = None
    st.session_state.custom_contract_text = raw
    for key in (
        "custom_contract_json_text", "custom_contract_editor_ports", "custom_contract_editor_parameters",
        "custom_contract_editor_clock", "custom_contract_editor_reset", "contract_clock_signal",
        "contract_clock_period", "contract_clock_edge", "contract_reset_signal",
        "contract_reset_active", "contract_reset_sync", "contract_reset_cycles", "contract_editor_notice",
    ):
        st.session_state.pop(key, None)
    st.session_state["contract_editor_gen"] = int(st.session_state.get("contract_editor_gen", 0)) + 1
    if raw:
        st.session_state.custom_contract_json_text = raw
        _set_contract_editor(raw)


def _clear_custom_upload() -> None:
    _replace_custom_contract_draft("")
    for key in (
        "custom_uploaded_key", "custom_uploaded_files", "custom_rtl_source",
        "custom_modules", "custom_selected_module", "custom_warnings",
    ):
        st.session_state.pop(key, None)
    st.session_state.custom_rtl_path = ""


def _contract_payload(
    *,
    module: str,
    ports: list,
    parameters: dict | None,
    clock_signal: str,
    clock_period: float,
    clock_edge: str,
    reset_signal: str,
    reset_active: Any,
    reset_sync: bool,
    reset_cycles: Any,
) -> dict:
    """把编辑区里的表格与时钟/复位字段拼成 contract 字典（纯函数，便于单测）。

    抽出来的理由：这段转换是"表格 → 合约"的唯一逻辑，出错的后果是**合约静默错位**
    （比如复位电平写反），而它原本埋在 Streamlit 控件代码里，无法在测试里直接调用。
    """

    payload: dict = {"module": module or "dut", "ports": list(ports)}
    if parameters:
        payload["parameters"] = dict(parameters)
    if str(clock_signal).strip():
        payload["clock"] = {"signal": str(clock_signal).strip(), "period_ns": float(clock_period), "edge": clock_edge}
    if str(reset_signal).strip():
        payload["reset"] = {
            "signal": str(reset_signal).strip(),
            "active_level": int(reset_active or 0),
            "synchronous": bool(reset_sync),
            "assert_cycles": int(reset_cycles or 1),
        }
    return payload


def _contract_editor_notice(level: str, message: str) -> None:
    """把一条提示留给 `_contract_editor` 在**下一次运行**开头渲染。

    为什么不直接 `st.success(...)`：校验逻辑放在控件回调里（见下），而回调在 fragment
    主体之前执行，此时渲染的提示会跑到编辑区最上方、与按钮离得很远；存下来在主体里渲染，
    位置稳定、也不会因为随后的重跑丢掉。
    """

    st.session_state["contract_editor_notice"] = (str(level), str(message))


def _validate_contract_on_click() -> None:
    """「校验 contract」按钮的回调：校验 + 规范化 + 回写文本框。

    **回调是关键**：Streamlit 在每次运行开始时先跑控件回调，再执行 fragment 主体，
    因此这里回写 `st.session_state.custom_contract_json_text` 完全合法——即使那个文本框
    带 `key` 也一样（它还没被创建）。

    真实事故：这段逻辑原先写在按钮的 `if st.button(...)` 分支里，位置在文本框**创建之后**，
    于是每次点「校验 contract」都抛
    `StreamlitAPIException: st.session_state.custom_contract_json_text cannot be modified
    after the widget with key ... is instantiated`，按钮等于完全不可用。
    """

    try:
        contract = DutContract.from_json(st.session_state.get("custom_contract_json_text", ""))
    except Exception as exc:
        _invalidate_custom_contract()
        _contract_editor_notice("error", f"接口定义有误：{exc}")
        return
    previous = st.session_state.get("custom_contract")
    if previous is None or previous.to_json() != contract.to_json():
        _invalidate_custom_contract()
    st.session_state.custom_contract = contract
    canonical = contract.to_json()
    st.session_state.custom_contract_text = canonical
    # 回调阶段回写控件 key 合法：文本框本次运行还没创建，下一次渲染就会显示规范格式。
    st.session_state.custom_contract_json_text = canonical
    _contract_editor_notice("success", "接口校验通过，可以生成测试计划了。")


def _apply_json_to_table_on_click() -> None:
    """「用 JSON 刷新表格」的回调：把 JSON 里的端口、时钟、复位同步到编辑控件。

    同样靠"回调先于主体执行"这条性质：换掉 data_editor 的 key（让它用新数据重新初始化）、
    直接写时钟/复位控件的 key，都不需要任何重跑。以前这一步用
    `st.rerun(scope="fragment")`，而整页运行时 Streamlit 会**拒绝**该 scope
    （"can only be specified from @st.fragment-decorated functions during fragment reruns"），
    同一个按钮在两种运行上下文里表现不一致；现在整条交互链里不再有 `st.rerun`。
    """

    try:
        parsed = DutContract.from_json(st.session_state.get("custom_contract_json_text", ""))
    except Exception as exc:
        _contract_editor_notice("error", f"JSON 无效：{exc}")
        return
    payload = parsed.to_dict()
    st.session_state.custom_contract_editor_ports = list(payload.get("ports", []))
    # 换一代 key：data_editor 用新端口列表重新初始化（数据始终只从影子列表来）。
    st.session_state["contract_editor_gen"] = int(st.session_state.get("contract_editor_gen", 0)) + 1
    st.session_state.custom_contract_text = parsed.to_json()
    _set_contract_editor(parsed.to_json())
    clock = payload.get("clock") or {}
    reset = payload.get("reset") or {}
    st.session_state["contract_clock_signal"] = str(clock.get("signal", ""))
    st.session_state["contract_clock_period"] = float(clock.get("period_ns", 10.0))
    st.session_state["contract_clock_edge"] = str(clock.get("edge", "posedge"))
    st.session_state["contract_reset_signal"] = str(reset.get("signal", ""))
    st.session_state["contract_reset_active"] = int(reset.get("active_level", 0))
    st.session_state["contract_reset_sync"] = bool(reset.get("synchronous", False))
    st.session_state["contract_reset_cycles"] = int(reset.get("assert_cycles", 2))
    # JSON 改过就必须重新校验，避免用旧合约继续跑
    _invalidate_custom_contract()
    _contract_editor_notice("success", "表格已更新，请校验接口。")


def _load_suggested_assertions_on_click() -> None:
    """「载入本案例推荐结构化断言」的回调：把已验证的建议写进断言文本框。

    放在回调里（而不是 `if st.button(...)` 分支里）有两个原因：回调在主体之前执行，
    写进去的值本次运行就会显示；而且不需要整页重跑——用户在「从表格生成 JSON」那里
    明确反馈过整页刷新很烦。

    当前 `rule_assertions` 的建议表是空的（原先 5 条全部不成立，见该模块说明），
    因此这个按钮暂时不会渲染；表里一旦重新加入经门禁验证的条目，按钮即可用。
    """

    case_key = str(st.session_state.get("case_name", ""))
    suggestions = assertion_suggestions(RULE_CASE_NAMES.get(case_key, case_key))
    if suggestions:
        st.session_state.structured_assertions_text = json.dumps(suggestions, ensure_ascii=False, indent=2)


def _contract_module_hint() -> str:
    """从当前 JSON 文本框里取 `module`，作为「从表格生成 JSON」的模块名兜底。

    只读、只认字符串且非空；解析失败就返回空串（调用方再兜底 "dut"）。
    """

    try:
        payload = json.loads(st.session_state.get("custom_contract_json_text") or "{}")
    except Exception:
        return ""
    if isinstance(payload, dict):
        module = payload.get("module")
        if isinstance(module, str) and module.strip():
            return module.strip()
    return ""


@st.fragment
def _contract_editor() -> None:
    """DUT contract 编辑区（**整段跑在 fragment 里**）。

    为什么要 fragment：Streamlit 默认"控件一变就重跑整个脚本"，编辑表格或点按钮都会让
    整页重新渲染——滚动位置丢失、其它区域闪烁，体验上就像刷新了整个页面。
    `@st.fragment` 让这一段的交互只重跑这一段。

    另外两处修正：
    - 表格 ↔ JSON 的同步原来是**自动双向**的（JSON 一变回写表格、表格一变又靠
      `st.rerun()` 回写），既容易互相覆盖，也必须多跑一遍脚本才生效。现在改成两个显式
      动作：表格 → JSON（表单提交）、JSON → 表格（按钮），不再有隐式重跑。
    - 原来"从表格生成 JSON"先 `st.success(...)` 再 `st.rerun()`，那条成功提示会被立刻
      丢掉（用户只看到页面一闪）。现在不重跑，提示留在原地。

    还有一条 Streamlit 硬规则必须绕开：**本**次运行里已经创建过 `key=X` 的控件之后，
    再写 `st.session_state.X` 会直接抛
    `StreamlitAPIException: ... cannot be modified after the widget with key ... is instantiated`。
    这里的对策是**按动作选位置**，而不是到处搬代码：
    - 「表格 → JSON」需要 data_editor 的返回值，只能在主体里做——它写的是文本框 key，
      但位置在文本框**之前**，合法；
    - 「校验 contract」不需要任何控件返回值（JSON 文本就在 session state 里），因此整个
      搬到 `on_click` 回调里，在主体之前执行，回写文本框 key 合法且当次立即生效；
    - 「JSON → 表格」要在渲染前换成新数据（换 data_editor 的 key、并回写时钟/复位控件），
      同样放在回调里，因此**整条交互链里没有 `st.rerun`**：不需要整页重跑，也不需要
      `scope="fragment"` 重跑（后者在整页运行时会被 Streamlit 直接拒绝）。
    """

    _refresh_workspace_if_needed()
    _notice = st.session_state.pop("contract_editor_notice", None)
    if isinstance(_notice, tuple) and len(_notice) == 2:
        _level, _message = str(_notice[0]), str(_notice[1])
        (st.error if _level == "error" else st.success)(_message)

    if not st.session_state.get("custom_contract_text"):
        return
    # 影子列表（端口数据）永远是 list：解析失败也要留一个空列表，否则后续读取会 KeyError。
    if not isinstance(st.session_state.get("custom_contract_editor_ports"), list):
        _set_contract_editor(st.session_state.custom_contract_text)
        if not isinstance(st.session_state.get("custom_contract_editor_ports"), list):
            st.session_state.custom_contract_editor_ports = []
    _ports_shadow = st.session_state["custom_contract_editor_ports"]
    # data_editor 的数据**始终**来自影子列表（`custom_contract_editor_ports`），
    # `key` 只用来标识控件。踩过的坑：`session_state[key]` 里存的是 Streamlit 自己的
    # **编辑状态**（`{edited_rows, added_rows, deleted_rows}`），不是端口数据；把它当数据
    # 喂回 data_editor，pandas 会抛 "Mixing dicts with non-Series…" 直接把整页打成 500
    # （真实事故，见 job 日志）。所以：数据只从一个地方来，编辑结果只看返回值。
    #
    # 需要"换一批数据"时（JSON → 表格），靠换 key 让编辑器重新初始化：
    _editor_generation = int(st.session_state.get("contract_editor_gen", 0))
    _editor_key = f"custom_ports_editor_{_editor_generation}"

    with st.expander("端口与时钟", expanded=True):
        with st.form("contract_form", clear_on_submit=False):
            rows = st.data_editor(
                _ports_shadow,
                num_rows="dynamic",
                use_container_width=True,
                key=_editor_key,
                column_config={
                    "name": st.column_config.TextColumn("端口名称", required=True),
                    "direction": st.column_config.SelectboxColumn(
                        "方向", options=["input", "output", "inout"], required=True
                    ),
                    "width": st.column_config.NumberColumn("位宽", min_value=1, max_value=4096, step=1, required=True),
                    "signed": st.column_config.CheckboxColumn("有符号", default=False),
                },
            )
            c1, c2, c3 = st.columns(3)
            clock = st.session_state.get("custom_contract_editor_clock", {"signal": "", "period_ns": 10.0, "edge": "posedge"})
            reset = st.session_state.get("custom_contract_editor_reset", {"signal": "", "active_level": 0, "synchronous": False, "assert_cycles": 2})
            with c1:
                clock_signal = st.text_input("时钟信号", value=clock.get("signal", ""), key="contract_clock_signal")
                clock_period = st.number_input("时钟周期 (ns)", min_value=0.001, value=float(clock.get("period_ns", 10.0)), key="contract_clock_period")
                clock_edge = st.selectbox("时钟边沿", ["posedge", "negedge"], index=0 if clock.get("edge", "posedge") == "posedge" else 1, key="contract_clock_edge")
            with c2:
                reset_signal = st.text_input("复位信号（可留空）", value=reset.get("signal", ""), key="contract_reset_signal")
                reset_active = st.selectbox("复位有效电平", [0, 1], index=int(reset.get("active_level", 0)), key="contract_reset_active")
                reset_sync = st.checkbox("同步复位", value=bool(reset.get("synchronous", False)), key="contract_reset_sync")
            with c3:
                reset_cycles = st.number_input("复位持续周期", min_value=1, max_value=10000, value=int(reset.get("assert_cycles", 2)), step=1, key="contract_reset_cycles")
                st.caption("没有复位信号时留空。")
            _submitted = st.form_submit_button("从表格生成 JSON", type="primary")
        if _submitted:
            try:
                payload = _contract_payload(
                    # 模块名的优先级：用户显式选的顶层 module → 当前 JSON 里写的 module →
                    # 兜底 "dut"。早先只写 `get("custom_selected_module", "dut")`：从没上传过
                    # RTL（例如直接手写 JSON 进编辑区）时会静默生成一份 `module="dut"` 的
                    # 合约——它自己校验得过，但和真实 RTL 的模块名对不上。
                    module=str(
                        st.session_state.get("custom_selected_module") or _contract_module_hint() or "dut"
                    ),
                    ports=list(rows),
                    parameters=st.session_state.get("custom_contract_editor_parameters"),
                    clock_signal=clock_signal,
                    clock_period=clock_period,
                    clock_edge=str(clock_edge or "posedge"),
                    reset_signal=reset_signal,
                    reset_active=reset_active,
                    reset_sync=reset_sync,
                    reset_cycles=reset_cycles,
                )
                _contract = DutContract.from_dict(payload)
                st.session_state.custom_contract_text = _contract.to_json()
                st.session_state.custom_contract_editor_ports = list(_contract.to_dict()["ports"])
                # 文本框在下方创建，本行在它之前执行，因此回写它的 key 合法。
                st.session_state.custom_contract_json_text = _contract.to_json()
                # 表格改过就必须重新校验，避免用旧合约继续跑
                _invalidate_custom_contract()
                st.success("JSON 已更新，请校验接口。")
            except Exception as exc:
                st.error(f"表格内容无效：{exc}")

    # 文本框带 `key`，值由 Streamlit 自己管；首帧用一个种子，避免出现空框。
    if "custom_contract_json_text" not in st.session_state:
        st.session_state.custom_contract_json_text = st.session_state.get("custom_contract_text", "")
    st.text_area(
        "接口定义 JSON",
        height=190,
        key="custom_contract_json_text",
        on_change=_invalidate_custom_contract,
        help="修改表格后点「从表格生成 JSON」；修改 JSON 后可点「用 JSON 刷新表格」。运行前请校验接口。",
    )
    _sync_col, _validate_col, _export_col = st.columns([1.8, 1.3, 1])
    with _sync_col:
        # 两个按钮的逻辑都放在 `on_click` 回调里：回调在本次运行**创建任何控件之前**执行，
        # 因此可以合法地回写控件 key、也可以在渲染前换掉 data_editor 的数据，
        # 既不需要整页重跑，也不需要 fragment 级重跑（见两个回调函数的说明）。
        st.button(
            "用 JSON 刷新表格",
            key="contract_json_to_editor",
            on_click=_apply_json_to_table_on_click,
        )
    with _validate_col:
        st.button(
            "校验接口",
            type="primary",
            key="validate_custom_contract",
            on_click=_validate_contract_on_click,
        )
    with _export_col:
        if st.session_state.get("custom_contract") is not None:
            with st.popover("导出"):
                st.download_button(
                    "接口定义 JSON",
                    st.session_state.custom_contract.to_json(),
                    file_name="dut_contract.json",
                    mime="application/json",
                    key="download_custom_contract",
                )
    _refresh_workspace_if_needed()


def _offline_provider(contract: DutContract, *, vector_count: int | None = None) -> DeterministicLocalProvider:
    """构造页面「离线」模式用的规划器：按**当前 DUT contract** 生成激励。

    真实事故：这里原先直接 `MockProvider()`，而它的默认返回值是一份写死的演示计划
    （design=demo，向量固定驱动 `rst_n`）。选中组合逻辑案例（`simple_alu`、`mux4`
    的合约中没有时钟也没有复位）后点「生成测试计划」，下游生成 testbench 时必然
    报 `vectors[0].inputs contains unknown port 'rst_n'`——而同一个案例点「执行真实
    Icarus 仿真」却是通过的，看起来像"离线模式坏了"。

    现在离线模式走仓库自带的确定性离线规划器（与本地调试模型服务同一个引擎），
    它按合约里真实存在的端口生成激励，因此对组合逻辑与时序案例都有效。
    """

    # seed 固定为 0：同一次输入永远得到同一份计划，报告与复现实验才能对齐。
    if vector_count is None:
        return offline_provider(contract, seed=0)
    return offline_provider(contract, seed=0, vector_count=vector_count)


def _build_provider(target: str):
    """读取稳定的控件状态；调用位置不依赖设置面板的渲染顺序。"""

    settings = st.session_state
    planner_mode = str(settings.get("planner_mode", ""))
    if planner_mode.startswith("本地调试"):
        return OpenAICompatibleProvider(
            endpoint=str(settings.get("provider_debug_endpoint", os.getenv("IVERILOG_AI_DEBUG_ENDPOINT", "http://127.0.0.1:11434/v1"))),
            model="debug-local",
            wire_api="chat_completions",
            reasoning_effort=None,
            allow_network=False,
            store=False,
            timeout=30,
        )
    endpoint = str(settings.get("provider_api_base", _api_default_base))
    model = str(settings.get("provider_api_model", _api_default_model))
    picked_model = str(settings.get("picked_model_from_list", "（不覆盖，使用上面的输入）"))
    if picked_model != "（不覆盖，使用上面的输入）":
        model = picked_model
    key = _configured_api_key(endpoint, str(settings.get("provider_api_key", "")))
    wire = _wire_api_for(str(settings.get("provider_wire_api", "Chat Completions API")))
    reasoning = str(settings.get("provider_reasoning", "不发送（兼容性最高）"))
    if "deepseek" in (endpoint + " " + model).lower() and wire == "responses":
        wire = "chat_completions"
    if not key.strip():
        raise ValueError(f"{target}需要当前 API 地址对应的密钥。请检查配置或输入 API Key。")
    return OpenAICompatibleProvider(
        endpoint=endpoint,
        model=model,
        api_key=key,
        wire_api=wire,
        reasoning_effort=None if reasoning.startswith("不发送") or wire != "responses" else reasoning,
        allow_network=True,
        store=False,
        timeout=int(settings.get("provider_api_timeout", 120)),
        max_output_tokens=int(settings.get("provider_api_output_tokens", 4096)),
    )


# ---------------------------------------------------------------------------
# 视觉主题：情报档案式控制台；样式和示意图均来自本地资源。
# ---------------------------------------------------------------------------
_UI_ASSETS = Path(__file__).resolve().parent / "assets"
import base64

# A bundled OFL font keeps the display typography available offline. Assets are
# embedded once; no external font request or Streamlit static-server dependency.
_DISPLAY_FONT = base64.b64encode((_UI_ASSETS / "fonts" / "Anton-Regular.ttf").read_bytes()).decode("ascii")
_RL_CSS = (
    "<style>@font-face{font-family:IcarusDisplay;src:url(data:font/ttf;base64,"
    + _DISPLAY_FONT + ") format('truetype');font-display:swap;}"
    + (_UI_ASSETS / "console.css").read_text(encoding="utf-8") + "</style>"
)


def _inject_theme() -> None:
    st.markdown(_RL_CSS, unsafe_allow_html=True)


def _section_header(index: str, english: str, title: str, description: str) -> None:
    subtitle = f'<p>{description}</p>' if description else ""
    st.markdown(
        f'<div class="console-section"><div><div class="section-kicker">{english} ://</div>'
        f'<h2>{title}</h2>{subtitle}</div><div class="section-index">{index}</div></div>',
        unsafe_allow_html=True,
    )


def _console_hero() -> None:
    """Original grayscale verification fixture; decorative, never run evidence."""
    graphic = base64.b64encode((_UI_ASSETS / "verification-map.svg").read_bytes()).decode("ascii")
    st.markdown(
        '<div class="console-hero"><div class="hero-copy">'
        '<div class="hero-eyebrow">ICARUS / RTL VERIFICATION SYSTEM</div>'
        '<div class="hero-english">VERIFICATION</div>'
        '<h1>验证工作台</h1><div class="hero-accent"></div>'
        '<p>从设计到证据。<br>生成测试计划，执行仿真，追踪每一次信号变化。</p>'
        '<div class="hero-rule"><span>DESIGN → PLAN → SIMULATION</span></div>'
        '</div><div class="hero-visual">'
        f'<img src="data:image/svg+xml;base64,{graphic}" '
        'alt="原创黑白技术插画：RTL芯片、测试探针和波形验证设备。">'
        '<span class="hero-caption">DUT / SIGNAL ACQUISITION</span></div>'
        '<div class="hero-chapter"><b>01</b><span>/ 06</span><strong>WORKSPACE</strong>'
        '<small>验证工作台</small></div><div class="hero-watermark" aria-hidden="true">ICARUS</div></div>',
        unsafe_allow_html=True,
    )


def _chips(items: list[tuple[str, str, str]]) -> None:
    """渲染状态小标签：`(标签, 值, 状态)`，状态取 ok/warn/err/idle。"""

    html = "".join(
        f'<span class="rl-chip"><i class="rl-dot {state}"></i>{label} <b>{value}</b></span>'
        for label, value, state in items
    )
    st.markdown(html, unsafe_allow_html=True)


def _brandbar() -> None:
    st.markdown(
        '<div class="rl-brand"><div class="brand-identity">'
        '<svg class="brand-symbol" viewBox="0 0 40 40" fill="none" aria-hidden="true">'
        '<path d="M5 4h30v32H5zM11 11h18v18H11z" stroke="#F2F3F3"/>'
        '<path d="M16 0v11m8-11v11M16 29v11m8-11v11M0 16h11M0 24h11m18-8h11m-11 8h11" stroke="#939A9E"/>'
        '<path d="m16 21 3 3 6-8" stroke="#00C8E8" stroke-width="2"/></svg>'
        '<div><div class="mark">ICARUS <span>智测</span></div>'
        '<div class="brand-subtitle">RTL VERIFICATION</div></div></div>'
        '<div class="tag"><b>RTL WORKSPACE</b><br>测试 · 仿真 · 波形</div></div>',
        unsafe_allow_html=True,
    )


_MANUAL_DIR = ROOT / "docs" / "manual"
_MANUAL_PAGES = (
    ("入门", "01_beginner.md"),
    ("进阶用法", "02_advanced.md"),
    ("原理与复现", "03_deep.md"),
    ("按目的查找", "04_by_goal.md"),
)


@st.cache_data(ttl=300, show_spinner=False)
def _manual_text(filename: str) -> str:
    """读一页手册（缓存 5 分钟）。

    手册每次重跑都会被渲染一遍（Streamlit 的 tabs 会渲染全部页签，只是隐藏未选中的），
    每次读盘 + 传输几 KB。缓存读盘部分，避免"点一下重发四个文档"。
    """

    path = _MANUAL_DIR / filename
    return path.read_text(encoding="utf-8") if path.is_file() else ""


#: AI 建议里的等级/置信度词（模型输出英文枚举，页面展示中文）。
_ADVICE_LEVEL_CN = {"must_fix": "必须改", "should_fix": "建议改", "consider": "可选"}
_ADVICE_CONFIDENCE_CN = {"low": "低", "medium": "中", "high": "高"}


def _advice_export_payload(review: dict, advice: dict | None, meta: dict | None) -> dict:
    """导出用载荷：把"事实层"与"AI 建议层"放在**不同键**下，互不覆盖。

    刻意不把建议写进 `review` 本身——那份字典是确定性审查的产物（sha256、评分、命中），
    掺进不可复现的 AI 文本会让"可复现"这件事失效。
    """

    payload = dict(review)
    if advice is not None:
        payload["ai_advice"] = {
            "source": (meta or {}).get("source", "unknown"),
            "model": (meta or {}).get("model"),
            "included_code_snippets": (meta or {}).get("included_code_snippets", False),
            "attempts": (meta or {}).get("attempts"),
            "review_sha256": (meta or {}).get("review_sha256"),
            "dropped_unknown_rule_ids": (meta or {}).get("dropped_unknown_rule_ids", []),
            "disclaimer": "AI 建议不修改规则命中、不参与质量评分；命中与评分以 review 字段为准。",
            "advice": advice,
        }
    return payload


def _advice_markdown(review: dict, advice: dict | None, meta: dict | None) -> str:
    """把建议层追加到 Markdown 审查报告末尾（事实层在前，建议层在后）。"""

    if not advice:
        return render_static_markdown(review)
    body = [render_static_markdown(review), "", "---", "", "## AI 复核与修复建议", ""]
    if (meta or {}).get("source") == "ai":
        body.append(f"> 来源：**AI 模型**（`{(meta or {}).get('model') or '未记录'}`）；发送内容："
                    f"{'结构化字段 + 命中行代码片段' if (meta or {}).get('included_code_snippets') else '仅结构化字段（不含源码）'}。")
    else:
        body.append("> 来源：**离线规则表**（非 AI 输出，无模型参与）。")
    body.append("> 本层**不修改规则命中，也不参与质量评分**；命中与评分以上面的确定性审查为准。")
    body.append("")
    body.append(f"**结论**：{advice.get('summary', '')}")
    priorities = advice.get("priorities") or []
    if priorities:
        body.extend(["", "### 处理优先级", "", "| 优先级 | 规则 | 行号 | 为什么 | 怎么改 |", "|---|---|---:|---|---|"])
        for item in priorities:
            body.append(
                f"| {_ADVICE_LEVEL_CN.get(str(item.get('level')), item.get('level'))} "
                f"| `{item.get('rule_id')}` | {item.get('line') or '-'} "
                f"| {str(item.get('why', '')).replace('|', '/')} | {str(item.get('fix', '')).replace('|', '/')} |"
            )
    false_positives = advice.get("false_positive_candidates") or []
    if false_positives:
        body.extend(["", "### 可能是误报（仅候选，不改命中）", ""])
        for item in false_positives:
            body.append(f"- `{item.get('rule_id')}` 行 {item.get('line') or '-'}：{item.get('reason')}"
                        f"（置信度 {_ADVICE_CONFIDENCE_CN.get(str(item.get('confidence')), item.get('confidence'))}）")
    suspects = advice.get("additional_suspects") or []
    if suspects:
        body.extend(["", "### 额外怀疑（未经规则验证）", ""])
        for item in suspects:
            rule = f"`{item.get('rule_id')}`" if item.get("rule_id") else "未映射到现有规则"
            body.append(f"- {rule} 行 {item.get('line') or '-'}：{item.get('reason')}"
                        f"（置信度 {_ADVICE_CONFIDENCE_CN.get(str(item.get('confidence')), item.get('confidence'))}）")
    assumptions = advice.get("assumptions") or []
    if assumptions:
        body.extend(["", "**假设**：" + "；".join(str(item) for item in assumptions)])
    dropped = (meta or {}).get("dropped_unknown_rule_ids") or []
    if dropped:
        body.extend(["", f"**被丢弃的无效规则 ID**（幻觉防护）：{', '.join(str(item) for item in dropped)}"])
    return "\n".join(body) + "\n"


def _render_static_advice(advice: dict, meta: dict) -> None:
    """渲染复核结果：建议 / 误报候选 / 额外怀疑三层分开，并写明来源与发送内容。"""

    is_ai = str(meta.get("source")) == "ai"
    _model = str(meta.get("model") or "")
    # 「本地调试模型」走的是回环 HTTP，但它只是确定性规则引擎、不是真实模型：
    # 这条路径的结论必须与真正调用模型区分开，否则会把规则输出说成模型输出。
    is_debug_local = "debug-local" in _model
    if is_ai and is_debug_local:
        st.info(
            f"**本地调试建议**（规则生成，未调用模型）：{advice.get('summary', '')}"
        )
    elif is_ai:
        st.success(f"**AI 建议**（`{_model or '未记录'}`）：{advice.get('summary', '')}")
    else:
        st.info(f"**离线规则建议**（非 AI）：{advice.get('summary', '')}")

    priorities = advice.get("priorities") or []
    if priorities:
        st.dataframe(
            [
                {
                    "优先级": _ADVICE_LEVEL_CN.get(str(item.get("level")), item.get("level")),
                    "规则ID": item.get("rule_id"),
                    "行号": item.get("line"),
                    "为什么": item.get("why"),
                    "怎么改": item.get("fix"),
                }
                for item in priorities
            ],
            use_container_width=True,
            hide_index=True,
            height=240,
        )
    else:
        st.caption("暂无待处理的规则问题。")

    false_positives = advice.get("false_positive_candidates") or []
    if false_positives:
        st.warning("以下问题可能是误报，请核对。规则结果和评分保持不变。")
        st.dataframe(
            [
                {
                    "规则ID": item.get("rule_id"),
                    "行号": item.get("line"),
                    "理由": item.get("reason"),
                    "置信度": _ADVICE_CONFIDENCE_CN.get(str(item.get("confidence")), item.get("confidence")),
                }
                for item in false_positives
            ],
            use_container_width=True,
            hide_index=True,
            height=160,
        )

    suspects = advice.get("additional_suspects") or []
    if suspects:
        st.info("以下是尚未经过规则验证的疑点，请核对。")
        st.dataframe(
            [
                {
                    "可能规则": item.get("rule_id") or "未映射到现有规则",
                    "行号": item.get("line"),
                    "信号": item.get("signal"),
                    "理由": item.get("reason"),
                    "置信度": _ADVICE_CONFIDENCE_CN.get(str(item.get("confidence")), item.get("confidence")),
                }
                for item in suspects
            ],
            use_container_width=True,
            hide_index=True,
            height=160,
        )

    assumptions = advice.get("assumptions") or []
    if assumptions:
        st.caption("建议基于以下假设：" + "；".join(str(item) for item in assumptions))

    sent = ("审查结果和命中行代码"
            if meta.get("included_code_snippets") else "审查结果（不含源码）")
    _source_label = "本地调试服务（确定性规则）" if is_debug_local else ("AI 模型" if is_ai else "离线规则表")
    st.caption(
        f"来源：{_source_label}；复核内容：{sent}。建议不改变规则结果，也不参与评分。"
    )
    dropped = meta.get("dropped_unknown_rule_ids") or []
    if dropped:
        st.caption("已忽略无效规则 ID：" + "、".join(str(item) for item in dropped))


def _render_manual() -> None:
    """在网页内渲染多版使用手册（内容源是仓库里的 Markdown，CLI 与网页共用一份）。"""

    tabs = st.tabs([title for title, _ in _MANUAL_PAGES])
    for tab, (title, filename) in zip(tabs, _MANUAL_PAGES):
        with tab:
            path = _MANUAL_DIR / filename
            if not path.is_file():
                st.warning(f"手册文件缺失：{path.relative_to(ROOT)}")
                continue
            with st.container(height=420):
                st.markdown(_manual_text(filename), unsafe_allow_html=False)
    st.caption("手册文件：`docs/manual/`。")


def _workspace_panel(page: str) -> Any:
    """Keep controls mounted while top navigation changes the visible panel.

    Provider fields and fragment widgets retain session state across navigation.
    Routing hides only this container, including it from the accessibility tree.
    """
    panel = st.container()
    with panel:
        st.markdown(f'<span class="workspace-route" data-page="{page}" aria-hidden="true"></span>', unsafe_allow_html=True)
    return panel


def _lane(number: str, title: str, description: str) -> None:
    subtitle = f'<small>{description}</small>' if description else ""
    st.markdown(
        f'<div class="workspace-lane"><span>{number}</span><div><b>{title}</b>{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def _open_task_workspace() -> None:
    st.session_state.workspace_page = "工作台"
    st.session_state.workspace_mobile_page = "工作台"


def _desktop_page_changed() -> None:
    st.session_state.workspace_mobile_page = st.session_state.workspace_page


def _mobile_page_changed() -> None:
    st.session_state.workspace_page = st.session_state.workspace_mobile_page


def _render_workspace_results() -> None:
    """Render each run once; all evidence and export actions survive reruns."""
    pipeline = st.session_state.get("last_pipeline_result")
    handwritten = st.session_state.get("last_handwritten_result")
    pipeline_valid = pipeline is not None and st.session_state.get("last_pipeline_case") == name
    handwritten_valid = handwritten is not None and st.session_state.get("last_handwritten_case") == name
    use_pipeline = pipeline_valid and (st.session_state.get("last_run_kind") != "handwritten" or not handwritten_valid)
    result = pipeline if use_pipeline else handwritten if handwritten_valid else None
    with _RESULTS:
        _lane("03", "测试结果", "")
        if result is None:
            st.markdown(
                '<div class="workspace-empty"><b>还没有测试结果</b>'
                '<p>先运行一次测试，结果会显示在这里。</p></div>',
                unsafe_allow_html=True,
            )
            return
        simulation = result.simulation if use_pipeline else result
        summary, waveform, repair, export = st.tabs(["结论", "波形", "修复建议", "导出证据"])
        with summary:
            _render_run_conclusion("本次验证结果", result.status, result.verdict, result.failures)
            _render_record_metric("实际仿真比对", result.records)
            _render_failure_guides(simulation, prefix="AI 计划" if use_pipeline else "手写 testbench")
            _render_expectation_source(simulation.config if isinstance(simulation.config, dict) else {})
            if use_pipeline:
                _show_synthesis(result.synthesis)
                coverage = result.coverage
                st.subheader("计划执行情况")
                st.caption("统计测试计划的执行情况，不代表 RTL 代码覆盖率。")
                col_vector, col_check = st.columns(2)
                vectors, checks = coverage["vectors"], coverage["checks"]
                col_vector.metric(
                    "测试向量覆盖",
                    f"{vectors['covered']}/{vectors['total']}" if vectors["total"] else "—",
                    f"{vectors['percent']}%" if vectors["total"] else None,
                )
                col_check.metric(
                    "计划显式检查覆盖",
                    f"{checks['covered']}/{checks['total']}" if checks["total"] else "—",
                    f"{checks['percent']}%" if checks["total"] else None,
                )
                if not checks["total"]:
                    st.caption("计划未写入预期值，此项显示为“—”。参考模型补充的检查计入上方实际比对。")
                if coverage["per_signal"]:
                    st.dataframe([
                        {"信号": signal, "已覆盖": item["covered"], "总检查": item["total"], "覆盖率": f"{item['percent']}%" if item["total"] else "—"}
                        for signal, item in coverage["per_signal"].items()
                    ], use_container_width=True, hide_index=True, height=220)
            with st.expander("运行详情"):
                with st.container(height=300):
                    st.json(simulation.to_dict())
        with waveform:
            vcd_value = result.artifacts.get("vcd", "")
            vcd_path = Path(vcd_value) if vcd_value else None
            if vcd_path is not None and vcd_path.is_file():
                st.caption(f"VCD 文件：{vcd_path.name} · {vcd_path.stat().st_size:,} bytes")
                st.download_button("下载 VCD 波形", vcd_path.read_bytes(), file_name=vcd_path.name, mime="application/octet-stream", key="workspace_download_vcd")
                preset = simulation.config.get("vcd_analysis", {}) if isinstance(simulation.config, dict) else None
                _show_vcd_analysis(vcd_path, key_prefix="workspace_vcd", preset=preset)
            else:
                st.info("本次没有波形文件。若使用自己的 testbench，请开启波形记录。")
        with repair:
            if result.failures:
                with st.expander("失败记录", expanded=True):
                    with st.container(height=260):
                        st.json([failure.to_dict() for failure in result.failures])
                _show_failure_explanation(result, "workspace_explain")
                _show_candidate_repair(result, case.get("rtl") or "", "workspace_repair")
                if use_pipeline:
                    _show_candidate_verify(simulation, ROOT / str(case["rtl"]), _contract(), result.plan, "workspace_candidate_verify")
                    if st.button("补充测试", help="根据失败记录补充计划，之后需要重新运行。", key="workspace_supplement"):
                        try:
                            contract = _contract()
                            spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
                            if use_online or use_debug_local:
                                feedback_provider = _build_provider("补充测试向量")
                            else:
                                feedback_provider = _offline_provider(contract, vector_count=2)
                                st.caption("离线模式只补充边界测试，不分析失败原因。")
                            with _busy("正在补充测试向量"):
                                st.session_state.ai_plan = supplement_tests(
                                    result.plan, result.failures, feedback_provider,
                                    context=spec_text + "\nDUT contract:\n" + contract.to_json(), max_new_vectors=10, max_retries=0,
                                )
                            st.success("计划已补充，请重新运行测试。")
                        except Exception as exc:
                            st.error(f"补充测试失败：{exc}")
            else:
                st.info("本次没有失败记录。")
        with export:
            report = Path(result.artifacts["output_dir"]) / "report.md" if use_pipeline else Path(st.session_state.last_handwritten_report)
            if report.is_file():
                st.download_button("下载 Markdown 报告", report.read_bytes(), file_name="report.md", mime="text/markdown", key="workspace_download_report")
            with st.expander("文件位置"):
                st.code(str(report), language="text")
                if use_pipeline:
                    st.code(str(result.artifacts.get("pipeline_result", "")), language="text")
            if use_pipeline:
                st.download_button("下载测试计划", json.dumps(result.plan.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8"), file_name="test-plan.json", mime="application/json", key="workspace_download_plan")
                with st.expander("生成的 testbench"):
                    with st.container(height=320):
                        st.code(Path(result.artifacts["testbench"]).read_text(encoding="utf-8"), language="verilog")
                if st.button("打包本次结果", key="create_pipeline_evidence_pack", help="包含报告、测试计划、testbench、波形和校验清单。"):
                    try:
                        # Use this run's artifacts, never the mutable latest-run pointer.
                        pack_dir = Path(simulation.artifacts["run_dir"]) / "evidence-pack"
                        with _busy("正在打包测试结果"):
                            manifest = create_evidence_pack(result.artifacts["pipeline_result"], pack_dir)
                        st.session_state.workspace_evidence_pack = (str(pack_dir), manifest, str(simulation.artifacts["run_dir"]))
                    except Exception as exc:
                        st.error(f"证据包生成失败：{exc}")
                saved_pack = st.session_state.get("workspace_evidence_pack")
                if saved_pack and saved_pack[2] == str(simulation.artifacts["run_dir"]):
                    pack_dir, manifest, _ = saved_pack
                    st.success(f"证据包已生成：{len(manifest['files'])} 个文件")
                    st.code(str(Path(pack_dir) / "README.md"), language="text")
                    zip_path = Path(manifest.get("zip_file", ""))
                    if zip_path.is_file():
                        st.download_button("下载证据包 ZIP", zip_path.read_bytes(), file_name=zip_path.name, mime="application/zip", key="download_pipeline_evidence_zip")


st.set_page_config(page_title="Icarus 智测", page_icon="⬢", layout="wide", initial_sidebar_state="collapsed")
_inject_theme()
_NAV_LABELS = {
    "工作台": "WORKSPACE\n工作台", "规则审查": "REVIEW\n规则审查",
    "运行档案": "ARCHIVE\n运行档案", "工具设置": "SETTINGS\n工具设置",
    "使用手册": "MANUAL\n使用手册", "项目概览": "PROJECT\n项目概览",
}
with st.container():
    st.markdown('<span class="ui-anchor top-navigation"></span>', unsafe_allow_html=True)
    _brand_col, _nav_col = st.columns([1, 3.8], gap="large", vertical_alignment="center")
    with _brand_col:
        _brandbar()
    with _nav_col:
        with st.container():
            st.markdown('<span class="ui-anchor desktop-navigation"></span>', unsafe_allow_html=True)
            _page = st.radio("工作空间", list(_NAV_LABELS), key="workspace_page", label_visibility="collapsed",
                             horizontal=True, format_func=lambda value: _NAV_LABELS[value], on_change=_desktop_page_changed)
        with st.container():
            st.markdown('<span class="ui-anchor mobile-navigation"></span>', unsafe_allow_html=True)
            if "workspace_mobile_page" not in st.session_state:
                st.session_state.workspace_mobile_page = st.session_state.workspace_page
            st.selectbox("页面导航", list(_NAV_LABELS), key="workspace_mobile_page", label_visibility="collapsed",
                         format_func=lambda value: _NAV_LABELS[value].replace("\n", " / "), on_change=_mobile_page_changed)
with st.container():
    st.markdown('<span class="ui-anchor workflow-navigation"></span>', unsafe_allow_html=True)
    st.radio("工作方式", list(_SCENARIOS), key="ui_scenario", label_visibility="collapsed", on_change=_open_task_workspace,
             horizontal=True,
             format_func=lambda value: {_SINGLE_SCENARIO: "验证一份 RTL", _DIFF_SCENARIO: "对比两份 RTL", _LEARN_SCENARIO: "学习模式"}[value])
_ev = _project_evidence()

_active_route = {"工作台": "compare" if _ui_scenario() == _DIFF_SCENARIO else "workbench", "规则审查": "quality", "运行档案": "history", "工具设置": "settings", "使用手册": "manual", "项目概览": "overview"}[str(_page)]
# Hide only a panel whose immediate child is its route marker. All provider
# widgets stay mounted, so navigation cannot discard credentials or settings.
st.markdown(
    '<style>'
    f'[data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .workspace-route):not(:has(> [data-testid="element-container"] [data-page="{_active_route}"])),'
    f'[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .workspace-route):not(:has(> [data-testid="stElementContainer"] [data-page="{_active_route}"]))'
    '{display:none !important;}</style>', unsafe_allow_html=True,
)
_WORKSPACE_META = st.container()
with _WORKSPACE_META:
    st.markdown('<span class="ui-anchor workspace-status"></span>', unsafe_allow_html=True)
_WORKBENCH = _workspace_panel("workbench")
with _WORKBENCH:
    _console_hero()
    _prepare_col, _plan_col = st.columns([1, 1.25], gap="large")
    with _prepare_col:
        _PREPARE = st.container()
        with _PREPARE:
            st.markdown('<span class="ui-anchor design-desk"></span>', unsafe_allow_html=True)
        with _PREPARE:
            _lane("01", "选择设计", "")
    with _plan_col:
        _PLAN = st.container()
        with _PLAN:
            st.markdown('<span class="ui-anchor execution-desk"></span>', unsafe_allow_html=True)
        with _PLAN:
            _lane("02", "运行测试", "")
    _RESULTS = st.container()
    with _RESULTS:
        st.markdown('<span class="ui-anchor results-desk"></span>', unsafe_allow_html=True)
with _PREPARE:
    name = st.selectbox("案例", ["自定义 RTL"] + list(CASES), key="case_name")
is_custom = name == "自定义 RTL"
case: dict[str, Any] = CASES.get(str(name), {"rtl": None, "tb": None, "top": None, "spec": "自定义 RTL", "contract": None})
_COMPARE = _workspace_panel("compare")
with _COMPARE:
    _section_header("02", "RTL COMPARISON", "对比两份 RTL", "")
    _render_verify_diff_panel()
_QUALITY = _workspace_panel("quality")
_SETTINGS = _workspace_panel("settings")
_MANUAL = _workspace_panel("manual")
_HISTORY = _workspace_panel("history")
_OVERVIEW = _workspace_panel("overview")

with _OVERVIEW:
    _section_header("06", "PROJECT", "项目概览", "ICARUS 智测 / RTL 验证工具")
    _render_evidence_header()

with _MANUAL:
    _section_header("05", "FIELD MANUAL", "使用手册", "")
    _render_manual()


with _PREPARE:
    if is_custom:
        if "custom_rtl_path" not in st.session_state:
            st.session_state.custom_rtl_path = ""
            st.session_state.custom_contract = None
            st.session_state.custom_contract_text = ""
        uploaded = st.file_uploader(
            "上传 RTL 文件",
            type=["v", "sv", "vh"], accept_multiple_files=True,
            help="可同时上传 .v、.sv、.vh 文件，每个文件不超过 2 MB。换版本时请先移除旧文件。",
        )
        upload_key = _uploaded_files_key(uploaded) if uploaded else ()
        if uploaded and st.session_state.get("custom_uploaded_key") != upload_key:
            # Replacing a DUT revokes its old contract and evidence even when the
            # new upload cannot be parsed. Never fall back to the previous DUT.
            _clear_custom_upload()
            try:
                imported_files = []
                sources = []
                for item in uploaded:
                    with _busy("正在导入并解析上传的 RTL"):
                        imported = import_rtl_bytes(item.name, item.getvalue(), ROOT)
                    imported_files.append(imported)
                    sources.append(f"// ---- {item.name} ----\n" + item.getvalue().decode("utf-8"))
                source = "\n\n".join(sources)
                digest = __import__("hashlib").sha256(source.encode("utf-8")).hexdigest()[:12]
                aggregate = ROOT / ".iverilog-ai" / "custom_rtl" / f"project-{digest}.sv"
                aggregate.write_text(source, encoding="utf-8")
                imported = imported_files[0]
                st.session_state.custom_uploaded_key = upload_key
                st.session_state.custom_uploaded_files = tuple(i.name for i in uploaded)
                st.session_state.custom_rtl_path = str(aggregate)
                _replace_custom_contract_draft(json.dumps(imported.contract, ensure_ascii=False, indent=2))
                st.session_state.custom_rtl_source = source
                st.session_state.custom_modules = available_modules(st.session_state.custom_rtl_source)
                st.session_state.custom_selected_module = imported.module
                st.session_state.custom_warnings = tuple(w for i in imported_files for w in i.warnings)
                st.success(f"已导入 {len(uploaded)} 个文件，模块：{', '.join(st.session_state.custom_modules) or '未识别'}")
            except RTLImportError as exc:
                st.error(str(exc))
        elif not uploaded and st.session_state.get("custom_uploaded_key"):
            _clear_custom_upload()
        modules = st.session_state.get("custom_modules", ())
        if len(modules) > 1:
            selected = st.selectbox("顶层模块", modules,
                                    index=max(0, modules.index(st.session_state.get("custom_selected_module", modules[0])))
                                    if st.session_state.get("custom_selected_module", modules[0]) in modules else 0)
            if selected != st.session_state.get("custom_selected_module"):
                try:
                    _, selected_contract, selected_warnings = extract_contract_draft(
                        st.session_state["custom_rtl_source"], module_name=selected
                    )
                    st.session_state.custom_selected_module = selected
                    _replace_custom_contract_draft(json.dumps(selected_contract, ensure_ascii=False, indent=2))
                    st.session_state.custom_warnings = selected_warnings
                    st.rerun()
                except RTLImportError as exc:
                    st.error(f"模块解析失败：{exc}")
        for warning in st.session_state.get("custom_warnings", ()):
            if not warning.startswith("draft only"):
                st.warning(warning)
        if st.session_state.get("custom_contract_text") and st.session_state.get("custom_contract") is None:
            st.caption("接口定义是自动提取的草稿。请确认端口、时钟和复位后，点击「校验接口」。")
        _contract_editor()
        case = {"rtl": st.session_state.get("custom_rtl_path"), "tb": None, "top": None, "spec": "自定义 RTL", "contract": None}
    else:
        st.caption(f"规格：{case['spec']}")
        with st.expander("查看 RTL 源码", expanded=True):
            with st.container(height=210):
                st.code((ROOT / str(case["rtl"])).read_text(encoding="utf-8"), language="verilog")
        with st.expander("接口定义"):
            with st.container(height=240):
                st.json(json.loads((ROOT / str(case["contract"])).read_text(encoding="utf-8")))

# Runs, plans, static findings and the custom/reference comparison belong to the
# actual DUT and confirmed contract, not just the display label "自定义 RTL".
_sync_workspace_input(str(name), case, is_custom)

with _COMPARE:
    if is_custom:
        reference_options = [p for p in sorted((ROOT / "rtl").glob("*.v")) if "_bug_" not in p.name and "bug_" not in p.name]
        if st.session_state.get("custom_rtl_source") and reference_options:
            reference_choice = Path(str(st.selectbox("标准 RTL 参考实现", reference_options, format_func=lambda p: p.name)))
            reference_fingerprint = _content_fingerprint(reference_choice)
            if st.session_state.get("custom_reference_fingerprint") not in {None, reference_fingerprint}:
                for key in ("rtl_comparison", "rtl_ai_review", "behavior_comparison"):
                    st.session_state.pop(key, None)
            st.session_state.custom_reference_fingerprint = reference_fingerprint
            if st.button("对比自定义 RTL 与标准实现", key="compare_custom_reference"):
                with _busy("正在对比两份 RTL 的结构"):
                    comparison = compare_rtl_sources(st.session_state.custom_rtl_source, reference_choice.read_text(encoding="utf-8"), user_name="上传 RTL", reference_name=reference_choice.name)
                st.session_state.rtl_comparison = comparison
        if st.session_state.get("rtl_comparison"):
            comparison = st.session_state.rtl_comparison
            st.subheader("RTL 结构对比与学习建议")
            st.metric("端口匹配", "通过" if comparison["port_match"] else "需检查")
            if comparison["strengths"]:
                st.success("已有的优点：" + "；".join(comparison["strengths"]))
            if comparison["gaps"]:
                st.warning("可以改进：" + "；".join(comparison["gaps"]))
            st.write("下一步学习计划：")
            for index, item in enumerate(comparison["learning_plan"], 1):
                st.write(f"{index}. {item}")
            with st.popover("导出对比报告"):
                st.download_button(
                    "RTL 对比 JSON",
                    json.dumps(comparison, ensure_ascii=False, indent=2),
                    file_name="rtl-comparison.json",
                    mime="application/json",
                    key="download_rtl_comparison",
                )
            st.caption("这里只比较代码结构。功能是否一致，还需要运行测试。")
            if st.session_state.get("custom_rtl_path") and Path(st.session_state.custom_rtl_path).is_file():
                if st.button("用当前计划对比", key="behavior_compare_button",
                             help="先生成测试计划，再用相同的输入测试两个版本。"):
                    current_plan = st.session_state.get("ai_plan")
                    if current_plan is None:
                        st.warning("请先生成测试计划。")
                    else:
                        try:
                            outcome = compare_rtl_behavior(
                                current_plan,
                                _contract(),
                                st.session_state.custom_rtl_path,
                                reference_choice,
                                ROOT / ".iverilog-ai" / "behavior-compare-ui" / reference_choice.stem,
                                allowed_roots=(ROOT,),
                                iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                                vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe",
                            )
                            st.session_state.behavior_comparison = outcome.to_dict()
                        except Exception as exc:
                            st.error(f"行为级对比失败：{exc}")
        if st.session_state.get("behavior_comparison"):
            _show_behavior_comparison(st.session_state.behavior_comparison)


with _QUALITY:
    _section_header("02", "CODE REVIEW", "规则审查", "检查代码中的常见问题。")
    if case.get("rtl") and Path(case["rtl"]).is_file():
        if st.button("检查代码", key="run_static_rtl_review", help="检查赋值、复位、分支和时钟域等常见问题，不代替仿真。"):
            try:
                with _busy("正在检查代码"):
                    st.session_state.static_rtl_review = review_rtl_file(case["rtl"])
            except Exception as exc:
                st.error(f"RTL 静态审查失败：{exc}")
    else:
        st.caption("先在「工作台」选择案例或上传 RTL。")
    if st.session_state.get("static_rtl_review"):
        static_review = st.session_state.static_rtl_review
        st.subheader("检查结果")
        st.caption(
            "评分只反映规则检查结果，不能说明功能是否正确；标出的问题还需要结合代码核对。"
        )
        _score_col, _status_col, _count_col = st.columns(3)
        _score_col.metric("参考评分", f"{static_review['quality_score']}/100", help="每条错误扣 20 分、警告扣 5 分、提示扣 1 分。")
        _status_col.metric(
            "检查状态",
            {"passed": "无错误", "warn": "有警告", "error": "有错误"}.get(
                static_review["status"], static_review["status"]
            ),
            help="这是规则检查的状态，不是仿真结果。",
        )
        _count_col.metric(
            "问题数量",
            static_review["finding_count"],
            f"错误 {static_review['counts'].get('error', 0)} / 警告 {static_review['counts'].get('warn', 0)} / 提示 {static_review['counts'].get('info', 0)}",
        )
        if static_review["findings"]:
            _severity_cn = {"error": "错误", "warn": "警告", "info": "提示"}
            st.dataframe(
                [
                    {
                        "规则ID": item["rule_id"],
                        "严重度": _severity_cn.get(item["severity"], item["severity"]),
                        "行号": item["line"],
                        "问题": item["message"],
                        "建议": item["suggestion"],
                        "代码片段": item.get("snippet", ""),
                    }
                    for item in static_review["findings"]
                ],
                use_container_width=True,
                hide_index=True,
                height=300,
            )
        else:
            st.success(f"已检查 {static_review.get('rule_count', 0)} 条规则，未发现问题。")
        with st.expander(f"规则与出处（{static_review.get('rule_count', 0)} 条）"):
            st.dataframe(
                [
                    {
                        "规则ID": item["rule_id"],
                        "严重度": _severity_cn.get(item["severity"], item["severity"]),
                        "规则": item["title"],
                        "出处": item["source"],
                    }
                    for item in static_review.get("rule_set", [])
                ],
                use_container_width=True,
                hide_index=True,
                height=300,
            )
        with st.expander("原始审查数据"):
            st.json({"counts": static_review["counts"], "finding_count": static_review["finding_count"], "source_sha256": static_review["source_sha256"]})

        # ── 事实层 / 建议层分界 ────────────────────────────────────────────
        st.divider()
        st.markdown("### 修复建议")
        st.caption(
            "建议供你参考，不改变规则检查结果，也不参与评分。"
        )
        _send_snippets = st.checkbox(
            "同时发送相关代码片段",
            value=False,
            key="static_review_send_snippets",
            help="默认只发送规则编号、严重度和行号等信息，不含源码。勾选后会发送命中行的代码，每段最多 200 字符。",
        )
        _advice_btn, _advice_hint = st.columns([1, 2])
        if _advice_btn.button("生成修复建议", key="run_static_review_advice", type="primary", help="在线模式会请求模型；返回格式不合要求时最多重试一次。"):
            try:
                _advice_case = RULE_CASE_NAMES.get(str(name), str(name))
                # 直接读本次控件状态，不能依赖设置面板尚未更新的派生变量。
                _advice_mode = str(st.session_state.get("planner_mode", ""))
                _planner_is_online = _advice_mode.startswith("在线")
                _planner_is_local = _advice_mode.startswith("本地调试")
                if _planner_is_online or _planner_is_local:
                    with _busy("正在生成修复建议"):
                        _advice_provider = _build_provider("AI 静态审查复核")
                        _advice, _advice_meta = advise_on_static_review(
                            _advice_provider,
                            static_review,
                            include_snippets=bool(_send_snippets),
                            design=_advice_case,
                        )
                        _advice_meta["model"] = getattr(_advice_provider, "model", "debug-local")
                        _advice_meta["usage"] = getattr(_advice_provider, "last_usage", None)
                else:
                    _advice = offline_review_advice(static_review)
                    _advice_meta = {
                        "source": "offline_rules",
                        "model": None,
                        "attempts": 0,
                        "included_code_snippets": False,
                        "review_sha256": static_review.get("source_sha256"),
                        "dropped_unknown_rule_ids": [],
                    }
                st.session_state.static_review_advice = _advice.model_dump(mode="json")
                st.session_state.static_review_advice_meta = _advice_meta
                st.session_state.static_review_advice_hash = static_review.get("source_sha256")
            except Exception as exc:
                st.error(f"AI 复核失败：{exc}")
        with _advice_hint:
            st.caption(
                "离线模式提供规则建议；使用 AI 请在「工具设置」中连接在线模型。"
            )
        if st.session_state.get("static_review_advice"):
            if st.session_state.get("static_review_advice_hash") != static_review.get("source_sha256"):
                st.warning("代码已更新，请重新生成建议。")
            _render_static_advice(
                st.session_state.static_review_advice,
                st.session_state.get("static_review_advice_meta") or {},
            )

        _export_advice = st.session_state.get("static_review_advice")
        _export_meta = st.session_state.get("static_review_advice_meta")
        if _export_advice and st.session_state.get("static_review_advice_hash") != static_review.get("source_sha256"):
            _export_advice, _export_meta = None, None  # 不导出与当前版本不匹配的建议
        with st.popover("导出审查报告"):
            st.download_button(
                "Markdown",
                _advice_markdown(static_review, _export_advice, _export_meta).encode("utf-8"),
                file_name="rtl_quality_report.md",
                mime="text/markdown",
                key="download_static_review_md",
            )
            st.download_button(
                "JSON",
                json.dumps(
                    _advice_export_payload(static_review, _export_advice, _export_meta),
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
                file_name="rtl_quality_report.json",
                mime="application/json",
                key="download_static_review_json",
            )


with _PLAN:
    _learn_mode = _ui_scenario() == _LEARN_SCENARIO
    # 学习模式把"验证目标 / 结构化断言 / 综合证据"收进一个折叠块；其它场景直接展开。
    # 用 nullcontext 而不是把整段代码抄两遍——两边逻辑必须完全一致，抄一遍就多一处会漂移的地方。
    _advanced: Any = (
        st.expander("高级选项") if _learn_mode else nullcontext()
    )
    if _learn_mode:
        st.info(
            "先选一个案例，生成计划后运行测试。遇到失败时，可以查看原因和相关代码。"
        )
    with _advanced:
        _obj_col = st.container()
        _asm_col = st.container() if _learn_mode else st.expander("断言与综合")
        with _obj_col:
            objective = st.text_area(
                "验证目标",
                st.session_state.get("objective_text", "覆盖复位、状态转换与边界时序"),
                height=88,
                help="写下你想重点测试的行为，例如复位、边界值或状态切换。",
                key="objective_text",
            )
        with _asm_col:
            assertions_text = st.text_area(
                "断言 JSON（可选）",
                value=st.session_state.get("structured_assertions_text", "[]"),
                height=88,
                help="使用 signal_equals、signal_stable、never_high、signal_sequence 或 signal_implies 模板，不支持直接填写 Verilog/SVA。断言检查整个采样序列。",
            )
            st.session_state.structured_assertions_text = assertions_text
            st.session_state.run_synthesis = st.checkbox(
                "同时运行 Yosys 综合",
                value=bool(st.session_state.get("run_synthesis", False)),
                help="在报告中附加综合结果，不改变仿真结论，也不做时序分析。",
            )
    with _asm_col:
        if not is_custom:
            _case_key = str(name)
            _suggested_assertions = assertion_suggestions(RULE_CASE_NAMES.get(_case_key, _case_key))
            if _suggested_assertions:
                # 回调在主体之前执行，写进去的值本次运行就会显示；不需要整页重跑。
                st.button(
                    "载入推荐断言",
                    key="load_case_assertions",
                    on_click=_load_suggested_assertions_on_click,
                )
            else:
                # 断言按"整个采样序列"判定，只有真正的全局不变量才适合写成断言；本案例没有
                # 经过验证的推荐断言（2026-09 复核：原先 4 个案例的 5 条建议全部不成立/空检查/
                # 字段非法，已全部撤掉）。这里给出可直接改用的模板形状，而不是一份会误报的清单。
                st.caption(
                    "本案例暂无推荐断言。模板和字段说明见「使用手册 → 进阶用法」。"
                )


with _SETTINGS:
    _section_header("04", "SETTINGS", "工具设置", "")
    with st.expander("测试计划与模型"):
        provider_mode = st.radio(
            "生成方式",
            ["离线确定性规划器（无需密钥、进程内）", "本地调试模型（HTTP 回环、无需密钥）", "在线 API（手动输入或本机密钥文件）"],
            horizontal=True,
            key="planner_mode",
            format_func=lambda value: "在线模型" if value.startswith("在线") else "本地调试" if value.startswith("本地调试") else "离线模式",
        )
        use_online = str(provider_mode).startswith("在线")
        use_debug_local = str(provider_mode).startswith("本地调试")
        use_offline = str(provider_mode).startswith("离线")
        # 页面里"质量与对比"页签的代码在源文件里**先于**设置页运行，因此它不能直接读这两个
        # 变量（早先就踩过：mypy 报 used-before-def，运行时也可能读到上一轮的旧值）。
        # 统一把结论放进 session_state，任何位置都能安全读取，默认即离线。
        st.session_state["planner_is_online"] = use_online
        st.session_state["planner_is_debug_local"] = use_debug_local
        debug_endpoint = st.text_input(
            "本地服务地址",
            value=os.getenv("IVERILOG_AI_DEBUG_ENDPOINT", "http://127.0.0.1:11434/v1"),
            key="provider_debug_endpoint",
            help="启动仓库自带服务：python -m iverilog_ai.ai.debug_server",
        )
        if use_debug_local:
            st.caption(
                "使用本地规则服务调试接口，不调用 AI 模型。"
            )
        elif use_offline:
            st.caption(
                "按接口定义生成测试，不联网，也不需要密钥；这不是 AI 模型生成的结果。"
            )
        api_base = st.text_input("API 地址", value=_api_default_base, key="provider_api_base", help="填写服务商的 Base URL。")
        api_model = st.text_input("模型名称", value=_api_default_model, key="provider_api_model", help="填写服务商提供的模型名称，也可以从模型列表中选择。")
        api_key = st.text_input("API Key", value="", type="password", key="provider_api_key", help="不会写入项目文件或报告")
        if _local_api_profile:
            st.caption("已配置本机密钥文件。API Key 留空即可；更换 API 地址后需要另行提供密钥。")
        elif _local_api_error:
            st.warning(f"本机 API 配置无法读取（{_local_api_error}），可在此手动填写。")
        api_timeout = st.slider("请求超时（秒）", min_value=30, max_value=300, value=120, step=10, key="provider_api_timeout", help="模型响应较慢时可适当调高。")
        api_output_tokens = st.slider("输出长度上限（token）", min_value=2048, max_value=8192, value=_local_api_profile.max_output_tokens if _local_api_profile else 4096, step=512, key="provider_api_output_tokens", help="设置过小可能导致测试计划生成不完整。")
        wire_api_label = st.selectbox("接口格式", ["Chat Completions API", "Responses API"], key="provider_wire_api", help="按服务商文档选择；不确定时使用 Chat Completions。")
        reasoning_label = st.selectbox("推理强度", ["不发送（兼容性最高）", "minimal", "low", "medium", "high", "xhigh"], key="provider_reasoning", help="仅 Responses 接口使用。服务商不支持时选择「不发送」。")
        if st.button("检查配置", help="仅检查参数，不请求模型。"):
            try:
                _diag_wire = _wire_api_for(str(wire_api_label))
                _diag_reasoning = None if str(reasoning_label).startswith("不发送") or _diag_wire != "responses" else reasoning_label
                _diag_provider = OpenAICompatibleProvider(endpoint=api_base, model=api_model, api_key=_configured_api_key(api_base, api_key) or " ",
                    wire_api=_diag_wire, reasoning_effort=_diag_reasoning, allow_network=True, store=False, timeout=api_timeout, max_output_tokens=api_output_tokens)
                st.json(_diag_provider.request_diagnostics())
            except Exception as exc:
                st.error(f"配置无效：{exc}")
        if st.button("读取模型列表", help="向当前服务商获取可用模型，需要 API Key。"):
            try:
                _models_wire = _wire_api_for(str(wire_api_label))
                if "deepseek" in (api_base + " " + api_model).lower():
                    _models_wire = "chat_completions"
                _models_key = _configured_api_key(api_base, api_key)
                if not _models_key:
                    raise ValueError("读取模型列表需要当前 API 地址对应的密钥")
                _models_provider = OpenAICompatibleProvider(
                    endpoint=api_base, model=api_model, api_key=_models_key,
                    wire_api=_models_wire, reasoning_effort=None, allow_network=True, store=False, timeout=api_timeout, max_output_tokens=api_output_tokens,
                )
                with _busy("正在向服务商请求模型列表"):
                    st.session_state.available_models = _models_provider.list_models()
                st.success(f"已读取 {len(st.session_state.available_models)} 个模型")
            except Exception as exc:
                st.error(f"读取模型列表失败：{exc}")
        if st.session_state.get("available_models"):
            _listed_models = list(st.session_state.available_models)
            # 读到列表就要能用：选中即覆盖上面的「模型」输入，避免用户手抄 ID。
            _picked_model = st.selectbox(
                "选择可用模型",
                ["（不覆盖，使用上面的输入）"] + _listed_models,
                key="picked_model_from_list",
                help="选中后优先使用列表中的模型。",
            )
            if _picked_model != "（不覆盖，使用上面的输入）":
                # st.selectbox 的返回值在类型标注上是宽泛的，显式转成 str：
                # 下游用它拼提示词与构造 provider，必须是字符串。
                api_model = str(_picked_model)
        if "deepseek" in (api_base + " " + api_model).lower() and str(wire_api_label).startswith("Responses"):
            st.info("当前 DeepSeek 配置会自动使用 Chat Completions 接口。")

    with st.expander("波形查看器（GTKWave）"):
        # 真实反馈："用 GTKWave 自动打开没反应，不知道是不是找不到路径"。
        # 因此这里既做自动探测（PATH → 常见目录 → 从 iverilog 安装位置推断），
        # 也允许手填路径并当场校验——两条路都必须存在。
        _detected_gtkwave = _configured_gtkwave()
        _gtkwave_cols = st.columns([3, 1])
        with _gtkwave_cols[0]:
            gtkwave_input = st.text_input(
                "GTKWave 可执行文件路径",
                value=str(st.session_state.get("gtkwave_path", "") or os.getenv("GTKWAVE_PATH", "")),
                help="留空自动查找，也可以填写 gtkwave.exe 的完整路径。",
            )
            st.session_state.gtkwave_path = gtkwave_input
        with _gtkwave_cols[1]:
            st.write("")
            st.write("")
            if st.button("自动检测", key="detect_gtkwave"):
                st.session_state.gtkwave_path = ""
                st.session_state.gtkwave_detected = _configured_gtkwave()
        _shown_gtkwave = _configured_gtkwave()
        if _shown_gtkwave:
            st.success(f"已找到 GTKWave：{_shown_gtkwave}")
        else:
            st.warning(
                "未找到 GTKWave，请填写安装路径。页面内的波形分析仍可使用。"
            )
        from iverilog_ai.core.toolchain import describe_tools
        st.caption("工具探测结果：" + describe_tools(_tools()))


with _COMPARE:
    if is_custom and st.session_state.get("rtl_comparison") and st.button("解读对比结果", key="ai_rtl_review"):
        try:
            if use_online or use_debug_local:
                review_provider = _build_provider("AI RTL 解读")
            else:
                review_provider = MockProvider(response={"review": "请依据结构对比结果，说明优点、不足和学习计划。"})
            review_prompt = ("请作为 FPGA RTL 教学审查员。仅依据以下已脱敏的结构化对比结果，输出 JSON："
                             '{"strengths":[...],"gaps":[...],"learning_plan":[...],"confidence":"low|medium|high"}。'
                             "不要输出代码、命令或路径。\n" + json.dumps(st.session_state.rtl_comparison, ensure_ascii=False))
            with _busy("正在请求 AI 解读"):
                raw_review = review_provider.generate(review_prompt)
            st.session_state.rtl_ai_review = raw_review
        except Exception as exc:
            st.error(f"AI RTL 解读失败：{exc}")
    if st.session_state.get("rtl_ai_review"):
        st.subheader("对比解读")
        with st.container(height=260):
            st.code(st.session_state.rtl_ai_review, language="json")


with _PLAN:
    if "ai_plan" not in st.session_state:
        st.session_state.ai_plan = None
    if "ai_error" not in st.session_state:
        st.session_state.ai_error = None
    if "ai_plan_case" not in st.session_state:
        st.session_state.ai_plan_case = None
    if st.session_state.ai_plan_case not in {None, name}:
        st.session_state.ai_plan = None
        st.session_state.ai_error = None
        st.session_state.ai_plan_case = None

    _plan_missing = st.session_state.get("ai_plan") is None
    if st.button(
        "生成测试计划",
        type="primary" if _plan_missing else "secondary",
        help="使用「工具设置」中选定的方式生成计划。在线模式会请求模型，格式校验失败时最多重试一次。",
        key="generate_plan",
    ):
        provider = None
        try:
            contract = _contract()
            spec_text = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户上传 RTL；请严格依据 DUT contract 规划测试。"
            if use_online or use_debug_local:
                provider = _build_provider("生成测试计划")
            else:
                provider = _offline_provider(contract)
            # 提示词里的 Design 用**合约里的模块名**，而不是案例列表上的中文标签：
            # 标签只是界面用语（"简单 ALU"），模型会把它当设计名回填，报告里的
            # 设计一栏也就跟着失去意义。模块名对内置案例与自定义 RTL 都成立，
            # 且与规则文件名、testbench 实例化的模块名三处一致。
            case_name = contract.module
            with _busy("正在生成测试计划"):
                generated_plan = plan_tests(
                    objective,
                    case_name,
                    provider=provider,
                    # 允许一次"带着拒绝原因"的重试：模型偶尔会写错一个字段名（例如给
                    # signal_implies 多写 signal），一次修正就能救回整轮；只在第一次被严格
                    # 校验拒绝时才会多发一次请求（认证/限流错误不会重试）。
                    max_retries=1,
                    context=_verification_rules(case_name, contract, spec_text),
                )
            try:
                requested_assertions = json.loads(assertions_text or "[]")
                if not isinstance(requested_assertions, list):
                    raise ValueError("结构化断言必须是 JSON 数组")
                st.session_state.ai_plan = generated_plan.model_copy(update={"assertions": requested_assertions})
                # Re-validate the copied plan so UI-authored assertions use the
                # same strict boundary as model-authored data.
                from iverilog_ai.ai.schema import TestPlan
                st.session_state.ai_plan = TestPlan.model_validate(st.session_state.ai_plan.model_dump(mode="json"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"结构化断言 JSON 无效：{exc}") from exc
            st.session_state.ai_plan_case = name
            st.session_state.ai_error = None
        except Exception as exc:
            st.session_state.ai_plan = None
            detail = str(exc)
            if provider is not None and hasattr(provider, "request_diagnostics"):
                diag = provider.request_diagnostics()
                detail += "\n请求诊断（已脱敏）：" + str(diag)
            st.session_state.ai_error = detail
            if "timed out" in detail.lower() or "超时" in detail:
                st.warning("模型响应超时，请检查模型名称和网络，或在「工具设置」中增加超时时间。")
    if st.session_state.ai_error:
        st.error(st.session_state.ai_error)
    if st.session_state.ai_plan is not None:
        st.success(f"计划已生成，共 {len(st.session_state.ai_plan.vectors)} 组测试。")
        with st.expander("测试计划与规则"):
            try:
                # 注意函数名：core.rules 里叫 `rule_manifest(root, case)`，
                # core.static_review 里的同名函数是 `static_rule_manifest()`（不同签名）。
                # 这里曾经写成不存在的 `rules_manifest`，抛出的 NameError 又不被
                # `except ValueError` 接住，于是**生成计划后整页渲染中断**。
                _case_key = str(name)
                _rule_files = rule_manifest(ROOT, RULE_CASE_NAMES.get(_case_key, _case_key))
                st.caption("规则版本：" + rules_fingerprint(_rule_files))
                st.json(_rule_files)
            except ValueError:
                pass
            with st.container(height=320):
                st.json(st.session_state.ai_plan.model_dump(mode="json"))


with _SETTINGS:
    with st.expander("编译选项"):
        st.text_input(
            "宏定义",
            value=st.session_state.get("compile_defines", ""),
            key="compile_defines",
            help="用逗号分隔，例如 WIDTH=16,SYNTHESIS。",
        )
        st.text_input(
            "include 目录",
            value=st.session_state.get("compile_includes", ""),
            key="compile_includes",
            help="用逗号分隔，仅支持项目内的目录。",
        )
        st.caption("对测试计划和示例测试都生效。")


with _PLAN:
    _run_plan_col, _run_tb_col = st.columns(2)
    _run_plan = _run_plan_col.button("运行测试计划", type="primary", key="run_generated_plan", disabled=st.session_state.ai_plan is None)
    _run_tb = _run_tb_col.button("运行示例测试", key="run_handwritten_tb", disabled=is_custom or not case.get("rtl"), help="使用内置案例自带的 testbench，无需生成计划。")
    if st.session_state.ai_plan is None:
        st.caption("先生成计划，或直接运行内置案例的示例测试。")
    if _run_tb:
        try:
            _defines, _includes = _compile_options()
            config = ExecutionConfig(rtl_path=ROOT / str(case["rtl"]), testbench_path=ROOT / str(case["tb"]), top_module=str(case["top"]), output_dir=ROOT / ".iverilog-ai" / "runs", allowed_roots=(ROOT,), defines=_defines, include_dirs=_includes)
            with _busy("正在运行示例测试"):
                simulation_result = IcarusExecutor(config).run()
            report = write_report(simulation_result, Path(simulation_result.artifacts["run_dir"]) / "report.md")
            st.session_state.last_handwritten_result = simulation_result
            st.session_state.last_handwritten_case = name
            st.session_state.last_handwritten_report = str(report)
            st.session_state.last_run_kind = "handwritten"
        except Exception as exc:
            st.error(f"测试未完成：{exc}")
    if _run_plan and st.session_state.ai_plan is not None:
        try:
            contract = _contract()
            _defines, _includes = _compile_options()
            with _busy("正在运行测试计划"):
                result = VerificationPipeline(run_synthesis=st.session_state.get("run_synthesis", False), yosys_path=os.getenv("YOSYS_PATH") or None).run(
                    st.session_state.ai_plan, contract.to_dict(), ROOT / str(case["rtl"]), ROOT / ".iverilog-ai" / "pipeline-ui" / f"workspace-{uuid.uuid4().hex[:12]}", allowed_roots=(ROOT,),
                    iverilog_path=os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe", vvp_path=os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe", defines=_defines, include_dirs=_includes, emit_vcd=True,
                )
            st.session_state.last_pipeline_result = result
            st.session_state.last_pipeline_case = name
            st.session_state.last_run_kind = "pipeline"
            pipeline_report = write_report(result.simulation, Path(result.artifacts["output_dir"]) / "report.md", title="Icarus 智测 AI 流水线报告")
            result.artifacts["report"] = str(pipeline_report)
            Path(result.artifacts["pipeline_result"]).write_text(result.to_json() + "\n", encoding="utf-8")
        except Exception as exc:
            st.error(f"测试未完成：{exc}")

with _PLAN:
    with st.expander("自动验证 Agent"):
        st.caption("通过 API 决定下一组测试，自动运行并保留每轮证据。找到反例或预算用尽时停止。")
        _agent_left, _agent_right = st.columns(2)
        _agent_rounds = int(_agent_left.number_input("最多验证轮数", min_value=1, max_value=5, value=3, key="agent_round_limit"))
        _agent_requests = int(_agent_right.number_input("最多 API 请求", min_value=1, max_value=5, value=3, key="agent_request_limit"))
        _agent_cycles = int(st.number_input("累计激励周期上限", min_value=20, max_value=20000, value=1000, step=20, key="agent_cycle_limit"))
        st.caption("会发送接口定义、规格、当前计划和仿真摘要。已有计划会先执行；请求可能计费，次数上限不等于金额上限。")
        _agent_run = st.button("启动自动验证", key="run_verification_agent", disabled=not use_online)
        if not use_online:
            st.caption("先在「工具设置」选择在线模型并填写 API 配置。")
        if _agent_run:
            try:
                _agent_contract = _contract()
                _agent_defines, _agent_includes = _compile_options()
                _agent_spec = (ROOT / case["spec"]).read_text(encoding="utf-8") if not is_custom else "用户自定义 RTL；接口定义不等于完整功能规格。"
                _agent_provider = _build_provider("自动验证")
                with _busy("Agent 正在验证，达到预算后自动停止"):
                    _agent_result = run_verification_agent(
                        provider=_agent_provider, contract=_agent_contract,
                        rtl_path=ROOT / str(case["rtl"]),
                        output_dir=ROOT / ".iverilog-ai/pipeline-ui" / f"agent-{uuid.uuid4().hex[:12]}",
                        objective=str(st.session_state.get("objective_text", "检查正常行为和边界条件，寻找可复现反例")),
                        specification=_agent_spec, initial_plan=st.session_state.get("ai_plan"),
                        limits=AgentLimits(max_rounds=_agent_rounds, max_requests=_agent_requests, max_total_cycles=_agent_cycles,
                                           max_output_tokens=min(_agent_provider.max_output_tokens, 8192),
                                           request_timeout_seconds=min(int(_agent_provider.timeout), 180)),
                        execution_options={"allowed_roots": (ROOT,), "defines": _agent_defines, "include_dirs": _agent_includes,
                                           "iverilog_path": os.getenv("IVERILOG_PATH") or r"D:\iverilog\bin\iverilog.exe",
                                           "vvp_path": os.getenv("VVP_PATH") or r"D:\iverilog\bin\vvp.exe"},
                    )
                st.session_state.workspace_agent_result = _agent_result
                if _agent_result.last_result is not None:
                    _agent_last = _agent_result.last_result
                    st.session_state.ai_plan = _agent_last.plan
                    st.session_state.ai_plan_case = name
                    st.session_state.last_pipeline_result = _agent_last
                    st.session_state.last_pipeline_case = name
                    st.session_state.last_run_kind = "pipeline"
                    _agent_last.artifacts["report"] = str(write_report(_agent_last.simulation, Path(_agent_last.artifacts["output_dir"]) / "report.md", title="Icarus 智测 Agent 运行报告"))
                    Path(_agent_last.artifacts["pipeline_result"]).write_text(_agent_last.to_json() + "\n", encoding="utf-8")
            except Exception as exc:
                st.error(f"自动验证未启动：{type(exc).__name__}。请检查 API 配置、接口定义和运行目录。")
        _saved_agent = st.session_state.get("workspace_agent_result")
        if _saved_agent is not None:
            st.info(STOP_LABELS[_saved_agent.stop_reason])
            st.caption(f"API 请求 {_saved_agent.trajectory['requests_attempted']} 次 · 已执行 {len(_saved_agent.trajectory['rounds'])} 轮 · 累计激励 {_saved_agent.trajectory['stimulus_cycles_executed']} 周期")
            if not _saved_agent.trajectory["rounds"]:
                st.caption("本次没有完成仿真；下方如有结果，来自此前运行。")
            if _saved_agent.trajectory["rounds"]:
                st.dataframe([{"轮次": row["round"], "检查数": row["observation"]["checks"],
                               "失败数": row["observation"]["failures"], "结论": row["observation"]["verdict"]}
                              for row in _saved_agent.trajectory["rounds"]], hide_index=True, use_container_width=True, height=180)
            st.download_button("下载完整 Agent 轨迹", _saved_agent.trajectory_path.read_bytes(), file_name="agent_trajectory.json", mime="application/json", key="download_agent_trajectory")

_render_workspace_results()
with _WORKSPACE_META:
    _chips([
        ("当前输入", str(name), "warn" if is_custom else "ok"),
        ("规划器", "在线模型" if use_online else "本地调试" if use_debug_local else "离线", "idle"),
        ("Icarus", "可用" if _ev.get("iverilog") else "缺失", "ok" if _ev.get("iverilog") else "err"),
    ])


with _HISTORY:
    _section_header("03", "RUN ARCHIVE", "运行档案", "")
    history_root = ROOT / ".iverilog-ai" / "pipeline-ui"
    history_files = sorted([*history_root.glob("runs/*/result.json"), *history_root.glob("workspace-*/runs/*/result.json"), *history_root.glob("agent-*/round-*/runs/*/result.json")], key=lambda item: item.stat().st_mtime, reverse=True) if history_root.is_dir() else []
    if not history_files:
        st.info("还没有运行记录。")
    if history_files:
        with st.expander(f"最近运行（{min(len(history_files), 10)} 条）"):
            for result_file in history_files[:10]:
                try:
                    summary = json.loads(result_file.read_text(encoding="utf-8"))
                    st.write(f"{summary.get('run_id', result_file.parent.name)} · {summary.get('status', 'unknown')} · {result_file}")
                except (OSError, json.JSONDecodeError):
                    st.write(str(result_file))


st.divider()

st.markdown(
    '<div class="console-footer"><span>ICARUS 智测 / OPEN SOURCE VERIFICATION</span>'
    '<span>CONTRACT → PLAN → SIMULATION → EVIDENCE</span></div>',
    unsafe_allow_html=True,
)
