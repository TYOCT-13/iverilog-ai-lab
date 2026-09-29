"""策略实验的预算/归一化/计分——**全部用离线负例**，不跑模型也不跑仿真。

路线图的要求是"先用离线负例证明预算、失败计分、检查数量和汇总逻辑正确，再进行正式模型
实验"。这里的每一组负例都对应一个真实发生过的错误口径：

- 生成失败让变体行消失，分母跟着缩小（`conventions-ab` 里 132 个请求全失败，
  报告显示 `defects_total: 0, detection_rate: 0.0`，看起来"跑完了"）；
- `compile_failed` 不算不可判定（`strategy-smoke2` 60/60 编译失败，不可判定数为 0）；
- 正确参考设计自己报了 10~11 条功能不一致，而那几轮的变体仍被记成"检出"；
- 同案例三组实际跑的周期数不同（fixed 4 / random 12 / ai 12 / online 18）。
"""
from __future__ import annotations

import pytest

from iverilog_ai.core.strategy_scoring import (
    REASON_COMPILE_FAILED,
    REASON_MISSING,
    REASON_REFERENCE_FALSE_ALARM,
    REASON_TIMEOUT,
    REASON_ZERO_COMPARABLE_CHECKS,
    budget_for,
    classify_undecidable,
    normalize_vectors,
    plan_cycles,
    summarize,
)

PAIRS = [("pwm", "duty_off_by_one"), ("pwm", "pwm_stuck_low"), ("sync_fifo", "full_early")]
STRATEGIES = ["fixed", "random", "ai"]


def _row(strategy, case, variant, seed, *, defects=False, status="passed_with_warnings",
         checks=5, warn=0, hard=0, check_count=None):
    return {
        "strategy": strategy,
        "case": case,
        "variant": variant,
        "seed": seed,
        "status": status,
        "defects_found": defects,
        "check_count": checks if check_count is None else check_count,
        "warning_failures": warn,
        "error_failures": hard,
        "plan_valid": True,
    }


def _complete(strategy, *, seeds=1, detected=(), **kwargs):
    """构造一份"正常跑完"的行集合：参考 + 三个变体 × 轮数。"""

    rows = []
    for seed in range(seeds):
        rows.append(_row(strategy, "pwm", "reference", seed, defects=False, status="passed"))
        rows.append(_row(strategy, "sync_fifo", "reference", seed, defects=False, status="passed"))
        for index, (case, variant) in enumerate(PAIRS):
            rows.append(
                _row(strategy, case, variant, seed, defects=(case, variant) in detected, **kwargs)
            )
    return rows


# ------------------------------------------------------------------ 预算

def test_budget_is_per_case_and_pre_declared():
    """预算按案例预先确定，且同案例与策略无关。"""

    uart = budget_for("uart_tx")
    pwm = budget_for("pwm")
    assert uart.cycles == 40 and "整帧" in uart.rationale
    assert pwm.cycles == 32
    assert uart.cycles != pwm.cycles, "不同案例的预算本来就该不同（UART 要整帧）"
    assert budget_for("没登记过的案例").cycles > 0


def test_uart_budget_covers_a_whole_frame():
    """UART 的预算必须真的够一帧，否则所有策略都测不到东西。"""

    # 起始位 + 8 数据位 + 停止位 = 10 位，每位 4 个时钟（CLKS_PER_BIT=4）
    assert budget_for("uart_tx").cycles >= 10 * 4


# ------------------------------------------------------------ 归一化

def test_short_plan_is_padded_by_holding_the_final_state():
    vectors = [
        {"name": "a", "inputs": {"x": 1}, "cycles": 2, "expected": {}},
        {"name": "b", "inputs": {"x": 0}, "cycles": 1, "expected": {}},
    ]
    plan = normalize_vectors(vectors, 10)
    assert plan.original_cycles == 3
    assert plan.normalized_cycles == 10
    assert plan.action == "padded"
    assert [v["inputs"] for v in plan.vectors] == [{"x": 1}, {"x": 0}, {"x": 0}]
    assert plan.vectors[-1]["cycles"] == 7
    # 补齐不新增期望值：它只是把末态多保持几拍
    assert plan.vectors[-1]["expected"] == {}
    # 原计划没有被就地修改
    assert vectors[1]["cycles"] == 1


def test_long_plan_is_truncated_from_the_tail_and_timing_is_preserved():
    vectors = [
        {"name": "a", "inputs": {"x": 1}, "cycles": 3, "expected": {}},
        {"name": "b", "inputs": {"x": 0}, "cycles": 5, "expected": {}},
        {"name": "c", "inputs": {"x": 1}, "cycles": 4, "expected": {}},
    ]
    plan = normalize_vectors(vectors, 6)
    assert plan.normalized_cycles == 6
    assert plan.action == "truncated"
    # 前面的输入时序一字不改；跨越边界的最后一条按剩余周期缩短
    assert [(v["inputs"]["x"], v["cycles"]) for v in plan.vectors] == [(1, 3), (0, 3)]
    assert plan.vectors[-1]["truncated_from"] == 5


def test_three_strategies_end_up_with_the_same_total_cycles():
    """不公平的根源就是这里：旧实现 fixed=4 / random=12 / ai=12 / online=18。"""

    hand_written = [{"name": "v1", "inputs": {"d": 1}, "cycles": 1} for _ in range(4)]
    random_like = [{"name": f"r{i}", "inputs": {"d": i}, "cycles": 1} for i in range(12)]
    model_like = [{"name": f"m{i}", "inputs": {"d": i}, "cycles": 2} for i in range(9)]
    budget = budget_for("pwm").cycles
    totals = {
        plan_cycles(normalize_vectors(plan, budget).vectors)
        for plan in (hand_written, random_like, model_like)
    }
    assert totals == {budget}


def test_empty_plan_is_rejected():
    with pytest.raises(ValueError):
        normalize_vectors([], 10)


# ------------------------------------------------------------ 不可判定原因

@pytest.mark.parametrize(
    ("status", "kwargs", "expected"),
    [
        ("compile_failed", {}, REASON_COMPILE_FAILED),
        ("timeout", {}, REASON_TIMEOUT),
        ("inconclusive", {"check_count": 0}, REASON_ZERO_COMPARABLE_CHECKS),
        (None, {}, "illegal_plan"),
    ],
)
def test_states_that_must_be_undecidable(status, kwargs, expected):
    assert classify_undecidable(status, **kwargs) == expected


def test_a_clean_row_is_decidable():
    assert classify_undecidable("passed", check_count=3) is None
    assert classify_undecidable("passed_with_warnings", defects_found=True, check_count=3) is None


def test_zero_check_row_is_undecidable_even_when_status_says_passed():
    """status=passed 但一条检查都没做：不能拿来判"通过"。"""

    assert classify_undecidable("passed", check_count=0, defects_found=False) == REASON_ZERO_COMPARABLE_CHECKS


# ------------------------------------------------------------ 汇总（负例）

def test_denominator_is_pre_fixed_even_when_every_run_fails():
    """132 个请求全失败的历史事故：分母不能变成 0。"""

    rows = [_row("ai", "pwm", "plan_generation", seed, status="inconclusive", defects=False, checks=None)
            for seed in range(3)]
    summary = summarize(rows, pairs=PAIRS, strategies=["ai"], rounds={"ai": 3})["ai"]
    assert summary["defects_total"] == len(PAIRS), "分母来自清单，不来自实际产出的行"
    assert summary["defects_found"] == 0
    assert summary["detection_rate"] == 0.0
    assert summary["undecidable_by_reason"][REASON_MISSING] == len(PAIRS) * 3


def test_missing_rows_are_counted_as_undecidable_not_dropped():
    """模型请求失败时变体行消失了——旧口径直接把它们从分母里删掉。"""

    rows = [_row("ai", "pwm", "duty_off_by_one", 0, defects=True)]
    summary = summarize(rows, pairs=PAIRS, strategies=["ai"], rounds={"ai": 1})["ai"]
    assert summary["defects_total"] == len(PAIRS)
    assert summary["defects_found"] == 1
    assert summary["detection_rate"] == pytest.approx(1 / 3)
    # 缺的那两条按未检出计入，并且明确记成"缺失"
    assert summary["undecidable_by_reason"][REASON_MISSING] == 2


def test_compile_failed_counts_as_undecidable():
    """strategy-smoke2 的事故：60/60 编译失败，不可判定数却是 0。"""

    rows = _complete("ai", seeds=1, status="compile_failed", checks=None)
    summary = summarize(rows, pairs=PAIRS, strategies=["ai"], rounds={"ai": 1})["ai"]
    assert summary["undecidable_runs"] >= len(PAIRS)
    assert summary["undecidable_by_reason"][REASON_COMPILE_FAILED] >= len(PAIRS)
    assert summary["defects_found"] == 0


def test_reference_false_alarm_invalidates_that_rounds_detections():
    """参考设计自己报了功能不一致，那几轮的"检出"不算有效检出。"""

    rows = []
    # 第 0 轮：参考设计报了 10 条功能不一致
    rows.append(_row("ai", "pwm", "reference", 0, warn=10, status="passed_with_warnings"))
    rows.append(_row("ai", "sync_fifo", "reference", 0, status="passed"))
    for case, variant in PAIRS:
        rows.append(_row("ai", case, variant, 0, defects=True))
    # 第 1 轮：参考干净，变体真的检出
    rows.append(_row("ai", "pwm", "reference", 1, status="passed"))
    rows.append(_row("ai", "sync_fifo", "reference", 1, status="passed"))
    for case, variant in PAIRS:
        rows.append(_row("ai", case, variant, 1, defects=True))

    summary = summarize(rows, pairs=PAIRS, strategies=["ai"], rounds={"ai": 2})["ai"]
    assert summary["reference_warn_mismatches"] == 1
    assert summary["alarming_plans"] == 1
    # 只有 pwm 那一轮的告警被判无效；sync_fifo 那一轮参考是干净的，它的检出仍然有效
    assert summary["plans_excluded_by_reference_alarm"] == 2, "pwm 的两个变体不算检出"
    # 累计并集：第 1 轮仍然做出了有效检出
    assert summary["defects_found"] == len(PAIRS)
    # 单轮：第 0 轮只剩 sync_fifo 那一条有效（1/3），第 1 轮 3/3 → 平均 2/3。
    # 粒度是"哪个 (案例,轮次) 的参考在乱报"，不是整轮作废。
    assert summary["detection_rate_single_round_mean"] == pytest.approx((1 / 3 + 1.0) / 2)
    assert summary["detection_rate_single_round_min"] == pytest.approx(1 / 3)
    assert summary["detection_rate_single_round_max"] == pytest.approx(1.0)


def test_single_round_and_cumulative_union_are_reported_separately():
    rows = []
    for seed in range(2):
        rows.append(_row("ai", "pwm", "reference", seed, status="passed"))
        rows.append(_row("ai", "sync_fifo", "reference", seed, status="passed"))
    # 第 0 轮只检出 1 个，第 1 轮检出另外 1 个
    rows.append(_row("ai", "pwm", "duty_off_by_one", 0, defects=True))
    rows.append(_row("ai", "pwm", "pwm_stuck_low", 1, defects=True))

    summary = summarize(rows, pairs=PAIRS, strategies=["ai"], rounds={"ai": 2})["ai"]
    assert summary["defects_found"] == 2, "累计并集"
    assert summary["detection_rate"] == pytest.approx(2 / 3)
    assert summary["detection_rate_single_round_mean"] == pytest.approx((1 / 3 + 1 / 3) / 2)


def test_zero_denominator_does_not_report_zero_percent():
    """0/0 不能写成 0.0%——那看起来像"一个都没检出"，而其实是"没东西可算"。"""

    summary = summarize([], pairs=[], strategies=["ai"], rounds={"ai": 1})["ai"]
    assert summary["defects_total"] == 0
    assert summary["detection_rate"] is None
    assert summary["detection_rate_single_round_mean"] is None


def test_three_strategies_are_scored_independently():
    rows = _complete("fixed", seeds=1, detected=PAIRS)
    rows += _complete("random", seeds=1, detected=PAIRS[:1])
    rows += _complete("ai", seeds=1, detected=())
    summary = summarize(rows, pairs=PAIRS, strategies=STRATEGIES, rounds={s: 1 for s in STRATEGIES})
    assert summary["fixed"]["detection_rate"] == pytest.approx(1.0)
    assert summary["random"]["detection_rate"] == pytest.approx(1 / 3)
    assert summary["ai"]["detection_rate"] == pytest.approx(0.0)
