"""Generate conservative structured-assertion suggestions from a case name.

Suggestions are plain data and must be reviewed by the user before being added
to a TestPlan. No Verilog or executable content is produced.
"""
from __future__ import annotations

from typing import Any


_SUGGESTIONS: dict[str, list[dict[str, Any]]] = {
    "mod10_counter": [
        {"kind": "signal_equals", "signal": "count", "value": 0},
        {"kind": "signal_stable", "signal": "count", "cycles": 2},
    ],
    "traffic_light_emergency": [
        {"kind": "signal_stable", "signal": "main_light", "cycles": 1},
        {"kind": "signal_stable", "signal": "side_light", "cycles": 1},
    ],
    "simple_alu": [],
    "sequence_101_overlap": [],
    "edge_detector": [],
    "pulse_stretcher": [],
    "sync_fifo": [
        {"kind": "signal_equals", "signal": "empty", "value": 1},
        {"kind": "never_high", "signal": "full", "cycles": 1},
    ],
    "uart_tx": [],
    "spi_master": [],
    "handshake_stage": [
        {"kind": "signal_stable", "signal": "out_data", "cycles": 2},
    ],
    "debounce": [],
    "pwm": [],
    "mux4": [],
    "sync_reset": [],
}


def assertion_suggestions(case: str) -> list[dict[str, Any]]:
    """Return a copy of conservative suggestions for ``case``."""
    return [dict(item) for item in _SUGGESTIONS.get(case, [])]


__all__ = ["assertion_suggestions"]
