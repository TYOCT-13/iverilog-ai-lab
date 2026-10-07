"""未可达代码与重复定义检查（AST，静态、不执行任何代码）。

**为什么需要它**：`core/reference_model.py` 里曾经有两份语义实现——`_DesignState.step`
（活的）和 `check_plan_consistency` 里 `return` 之后的 150 行副本（死的）。死的这份
不会报错、不会被测试覆盖，但会让读者以为"诊断路径自己算了一遍"，也会引诱后人去改错
那一份。Python 不把这种情况当语法错误，ruff/flake8 的默认规则集也不报。

同一类问题的另一种形态是**同名函数定义两次**：`core/static_review.py` 里
`_numeric_findings` 被定义了两次，后一份静默覆盖前一份，前一份成了永远不执行的死代码
（mypy 的 `no-redef` 会报，但项目没有跑 mypy 门禁）。本脚本一并检查。

判据保守，只报**确定有问题**的：
- 同一个语句块里，跟在 `return` / `raise` / `break` / `continue` 之后的语句；
- `if/else` 两个分支都以终止语句结束、或 `while True` 且体内没有 `break` 时的后续语句；
- 同一作用域内同名的函数/类定义出现多次（后一份覆盖前一份）。

用法：`python scripts/check_dead_code.py`（有问题退出码 1）。
"""

from __future__ import annotations

import ast
from collections import Counter
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git", ".iverilog-ai", ".dsh-tmp", "__pycache__", "build", "dist", "node_modules",
    ".venv", "venv", ".tmp-codex", ".tmp-test", ".ci-runs", ".mypy_cache",
}
TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _terminates(node: ast.AST) -> bool:
    """该语句是否**必然**终止本块（保守判断，宁可漏报不可误报）。"""

    if isinstance(node, TERMINATORS):
        return True
    if isinstance(node, ast.If) and node.body and node.orelse:
        return _terminates(node.body[-1]) and _terminates(node.orelse[-1])
    if isinstance(node, ast.While) and node.orelse:
        if _terminates(node.body[-1]) if node.body else False:
            return False  # 有 else 分支时复杂，交给保守判断
    if isinstance(node, ast.Try) and node.finalbody and _terminates(node.finalbody[-1]):
        return True
    return False


def _always_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _has_break(body: list[ast.stmt]) -> bool:
    for item in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(item, ast.Break):
            return True
    return False


def _check_body(body: list[ast.stmt], where: str, out: list[str]) -> None:
    for index, statement in enumerate(body):
        if index + 1 < len(body) and _terminates(statement):
            following = body[index + 1]
            out.append(f"{where}:{following.lineno}: 该语句在 {statement.lineno} 行的终止语句之后，永远不会执行")
            break
        if isinstance(statement, ast.While) and _always_true(statement.test) and not _has_break(statement.body):
            if index + 1 < len(body):
                following = body[index + 1]
                out.append(f"{where}:{following.lineno}: 该语句在 {statement.lineno} 行的无限循环之后，永远不会执行")
                break
        for field in ("body", "orelse", "finalbody"):
            nested = getattr(statement, field, None)
            if isinstance(nested, list) and nested and all(isinstance(item, ast.stmt) for item in nested):
                if field == "orelse" and not nested:
                    continue
                _check_body(nested, where, out)
        for handler in getattr(statement, "handlers", []) or []:
            if handler.body:
                _check_body(handler.body, where, out)


def _definition_findings(tree: ast.AST, path: Path) -> list[str]:
    """同一作用域内同名的函数/类定义出现多次：后一份会静默覆盖前一份。"""

    findings: list[str] = []
    scopes: list[tuple[str, list[ast.stmt]]] = [("<module>", getattr(tree, "body", []))]

    def visit(scope_name: str, body: list[ast.stmt]) -> None:
        names = [
            statement.name
            for statement in body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for name, count in Counter(names).items():
            if count > 1:
                lines = [
                    statement.lineno
                    for statement in body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and statement.name == name
                ]
                findings.append(
                    f"{path.relative_to(ROOT)}::{scope_name}: 定义 `{name}` 出现 {count} 次（行 {lines}）——"
                    "后一份会静默覆盖前一份，前一份是永远不执行的死代码"
                )
        for statement in body:
            nested = getattr(statement, "body", None)
            if isinstance(nested, list) and nested and all(isinstance(item, ast.stmt) for item in nested):
                child = statement.name if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else scope_name
                visit(child, nested)
            for field in ("orelse", "finalbody"):
                extra = getattr(statement, field, None)
                if isinstance(extra, list) and extra and all(isinstance(item, ast.stmt) for item in extra):
                    visit(scope_name, extra)
            for handler in getattr(statement, "handlers", []) or []:
                if handler.body:
                    visit(scope_name, handler.body)

    visit("<module>", scopes[0][1])
    return findings


def scan_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: 语法错误：{exc.msg}"]
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_body(node.body, f"{path.relative_to(ROOT)}::{node.name}", findings)
    findings.extend(_definition_findings(tree, path))
    return findings


def main() -> int:
    findings: list[str] = []
    files = [
        path
        for path in sorted(ROOT.rglob("*.py"))
        if not (SKIP_PARTS & set(path.parts)) and path.resolve() != Path(__file__).resolve()
    ]
    for path in files:
        findings.extend(scan_file(path))
    if not findings:
        print(f"未可达代码检查：{len(files)} 个文件，未发现")
        return 0
    for item in findings:
        print(item)
    print(f"\n共 {len(findings)} 处不可达代码")
    return 1


if __name__ == "__main__":
    sys.exit(main())
