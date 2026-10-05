"""正确规格的独立逐拍语义：到期令牌队列与事件集合基数。"""
from __future__ import annotations

from typing import Mapping, Sequence


def _known(row: Mapping[str, int], signal: str, maximum: int) -> int:
    value = row[signal]
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("reference_input_not_known_or_in_range")
    return value


def valid_data_pipeline(rows: Sequence[Mapping[str, int]]) -> list[dict[str, int]]:
    """E0捕获令牌在E1投递；flush/rst清掉所有尚未投递的令牌。"""
    pending: dict[int, int] = {}
    observations: list[dict[str, int]] = []
    for edge, row in enumerate(rows):
        reset = _known(row, "i_rstn", 1)
        flush = _known(row, "i_flush", 1)
        valid = _known(row, "i_valid", 1)
        data = _known(row, "i_data", 255)
        if not reset or flush:
            pending.clear()
            result = {"o_valid": 0, "o_data": 0}
        else:
            delivered = pending.pop(edge, None)
            result = {"o_valid": int(delivered is not None), "o_data": 0 if delivered is None else delivered}
            if valid:
                pending[edge + 1] = data
        observations.append(result)
    return observations


def event_accumulator(rows: Sequence[Mapping[str, int]]) -> list[dict[str, int]]:
    """计数是最近复位/清除后接受事件集合的基数模16，不复用RTL递加器。"""
    accepted_edges: set[int] = set()
    observations: list[dict[str, int]] = []
    for edge, row in enumerate(rows):
        reset = _known(row, "i_rstn", 1)
        clear = _known(row, "i_clear", 1)
        enabled = _known(row, "i_enable", 1)
        event = _known(row, "i_event", 1)
        if not reset or clear:
            accepted_edges.clear()
        elif enabled and event:
            accepted_edges.add(edge)
        observations.append({"o_count": len(accepted_edges) % 16})
    return observations


REFERENCES = {"valid_data_pipeline": valid_data_pipeline, "event_accumulator": event_accumulator}
