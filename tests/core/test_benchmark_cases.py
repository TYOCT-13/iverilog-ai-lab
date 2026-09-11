"""基准案例表与 manifest 的一致性门禁。

这三条断言针对的是同一类**静默失败**：表里少一个案例，那个案例的参考设计就
不会被跑，而矩阵照样报"全过"——分母悄悄变小，结论看起来毫无变化。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.benchmark_cases import (
    CASE_TABLE,
    case_table,
    load_manifest,
    top_for_testbench,
    validate_case_table,
)

ROOT = Path(__file__).resolve().parents[2]


def test_case_table_matches_manifest_categories_exactly():
    manifest = load_manifest(ROOT)
    assert set(CASE_TABLE) == set(manifest["categories"])


def test_case_table_paths_exist_and_are_unique():
    rtl = [info["rtl"] for info in CASE_TABLE.values()]
    tb = [info["testbench"] for info in CASE_TABLE.values()]
    assert len(set(rtl)) == len(rtl), "两个案例指向同一份 RTL"
    assert len(set(tb)) == len(tb), "两个案例共用同一份 testbench"
    for case, info in CASE_TABLE.items():
        assert (ROOT / info["rtl"]).is_file(), f"{case} 的 RTL 不存在"
        assert (ROOT / info["testbench"]).is_file(), f"{case} 的 testbench 不存在"


def test_validate_rejects_missing_category(tmp_path):
    """把 manifest 复制到临时目录并加一个案例，校验必须报错而不是放行。"""

    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "rtl").mkdir()
    (tmp_path / "tb").mkdir()
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    manifest["categories"] = list(manifest["categories"]) + ["ghost_case"]
    (tmp_path / "benchmarks" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="静默漏跑"):
        validate_case_table(tmp_path)


def test_validate_rejects_missing_file(tmp_path):
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "rtl").mkdir()
    (tmp_path / "tb").mkdir()
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "benchmarks" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    for info in CASE_TABLE.values():
        (tmp_path / info["rtl"]).write_text("module x; endmodule\n", encoding="utf-8")
    # testbench 故意不建
    with pytest.raises(ValueError, match="不存在"):
        validate_case_table(tmp_path)


def test_case_table_returns_a_copy():
    """调用方改返回值不能污染全局表。"""

    table = case_table(ROOT)
    table["pwm"]["top"] = "hacked"
    assert CASE_TABLE["pwm"]["top"] == "tb_pwm"


def test_top_for_testbench_uses_declared_top_for_default_testbench():
    info = CASE_TABLE["pwm"]
    assert top_for_testbench(info["testbench"], info) == info["top"]
    # 专用 testbench 用文件名当顶层
    assert top_for_testbench("tb/tb_pwm_special.v", info) == "tb_pwm_special"
