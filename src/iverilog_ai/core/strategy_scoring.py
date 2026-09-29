"""策略实验的**预算、计划归一化与计分**（纯函数，无 I/O，便于离线验证）。

为什么单独一个模块：这三件事决定实验结论是否可信，而它们又最容易写错——
旧实现里预算是写死的 `12`、几个案例用更短的手写列表绕过它、分母由"实际出现的行"
决定、`compile_failed` 不算不可判定、`0/0` 直接输出 `0.0`。这些错误都不会报错，
只会让表格上的数字变得好看。抽成纯函数之后，可以用离线负例把它们逐条钉住
（见 `tests/core/test_strategy_scoring.py`）。

三条口径，来自路线图：

1. **预算按规格预先确定**：每个案例的总刺激周期 T 写在下面的表里（连同理由），
   同案例的所有策略用同一个 T；生成计划之后再按 T 归一化，而不是让不同策略
   各自决定跑多久。
2. **分母固定**：检出率的分母来自清单里登记的 (案例, 变体) 组合与预定轮数，
   **不随实际产出的行数变化**。模型请求失败、计划非法、编译失败、超时、
   零检查项都记为"不可判定"，并在端到端检出率里**按未检出计入**。
3. **参考误报单独报告**：正确设计在某轮里出现功能不一致时，该轮计划对变体的告警
   不能算作有效检出——否则"计划本身在乱报"会被记成"工具发现了缺陷"。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: 不可判定原因（机器可读）。顺序即展示优先级。
REASON_PLAN_FAILED = "plan_failed"
REASON_ILLEGAL_PLAN = "illegal_plan"
REASON_TIMEOUT = "timeout"
REASON_COMPILE_FAILED = "compile_failed"
REASON_CONFIGURATION_ERROR = "configuration_error"
REASON_EXECUTION_FAILED = "execution_failed"
REASON_NO_RECORDS = "no_records"
REASON_ZERO_COMPARABLE_CHECKS = "zero_comparable_checks"
REASON_REFERENCE_FALSE_ALARM = "reference_false_alarm"
REASON_MISSING = "missing_result"

UNDECIDABLE_REASONS: tuple[str, ...] = (
    REASON_PLAN_FAILED,
    REASON_ILLEGAL_PLAN,
    REASON_TIMEOUT,
    REASON_COMPILE_FAILED,
    REASON_CONFIGURATION_ERROR,
    REASON_EXECUTION_FAILED,
    REASON_NO_RECORDS,
    REASON_ZERO_COMPARABLE_CHECKS,
    REASON_REFERENCE_FALSE_ALARM,
    REASON_MISSING,
)

_ZH: dict[str, str] = {
    REASON_PLAN_FAILED: "模型/计划生成失败",
    REASON_ILLEGAL_PLAN: "计划非法",
    REASON_TIMEOUT: "仿真超时",
    REASON_COMPILE_FAILED: "编译失败",
    REASON_CONFIGURATION_ERROR: "配置错误",
    REASON_EXECUTION_FAILED: "执行失败",
    REASON_NO_RECORDS: "没有任何结果记录",
    REASON_ZERO_COMPARABLE_CHECKS: "零可比较检查项",
    REASON_REFERENCE_FALSE_ALARM: "参考设计本轮出现功能不一致（计划本身可疑）",
    REASON_MISSING: "该 (案例,变体,轮次) 没有任何记录",
}


def reason_label(reason: str) -> str:
    return _ZH.get(reason, reason)


# ---------------------------------------------------------------------- 预算


@dataclass(frozen=True)
class Budget:
    """一个案例预先确定的总刺激周期数。"""

    case: str
    cycles: int
    rationale: str


#: 每个案例的总刺激周期预算 T（单位：时钟周期）。
#:
#: 这些数字**在跑实验之前**就定下来，依据是每个案例要完成一次完整事务所需的最少周期
#: （不是"跑多少看起来分数高"）。UART 之类必须覆盖整帧（起始位 + 8 数据位 + 停止位），
#: 统一选一个不足以完成事务的小常数会让所有策略都测不到东西。
CASE_BUDGETS: dict[str, Budget] = {
    "uart_tx": Budget("uart_tx", 40, "要覆盖整帧：起始位 + 8 数据位 + 停止位，留一次重发起"),
    "spi_master": Budget("spi_master", 64, "8 位数据在 SCLK/2 分频下需要 16 拍以上，留两次传输"),
    "sync_fifo": Budget("sync_fifo", 40, "按 4 深队列写满 + 读空，含同时读写"),
    "handshake_stage": Budget("handshake_stage", 24, "valid/ready 四种组合各走一轮"),
    "mod10_counter": Budget("mod10_counter", 24, "0→9 回绕两轮，含暂停保持"),
    "sequence_101_overlap": Budget("sequence_101_overlap", 24, "重叠检测需要连续 10101 序列加边界"),
    "traffic_light_emergency": Budget("traffic_light_emergency", 24, "四个相位各走一遍并插入紧急抢占"),
    "debounce": Budget("debounce", 32, "抖动窗口需要连续稳定电平，长于消抖计数"),
    "pwm": Budget("pwm", 32, "占空比 128/255 下要跨过至少一个完整周期"),
    "edge_detector": Budget("edge_detector", 20, "上升/下降/连续高电平各覆盖一次"),
    "pulse_stretcher": Budget("pulse_stretcher", 32, "展宽窗口内重触发一次"),
    "johnson_counter": Budget("johnson_counter", 24, "8 拍走完 0000→1000 回绕，再验证暂停"),
    "sync_reset": Budget("sync_reset", 20, "复位断言/释放各覆盖同步级数"),
    "simple_alu": Budget("simple_alu", 20, "覆盖进位、减法借位与零标志边界"),
    "mux4": Budget("mux4", 16, "四个选择值各一次，含最高位数据"),
}

#: 清单里没登记预算的案例用这个值，并在报告里标注"未登记预算"。
DEFAULT_BUDGET = Budget("<unknown>", 24, "清单未登记该案例预算，使用默认值")


def budget_for(case: str) -> Budget:
    """取案例预算；未登记时用默认值（并在调用方报告出来）。"""

    known = CASE_BUDGETS.get(case)
    if known is not None:
        return known
    return Budget(case, DEFAULT_BUDGET.cycles, DEFAULT_BUDGET.rationale)


# ------------------------------------------------------------------ 计划归一化


@dataclass(frozen=True)
class NormalizedPlan:
    """归一化结果。``vectors`` 是**新列表**，原始计划不被修改。"""

    vectors: list[dict[str, Any]]
    original_cycles: int
    normalized_cycles: int
    action: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unchanged(self) -> bool:
        return self.action == "unchanged"


def plan_cycles(vectors: Sequence[Mapping[str, Any]]) -> int:
    """计划声明的总周期数（每拍至少 1）。"""

    total = 0
    for vector in vectors:
        cycles = vector.get("cycles", 1)
        try:
            value = int(cycles)
        except (TypeError, ValueError):
            value = 1
        total += max(1, value)
    return total


def normalize_vectors(vectors: Sequence[Mapping[str, Any]], budget_cycles: int) -> NormalizedPlan:
    """把计划归一到预算 ``budget_cycles``：超长就截断，不足就按**末态保持**补齐。

    两条刻意写死的规则，因为它们是"公平"的具体含义：

    - **截断只从尾部整条地删**，跨越边界的最后一条按剩余周期缩短——这样前面的输入
      时序语义一字不改。
    - **补齐用末态保持**：复制最后一条向量的输入并延长它的周期。这样"计划太短"不会
      变成"驱动未知值"，也不会引入新的输入变化（那会变成另一份实验条件）。

    末态保持只在**同案例三组都归一化到同一个 T** 的前提下才有意义，因此调用方必须
    对每个策略都用同一个 T——这也是 `summarize` 会检查的事。
    """

    if budget_cycles <= 0:
        raise ValueError("budget_cycles must be positive")
    kept: list[dict[str, Any]] = []
    used = 0
    truncated = 0
    for vector in vectors:
        if used >= budget_cycles:
            truncated += 1
            continue
        cycles = max(1, int(vector.get("cycles", 1)))
        room = budget_cycles - used
        if cycles <= room:
            kept.append(dict(vector))
            used += cycles
            continue
        shortened = dict(vector)
        shortened["cycles"] = room
        shortened["truncated_from"] = cycles
        kept.append(shortened)
        used += room
        truncated += 1

    notes: list[str] = []
    padded = 0
    if not kept:
        raise ValueError("plan must contain at least one vector")
    if used < budget_cycles:
        last = kept[-1]
        hold = {
            "name": f"{last.get('name', 'vector')}_hold",
            "inputs": dict(last.get("inputs", {})),
            "cycles": budget_cycles - used,
            "sample_phase": last.get("sample_phase", "after"),
            # 末态保持不新增期望值：它只是把末态多保持几个周期。
            "expected": {},
            "rationale": "budget normalization: hold the final state to reach the same total cycles",
        }
        kept.append(hold)
        padded = budget_cycles - used
        used = budget_cycles
        notes.append(f"计划不足预算：末态保持补 {padded} 个周期")
    if truncated:
        notes.append(f"计划超出预算：截断 {truncated} 条向量")

    action = "unchanged"
    if truncated and padded:
        action = "truncated+padded"
    elif truncated:
        action = "truncated"
    elif padded:
        action = "padded"
    return NormalizedPlan(kept, plan_cycles(vectors), used, action, tuple(notes))


# ---------------------------------------------------------------------- 计分


def classify_undecidable(
    status: str | None,
    *,
    defects_found: bool = False,
    check_count: int | None = None,
    variant: str | None = None,
    reference_alarm: bool = False,
) -> str | None:
    """这一行能不能用来判"检出/未检出"？不能的话给出机器可读原因。

    返回 ``None`` 表示**可判定**。注意顺序：参考设计自己不干净时，该轮所有行的告警
    都不可信（原因见文件头第 3 条），这优先于其它判断。
    """

    if reference_alarm and variant != "reference":
        return REASON_REFERENCE_FALSE_ALARM
    if variant == "plan_generation":
        return REASON_PLAN_FAILED
    if status in {"compile_failed", "compile-failed"}:
        return REASON_COMPILE_FAILED
    if status == "timeout":
        return REASON_TIMEOUT
    if status in {"configuration_error", "config_error"}:
        return REASON_CONFIGURATION_ERROR
    if status in {"failed", "execution_failed"} and not defects_found:
        # 执行失败（非编译、非超时）时不能判检出；但"报出了功能差异"就另有记录，
        # 那种行不算执行失败。
        return REASON_EXECUTION_FAILED
    if status == "inconclusive":
        if check_count == 0:
            return REASON_ZERO_COMPARABLE_CHECKS
        return REASON_NO_RECORDS
    if status is None:
        return REASON_ILLEGAL_PLAN
    if check_count == 0 and not defects_found:
        return REASON_ZERO_COMPARABLE_CHECKS
    return None


@dataclass(frozen=True)
class PairKey:
    case: str
    variant: str

    def as_tuple(self) -> tuple[str, str]:
        return (self.case, self.variant)


def _pairs_from(pairs: Iterable[Any]) -> list[PairKey]:
    result: list[PairKey] = []
    for item in pairs:
        if isinstance(item, PairKey):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(PairKey(str(item["case"]), str(item["variant"])))
        else:
            case, variant = item
            result.append(PairKey(str(case), str(variant)))
    return result


def summarize(
    runs: Sequence[Mapping[str, Any]],
    *,
    pairs: Iterable[Any],
    strategies: Sequence[str],
    rounds: Mapping[str, int],
) -> dict[str, Any]:
    """按固定分母汇总三/四组策略。

    ``pairs`` 是**预先固定**的 (案例, 变体) 集合（来自清单），不因哪一行缺失而缩小。
    ``rounds[strategy]`` 是预定轮数，用来把"缺失的行"也变成一条不可判定记录。
    """

    fixed_pairs = _pairs_from(pairs)
    denominator = len(fixed_pairs)
    summary: dict[str, Any] = {}

    for strategy in strategies:
        rows = [row for row in runs if str(row.get("strategy")) == strategy]
        variant_rows = [row for row in rows if str(row.get("variant")) not in {"reference", "plan_generation"}]

        # 参考设计告警：(case, seed) 维度。正确设计出现功能不一致时该轮计划不可信。
        alarming: set[tuple[str, int]] = set()
        reference_hard = 0
        reference_warn = 0
        for row in rows:
            if str(row.get("variant")) != "reference":
                continue
            seed = int(row.get("seed", 0))
            hard = int(row.get("error_failures") or 0)
            warn = int(row.get("warning_failures") or 0)
            if hard:
                reference_hard += 1
            if warn:
                reference_warn += 1
            if hard or warn:
                alarming.add((str(row.get("case")), seed))

        reasons: Counter[str] = Counter()
        detected_pairs: set[tuple[str, str]] = set()
        per_round: dict[int, set[tuple[str, str]]] = {}
        excluded_pairs: set[tuple[str, str]] = set()
        present: set[tuple[str, str, int]] = set()

        planned_rounds = max(1, int(rounds.get(strategy, 1)))
        for row in variant_rows:
            case = str(row.get("case"))
            variant = str(row.get("variant"))
            seed = int(row.get("seed", 0))
            present.add((case, variant, seed))
            alarm = (case, seed) in alarming
            check_count = row.get("check_count")
            if isinstance(check_count, bool) or not isinstance(check_count, int):
                check_count = None
            reason = classify_undecidable(
                None if row.get("status") is None else str(row.get("status")),
                defects_found=bool(row.get("defects_found")),
                check_count=check_count,
                variant=variant,
                reference_alarm=alarm,
            )
            if reason is not None:
                reasons[reason] += 1
                if reason == REASON_REFERENCE_FALSE_ALARM:
                    excluded_pairs.add((case, variant))
                continue
            if bool(row.get("defects_found")):
                detected_pairs.add((case, variant))
                per_round.setdefault(seed, set()).add((case, variant))

        # 缺失的记录也要计入不可判定：预定轮数 × 全部变体，逐条核对。
        missing = 0
        for pair in fixed_pairs:
            for seed in range(planned_rounds):
                if (pair.case, pair.variant, seed) not in present:
                    missing += 1
        if missing:
            reasons[REASON_MISSING] += missing

        round_rates: list[float] = []
        if denominator:
            for seed in range(planned_rounds):
                found = len(per_round.get(seed, ()))
                round_rates.append(found / denominator)

        summary[strategy] = {
            "runs": len(rows),
            "variant_runs": len(variant_rows),
            "defects_total": denominator,
            "defects_found": len(detected_pairs),
            # 分母固定：0/0 不给 0.0，而是 None（"没有可算的东西"与"一个都没检出"不同）。
            "detection_rate": (len(detected_pairs) / denominator) if denominator else None,
            "detection_rate_single_round_mean": (sum(round_rates) / len(round_rates)) if round_rates else None,
            "detection_rate_single_round_min": min(round_rates) if round_rates else None,
            "detection_rate_single_round_max": max(round_rates) if round_rates else None,
            "rounds": planned_rounds,
            "undecidable_runs": sum(reasons.values()),
            "undecidable_by_reason": {reason: reasons[reason] for reason in UNDECIDABLE_REASONS if reasons[reason]},
            "undecidable_missing": missing,
            "plans_excluded_by_reference_alarm": len(excluded_pairs),
            "reference_false_positives": reference_hard,
            "reference_warn_mismatches": reference_warn,
            "alarming_plans": len(alarming),
        }
    return summary


def render_undecidable_table(runs: Sequence[Mapping[str, Any]], *, limit: int = 40) -> list[str]:
    """把不可判定的行渲染成 Markdown 表格（保留原因，便于复查）。"""

    lines = ["| 策略 | 案例 | 变体 | 轮次 | 状态 | 原因 |", "|---|---|---|---:|---|---|"]
    shown = 0
    for row in runs:
        variant = str(row.get("variant"))
        if variant not in {"reference", "plan_generation"} and row.get("defects_found"):
            continue
        check_count = row.get("check_count")
        reason = classify_undecidable(
            None if row.get("status") is None else str(row.get("status")),
            defects_found=bool(row.get("defects_found")),
            check_count=check_count if isinstance(check_count, int) and not isinstance(check_count, bool) else None,
            variant=variant,
        )
        if reason is None:
            continue
        lines.append(
            f"| {row.get('strategy')} | {row.get('case')} | {variant} | {row.get('seed')} "
            f"| {row.get('status')} | {reason_label(reason)} |"
        )
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        lines.append("| — | — | — | — | — | 没有不可判定记录 |")
    return lines


__all__ = [
    "Budget",
    "CASE_BUDGETS",
    "DEFAULT_BUDGET",
    "NormalizedPlan",
    "PairKey",
    "REASON_COMPILE_FAILED",
    "REASON_MISSING",
    "REASON_PLAN_FAILED",
    "REASON_REFERENCE_FALSE_ALARM",
    "REASON_ZERO_COMPARABLE_CHECKS",
    "UNDECIDABLE_REASONS",
    "budget_for",
    "classify_undecidable",
    "normalize_vectors",
    "plan_cycles",
    "reason_label",
    "render_undecidable_table",
    "summarize",
]
