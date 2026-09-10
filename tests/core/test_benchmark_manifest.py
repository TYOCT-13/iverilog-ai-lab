import json
from pathlib import Path


def test_benchmark_manifest_has_fifty_distinct_existing_defects():
    root = Path(__file__).parents[2]
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    defects = manifest["defects"]
    assert len(defects) == 50
    assert len({item["id"] for item in defects}) == 50
    assert all((root / item["file"]).is_file() for item in defects)
    assert all(item.get("trigger") and item.get("expected") and item.get("actual") for item in defects)
