"""Generate conservative structured-assertion suggestions from a case name.

Suggestions are plain data and must be reviewed by the user before being added
to a TestPlan. No Verilog or executable content is produced.

**为什么现在这份表是空的（2026-09 复核）**

结构化断言是按"该信号的**整个采样序列**"判定的（`core.pipeline._evaluate_structured_assertions`），
没有作用域、没有"第几拍"的概念。原来给 4 个案例写了 5 条建议，逐条实测（参考设计 +
本仓库的确定性激励）后发现：

| 原建议 | 实测结果 |
|---|---|
| `mod10_counter`: `signal_equals{count, 0}` | **失败**——`signal_equals` 的含义是"每一拍都等于 0"，而计数器会递增 |
| `mod10_counter`: `signal_stable{count, 2}` | **失败**——计数器本来就在变 |
| `traffic_light_emergency`: `signal_stable{main_light, 1}` | **恒真**——`cycles=1` 时每个窗口长度为 1，永远"稳定"，等于没有检查 |
| `traffic_light_emergency`: `signal_stable{side_light, 1}` | 同上 |
| `sync_fifo`: `signal_equals{empty, 1}` | **失败**——写入后 `empty` 会拉低 |
| `sync_fifo`: `never_high{full, cycles: 1}` | **非法**——`never_high` 没有 `cycles` 字段，载入后计划直接校验失败 |

也就是说：一键载入的"推荐断言"要么必然误报、要么是空检查、要么根本通不过严格校验。
在这套模板（全局语义）下，这些案例里没有能同时满足"成立 + 非空检查"的断言可写，
因此表清空——宁可没有推荐，也不给用户一份看着像检查、其实必然误报的清单。

要重新加入条目，必须先在参考设计上跑通：`tests/core/test_rule_assertions.py` 会把
每一条建议都真的跑一遍（校验 + 参考设计通过 + 非空检查），加不进去就说明它不成立。
"""
from __future__ import annotations

from typing import Any


#: 案例名 → 已验证的断言建议。**加条目必须同时通过 tests/core/test_rule_assertions.py 的门禁。**
_SUGGESTIONS: dict[str, list[dict[str, Any]]] = {}


def assertion_suggestions(case: str) -> list[dict[str, Any]]:
    """Return a copy of conservative suggestions for ``case`` (可能为空列表）。"""
    return [dict(item) for item in _SUGGESTIONS.get(case, [])]


__all__ = ["assertion_suggestions"]
