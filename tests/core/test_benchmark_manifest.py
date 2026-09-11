import json
import re
from collections import defaultdict
from pathlib import Path


def test_benchmark_manifest_defects_are_distinct_complete_and_existing():
    """缺陷基准必须完整、唯一、可追溯，且每个缺陷文件真实存在。"""

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    defects = manifest["defects"]

    # 规模断言：基准已从 4 案例 50 缺陷扩展到 14 案例 80 缺陷。
    assert len(defects) >= 80
    assert len({item["id"] for item in defects}) == len(defects)
    assert all((root / item["file"]).is_file() for item in defects)
    assert all(item.get("trigger") and item.get("expected") and item.get("actual") for item in defects)
    assert all(item.get("testbench") for item in defects)
    assert all((root / item["testbench"]).is_file() for item in defects)


def _normalized_source(path: Path) -> str:
    """去掉注释与空白后的代码本体：用于判断两个变体是不是同一个缺陷。"""

    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def test_no_two_defects_have_identical_source():
    """任何两个缺陷变体的代码本体都不能完全相同。

    这条断言来自一次真实事故：`srst_bug_single_stage_only` 与
    `srst_bug_single_stage` 的代码**逐字节相同**，只是 id 不同，于是"80 个缺陷"
    里有一个是重复计数。id 唯一并不等于缺陷唯一，必须比对代码本体。
    """

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    groups: dict[str, list[str]] = defaultdict(list)
    for item in manifest["defects"]:
        groups[_normalized_source(root / item["file"])].append(item["id"])
    duplicates = {body: ids for body, ids in groups.items() if len(ids) > 1}
    assert not duplicates, f"存在代码完全相同的重复缺陷：{list(duplicates.values())}"


def test_no_defect_source_equals_its_reference():
    """缺陷必须真的与参考设计不同，否则它根本不是缺陷。"""

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["defects"]:
        reference = root / "rtl" / f"{item['type']}.v"
        assert _normalized_source(root / item["file"]) != _normalized_source(reference), (
            f"{item['id']} 与其参考设计 {reference.name} 代码相同，不构成缺陷"
        )


def test_every_case_has_at_least_two_independent_defects():
    """每个案例至少要有 2 个缺陷，否则该案例的检出能力没有区分度。"""

    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    per_case: dict[str, int] = defaultdict(int)
    for item in manifest["defects"]:
        per_case[item["type"]] += 1
    for case in manifest["categories"]:
        assert per_case.get(case, 0) >= 2, f"案例 {case} 的缺陷少于 2 个"


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
        "johnson_counter",
        "edge_detector",
    ):
        assert case in categories
        assert case in defect_types
