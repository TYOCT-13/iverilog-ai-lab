"""推荐结构化断言的门禁：**每一条都必须在参考设计上真的成立**。

为什么需要这个文件：断言建议是"一键载入"给用户直接用的，任何一条不成立都会变成
参考设计上的假失败。2026-09 复核发现原来 5 条建议全部有问题（2 条必然误报、2 条恒真
等于没检查、1 条字段非法），根因是它们从没被真的跑过。现在：
1. 表里每一条都要能通过严格校验（`TestPlan`）；
2. 每一条都要在参考设计 + 本仓库确定性激励下判定为通过；
3. 不允许恒真的空检查（`signal_stable` 的 `cycles` 至少 2）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iverilog_ai.ai import offline_provider, plan_tests
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rule_assertions import _SUGGESTIONS, assertion_suggestions

ROOT = Path(__file__).resolve().parents[2]


def test_unknown_case_has_no_suggestions():
    assert assertion_suggestions("unknown_case") == []
    assert assertion_suggestions("") == []


def test_suggestions_are_copies_not_shared_state():
    for case in _SUGGESTIONS:
        first = assertion_suggestions(case)
        first.append({"kind": "signal_equals", "signal": "x", "value": 0})
        assert len(assertion_suggestions(case)) == len(_SUGGESTIONS[case])


def test_no_vacuous_suggestions():
    """`signal_stable{cycles: 1}` 恒真：看着像检查，其实什么都没查。"""

    for case, suggestions in _SUGGESTIONS.items():
        for item in suggestions:
            if item.get("kind") == "signal_stable":
                assert int(item.get("cycles", 1)) >= 2, f"{case} 的 {item} 是空检查"


def test_every_suggestion_holds_on_the_reference_design():
    """在参考设计上真的跑一遍：建议必须全部通过，且不能是空检查。

    推荐表为空时跳过（当前就是如此，原因见 `rule_assertions` 模块说明）；表里一旦有
    条目，这里就会逐个案例真跑仿真。
    """

    if not _SUGGESTIONS:
        pytest.skip("推荐断言表当前为空：没有可验证的条目（见 core/rule_assertions.py 的说明）")

    for case in sorted(_SUGGESTIONS):
        suggestions = assertion_suggestions(case)
        contract = DutContract.from_json((ROOT / "examples" / f"{case}_contract.json").read_text(encoding="utf-8"))
        base = plan_tests("覆盖复位与回绕", case, provider=offline_provider(contract), max_retries=0)
        plan = TestPlan.model_validate({**base.model_dump(mode="json"), "assertions": suggestions})
        result = VerificationPipeline().run(
            plan, contract, ROOT / "rtl" / f"{case}.v",
            ROOT / ".iverilog-ai" / "rule-assertions-gate", allowed_roots=(ROOT,), emit_vcd=False,
        )
        report = (result.simulation.config or {}).get("structured_assertions") or {}
        results = report.get("results") or []
        assert len(results) == len(suggestions)
        failures = [item for item in results if not item.get("passed")]
        assert not failures, f"{case} 的推荐断言在参考设计上失败：{failures}"
        for item in results:
            assert "恒真" not in str(item.get("message", "")), f"{case} 的 {item} 是空检查"


def test_the_known_broken_suggestions_stay_removed():
    """把 2026-09 复核删掉的那几条钉住：它们不许被原样加回来。

    每一条都附了当时的实测结论——重新加回来必须先证明它成立。
    """

    broken = [
        ("mod10_counter", {"kind": "signal_equals", "signal": "count", "value": 0}),
        ("mod10_counter", {"kind": "signal_stable", "signal": "count", "cycles": 2}),
        ("traffic_light_emergency", {"kind": "signal_stable", "signal": "main_light", "cycles": 1}),
        ("traffic_light_emergency", {"kind": "signal_stable", "signal": "side_light", "cycles": 1}),
        ("sync_fifo", {"kind": "signal_equals", "signal": "empty", "value": 1}),
        ("sync_fifo", {"kind": "never_high", "signal": "full", "cycles": 1}),
    ]
    for case, item in broken:
        assert item not in assertion_suggestions(case), (
            f"{case} 的 {item} 已经实测为不成立/空检查/字段非法，不能直接加回；"
            "先让 test_every_suggestion_holds_on_the_reference_design 通过"
        )


def test_never_high_has_no_cycles_field_and_that_is_enforced():
    """`never_high` 只接受 `kind`/`signal`：多写 `cycles` 会被严格校验拒绝。

    这与手册一致，也是上面第 6 条被删掉的原因（它写了 `cycles: 1`，载入后计划直接校验失败）。
    """

    from iverilog_ai.ai.schema import ASSERTION_FIELDS

    assert set(ASSERTION_FIELDS["never_high"]) == {"kind", "signal"}
    with pytest.raises(Exception, match="unsupported field"):
        TestPlan.model_validate(
            {
                "design": "mod10_counter",
                "objective": "check",
                "vectors": [{"name": "v1", "inputs": {"enable": 1}, "cycles": 1, "expected": {}}],
                "assertions": [{"kind": "never_high", "signal": "full", "cycles": 1}],
            }
        )
