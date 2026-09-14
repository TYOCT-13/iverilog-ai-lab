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


# ---------------------------------------------------------------------------
# 采样值是 Verilog 位串（'0000'），断言值是整数（0）——必须按值比较
# ---------------------------------------------------------------------------

def test_bitstring_samples_compare_equal_to_integer_values():
    """真实事故：`signal_equals{count: 0}` 在参考设计上被判成 "expected 0, observed '0000'"。

    采样记录里的多比特信号是位串，断言里的 value 通常写整数；直接 `'0000' == 0` 永远为假，
    于是**参考设计上也会报假失败**（我们自己的推荐断言就踩了这个坑）。
    """

    assert evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": 0},
                              [{"count": "0000"}, {"count": "0000"}]).passed
    assert evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": 5},
                              [{"count": "0101"}]).passed
    assert not evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": 0},
                                  [{"count": "0001"}]).passed
    # 位串写法也认（模型有时直接把位串当 value）
    assert evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": "0101"},
                              [{"count": "0101"}]).passed
    # 1 位信号同样按值比较，bool 与 0/1 等价
    assert evaluate_assertion({"kind": "signal_equals", "signal": "done", "value": True},
                              [{"done": "1"}]).passed
    assert evaluate_assertion({"kind": "never_high", "signal": "alarm"},
                              [{"alarm": "0"}, {"alarm": "0"}]).passed
    assert not evaluate_assertion({"kind": "never_high", "signal": "alarm"}, [{"alarm": "1"}]).passed


def test_bitstring_sequence_and_implies_compare_by_value():
    assert evaluate_assertion({"kind": "signal_sequence", "signal": "count", "values": [0, 1], "cycles": 2},
                              [{"count": "00"}, {"count": "01"}]).passed
    implication = {"kind": "signal_implies", "when_signal": "req", "when_value": 1,
                   "then_signal": "ack", "then_value": 1, "within_cycles": 1}
    assert evaluate_assertion(implication, [{"req": "1", "ack": "0"}, {"req": "0", "ack": "1"}]).passed
    assert not evaluate_assertion(implication, [{"req": "1", "ack": "0"}, {"req": "0", "ack": "0"}]).passed


def test_unknown_bits_are_not_silently_equal_to_zero():
    """`x`/`z` 是**不定值**，不能折算成 0 后"等于期望值"——那是伪造通过。"""

    assert not evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": 0},
                                  [{"count": "xxxx"}]).passed
    assert not evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": 0},
                                  [{"count": "zzzz"}]).passed
    assert evaluate_assertion({"kind": "signal_equals", "signal": "count", "value": "xxxx"},
                              [{"count": "xxxx"}]).passed


def test_signal_stable_with_one_cycle_is_reported_as_vacuous():
    """`cycles=1` 的 signal_stable 恒真——判定通过，但必须把"这是空检查"说出来。"""

    result = evaluate_assertion({"kind": "signal_stable", "signal": "state", "cycles": 1},
                                [{"state": 0}, {"state": 1}, {"state": 0}])
    assert result.passed
    assert "恒真" in result.message
