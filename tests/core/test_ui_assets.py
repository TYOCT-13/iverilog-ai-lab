"""页面案例表与仓库资产的一致性测试。

为什么值得测：`ui/app.py` 里的案例表是**手写**的路径清单，而基准案例集来自
`benchmarks/manifest.json`。两边一旦漂移，页面会出现"案例在清单里但点开没有
testbench"这类问题——而且只在人工点页面时才会发现。这里把它变成自动化断言。

本测试只做静态解析，不真正启动 Streamlit，因此可以在普通测试流程里跑。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
APP = ROOT / "ui" / "app.py"


def _literal(node: ast.AST) -> object:
    """取出字面量；遇到非字面量直接失败，避免测试悄悄跳过检查。"""

    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:  # pragma: no cover - 结构变更时才会触发
        raise AssertionError(f"ui/app.py 中的表不再是纯字面量，测试需要同步更新：{exc}") from exc


def _module_level_tables() -> dict[str, dict]:
    """从 ui/app.py 里取出 CASES 与 RULE_CASE_NAMES 两张表。"""

    tree = ast.parse(APP.read_text(encoding="utf-8"))
    tables: dict[str, dict] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"CASES", "RULE_CASE_NAMES"}:
                tables[target.id] = _literal(node.value)  # type: ignore[assignment]
    return tables


def test_ui_module_exposes_expected_tables():
    tables = _module_level_tables()
    assert "CASES" in tables, "ui/app.py 未找到 CASES 表"
    assert "RULE_CASE_NAMES" in tables, "ui/app.py 未找到 RULE_CASE_NAMES 表"
    assert tables["CASES"], "CASES 表为空"


def test_every_ui_case_file_exists():
    """页面案例表里引用的 RTL / testbench / contract / spec 必须都真实存在。"""

    cases = _module_level_tables()["CASES"]
    missing: list[str] = []
    for label, entry in cases.items():
        for key in ("rtl", "tb", "top", "spec", "contract"):
            value = entry.get(key)
            if key == "top":
                continue
            if not value:
                missing.append(f"{label}: 缺少字段 {key}")
                continue
            if not (ROOT / value).is_file():
                missing.append(f"{label}: {key} 指向的文件不存在 -> {value}")
    assert not missing, "页面案例表与仓库资产不一致：\n" + "\n".join(missing)


def test_ui_cases_cover_every_benchmark_category():
    """基准清单里的每个案例都必须在页面上可选，否则演示会漏掉已交付的成果。"""

    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    categories = set(manifest["categories"])
    rule_names = _module_level_tables()["RULE_CASE_NAMES"]
    covered = {value for key, value in rule_names.items() if key != "自定义 RTL"}
    missing = sorted(categories - covered)
    assert not missing, f"以下基准案例在页面案例表中缺失：{missing}"


def test_ui_case_contracts_are_valid_json():
    """页面案例表指向的 contract 必须是可解析、可校验的 DUT 合约。"""

    from iverilog_ai.core.contracts import DutContract

    cases = _module_level_tables()["CASES"]
    for label, entry in cases.items():
        contract_path = ROOT / entry["contract"]
        if not contract_path.is_file():
            continue
        contract = DutContract.from_json(contract_path.read_text(encoding="utf-8"))
        assert contract.ports, f"{label} 的 contract 没有端口声明"
        assert contract.module, f"{label} 的 contract 没有模块名"


def test_evidence_header_sources_are_real():
    """页面"实证状态"面板依赖的三处数据源必须可读，否则面板会退化成一排"—"。"""

    from iverilog_ai.core.reference_model import AUTHORITATIVE, SUPPORTED
    from iverilog_ai.core.static_review import rule_manifest

    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["categories"]) > 0
    assert len(manifest["defects"]) > 0
    assert len(rule_manifest()) > 0
    assert AUTHORITATIVE <= SUPPORTED
    assert list((ROOT / "tests").rglob("test_*.py"))


def _ui_test_counter():
    """从 ui/app.py 抽出 `_count_test_cases` 单独执行（不启动 Streamlit）。"""

    tree = ast.parse(APP.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_count_test_cases"
    )
    namespace: dict = {"Path": Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "ui/app.py:tests", "exec"), namespace)
    return namespace["_count_test_cases"]


def test_ui_test_count_matches_pytest_collection():
    """页面显示的"自动化测试"数必须等于 pytest 实际收集到的用例数。

    页面统计的是**测试函数数**（AST 数 `def test_*`），而 pytest 会把
    `@pytest.mark.parametrize` 展开成多条用例——两者口径不同。这里用
    `--collect-only` 的实际数字兜底，防止页面上出现一个与真实测试规模脱节的数字。
    """

    import subprocess
    import sys

    counter = _ui_test_counter()
    reported = counter(ROOT / "tests")
    assert isinstance(reported, int) and reported > 0

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert collected.returncode == 0, collected.stdout[-2000:] + collected.stderr[-2000:]
    lines = [line for line in collected.stdout.splitlines() if "::" in line]
    assert lines, collected.stdout[-2000:]
    # 收集数 >= 函数数（参数化会展开），且不得少于函数数
    assert len(lines) >= reported, (
        f"pytest 收集到 {len(lines)} 条用例，却少于页面统计的测试函数数 {reported}，"
        "说明页面统计逻辑与测试布局不一致"
    )
