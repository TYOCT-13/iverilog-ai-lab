"""Compare fixed, seeded-random, and offline-AI test-plan strategies.

This experiment uses the same explicit DUT contracts and the same
``VerificationPipeline`` for every run.  Random and AI plans are generated
from deterministic seeds; the AI path still goes through ``plan_tests`` and a
``MockProvider`` so legality is measured independently from simulation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import time
from typing import Any, Literal, Callable, Mapping, Sequence

from iverilog_ai.ai import MockProvider, OpenAICompatibleProvider, plan_tests
from iverilog_ai.ai.provider import Provider
from iverilog_ai.ai.debug_server import build_plan_response
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.reference_model import completed_inputs
from iverilog_ai.core.rules import rules_context, rules_fingerprint
from iverilog_ai.core.strategy_scoring import (
    CASE_BUDGETS,
    budget_for,
    classify_undecidable,
    normalize_vectors,
    plan_cycles,
    render_undecidable_table,
    summarize as summarize_scoring,
)

# 脚本所在仓库根目录；用于按案例定位 examples/<case>_contract.json。
ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_cases(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """从 benchmarks/manifest.json 发现全部案例，并加载各自的显式 DUT 合约。

    案例集合由 manifest 的 categories 决定，而不是脚本里写死的列表：这样基准
    扩展到新案例时，公平比较实验会自动跟着覆盖，不会出现"基准有 12 个案例、
    实验只跑 4 个"的口径错位。

    返回 (可用案例, 被跳过的案例及原因)。纯组合逻辑案例（合约里没有时钟）无法
    用向量式 testbench 表达时序语义，因此不参与本实验，但仍保留在基准矩阵中
    由手写 testbench 覆盖。
    """

    manifest_path = root / "benchmarks" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for case in manifest.get("categories", []):
        contract_rel = f"examples/{case}_contract.json"
        contract_path = root / contract_rel
        if not contract_path.is_file():
            raise SystemExit(f"案例 {case} 缺少合约文件 {contract_rel}")
        rtl_rel = f"rtl/{case}.v"
        if not (root / rtl_rel).is_file():
            raise SystemExit(f"案例 {case} 缺少参考 RTL {rtl_rel}")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if "clock" not in contract:
            skipped[str(case)] = "合约未定义时钟：纯组合逻辑，向量式 testbench 不适用"
            continue
        cases[str(case)] = {"rtl": rtl_rel, "contract": contract}
    if not cases:
        raise SystemExit("benchmarks/manifest.json 没有登记任何可计划化案例")
    return cases, skipped


def _alu(a: int, b: int, op: int) -> dict[str, int]:
    if op == 0:
        value = a + b; return {"result": value & 255, "carry": int(value > 255), "zero": int((value & 255) == 0)}
    if op == 1:
        value = (a - b) & 255; return {"result": value, "carry": int(a >= b), "zero": int(value == 0)}
    if op == 2: value = a & b
    elif op == 3: value = a | b
    elif op == 4: value = a ^ b
    elif op == 5: value = (a << 1) & 255
    elif op == 6: value = a >> 1
    else: value = 0
    return {"result": value, "carry": 0, "zero": int(value == 0)}


def _contract_stimulus(case: str, seed: int, count: int) -> list[dict[str, Any]]:
    """为任意案例生成一组确定性激励（只含 inputs，由预言机负责期望值）。

    激励形状复用本地调试模型服务的取值表：它按案例给出了能走到状态空间边界
    （写满、回绕、位序、门限、占空比边界、同步级数）的输入顺序，因此新案例
    不必在实验脚本里再维护一份重复的激励表。期望值留空——正确性由参考模型与
    Icarus 裁决，这正是本实验要验证的口径。
    """

    contract_rel = ROOT_DIR / "examples" / f"{case}_contract.json"
    contract = json.loads(contract_rel.read_text(encoding="utf-8"))
    prompt = "Design: %s DUT context: %s Schema: {}" % (case, json.dumps(contract, ensure_ascii=False))
    plan = build_plan_response(prompt, vector_count=count, seed=seed)
    return [
        {"name": f"{case}_{seed}_{index}", "inputs": vector["inputs"], "cycles": vector.get("cycles", 1), "expected": {}}
        for index, vector in enumerate(plan["vectors"])
    ]


def _vectors(case: str, seed: int, count: int = 12) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    vectors: list[dict[str, Any]] = []
    if case == "simple_alu":
        for index in range(count):
            a, b, op = rng.randrange(256), rng.randrange(256), rng.randrange(7)
            vectors.append({"name": f"alu_{seed}_{index}", "inputs": {"a": a, "b": b, "op": op}, "expected": _alu(a, b, op)})
    elif case == "mod10_counter":
        value = 0
        for index in range(count):
            enable = rng.randrange(2)
            if enable: value = 0 if value == 9 else value + 1
            vectors.append({"name": f"count_{seed}_{index}", "inputs": {"enable": enable}, "expected": {"count": value}})
    elif case == "sequence_101_overlap":
        history = 0
        for index in range(count):
            bit = rng.randrange(2)
            detected = int(((history << 1) | bit) == 5)
            history = ((history & 1) << 1) | bit
            vectors.append({"name": f"seq_{seed}_{index}", "inputs": {"bit_in": bit}, "expected": {"detected": detected}})
    elif case == "traffic_light_emergency":
        state = 0
        for index in range(count):
            emergency = rng.randrange(2)
            state = 1 if emergency else (state + 1) % 4
            main, side = (1, 0) if emergency else ((2, 0), (1, 0), (0, 2), (0, 1))[state]
            vectors.append({"name": f"traffic_{seed}_{index}", "inputs": {"emergency": emergency}, "expected": {"main_light": main, "side_light": side}})
    else:
        # 其余案例：使用取值表驱动的确定性激励，随机策略用种子区分取值相位。
        vectors = _contract_stimulus(case, seed, count)
    return [_complete_inputs(case, vector) for vector in vectors]


def _complete_inputs(case: str, vector: dict[str, Any]) -> dict[str, Any]:
    """按参考模型的输入默认值补全向量里未列出的输入。

    激励常常只写本拍关心的端口，其余端口靠"保持上一次的值"延续。测试台对未
    赋值的输入端口只有端口初值（0），而模型有自己的默认值——两者不一致时，
    参考设计上会冒出伪失败。这里统一用 ``reference_model.INPUT_DEFAULTS``
    把向量补全，使测试台、模型、对齐测试三方口径一致。
    """

    completed = completed_inputs(case, vector.get("inputs", {}))
    return {**vector, "inputs": completed}


def _fixed(case: str) -> list[dict[str, Any]]:
    if case == "simple_alu":
        values = [(240, 32, 0), (255, 1, 0), (32, 5, 1), (240, 15, 2), (240, 15, 3), (170, 85, 4), (129, 0, 5), (129, 0, 6), (0, 0, 0)]
        return [{"name": f"fixed_{i}", "inputs": {"a": a, "b": b, "op": op}, "expected": _alu(a, b, op)} for i, (a, b, op) in enumerate(values)]
    if case == "mod10_counter":
        vectors = [{"name": "fixed_hold", "inputs": {"enable": 0}, "expected": {"count": 0}}]
        for value in range(1, 10):
            vectors.append({"name": f"fixed_count_{value}", "inputs": {"enable": 1}, "expected": {"count": value}})
        vectors.append({"name": "fixed_wrap", "inputs": {"enable": 1}, "expected": {"count": 0}})
        return vectors
    if case == "sequence_101_overlap":
        history = 0
        vectors = []
        for index, bit in enumerate((1, 0, 0, 1, 0, 1, 0, 1)):
            detected = int(((history << 1) | bit) == 5)
            history = ((history & 1) << 1) | bit
            vectors.append({"name": f"fixed_seq_{index}", "inputs": {"bit_in": bit}, "expected": {"detected": detected}})
        return vectors
    if case == "traffic_light_emergency":
        return [
            {"name": "fixed_emergency_visible", "inputs": {"emergency": 1}, "sample_phase": "before", "expected": {"main_light": 1, "side_light": 0}},
            {"name": "fixed_side_green", "inputs": {"emergency": 0}, "expected": {"main_light": 0, "side_light": 2}},
            {"name": "fixed_side_yellow", "inputs": {"emergency": 0}, "expected": {"main_light": 0, "side_light": 1}},
            {"name": "fixed_main_green", "inputs": {"emergency": 0}, "expected": {"main_light": 2, "side_light": 0}},
        ]
    # 其余案例：固定策略使用取值表的 0 号相位，激励条数与随机策略一致。
    return _contract_stimulus(case, 0, 12)


def _payload(case: str, vectors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "design": case, "objective": f"bounded verification for {case}", "vectors": vectors}


#: 允许出现在计划向量里的字段（归一化会加 `truncated_from` 之类的备注字段，
#: 回填进 TestPlan 之前必须去掉，否则严格 Schema 会拒绝）。
_VECTOR_FIELDS = {"name", "inputs", "cycles", "sample_phase", "expected", "rationale"}


def _plan_with_vectors(plan: Any, vectors: Sequence[Mapping[str, Any]]) -> Any:
    """用归一化后的向量重建 TestPlan（校验照旧执行）。"""

    from iverilog_ai.ai.schema import TestPlan

    payload = json.loads(plan.model_dump_json())
    payload["vectors"] = [
        {key: value for key, value in vector.items() if key in _VECTOR_FIELDS} for vector in vectors
    ]
    return TestPlan.model_validate(payload)


def _row_payload(
    *,
    strategy: str,
    case: str,
    variant: str,
    seed: int,
    request_id: str,
    budget_cycles: int,
    vectors: Any,
    plan_valid: bool,
    plan_sha256: str,
    plan_raw_sha256: str,
    generation_ms: int | None,
    usage: Any,
    attempts: int,
    compile_ms: int | None,
    sim_ms: int | None,
    time_to_first_failure_ms: int | None,
    records_pass: int,
    failures: int,
    warning_failures: int,
    error_failures: int,
    check_count: int | None,
    total_cycles: int,
    model: str | None,
    endpoint: str | None,
    prompt_sha256: str,
    status: str,
    reason: str | None,
    defect_found: bool,
    error_msg: str | None,
    artifacts: Mapping[str, str],
    expectation_source: str | None,
    ai_expected_checked: Any,
    ai_expected_matched: Any,
) -> dict[str, Any]:
    """一行实验结果。字段名与旧矩阵保持兼容（只做加法）。"""

    vector_count = vectors if isinstance(vectors, int) else len(vectors)
    row: dict[str, Any] = {
        "strategy": strategy,
        "case": case,
        "variant": variant,
        "seed": seed,
        "request_id": request_id,
        "budget_s": 30.0,          # 兼容旧字段：仿真超时上限（秒）
        "budget_cycles": budget_cycles,
        "vectors": vector_count,
        "total_cycles": total_cycles,
        "plan_valid": plan_valid,
        "plan_sha256": plan_sha256,
        "plan_raw_sha256": plan_raw_sha256,
        "generation_ms": generation_ms,
        "usage": usage,
        "attempts": attempts,
        "model": model,
        "endpoint": endpoint,
        "prompt_sha256": prompt_sha256,
        "compile_ms": compile_ms,
        "sim_ms": sim_ms,
        "time_to_first_failure_ms": time_to_first_failure_ms,
        "records_pass": records_pass,
        "failures": failures,
        "warning_failures": warning_failures,
        "error_failures": error_failures,
        "check_count": check_count,
        "defects_found": defect_found,
        "expectation_source": expectation_source,
        "ai_expected_checked": ai_expected_checked,
        "ai_expected_matched": ai_expected_matched,
        "status": status,
        "artifact_path": artifacts.get("run_dir", ""),
        "artifact_paths": dict(artifacts),
    }
    row["undecidable_reason"] = classify_undecidable(
        status, defects_found=defect_found, check_count=check_count, variant=variant
    )
    if reason is not None:
        row["undecidable_reason"] = reason
    if error_msg:
        row["error"] = error_msg
    return row


def _progress_text(done: int, total: int, started: float) -> str:
    elapsed = time.perf_counter() - started
    percent = (100.0 * done / total) if total else 100.0
    eta = (elapsed / done * (total - done)) if done else None
    eta_text = f"；预计剩余 {eta:.1f}s" if eta is not None else ""
    return f"进度 {done}/{total}（{percent:.1f}%）；已耗时 {elapsed:.1f}s{eta_text}"


def _code_revision(root: Path) -> tuple[str, bool]:
    """取当前代码版本与"工作区是否脏"。

    路线图明确要求记录**代码版本及未提交差异**：换一个版本标签不算重跑实验，
    而没有 commit 的改动意味着别人无法从哈希复现这次实验。
    取不到 git 时返回 ("unknown", False)——如实标注未知，不假装干净。
    """

    import subprocess

    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        if head.returncode != 0:
            return ("unknown", False)
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=15
        )
        return (head.stdout.strip(), bool(status.stdout.strip()))
    except (OSError, ValueError):
        return ("unknown", False)


def _write_experiment_report(path: Path, payload: dict[str, Any], *, endpoint: str | None, model: str | None) -> None:
    """Write a human-readable, auditable summary without secrets or raw prompts."""
    lines = [
        "# Icarus 智测策略实验报告", "",
        f"- 开始时间：`{payload['started_at']}`",
        f"- 结束时间：`{payload['finished_at']}`",
        f"- 总耗时：`{payload['duration_ms'] / 1000:.1f}s`",
        f"- 完成任务：`{payload['completed_units']}/{payload['total_units']}`",
        f"- 代码版本：`{payload.get('code_revision', 'unknown')}`"
        + ("（**工作区有未提交改动**：本次结果无法仅凭 commit 复现）" if payload.get("working_tree_dirty") else ""),
        f"- 在线端点：`{endpoint or '未启用'}`",
        f"- 在线模型：`{model or '未启用'}`", "",
        "> API Key、原始提示词和模型响应正文不会写入本报告。", "",
        "## 验证规则版本", "",
    ]
    for case, info in payload.get("rule_sets", {}).items():
        lines.append(f"- `{case}`：规则集指纹 `{info.get('fingerprint', '')}`")
        for item in info.get("files", []):
            lines.append(f"  - `{item['file']}`：`{item['sha256']}`")
    lines.extend(["",
        "## 汇总指标", "",
        "| 策略 | 模型请求数 | 请求级合法率 | 参考误报(硬失败) | 参考设计期望值不一致 | 缺陷总数 | 缺陷检出(累计并集) | 单轮平均检出率 | 单轮范围 | 不可判定 | 因参考告警作废 | 平均生成(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ])
    for strategy, item in payload["summary"].items():
        accuracy = item.get("ai_expected_accuracy")
        generation = item.get("mean_generation_ms")
        rate = item.get("detection_rate")
        single = item.get("detection_rate_single_round_mean")
        low, high = item.get("detection_rate_single_round_min"), item.get("detection_rate_single_round_max")
        # 0/0 不能写成 0.0%：那是"没有可算的东西"，与"一个都没检出"是两件事。
        rate_text = "n/a" if rate is None else f"{rate * 100:.1f}%"
        single_text = "n/a" if single is None else f"{single * 100:.1f}%"
        range_text = "n/a" if low is None or high is None else f"{low * 100:.0f}%~{high * 100:.0f}%"
        generation_text = "-" if generation is None else f"{generation:.1f}"
        lines.append(
            f"| {strategy} | {item.get('plan_requests', 0)} | "
            f"{item.get('request_plan_valid_rate', 0) * 100:.1f}% | "
            f"{item.get('reference_false_positives', 0)} | "
            f"{item.get('reference_warn_mismatches', 0)} | "
            f"{item.get('defects_total', 0)} | "
            f"{item.get('defects_found', 0)} | {single_text} | {range_text} | "
            f"{item.get('undecidable_runs', 0)} | "
            f"{item.get('plans_excluded_by_reference_alarm', 0)} | {generation_text} |"
        )
        if accuracy is not None:
            lines.append(
                f"| ↳ {strategy} 期望值口径 | 检查项 {item.get('ai_expected_checked', 0)} | "
                f"AI 期望值准确率 {accuracy * 100:.1f}% | | | | | | | | | |"
            )
    lines.extend([
        "",
        "### 指标口径说明",
        "",
        "- **缺陷总数（分母）**：来自 `benchmarks/manifest.json` 登记的 (案例, 缺陷变体) 组合，"
        "**在跑实验之前就固定**。它不随实际产出的行变化——否则请求失败会让分母一起缩小，检出率反而变好看。",
        "- **缺陷检出(累计并集)**：多轮跑完后，被检出过的 (案例, 变体) 去重计数。",
        "- **单轮平均检出率**：先按轮次各算一次，再取平均；累计并集不能与单轮直接比较"
        "（同一案例的多个变体也不是彼此独立的大样本）。",
        "- **不可判定**：计划生成失败、计划非法、编译失败、超时、零可比较检查项，"
        "以及「预定轮次里缺失的记录」。它们**按未检出计入**端到端检出率，理由见 `undecidable_by_reason`。",
        "- **因参考告警作废**：某一轮的**参考设计**自己出现了功能不一致（硬失败或期望值不一致）时，"
        "该轮计划对变体的告警不算有效检出——否则「计划本身在乱报」会被记成「工具发现了缺陷」。"
        "作废的是那个 (案例,轮次)，不是整轮。",
        "- **同一刺激预算 ≠ 同一端到端成本**：三组策略的**总周期数**按案例统一（见 `budget_cycles`），"
        "但生成时间、重试次数与费用单列，不参与检出率。",
        "- **参考误报(硬失败)**：参考设计上出现 `severity=error` 的失败反例，属于工具缺陷。",
        "- **参考设计期望值不一致**：参考设计上出现 `severity=warn` 的失败反例，等价于「AI 期望值判断错误」，是诊断指标而非工具缺陷。",
        "- **AI 期望值准确率**：内置案例的期望值由独立参考模型复算并作为权威预言机；该比率衡量 AI 自己写的期望值中有多少与参考模型一致。",
        "- 当某个策略产出的计划**不写任何期望值**时（例如本地调试模型只施加激励），该比率为空 `n/a`：没有可比对的 AI 数字，不代表准确率为零。",
    ])
    lines.extend(["", "## 不可判定和错误记录", ""])
    lines.extend(render_undecidable_table(payload["runs"]))
    missing = [
        (strategy, item.get("undecidable_missing", 0))
        for strategy, item in payload["summary"].items()
        if item.get("undecidable_missing")
    ]
    if missing:
        lines.extend([
            "",
            "缺失记录（预定了轮次但没有任何行）——按未检出计入：",
            "",
            "| 策略 | 缺失条数 |",
            "|---|---:|",
        ])
        for strategy, count in missing:
            lines.append(f"| {strategy} | {count} |")
    lines.extend(["", "## 逐次结果", "", "逐次机器可读记录位于同目录的 `strategy_matrix.json`；其中包含每次运行的计划哈希（原始与归一化）、生成耗时、重试次数、编译/仿真耗时、warn/error 计数、实际总周期与检查项数、不可判定原因和全部证据路径。", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summarize(
    rows: list[dict[str, Any]],
    strategies: list[str],
    *,
    pairs: Sequence[tuple[str, str]],
    rounds: Mapping[str, int],
) -> dict[str, Any]:
    """按策略汇总逐次记录：中途落盘与最终写盘共用同一份口径。

    计分口径全部交给 `core.strategy_scoring`（纯函数、有离线负例），这里只负责把
    脚本侧的行结构喂进去、再补上报告需要的旧字段。**分母来自清单**（`pairs`），
    不来自实际产出的行——否则"跑失败"会让分母缩小，检出率反而变好看。
    """

    scoring = summarize_scoring(rows, pairs=pairs, strategies=strategies, rounds=rounds)
    summary: dict[str, Any] = {}
    for strategy in strategies:
        selected = [row for row in rows if row["strategy"] == strategy]
        refs = [row for row in selected if row["variant"] == "reference"]
        defects = [row for row in selected if row["variant"] not in {"reference", "plan_generation"}]
        valid_runs = sum(1 for row in selected if row["plan_valid"])
        request_rows: dict[str, dict[str, Any]] = {}
        for row in selected:
            request_rows.setdefault(row["request_id"], row)
            if not row.get("plan_valid", False):
                request_rows[row["request_id"]] = row
        # 显式转成 int 列表：`row.get(...)` 的静态类型是 Any | None，
        # 直接求和会让"均值"这条统计在类型层面不可信（也可能混进 None）。
        generation_times = [
            int(row["generation_ms"])
            for row in request_rows.values()
            if isinstance(row.get("generation_ms"), int)
        ]
        ai_checked = sum(int(row.get("ai_expected_checked") or 0) for row in selected)
        ai_matched = sum(int(row.get("ai_expected_matched") or 0) for row in selected)
        valid_requests = sum(bool(row.get("plan_valid")) for row in request_rows.values())
        scored = scoring[strategy]
        summary[strategy] = {
            "runs": len(selected),
            "plan_requests": len(request_rows),
            "valid_plan_requests": valid_requests,
            "request_plan_valid_rate": valid_requests / len(request_rows) if request_rows else 0.0,
            "plan_valid": all(row["plan_valid"] for row in selected),
            "plan_valid_runs": valid_runs,
            "plan_total_runs": len(selected),
            "plan_valid_rate": valid_runs / len(selected) if selected else 0.0,
            "reference_false_positives": scored["reference_false_positives"],
            "reference_warn_mismatches": scored["reference_warn_mismatches"],
            "reference_alarming_plans": scored["alarming_plans"],
            "plans_excluded_by_reference_alarm": scored["plans_excluded_by_reference_alarm"],
            "ai_expected_checked": ai_checked,
            "ai_expected_matched": ai_matched,
            "ai_expected_accuracy": (ai_matched / ai_checked) if ai_checked else None,
            "defects_total": scored["defects_total"],
            "defects_found": scored["defects_found"],
            "detection_rate": scored["detection_rate"],
            "detection_rate_single_round_mean": scored["detection_rate_single_round_mean"],
            "detection_rate_single_round_min": scored["detection_rate_single_round_min"],
            "detection_rate_single_round_max": scored["detection_rate_single_round_max"],
            "rounds": scored["rounds"],
            "undecidable_runs": scored["undecidable_runs"],
            "undecidable_by_reason": scored["undecidable_by_reason"],
            "undecidable_missing": scored["undecidable_missing"],
            "inconclusive_runs": sum(1 for row in selected if row["status"] == "inconclusive"),
            "mean_generation_ms": (sum(generation_times) / len(generation_times) if generation_times else None),
            "mean_time_to_first_failure_ms": (sum(int(row["time_to_first_failure_ms"] or 0) for row in defects if row.get("time_to_first_failure_ms") is not None) / max(1, sum(1 for row in defects if row.get("time_to_first_failure_ms") is not None))),
        }
    return summary


def _build_payload(
    *,
    rows: list[dict[str, Any]],
    summaries: dict[str, Any],
    total_units: int,
    completed_units: int,
    rule_sets: dict[str, Any],
    skipped: dict[str, str],
    started_wall: datetime,
    finished_wall: datetime,
    started_perf: float,
    partial: bool,
    code_revision: str,
    working_tree_dirty: bool,
) -> dict[str, Any]:
    """组装实验记录。

    ``partial=True`` 表示这是一次**中途落盘**（进程仍在跑）：真实模型实验动辄几小时，
    只在最后写一次文件的话，一次中断就会丢掉已经花掉 token 的全部结果。
    """

    return {
        "schema_version": "1.0",
        "partial": partial,
        "started_at": started_wall.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_wall.isoformat().replace("+00:00", "Z"),
        "duration_ms": int((time.perf_counter() - started_perf) * 1000),
        "total_units": total_units,
        "completed_units": completed_units,
        "code_revision": code_revision,
        "working_tree_dirty": working_tree_dirty,
        "rule_sets": rule_sets,
        "skipped_cases": skipped,
        "runs": rows,
        "summary": summaries,
    }


def _write_payload(output: Path, payload: dict[str, Any]) -> None:
    """写盘（先写临时文件再替换，避免读到写了一半的 JSON）。"""

    target = output / "strategy_matrix.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """累计 token 用量（**按请求去重**）：真实模型实验必须能随时看到已经花了多少。

    一次计划请求的计划会被同一案例的所有变体复用，因此每个变体行都挂着同一份
    usage。按行相加会把总量放大到"变体数"倍（实测 13 倍）——成本直接被说高一个
    数量级，而且不会有任何报错。这里按 `request_id` 只记一次。
    """

    totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    seen: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        usage = row.get("usage") or {}
        if not usage:
            continue
        request_id = str(row.get("request_id") or f"row-{index}")
        seen.setdefault(request_id, usage)
    for usage in seen.values():
        totals["requests"] += 1
        totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        totals["total_tokens"] += int(usage.get("total_tokens") or 0)
    return totals


def _main() -> int:
    experiment_started_wall = datetime.now(timezone.utc)
    experiment_started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--iverilog", default=None)
    parser.add_argument("--vvp", default=None)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--online", action="store_true", help="also run a real online model (credentials are read from an environment variable)")
    parser.add_argument("--online-endpoint", default=None, help="OpenAI-compatible HTTPS base URL")
    parser.add_argument("--online-model", default=None)
    parser.add_argument("--online-api-key-env", default="IVERILOG_AI_API_KEY")
    parser.add_argument("--online-repeats", type=int, default=10, help="repetitions per case for online model")
    parser.add_argument(
        "--debug-local",
        action="store_true",
        help="run the online_ai strategy against the local offline debug model instead of a real provider; "
        "requires no API key and no network. Start it with: python -m iverilog_ai.ai.debug_server",
    )
    parser.add_argument(
        "--debug-endpoint",
        default="http://127.0.0.1:11434/v1",
        help="base URL of the local debug model server (loopback only)",
    )
    parser.add_argument(
        "--online-stream",
        choices=["auto", "on", "off"],
        default="auto",
        help="request shape for the real model: auto tries non-streaming first and falls back; "
        "on forces SSE streaming; off forces non-streaming",
    )
    args = parser.parse_args()
    root = Path(args.project_root).expanduser().resolve()
    output = (Path(args.output_dir) if args.output_dir else root / ".iverilog-ai" / "strategy-experiment").expanduser().resolve()
    output.relative_to(root)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    defect_files = {str(item["id"]): str(item["file"]) for item in manifest.get("defects", [])}
    # 案例集合与合约由 manifest 决定，保证实验覆盖面与基准一致。
    CASES, SKIPPED_CASES = _load_cases(root)
    if SKIPPED_CASES:
        for _case, _reason in SKIPPED_CASES.items():
            print(f"跳过案例 {_case}：{_reason}", flush=True)
    if args.online and args.debug_local:
        parser.error("--online and --debug-local are mutually exclusive")
    if (args.online or args.debug_local) and args.online_repeats < 1:
        parser.error("--online-repeats must be >= 1")
    online_key = os.getenv(args.online_api_key_env, "") if args.online else ""
    if args.online and (not args.online_endpoint or not args.online_model or not online_key):
        parser.error("online mode requires --online-endpoint, --online-model, and the environment variable named by --online-api-key-env")
    use_remote_or_debug = bool(args.online or args.debug_local)
    rows: list[dict[str, Any]] = []
    rule_sets: dict[str, dict[str, Any]] = {}
    for case_name, case_spec in CASES.items():
        _, files = rules_context(root, case_name, case_spec["contract"])
        rule_sets[case_name] = {"fingerprint": rules_fingerprint(files), "files": files}
    strategies = ["fixed", "random", "ai"] + (["online_ai"] if use_remote_or_debug else [])
    # 代码版本与工作区状态写进产物：别人才能判断这次结果对应哪份代码，
    # 而"工作区有未提交改动"意味着仅凭 commit 无法复现。
    CODE_REVISION, WORKING_TREE_DIRTY = _code_revision(root)
    if WORKING_TREE_DIRTY:
        print("警告：工作区有未提交改动，本次实验无法仅凭 commit 复现", flush=True)
    # **预先固定的分母**：来自清单登记的 (案例, 缺陷变体)，与"实际跑出了哪些行"无关。
    # 旧口径在行集合上求分母，于是模型请求失败会让分母一起缩小。
    expected_pairs: list[tuple[str, str]] = [
        (case, str(item["id"]))
        for case in CASES
        for item in manifest.get("defects", [])
        if item["type"] == case
    ]
    strategy_rounds = {
        strategy: (1 if strategy == "fixed" else (args.online_repeats if strategy == "online_ai" else args.seeds))
        for strategy in strategies
    }
    total_units = sum(
        len([0] if strategy == "fixed" else (range(args.online_repeats) if strategy == "online_ai" else range(args.seeds)))
        * (1 + sum(1 for item in manifest.get("defects", []) if item["type"] == case))
        for case in CASES for strategy in strategies
    )
    completed_units = 0
    print(f"实验开始：{experiment_started_wall.isoformat().replace('+00:00', 'Z')}；预计任务数：{total_units}", flush=True)
    for case, spec in CASES.items():
        # 每进入一个新案例就落盘一次：真实模型实验可能跑几小时，
        # 中途落盘保证任何中断都不会丢掉已经花掉 token 的结果。
        if rows:
            _write_payload(
                output,
                _build_payload(
                    rows=rows,
                    summaries=_summarize(rows, strategies, pairs=expected_pairs, rounds=strategy_rounds),
                    total_units=total_units,
                    completed_units=completed_units,
                    rule_sets=rule_sets,
                    skipped=SKIPPED_CASES,
                    started_wall=experiment_started_wall,
                    finished_wall=datetime.now(timezone.utc),
                    started_perf=experiment_started,
                    partial=True,
                    code_revision=CODE_REVISION,
                    working_tree_dirty=WORKING_TREE_DIRTY,
                ),
            )
            _usage = _usage_totals(rows)
            if _usage["total_tokens"]:
                print(
                    f"  已用 token 累计：{_usage['total_tokens']:,}（带用量请求 {_usage['requests']}）",
                    flush=True,
                )
        variants = ["reference"] + [str(item["id"]) for item in manifest.get("defects", []) if item["type"] == case]
        # 预算**在跑之前**就按案例定好，三组策略共用同一个 T；生成出来的计划一律
        # 按 T 归一化后再执行。旧实现让 fixed/random/ai/online 各自决定跑多久
        # （实测 4 / 12 / 12 / 18 个向量），"同预算比较"从一开始就不成立。
        budget = budget_for(case)
        budget_unregistered = case not in CASE_BUDGETS
        if budget_unregistered:
            print(f"  注意：案例 {case} 未登记预算，使用默认 {budget.cycles} 周期", flush=True)
        # 提示词指纹：模型版本标签可以改，"喂进去的规格 + 规则"才是可复查的输入。
        rules_text, _rules_files = rules_context(root, case, spec["contract"])
        prompt_hash = hashlib.sha256(
            f"{case}\n{_payload(case, [])['objective']}\n{rules_text}".encode("utf-8")
        ).hexdigest()[:16]
        for strategy in strategies:
            model_label = None
            endpoint_label = None
            if strategy in {"ai", "online_ai"}:
                # 模型/端点写进行记录：旧矩阵只能靠目录名反推模型，那是不可复查的。
                model_label = "mock" if strategy == "ai" else ("debug-local" if args.debug_local else str(args.online_model))
                endpoint_label = None if strategy == "ai" else (str(args.debug_endpoint) if args.debug_local else str(args.online_endpoint))
            seeds = [0] if strategy == "fixed" else (list(range(args.online_repeats)) if strategy == "online_ai" else list(range(args.seeds)))
            for seed in seeds:
                request_started = time.perf_counter()
                raw_vectors = _fixed(case) if strategy == "fixed" else _vectors(case, seed)
                raw_payload = _payload(case, raw_vectors)
                plan_valid = True
                request_id = f"{strategy}-{case}-{seed}"
                # 两个分支会构造不同的 provider，统一标注成公共基类类型。
                provider: Provider | None = None
                generation_ms = None
                usage = None
                attempts = 0
                if strategy in {"ai", "online_ai"}:
                    try:
                        if strategy == "ai":
                            provider = MockProvider(response=raw_payload)
                        elif args.debug_local:
                            # 本地离线调试模型：回环地址、无密钥、确定性计划。
                            provider = OpenAICompatibleProvider(endpoint=args.debug_endpoint, model="debug-local", wire_api="chat_completions", reasoning_effort=None, allow_network=False, store=False, timeout=30)
                        else:
                            # stream="auto"：先非流式，若网关只接受流式（会在返回
                            # 响应前断连）或返回空正文，则自动改用 SSE 重试。
                            # 实测某些网关必须显式强制流式才稳定，故提供开关。
                            stream_mode: bool | Literal["auto"] = "auto"
                            if str(args.online_stream) == "on":
                                stream_mode = True
                            elif str(args.online_stream) == "off":
                                stream_mode = False
                            provider = OpenAICompatibleProvider(endpoint=args.online_endpoint, model=args.online_model, api_key=online_key, wire_api="chat_completions", reasoning_effort=None, allow_network=True, store=False, timeout=180, stream=stream_mode)
                        generation_started = time.perf_counter()
                        # Give online models the exact contract; otherwise
                        # they may invent aliases such as ``en`` for ``enable``.
                        # max_retries=1：允许模型在收到严格 Schema 的拒绝原因后
                        # 自我纠正一次（常见错误是断言模板名或字段名不合规）。
                        # 只重试一次，避免把一次失败放大成多次请求与多份费用。
                        plan = plan_tests(
                            raw_payload["objective"], case, provider=provider,
                            max_retries=1,
                            context=rules_text,
                        )
                        attempts = int(getattr(provider, "request_count", 0) or 0)
                        generation_ms = int((time.perf_counter() - generation_started) * 1000)
                        usage = getattr(provider, "last_usage", None)
                    except Exception as exc:
                        # 生成失败**不能只留一行**：那会让该轮的所有变体从分母里消失。
                        # 为每个预定变体补一条"不可判定"记录，分母因此保持不变。
                        failed_ms = int((time.perf_counter() - request_started) * 1000)
                        rows.append({
                            "strategy": strategy, "case": case, "variant": "plan_generation", "seed": seed,
                            "request_id": request_id, "plan_valid": False,
                            "generation_ms": failed_ms, "attempts": attempts,
                            "usage": usage, "error": str(exc), "status": "inconclusive",
                            "undecidable_reason": "plan_failed",
                        })
                        for variant in variants:
                            rows.append({
                                "strategy": strategy, "case": case, "variant": variant, "seed": seed,
                                "request_id": request_id, "plan_valid": False,
                                "budget_cycles": budget.cycles, "vectors": 0,
                                "plan_raw_sha256": "", "plan_sha256": "",
                                "generation_ms": failed_ms, "usage": usage,
                                "compile_ms": None, "sim_ms": None, "time_to_first_failure_ms": None,
                                "records_pass": 0, "failures": 0, "check_count": 0,
                                "total_cycles": 0, "defects_found": False,
                                "status": "inconclusive", "undecidable_reason": "plan_failed",
                                "error": str(exc), "artifact_path": "",
                            })
                        completed_units += len(variants)
                        print(f"{_progress_text(completed_units, total_units, experiment_started)}；{strategy}/{case}/seed={seed} 计划失败（已为 {len(variants)} 个变体记不可判定）", flush=True)
                        continue
                else:
                    from iverilog_ai.ai.schema import TestPlan
                    plan = TestPlan.model_validate(raw_payload)

                # 归一化：原始计划与执行计划都留档，两个哈希都写进行记录。
                raw_plan_json = plan.model_dump_json()
                normalized = normalize_vectors([vector.model_dump() for vector in plan.vectors], budget.cycles)
                execution_plan = _plan_with_vectors(plan, normalized.vectors)
                plan_hash = hashlib.sha256(execution_plan.model_dump_json().encode()).hexdigest()[:12]
                plan_raw_hash = hashlib.sha256(raw_plan_json.encode()).hexdigest()[:12]
                plan_dir = output / strategy / case / str(seed)
                plan_dir.mkdir(parents=True, exist_ok=True)
                (plan_dir / "plan_raw.json").write_text(json.dumps(json.loads(raw_plan_json), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (plan_dir / "plan_normalized.json").write_text(json.dumps(json.loads(execution_plan.model_dump_json()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                plan = execution_plan
                vectors = normalized.vectors
                for variant in variants:
                    rtl = root / spec["rtl"] if variant == "reference" else root / defect_files[variant]
                    started = time.perf_counter()
                    try:
                        result = VerificationPipeline().run(plan, DutContract.from_dict(spec["contract"]), rtl, output / strategy / case / str(seed) / variant, allowed_roots=(root,), iverilog_path=args.iverilog, vvp_path=args.vvp)
                    except Exception as exc:
                        # A malformed model plan or generation/tool error must
                        # not abort the remaining cases. Preserve it as an
                        # auditable inconclusive row instead.
                        rows.append(_row_payload(
                            strategy=strategy, case=case, variant=variant, seed=seed, request_id=request_id,
                            budget_cycles=budget.cycles, vectors=vectors, plan_valid=False,
                            plan_sha256=plan_hash, plan_raw_sha256=plan_raw_hash,
                            generation_ms=generation_ms, usage=usage, attempts=attempts,
                            compile_ms=None, sim_ms=None, time_to_first_failure_ms=None,
                            records_pass=0, failures=0, warning_failures=0, error_failures=0,
                            check_count=None, total_cycles=budget.cycles,
                            model=model_label, endpoint=endpoint_label, prompt_sha256=prompt_hash,
                            status="inconclusive", reason="execution_failed",
                            defect_found=False, error_msg=str(exc),
                            artifacts={}, expectation_source=None,
                            ai_expected_checked=None, ai_expected_matched=None,
                        ))
                        completed_units += 1
                        print(f"{_progress_text(completed_units, total_units, experiment_started)}；{strategy}/{case}/{variant} 不可判定", flush=True)
                        continue
                    elapsed = int((time.perf_counter() - started) * 1000)
                    # Functional mismatches are intentionally WARN in the UI,
                    # therefore the overall status may be passed_with_warnings.
                    # For mutation testing, any structured mismatch on a known
                    # defect is still a detection. Keep fatal errors separate.
                    warning_failures = sum(1 for item in result.failures if item.severity == "warn")
                    error_failures = sum(1 for item in result.failures if item.severity == "error")
                    defect_found = variant != "reference" and bool(result.failures)
                    # 预言机诊断：内置案例的期望值由参考模型复算，AI 自己写的
                    # 期望值偏差单独统计，不再混入失败反例或误报。
                    oracle = (result.simulation.config or {}).get("oracle", {}) or {}
                    ai_expected_checked = oracle.get("checked_expected")
                    ai_expected_matched = oracle.get("matched_expected")
                    check_count = result.simulation.check_count
                    rows.append(_row_payload(
                        strategy=strategy, case=case, variant=variant, seed=seed, request_id=request_id,
                        budget_cycles=budget.cycles, vectors=plan.vectors, plan_valid=plan_valid,
                        plan_sha256=plan_hash, plan_raw_sha256=plan_raw_hash,
                        generation_ms=generation_ms, usage=usage, attempts=attempts,
                        compile_ms=result.simulation.compile.duration_ms,
                        sim_ms=None if result.simulation.run is None else result.simulation.run.duration_ms,
                        time_to_first_failure_ms=elapsed if defect_found else None,
                        records_pass=sum(1 for record in result.records if record.ok),
                        failures=len(result.failures), warning_failures=warning_failures,
                        error_failures=error_failures, check_count=check_count,
                        total_cycles=int(result.simulation.summary.get("cycles", plan_cycles(vectors))),
                        model=model_label, endpoint=endpoint_label, prompt_sha256=prompt_hash,
                        status=result.status.value,
                        reason=None,
                        defect_found=defect_found, error_msg=result.simulation.error,
                        artifacts=dict(result.simulation.artifacts),
                        expectation_source=oracle.get("expectation_source"),
                        ai_expected_checked=ai_expected_checked, ai_expected_matched=ai_expected_matched,
                    ))
                    completed_units += 1
                    print(f"{_progress_text(completed_units, total_units, experiment_started)}；{strategy}/{case}/{variant} -> {result.status.value}；本组 {time.perf_counter() - request_started:.1f}s", flush=True)
    summary = _summarize(
        rows,
        strategies,
        pairs=expected_pairs,
        rounds=strategy_rounds,
    )
    experiment_finished_wall = datetime.now(timezone.utc)
    payload = _build_payload(
        rows=rows,
        summaries=summary,
        total_units=total_units,
        completed_units=completed_units,
        rule_sets=rule_sets,
        skipped=SKIPPED_CASES,
        started_wall=experiment_started_wall,
        finished_wall=experiment_finished_wall,
        started_perf=experiment_started,
        partial=False,
        code_revision=CODE_REVISION,
        working_tree_dirty=WORKING_TREE_DIRTY,
    )
    _write_payload(output, payload)
    _write_experiment_report(
        output / "strategy_report.md",
        payload,
        endpoint=(args.debug_endpoint if args.debug_local else args.online_endpoint) if use_remote_or_debug else None,
        model=("debug-local (offline)" if args.debug_local else args.online_model) if use_remote_or_debug else None,
    )
    print(f"实验完成：总耗时 {payload['duration_ms'] / 1000:.1f}s；结果：{output / 'strategy_matrix.json'}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
