import pytest
from pydantic import ValidationError

from iverilog_ai.ai.schema import TestPlan as Plan


def _plan(**overrides):
    payload = {
        "design": "counter",
        "objective": "verify boundaries",
        "vectors": [{"name": "zero", "inputs": {"a": 0}, "expected": {"y": 0}}],
    }
    payload.update(overrides)
    return payload


def test_ai_schema_rejects_unknown_and_unsafe_fields():
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(extra_field="nope"))
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(vectors=[{"name": "x", "inputs": {"a; $finish": 0}}]))
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(reset={"signal": "rst_n", "command": "iverilog"}))


def test_ai_schema_rejects_duplicate_vector_names_and_non_scalar_values():
    with pytest.raises(ValidationError):
        Plan.model_validate(
            _plan(
                vectors=[
                    {"name": "same", "inputs": {"a": 0}},
                    {"name": "same", "inputs": {"a": 1}},
                ]
            )
        )


def test_structured_assertions_are_typed_templates_only():
    plan = Plan.model_validate(_plan(assertions=[{"kind": "signal_equals", "signal": "y", "value": 0}]))
    assert plan.assertions[0]["kind"] == "signal_equals"
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(assertions=[{"kind": "raw_sva", "signal": "y", "code": "assert(1)"}]))
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(vectors=[{"name": "bad", "inputs": {"a": ["1", "2"]}}]))


def test_ai_schema_accepts_explicit_sampling_phase_only():
    plan = Plan.model_validate(_plan(vectors=[{"name": "before", "inputs": {"a": 0}, "sample_phase": "before"}]))
    assert plan.vectors[0].sample_phase == "before"
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(vectors=[{"name": "bad", "inputs": {"a": 0}, "sample_phase": "during"}]))
