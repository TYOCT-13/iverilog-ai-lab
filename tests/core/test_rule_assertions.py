from iverilog_ai.core.rule_assertions import assertion_suggestions


def test_rule_assertion_suggestions_are_bounded_data():
    suggestions = assertion_suggestions("mod10_counter")
    assert suggestions
    assert all("kind" in item and "signal" in item for item in suggestions)
    assert assertion_suggestions("unknown_case") == []
