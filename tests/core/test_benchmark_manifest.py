import json
from pathlib import Path


def test_benchmark_manifest_defects_are_distinct_complete_and_existing():
    """缺陷基准必须完整、唯一、可追溯，且每个缺陷文件真实存在。"""

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    defects = manifest["defects"]

    # 规模断言：基准已从 4 案例 50 缺陷扩展到 12 案例 70 缺陷。
    assert len(defects) >= 70
    assert len({item["id"] for item in defects}) == len(defects)
    assert all((root / item["file"]).is_file() for item in defects)
    assert all(item.get("trigger") and item.get("expected") and item.get("actual") for item in defects)
    assert all(item.get("testbench") for item in defects)
    assert all((root / item["testbench"]).is_file() for item in defects)


def test_benchmark_categories_cover_the_bundled_cases():
    """manifest 登记的案例必须与 benchmarks 声明的分类一致，且覆盖常用 FPGA 案例。"""

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    categories = set(manifest["categories"])
    defect_types = {item["type"] for item in manifest["defects"]}

    # 每个缺陷的案例都必须在分类里声明，避免出现"孤儿"缺陷。
    assert defect_types <= categories
    # 常用 FPGA 案例必须已纳入基准，而不是只有参考设计与 testbench。
    for case in (
        "sync_fifo",
        "uart_tx",
        "spi_master",
        "handshake_stage",
        "debounce",
        "pwm",
        "mux4",
        "sync_reset",
    ):
        assert case in categories
        assert case in defect_types
