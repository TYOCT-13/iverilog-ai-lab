import pytest

from iverilog_ai.core.assertions import (
    AssertionValidationError, StructuredAssertion, build_assertion,
    evaluate_assertion,
)


def test_signal_equals_and_roundtrip():
    a = build_assertion({"kind": "signal_equals", "signal": "done", "value": 1})
    assert isinstance(a, StructuredAssertion)
    assert a.to_dict() == {"kind": "signal_equals", "signal": "done", "value": 1}
    assert evaluate_assertion(a, [{"done": 1}, {"done": 1}]).passed
    assert not evaluate_assertion(a, [{"done": 0}]).passed


def test_stable_and_never_high():
    assert evaluate_assertion({"kind": "signal_stable", "signal": "state", "cycles": 2},
                              [{"state": 0}, {"state": 0}, {"state": 1}]).passed is False
    assert evaluate_assertion({"kind": "never_high", "signal": "alarm"},
                              [{"alarm": 0}, {"alarm": False}]).passed
    assert not evaluate_assertion({"kind": "never_high", "signal": "alarm"}, [{"alarm": 1}]).passed


@pytest.mark.parametrize("description", [
    {"kind": "signal_equals", "signal": "x; $display(1)", "value": 0},
    {"kind": "arbitrary", "signal": "x"},
    {"kind": "never_high", "signal": "x", "code": "bad"},
    {"kind": "signal_stable", "signal": "x", "cycles": 0},
])
def test_templates_reject_unsafe_or_invalid(description):
    with pytest.raises(AssertionValidationError):
        build_assertion(description)


def test_missing_signal_is_failure():
    result = evaluate_assertion({"kind": "signal_equals", "signal": "done", "value": 1}, [{"other": 1}])
    assert not result.passed
    assert "missing" in result.message


def test_sequence_and_implies_templates():
    sequence = build_assertion({"kind": "signal_sequence", "signal": "done", "values": [0, 1], "cycles": 2})
    assert evaluate_assertion(sequence, [{"done": 0}, {"done": 1}]).passed
    implication = build_assertion({"kind": "signal_implies", "when_signal": "req", "when_value": 1, "then_signal": "ack", "then_value": 1, "within_cycles": 1})
    assert evaluate_assertion(implication, [{"req": 1, "ack": 0}, {"req": 0, "ack": 1}]).passed
    assert not evaluate_assertion(implication, [{"req": 1, "ack": 0}, {"req": 0, "ack": 0}]).passed
