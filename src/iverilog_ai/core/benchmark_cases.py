"""基准案例表：把"案例名 → RTL / 边界 testbench / 顶层模块"这份映射收拢到一处。

**为什么需要这个模块**：这份映射原先在 `scripts/run_benchmark_matrix.py`、
`scripts/run_strategy_experiment.py` 与 `ui/app.py` 各写了一份，而
`benchmarks/manifest.json` 只登记案例名与缺陷，不登记路径。三份表之间没有任何
门禁，于是存在一种**静默失败**：往 manifest 的 `categories` 加一个案例，却忘了往
基准矩阵脚本的表里加，那个案例的参考设计就**根本不会被跑**，而矩阵仍然报
"15 / 15 参考全过"——分母变小了，结论却看起来一样漂亮。

本模块把表收成一份，并提供 :func:`validate_case_table` 在脚本启动时校验；
`tests/core/test_benchmark_cases.py` 把它钉成回归用例。

映射里的 `top` 指的是**该案例默认 testbench 的顶层模块名**；缺陷若声明了专用
testbench，其顶层名由 :func:`top_for_testbench` 推出。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "CASE_TABLE",
    "case_table",
    "load_manifest",
    "top_for_testbench",
    "validate_case_table",
]


#: 案例名 → ``rtl`` / ``testbench`` / ``top``。顺序即报告顺序。
CASE_TABLE: dict[str, dict[str, str]] = {
    "mod10_counter": {"rtl": "rtl/mod10_counter.v", "testbench": "tb/tb_mod10_counter.v", "top": "tb_mod10_counter"},
    "traffic_light_emergency": {
        "rtl": "rtl/traffic_light_emergency.v",
        "testbench": "tb/tb_traffic_light_emergency.v",
        "top": "tb_traffic_light_emergency",
    },
    "simple_alu": {"rtl": "rtl/simple_alu.v", "testbench": "tb/tb_simple_alu.v", "top": "tb_simple_alu"},
    "sequence_101_overlap": {
        "rtl": "rtl/sequence_101_overlap.v",
        "testbench": "tb/tb_sequence_101_overlap.v",
        "top": "tb_sequence_101_overlap",
    },
    # 常用 FPGA 案例的边界基准：每个案例使用专门的边界 testbench，
    # 覆盖写满/回绕、位序、握手保持、门限、占空比边界、同步级数等触发条件。
    "sync_fifo": {"rtl": "rtl/sync_fifo.v", "testbench": "tb/tb_sync_fifo.v", "top": "tb_sync_fifo"},
    "uart_tx": {"rtl": "rtl/uart_tx.v", "testbench": "tb/tb_uart_tx.v", "top": "tb_uart_tx"},
    "spi_master": {"rtl": "rtl/spi_master.v", "testbench": "tb/tb_spi_master.v", "top": "tb_spi_master"},
    "handshake_stage": {"rtl": "rtl/handshake_stage.v", "testbench": "tb/tb_handshake_stage.v", "top": "tb_handshake_stage"},
    "debounce": {"rtl": "rtl/debounce.v", "testbench": "tb/tb_debounce.v", "top": "tb_debounce"},
    "pwm": {"rtl": "rtl/pwm.v", "testbench": "tb/tb_pwm.v", "top": "tb_pwm"},
    "mux4": {"rtl": "rtl/mux4.v", "testbench": "tb/tb_mux4.v", "top": "tb_mux4"},
    "sync_reset": {"rtl": "rtl/sync_reset.v", "testbench": "tb/tb_sync_reset.v", "top": "tb_sync_reset"},
    "johnson_counter": {"rtl": "rtl/johnson_counter.v", "testbench": "tb/tb_johnson_counter.v", "top": "tb_johnson_counter"},
    "edge_detector": {"rtl": "rtl/edge_detector.v", "testbench": "tb/tb_edge_detector.v", "top": "tb_edge_detector"},
    "pulse_stretcher": {"rtl": "rtl/pulse_stretcher.v", "testbench": "tb/tb_pulse_stretcher.v", "top": "tb_pulse_stretcher"},
}


def case_table(root: str | Path) -> dict[str, dict[str, str]]:
    """返回校验通过的案例表（校验失败直接抛错，不做静默降级）。"""

    validate_case_table(root)
    return {case: dict(spec) for case, spec in CASE_TABLE.items()}


def load_manifest(root: str | Path) -> dict[str, Any]:
    """读取 ``benchmarks/manifest.json``。"""

    path = Path(root) / "benchmarks" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def top_for_testbench(testbench_rel: str, info: dict[str, str]) -> str:
    """由 testbench 路径推出顶层模块名；与案例默认 testbench 一致时复用声明值。"""

    if testbench_rel == info["testbench"]:
        return info["top"]
    return Path(testbench_rel).stem


def validate_case_table(root: str | Path) -> None:
    """校验案例表与 manifest 一致、路径真实存在。

    三类问题都必须**报错而不是跳过**：

    1. manifest 里的案例在表里没有对应行 → 该案例的参考设计会被静默漏跑；
    2. 表里的案例没在 manifest 登记 → 报告口径与基准清单不一致；
    3. RTL / testbench 文件不存在 → 跑起来才发现，浪费一次矩阵时间。
    """

    root_path = Path(root)
    manifest = load_manifest(root_path)
    categories = {str(name) for name in manifest.get("categories", [])}
    listed = set(CASE_TABLE)
    missing = sorted(categories - listed)
    extra = sorted(listed - categories)
    if missing:
        raise ValueError(f"案例表缺少 manifest 登记的案例（会导致参考设计被静默漏跑）：{missing}")
    if extra:
        raise ValueError(f"案例表存在 manifest 未登记的案例（口径不一致）：{extra}")
    for case, info in CASE_TABLE.items():
        for key in ("rtl", "testbench", "top"):
            if not str(info.get(key) or "").strip():
                raise ValueError(f"案例 {case} 缺少 {key}")
        for key in ("rtl", "testbench"):
            if not (root_path / info[key]).is_file():
                raise ValueError(f"案例 {case} 的 {key} 不存在：{info[key]}")
    known = categories
    for defect in manifest.get("defects", []):
        case = str(defect.get("type"))
        if case not in known:
            raise ValueError(f"缺陷 {defect.get('id')} 指向未登记的案例：{case}")
        rtl = root_path / str(defect.get("file", ""))
        if not rtl.is_file():
            raise ValueError(f"缺陷 {defect.get('id')} 的 RTL 不存在：{defect.get('file')}")
