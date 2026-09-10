from iverilog_ai.core.reference_model import check_plan_consistency


def test_reference_model_reports_expected_consistency():
    plan = {
        "design": "simple_alu",
        "vectors": [
            {"name": "ok", "inputs": {"a": 1, "b": 2, "op": 0}, "expected": {"result": 3, "carry": 0, "zero": 0}},
            {"name": "bad", "inputs": {"a": 1, "b": 2, "op": 0}, "expected": {"result": 9}},
        ],
    }
    result = check_plan_consistency(plan)
    assert result["checked_expected"] == 4
    assert result["matched_expected"] == 3
    assert result["consistency_rate"] == 0.75
    assert result["status"] == "warn"
