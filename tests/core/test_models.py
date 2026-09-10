import json

import pytest

from iverilog_ai.core.models import ModelValidationError, ResultRecord, TestPlan as Plan


def test_test_plan_round_trip_and_sequential_cycles():
    plan = Plan.from_dict(
        {
            "schema_version": "1.0",
            "dut_module": "mod10_counter",
            "clock": {"signal": "clk", "period_ns": 10},
            "reset": {"signal": "rst_n", "active_level": 0},
            "cases": [
                {
                    "id": "reset",
                    "steps": [
                        {"inputs": {"rst_n": 0}, "hold_cycles": 2},
                        {"inputs": {"rst_n": 1}},
                    ],
                }
            ],
        }
    )
    assert plan.cases[0].steps[0].cycle == 0
    assert plan.cases[0].steps[1].cycle == 2
    restored = Plan.from_json(plan.to_json())
    assert restored.to_dict() == plan.to_dict()


@pytest.mark.parametrize(
    "payload",
    [
        {"dut_module": "bad-name", "cases": [{"id": "x", "steps": [{"inputs": {}}]}]},
        {"dut_module": "dut", "cases": [{"id": "x", "steps": [{"inputs": {"bad.name": 1}}]}]},
        {"dut_module": "dut", "cases": [{"id": "x", "steps": [{"inputs": {}}], "unknown": 1}]},
    ],
)
def test_plan_rejects_unsafe_or_unknown_fields(payload):
    with pytest.raises(ModelValidationError):
        Plan.from_dict(payload)


def test_result_record_accepts_status_alias():
    record = ResultRecord.from_dict(
        {"status": "failed", "test": "wrap", "cycle": 11, "signal": "count", "expected": 0, "actual": 10}
    )
    assert record.ok is False
    assert record.test_id == "wrap"
    assert json.loads(json.dumps(record.to_dict()))["actual"] == 10
