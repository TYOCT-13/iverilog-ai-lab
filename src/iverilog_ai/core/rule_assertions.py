"""Provide validated structured-assertion suggestions for registered cases.

断言按整个采样序列判定，没有向量级作用域。递增计数器不适用全局 count=0 或
稳定性断言，FIFO 的 empty 也不能在写入后继续要求为 1。cycles=1 的稳定窗口
没有有效检查作用；never_high 模板不接受 cycles 字段。

当前建议表为空。新增建议必须通过 tests/core/test_rule_assertions.py：字段合法、
正确参考设计通过，且实际产生非空检查。建议为普通数据，不生成自由 Verilog 代码。
"""
from __future__ import annotations

from typing import Any


#: 案例名 → 已验证的断言建议。**加条目必须同时通过 tests/core/test_rule_assertions.py 的门禁。**
_SUGGESTIONS: dict[str, list[dict[str, Any]]] = {}


def assertion_suggestions(case: str) -> list[dict[str, Any]]:
    """Return a copy of conservative suggestions for ``case`` (可能为空列表）。"""
    return [dict(item) for item in _SUGGESTIONS.get(case, [])]


__all__ = ["assertion_suggestions"]
