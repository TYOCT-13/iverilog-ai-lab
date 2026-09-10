from pathlib import Path

from iverilog_ai.core.static_review import review_rtl_file


def test_builtin_reference_rtl_has_review_result():
    root = Path(__file__).parents[2]
    result = review_rtl_file(root / "rtl" / "mod10_counter.v")
    assert result["filename"] == "mod10_counter.v"
    assert result["source_sha256"]
    assert "findings" in result
