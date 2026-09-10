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
from typing import Any, Callable

from iverilog_ai.ai import MockProvider, OpenAICompatibleProvider, plan_tests
from iverilog_ai.ai.debug_server import build_plan_response
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.models import ResultStatus
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rules import rules_context, rules_fingerprint

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
        return _contract_stimulus(case, seed, count)
    return vectors


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


def _progress_text(done: int, total: int, started: float) -> str:
    elapsed = time.perf_counter() - started
    percent = (100.0 * done / total) if total else 100.0
    eta = (elapsed / done * (total - done)) if done else None
    eta_text = f"；预计剩余 {eta:.1f}s" if eta is not None else ""
    return f"进度 {done}/{total}（{percent:.1f}%）；已耗时 {elapsed:.1f}s{eta_text}"


def _write_experiment_report(path: Path, payload: dict[str, Any], *, endpoint: str | None, model: str | None) -> None:
    """Write a human-readable, auditable summary without secrets or raw prompts."""
    lines = [
        "# Icarus 智测策略实验报告", "",
        f"- 开始时间：`{payload['started_at']}`",
        f"- 结束时间：`{payload['finished_at']}`",
        f"- 总耗时：`{payload['duration_ms'] / 1000:.1f}s`",
        f"- 完成任务：`{payload['completed_units']}/{payload['total_units']}`",
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
        "| 策略 | 模型请求数 | 请求级合法率 | 参考误报(硬失败) | 参考设计期望值不一致 | 缺陷总数 | 缺陷检出 | 检出率 | 不可判定 | 平均生成(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for strategy, item in payload["summary"].items():
        accuracy = item.get("ai_expected_accuracy")
        generation = item.get("mean_generation_ms")
        lines.append(
            f"| {strategy} | {item.get('plan_requests', 0)} | "
            f"{item.get('request_plan_valid_rate', 0) * 100:.1f}% | "
            f"{item.get('reference_false_positives', 0)} | "
            f"{item.get('reference_warn_mismatches', 0)} | "
            f"{item.get('defects_total', 0)} | "
            f"{item.get('defects_found', 0)} | {item.get('detection_rate', 0) * 100:.1f}% | "
            f"{item.get('inconclusive_runs', 0)} | "
            f"{generation:.1f} |" if generation is not None else
            f"| {strategy} | {item.get('plan_requests', 0)} | {item.get('request_plan_valid_rate', 0) * 100:.1f}% | {item.get('reference_false_positives', 0)} | {item.get('reference_warn_mismatches', 0)} | {item.get('defects_total', 0)} | {item.get('defects_found', 0)} | {item.get('detection_rate', 0) * 100:.1f}% | {item.get('inconclusive_runs', 0)} | - |"
        )
        if accuracy is not None:
            lines.append(
                f"| ↳ {strategy} 期望值口径 | 检查项 {item.get('ai_expected_checked', 0)} | "
                f"AI 期望值准确率 {accuracy * 100:.1f}% | | | | | | | |"
            )
    lines.extend([
        "",
        "### 指标口径说明",
        "",
        "- **参考误报(硬失败)**：参考设计上出现 `severity=error` 的失败反例，属于工具缺陷。",
        "- **参考设计期望值不一致**：参考设计上出现 `severity=warn` 的失败反例，等价于「AI 期望值判断错误」，是诊断指标而非工具缺陷。",
        "- **AI 期望值准确率**：内置案例的期望值由独立参考模型复算并作为权威预言机；该比率衡量 AI 自己写的期望值中有多少与参考模型一致。",
        "- 当某个策略产出的计划**不写任何期望值**时（例如本地调试模型只施加激励），该比率为空 `n/a`：没有可比对的 AI 数字，不代表准确率为零。",
        "- 缺陷判定与误报判定使用同一套结构化失败反例，因此必须先排除期望值口径的干扰，再解读检出率。",
    ])
    failures = [row for row in payload["runs"] if row.get("status") == "inconclusive" or row.get("error")]
    lines.extend(["", "## 不可判定和错误记录", ""])
    if failures:
        lines.append("| 策略 | 案例 | 变体 | seed | 错误 |")
        lines.append("|---|---|---|---:|---|")
        for row in failures:
            error = str(row.get("error", "未提供")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {row.get('strategy')} | {row.get('case')} | {row.get('variant')} | {row.get('seed', '-')} | {error} |")
    else:
        lines.append("无。")
    lines.extend(["", "## 逐次结果", "", "逐次机器可读记录位于同目录的 `strategy_matrix.json`；其中包含每次运行的计划哈希、生成耗时、编译/仿真耗时、warn/error 计数和证据目录。", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    total_units = sum(
        len([0] if strategy == "fixed" else (range(args.online_repeats) if strategy == "online_ai" else range(args.seeds)))
        * (1 + sum(1 for item in manifest.get("defects", []) if item["type"] == case))
        for case in CASES for strategy in strategies
    )
    completed_units = 0
    print(f"实验开始：{experiment_started_wall.isoformat().replace('+00:00', 'Z')}；预计任务数：{total_units}", flush=True)
    for case, spec in CASES.items():
        variants = ["reference"] + [str(item["id"]) for item in manifest.get("defects", []) if item["type"] == case]
        for strategy in strategies:
            seeds = [0] if strategy == "fixed" else (list(range(args.online_repeats)) if strategy == "online_ai" else list(range(args.seeds)))
            for seed in seeds:
                request_started = time.perf_counter()
                vectors = _fixed(case) if strategy == "fixed" else _vectors(case, seed)
                payload = _payload(case, vectors)
                plan_valid = True
                request_id = f"{strategy}-{case}-{seed}"
                provider = None
                generation_ms = None
                usage = None
                if strategy in {"ai", "online_ai"}:
                    try:
                        if strategy == "ai":
                            provider = MockProvider(response=payload)
                        elif args.debug_local:
                            # 本地离线调试模型：回环地址、无密钥、确定性计划。
                            provider = OpenAICompatibleProvider(endpoint=args.debug_endpoint, model="debug-local", wire_api="chat_completions", reasoning_effort=None, allow_network=False, store=False, timeout=30)
                        else:
                            # stream="auto"：先非流式，若网关只接受流式（会在返回
                            # 响应前断连）则自动改用 SSE 重试一次。真实模型实验
                            # 因此对两类网关都可用。
                            provider = OpenAICompatibleProvider(endpoint=args.online_endpoint, model=args.online_model, api_key=online_key, wire_api="chat_completions", reasoning_effort=None, allow_network=True, store=False, timeout=180, stream="auto")
                        generation_started = time.perf_counter()
                        # Give online models the exact contract; otherwise
                        # they may invent aliases such as ``en`` for ``enable``.
                        plan = plan_tests(
                            payload["objective"], case, provider=provider,
                            max_retries=0,
                            context=rules_context(root, case, spec["contract"])[0],
                        )
                        generation_ms = int((time.perf_counter() - generation_started) * 1000)
                        usage = getattr(provider, "last_usage", None)
                    except Exception as exc:
                        plan_valid = False
                        rows.append({"strategy": strategy, "case": case, "variant": "plan_generation", "seed": seed, "request_id": request_id, "plan_valid": False, "generation_ms": generation_ms, "usage": usage, "error": str(exc), "status": "inconclusive"})
                        completed_units += len(variants)
                        print(f"{_progress_text(completed_units, total_units, experiment_started)}；{strategy}/{case}/seed={seed} 计划失败", flush=True)
                        continue
                else:
                    from iverilog_ai.ai.schema import TestPlan
                    plan = TestPlan.model_validate(payload)
                plan_hash = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()[:12]
                for variant in variants:
                    rtl = root / spec["rtl"] if variant == "reference" else root / defect_files[variant]
                    started = time.perf_counter()
                    try:
                        result = VerificationPipeline().run(plan, DutContract.from_dict(spec["contract"]), rtl, output / strategy / case / str(seed) / variant, allowed_roots=(root,), iverilog_path=args.iverilog, vvp_path=args.vvp)
                    except Exception as exc:
                        # A malformed model plan or generation/tool error must
                        # not abort the remaining cases. Preserve it as an
                        # auditable inconclusive row instead.
                        rows.append({"strategy": strategy, "case": case, "variant": variant, "seed": seed, "request_id": request_id, "budget_s": 30.0, "vectors": len(vectors), "plan_valid": False, "plan_sha256": plan_hash, "generation_ms": generation_ms, "usage": usage, "compile_ms": None, "sim_ms": None, "time_to_first_failure_ms": None, "records_pass": 0, "failures": 0, "defects_found": False, "status": "inconclusive", "error": str(exc), "artifact_path": ""})
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
                    rows.append({"strategy": strategy, "case": case, "variant": variant, "seed": seed, "request_id": request_id, "budget_s": 30.0, "vectors": len(plan.vectors), "plan_valid": plan_valid, "plan_sha256": plan_hash, "generation_ms": generation_ms, "usage": usage, "compile_ms": result.simulation.compile.duration_ms, "sim_ms": None if result.simulation.run is None else result.simulation.run.duration_ms, "time_to_first_failure_ms": elapsed if defect_found else None, "records_pass": sum(1 for record in result.records if record.ok), "failures": len(result.failures), "warning_failures": warning_failures, "error_failures": error_failures, "defects_found": defect_found, "expectation_source": oracle.get("expectation_source"), "ai_expected_checked": ai_expected_checked, "ai_expected_matched": ai_expected_matched, "status": result.status.value, "artifact_path": result.artifacts.get("run_dir", "")})
                    completed_units += 1
                    print(f"{_progress_text(completed_units, total_units, experiment_started)}；{strategy}/{case}/{variant} -> {result.status.value}；本组 {time.perf_counter() - request_started:.1f}s", flush=True)
    summary: dict[str, Any] = {}
    for strategy in strategies:
        selected = [row for row in rows if row["strategy"] == strategy]
        refs = [row for row in selected if row["variant"] == "reference"]
        defects = [row for row in selected if row["variant"] not in {"reference", "plan_generation"}]
        found_pairs = {(row["case"], row["variant"]) for row in defects if row.get("defects_found")}
        total_pairs = {(row["case"], row["variant"]) for row in defects}
        valid_runs = sum(1 for row in selected if row["plan_valid"])
        request_rows: dict[str, dict[str, Any]] = {}
        for row in selected:
            request_rows.setdefault(row["request_id"], row)
            if not row.get("plan_valid", False):
                request_rows[row["request_id"]] = row
        generation_times = [row.get("generation_ms") for row in request_rows.values() if isinstance(row.get("generation_ms"), int)]
        # 参考误报只统计真正的硬失败；warn 级反例在参考设计上代表"AI 期望值
        # 与参考模型不一致"，属于诊断指标，单独统计，避免把工具缺陷记成误报。
        reference_false_positives = sum(bool(row.get("error_failures")) for row in refs)
        reference_warn_mismatches = sum(bool(row.get("warning_failures")) for row in refs)
        ai_checked = sum(int(row.get("ai_expected_checked") or 0) for row in selected)
        ai_matched = sum(int(row.get("ai_expected_matched") or 0) for row in selected)
        valid_requests = sum(bool(row.get("plan_valid")) for row in request_rows.values())
        summary[strategy] = {"runs": len(selected), "plan_requests": len(request_rows), "valid_plan_requests": valid_requests, "request_plan_valid_rate": valid_requests / len(request_rows) if request_rows else 0.0, "plan_valid": all(row["plan_valid"] for row in selected), "plan_valid_runs": valid_runs, "plan_total_runs": len(selected), "plan_valid_rate": valid_runs / len(selected) if selected else 0.0, "reference_false_positives": reference_false_positives, "reference_warn_mismatches": reference_warn_mismatches, "ai_expected_checked": ai_checked, "ai_expected_matched": ai_matched, "ai_expected_accuracy": (ai_matched / ai_checked) if ai_checked else None, "defects_total": len(total_pairs), "defects_found": len(found_pairs), "detection_rate": len(found_pairs) / len(total_pairs) if total_pairs else 0.0, "inconclusive_runs": sum(row["status"] == "inconclusive" for row in selected), "mean_generation_ms": (sum(generation_times) / len(generation_times) if generation_times else None), "mean_time_to_first_failure_ms": (sum(row["time_to_first_failure_ms"] for row in defects if row.get("time_to_first_failure_ms") is not None) / max(1, sum(row.get("time_to_first_failure_ms") is not None for row in defects)))}
    experiment_finished_wall = datetime.now(timezone.utc)
    payload = {"schema_version": "1.0", "started_at": experiment_started_wall.isoformat().replace("+00:00", "Z"), "finished_at": experiment_finished_wall.isoformat().replace("+00:00", "Z"), "duration_ms": int((time.perf_counter() - experiment_started) * 1000), "total_units": total_units, "completed_units": completed_units, "rule_sets": rule_sets, "skipped_cases": SKIPPED_CASES, "runs": rows, "summary": summary}
    (output / "strategy_matrix.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_experiment_report(output / "strategy_report.md", payload, endpoint=(args.debug_endpoint if args.debug_local else args.online_endpoint) if use_remote_or_debug else None, model=("debug-local (offline)" if args.debug_local else args.online_model) if use_remote_or_debug else None)
    print(f"实验完成：总耗时 {payload['duration_ms'] / 1000:.1f}s；结果：{output / 'strategy_matrix.json'}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
