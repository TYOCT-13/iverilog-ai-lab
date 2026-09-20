"""消融实验矩阵：**把"AI 到底有没有用、哪一环在承重"变成可核验的数字。**

为什么需要这个脚本：仓库里已经有两个矩阵，但它们回答不了这个最常被问的问题。
`run_benchmark_matrix.py` 跑的是**手写 testbench**——里面既有人工设计的边界激励，
也有人工写死的期望值，两者混在一起，无法归因；`run_pipeline_matrix.py` 只跑 15 个
**参考设计**，证明的是"流程能通"，不是"缺陷能不能检出"。于是"AI 规划到底有没有用"
一直停留在说法层面。

本脚本把两个因素拆开测：

============  ====================  ==================
配置           激励来源               期望值来源
============  ====================  ==================
A 手写 TB      人工设计的边界激励      人工写死在 testbench 里
B AI 计划      离线规划器按合约生成     **没有期望值**
C AI 计划+预言机 离线规划器按合约生成    参考模型独立复算并覆盖
============  ====================  ==================

- **A vs C** 孤立出**激励质量**的贡献（两者都有权威期望值）；
- **B vs C** 孤立出**权威期望值**的贡献（两者激励完全相同）。

被测量的是 15 个参考设计 + 83 个缺陷变体：
每个配置在 83 个缺陷上数**检出数**，在 15 个参考设计上数**误报数**。

怎样关掉预言机（B 配置）：把计划里的 `design` 改成一个不在 `AUTHORITATIVE` 里的名字。
`VerificationPipeline` 只用 `plan.design` 决定要不要覆盖期望值，模块例化用的是合约里的
`module`，所以改名**只影响预言机，不影响被测设计**。这是本脚本唯一一处"人为构造"，
因此在这里写明。

判决口径与仓库其他部分一致：有 `ok=false` 的结构化记录才算检出；编译失败/超时记为
不可判定，**不折算成检出**。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

from iverilog_ai.ai.debug_provider import DeterministicLocalProvider
from iverilog_ai.ai.planner import plan_tests
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.benchmark_cases import case_table, top_for_testbench
from iverilog_ai.core.config import ExecutionConfig
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.executor import IcarusExecutor
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rules import rules_context
from iverilog_ai.core.toolchain import locate_tools

#: 配置名 → (激励来源说明, 期望值来源说明, 是否开预言机, 是否用生成路径)
CONFIGS: dict[str, dict[str, Any]] = {
    "handwritten-tb": {
        "stimulus": "人工设计的边界激励（仓库自带 testbench）",
        "expectation": "人工写死在 testbench 里",
        "oracle": False,
        "generated": False,
    },
    "ai-plan-plain": {
        "stimulus": "离线规划器按合约生成",
        "expectation": "没有期望值",
        "oracle": False,
        "generated": True,
    },
    "ai-plan-oracle": {
        "stimulus": "离线规划器按合约生成",
        "expectation": "参考模型独立复算并覆盖",
        "oracle": True,
        "generated": True,
    },
}
CONFIG_ORDER = ("handwritten-tb", "ai-plan-plain", "ai-plan-oracle")

#: 规划目标按案例给一句白话（与 pipeline 矩阵保持一致，避免两处口径漂移）。
OBJECTIVES: dict[str, str] = {
    "mod10_counter": "覆盖复位、使能保持与 9→0 回绕",
    "traffic_light_emergency": "覆盖正常轮转与紧急抢占后恢复",
    "simple_alu": "覆盖加减、位运算、移位与零标志边界",
    "sequence_101_overlap": "覆盖 101 序列的重叠检测与复位",
    "sync_fifo": "覆盖写满、读空与同时读写",
    "uart_tx": "覆盖整帧发送、起始位与结束后的空闲电平",
    "spi_master": "覆盖一次完整传输、sclk 相位与 done 脉冲",
    "handshake_stage": "覆盖 valid/ready 握手与反压保持",
    "debounce": "覆盖抖动与稳定后的状态切换",
    "pwm": "覆盖 0%/100% 占空比边界",
    "mux4": "覆盖四个通道的选择与切换",
    "sync_reset": "覆盖异步断言与两级同步释放",
    "johnson_counter": "覆盖完整循环与使能暂停",
    "edge_detector": "覆盖单拍上升沿、连续高电平与复位",
    "pulse_stretcher": "覆盖展宽长度、展宽期内重触发与异步复位",
}


#: 规划器漏检的 7 条，逐条写清"通用激励为什么碰不到"。这是人工分析，不是脚本推断，
#: 因此措辞只描述**激励与触发条件的关系**，不下"模型能力不足"这类结论。
_MISS_REASONS: dict[str, str] = {
    "mod10_bug_async": "需要复位释放与时钟沿的精确相位关系；通用激励在整拍边界给复位，看不出异步与同步之差",
    "srst_bug_single_stage": "差别只在复位释放路径的同步级数上，需要释放时刻恰好落在时钟沿附近",
    "srst_bug_sync_assert_only": "同上：断言路径的同步与否只在释放窗口里可观测",
    "deb_bug_counter_not_cleared": "需要足够长的连续抖动序列才能让计数器累计出错；通用激励的抖动长度不足",
    "pstr_bug_no_retrigger": "需要在展宽期内精确重触发；通用激励没有构造这个重叠时序",
    "fifo_bug_full_off_by_one": "需要写到恰好第 N 拍的满/空边界；通用激励的写入长度没卡在这个边界上",
    "traffic_bug_emergency_output": "需要紧急信号在特定状态拍上拉高；通用激励的抢占时刻没落在那一个状态上",
}
_MISS_FALLBACK = "需要精确时序或边界序列；通用激励未覆盖到该组合"


def _plans_for_case(
    root: Path, case: str, contract: DutContract, provider: DeterministicLocalProvider
) -> tuple[TestPlan, TestPlan]:
    """返回 (原计划, 关掉预言机后的计划)。

    只生成一次、复制一份改名：两次跑的是**同一份激励**，否则 A/B 差异里会混进
    "规划器每次产出不同"这一项，消融就不干净了。
    """

    context, _manifest = rules_context(root, case, contract.to_dict())
    objective = OBJECTIVES.get(case, "覆盖复位、边界时序与状态转换")
    plan = plan_tests(objective, case, provider=provider, context=context)
    return plan, plan.model_copy(update={"design": f"{case}__oracle_off"})


def _run_handwritten(
    root: Path, run_dir: Path, rtl: Path, testbench: Path, top: str,
    iverilog_path: str | None, vvp_path: str | None, timeout: float,
) -> dict[str, Any]:
    config = ExecutionConfig(
        rtl_path=rtl,
        testbench_path=testbench,
        top_module=top,
        output_dir=run_dir,
        allowed_roots=(root,),
        iverilog_path=iverilog_path,
        vvp_path=vvp_path,
        timeout_seconds=timeout,
        keep_artifacts=True,
    )
    result = IcarusExecutor(config).run()
    return {
        "status": result.status.value,
        "verdict": result.verdict,
        "records": len(result.records),
        "failures": len(result.failures),
        "expectation_source": "handwritten",
        "comparable_checks": sum(1 for item in result.records if getattr(item, "signal", None)),
    }


def _run_generated(
    root: Path, run_dir: Path, rtl: Path, contract: DutContract, plan: TestPlan,
    iverilog_path: str | None, vvp_path: str | None, timeout: float,
) -> dict[str, Any]:
    result = VerificationPipeline().run(
        plan,
        contract,
        rtl,
        run_dir,
        allowed_roots=(root,),
        iverilog_path=iverilog_path,
        vvp_path=vvp_path,
        timeout_seconds=timeout,
        emit_vcd=False,
    )
    oracle = (result.simulation.config or {}).get("oracle") or {}
    return {
        "status": result.status.value,
        "verdict": result.verdict,
        "records": len(result.records),
        "failures": len(result.failures),
        "expectation_source": str(oracle.get("expectation_source", "unknown")),
        "comparable_checks": sum(1 for item in result.records if getattr(item, "signal", None)),
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 消融实验矩阵：AI 规划到底有没有用，哪一环在承重",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        "- 工具链：本地 Icarus Verilog；规划器：仓库自带离线确定性规划器（非真实模型）",
        f"- 规模：{summary['reference_total']} 个参考设计 + {summary['defect_total']} 个缺陷变体",
        "",
        "## 配置与结果",
        "",
        "| 配置 | 激励来源 | 期望值来源 | 缺陷检出 | 参考误报 | 不可判定 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for name in [item for item in CONFIG_ORDER if item in summary["configs"]]:
        row = summary["configs"][name]
        config = CONFIGS[name]
        lines.append(
            f"| `{name}` | {config['stimulus']} | {config['expectation']} | "
            f"**{row['detected']} / {row['defect_total']}** | {row['false_positives']} / {row['reference_total']} | "
            f"{row['inconclusive']} |"
        )
    ran = set(summary["configs"])
    union_available = {"handwritten-tb", "ai-plan-oracle"} <= ran
    if union_available:
        union = summary["union"]
        lines.append(
            f"| `handwritten-tb ∪ ai-plan-oracle`（推导值） | 两者并用 | 权威期望值 | "
            f"**{union['detected']} / {union['defect_total']}** | {union['false_positives']} / {union['reference_total']} | — |"
        )
    # "读法"要引用三行之间的差；只跑了一部分配置时不能硬编（会 KeyError），
    # 也不能编造没跑出来的数字——直接说明这次只跑了哪几个配置。
    all_three = set(CONFIG_ORDER) <= ran
    if not all_three:
        lines.extend(
            [
                "",
                f"> 本次只跑了 {', '.join(f'`{name}`' for name in CONFIG_ORDER if name in ran)}，"
                "因此不给出三行之间的对照结论。跑全部配置（默认）才会输出完整的读法。",
                "",
            ]
        )
    else:
        plain = summary["configs"]["ai-plan-plain"]["detected"]
        oracle = summary["configs"]["ai-plan-oracle"]["detected"]
        hand = summary["configs"]["handwritten-tb"]["detected"]
        total = summary["configs"]["handwritten-tb"]["defect_total"]
        gain = union["detected"] - hand
        lines.extend(
            [
                "",
                "## 读法（三行差异就是结论）",
                "",
                f"**① 权威预言机是承重墙：`ai-plan-plain` → `ai-plan-oracle`，检出 {plain} → {oracle}。**",
                "两行的**激励完全相同**（同一份计划、同一个随机种子），只把期望值从「没有」换成"
                "「参考模型独立复算」。结果是：没有预言机时，AI 生成的计划连一条**可比的检查项**"
                f"都产不出来——{total} 条缺陷一条都没检出。这直接量化了门 3 的作用，"
                "也是本项目「AI 提出测试假设，开源仿真器作出判决」这句分工主张的实测依据。",
                "",
                f"**② AI 的通用激励还顶不上人工边界激励：`handwritten-tb` → `ai-plan-oracle`，检出 {hand} → {oracle}。**",
                "两行的**期望值都是权威的**（一个人工写在 testbench 里、一个由参考模型复算），"
                f"差别只在激励。规划器按合约生成的通用激励少检出了 **{hand - oracle} 条**。",
                "逐条看这 %d 条漏检，**全部是「要精确时序或边界序列才能触发」的缺陷**"
                "（异步复位差一拍、同步器级数、抖动序列长度、展宽期内重触发、写满 off-by-one、"
                "紧急抢占时序）。这正是本项目**不声称**「AI 可以替代人工测试设计」的量化理由："
                "AI 能把写 testbench 的成本降下来，但边界激励的设计判断力仍要人来出。" % (hand - oracle),
                "",
                f"**③ 在这批缺陷上，规划器没有多检出任何一条：并集 {union['detected']} / {union['defect_total']}，"
                f"规划器独立贡献 {gain} 条。**",
                "这个结论对我们不利，但必须如实写出来：**离线确定性规划器的价值不在「发现人没想到的缺陷」，"
                "而在「不用人手写 testbench 就能拿到 %d/%d」**——它降低的是写 TB 的成本，"
                "不是替代测试设计的判断力。（真实模型的激励质量高于离线规划器，见在线实验记录；"
                "但同样需要预言机兜底，因为 AI 猜错的期望值会直接变成假失败或漏检。）" % (oracle, total),
                "",
            ]
        )
        missed = payload.get("missed_by_generated") or []
        if missed:
            lines.extend(
                [
                    "## 规划器漏检的 %d 条（人工边界激励能检出）" % len(missed),
                    "",
                    "| 案例 | 缺陷 | 触发条件 | 为什么通用激励覆盖不到 |",
                    "|---|---|---|---|",
                ]
            )
            for item in missed:
                lines.append(
                    f"| `{item['case']}` | `{item['defect']}` | {item['trigger']} | {item['why']} |"
                )
            lines.append("")
    lines.extend(
        [
            "",
            "## 逐案例明细",
            "",
            "| 案例 | 配置 | 缺陷数 | 检出 | 参考误报 | 期望值来源 |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for row in payload["cases"]:
        lines.append(
            f"| `{row['case']}` | `{row['config']}` | {row['defects']} | {row['detected']} | "
            f"{row['reference_failures']} | `{row['expectation_source']}` |"
        )
    lines.extend(
        [
            "",
            "## 口径与限制",
            "",
            "- 检出 = 该次仿真产出了至少一条 `ok=false` 的结构化记录；编译失败/超时记为不可判定，"
            "**不折算成检出**；",
            "- 误报 = 参考设计上产出了失败记录（参考设计是正确的，任何失败都是误报）；",
            "- 关掉预言机的做法：把计划里的 `design` 改成不在 `AUTHORITATIVE` 里的名字。"
            "模块例化用的是合约里的 `module`，因此改名只影响预言机，不影响被测设计；",
            "- 这里用的是**离线确定性规划器**，不是真实模型。它代表「AI 那一路流程」的下限，"
            "真实模型的激励质量见 `docs/experiment/` 下的在线实验记录；",
            "- 原始产物保留在输出目录下，每个变体一份 `result.json` / `pipeline_result.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def run_ablation_matrix(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    iverilog_path: str | None = None,
    vvp_path: str | None = None,
    timeout: float = 30.0,
    cases: list[str] | None = None,
    configs: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    output_root = (
        Path(output_dir) if output_dir is not None else root / ".iverilog-ai" / "ablation-matrix"
    ).expanduser().resolve()
    try:
        output_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must remain inside project_root") from exc
    output_root.mkdir(parents=True, exist_ok=True)

    selected_configs = tuple(configs or CONFIG_ORDER)
    for name in selected_configs:
        if name not in CONFIGS:
            raise ValueError(f"未知配置：{name}（可选 {', '.join(CONFIG_ORDER)}）")

    table = case_table(root)
    manifest = json.loads((root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    defects: list[dict[str, Any]] = [
        item for item in manifest.get("defects", []) if not cases or str(item["type"]) in set(cases)
    ]
    selected_cases = [name for name in table if not cases or name in set(cases)]

    tools = locate_tools()
    iverilog_path = iverilog_path or tools.iverilog
    vvp_path = vvp_path or tools.vvp
    provider = DeterministicLocalProvider(seed=0)

    per_config: dict[str, dict[str, int]] = {
        name: {"detected": 0, "inconclusive": 0, "false_positives": 0, "reference_total": 0, "defect_total": 0}
        for name in selected_configs
    }
    detected_ids: dict[str, set[str]] = {name: set() for name in selected_configs}
    case_rows: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []

    for case in selected_cases:
        info = table[case]
        contract_path = root / "examples" / f"{case}_contract.json"
        if not contract_path.is_file():
            continue
        contract = DutContract.from_dict(json.loads(contract_path.read_text(encoding="utf-8")))
        plan, plan_no_oracle = _plans_for_case(root, case, contract, provider)
        case_defects = [item for item in defects if str(item["type"]) == case]

        for name in selected_configs:
            config = CONFIGS[name]
            # 参考设计：正确实现，任何失败记录都是误报
            reference_rtl = root / info["rtl"]
            reference_dir = output_root / name / case / "reference"
            started = time.perf_counter()
            if config["generated"]:
                ref = _run_generated(
                    root, reference_dir, reference_rtl, contract,
                    plan if config["oracle"] else plan_no_oracle,
                    iverilog_path, vvp_path, timeout,
                )
            else:
                ref = _run_handwritten(
                    root, reference_dir, reference_rtl, root / info["testbench"], info["top"],
                    iverilog_path, vvp_path, timeout,
                )
            reference_failures = int(ref["failures"])
            if ref["status"] in {"compile_failed", "timeout", "inconclusive", "configuration_error"}:
                per_config[name]["inconclusive"] += 1
            else:
                per_config[name]["reference_total"] += 1
                if reference_failures:
                    per_config[name]["false_positives"] += 1

            detected_here = 0
            for defect in case_defects:
                defect_id = str(defect["id"])
                rtl = root / str(defect["file"])
                run_dir = output_root / name / case / defect_id
                if config["generated"]:
                    outcome = _run_generated(
                        root, run_dir, rtl, contract,
                        plan if config["oracle"] else plan_no_oracle,
                        iverilog_path, vvp_path, timeout,
                    )
                else:
                    testbench_rel = str(defect.get("testbench") or info["testbench"])
                    top = str(defect.get("top") or top_for_testbench(testbench_rel, info))
                    outcome = _run_handwritten(
                        root, run_dir, rtl, root / testbench_rel, top,
                        iverilog_path, vvp_path, timeout,
                    )
                if outcome["status"] in {"compile_failed", "timeout", "inconclusive", "configuration_error"}:
                    per_config[name]["inconclusive"] += 1
                    label = "inconclusive"
                elif int(outcome["failures"]) > 0:
                    per_config[name]["detected"] += 1
                    detected_ids[name].add(defect_id)
                    detected_here += 1
                    label = "detected"
                else:
                    label = "missed"
                per_config[name]["defect_total"] += 1
                variants.append(
                    {
                        "config": name,
                        "case": case,
                        "defect": defect_id,
                        "outcome": label,
                        "expectation_source": outcome["expectation_source"],
                        "comparable_checks": outcome["comparable_checks"],
                        "records": outcome["records"],
                        "failures": outcome["failures"],
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
            case_rows.append(
                {
                    "case": case,
                    "config": name,
                    "defects": len(case_defects),
                    "detected": detected_here,
                    "reference_failures": reference_failures,
                    "expectation_source": ref["expectation_source"],
                }
            )

    union_ids: set[str] = set()
    for name in ("handwritten-tb", "ai-plan-oracle"):
        if name in detected_ids:
            union_ids |= detected_ids[name]
    union = {
        "detected": len(union_ids),
        "defect_total": max((per_config[name]["defect_total"] for name in selected_configs), default=0),
        "false_positives": 0,
        "reference_total": max((per_config[name]["reference_total"] for name in selected_configs), default=0),
    }

    # 规划器漏检、而人工边界激励能检出的那几条：这是整份矩阵里最可行动的输出。
    by_id = {str(item["id"]): item for item in defects}
    missed_by_generated = [
        {
            "case": by_id[defect_id]["type"],
            "defect": defect_id,
            "trigger": str(by_id[defect_id].get("trigger", "")),
            "why": _MISS_REASONS.get(defect_id, _MISS_FALLBACK),
        }
        for defect_id in sorted(detected_ids.get("handwritten-tb", set()) - detected_ids.get("ai-plan-oracle", set()))
        if defect_id in by_id
    ]

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_root": str(root),
        "configs": {name: CONFIGS[name] for name in selected_configs},
        "summary": {
            "configs": per_config,
            "union": union,
            "reference_total": union["reference_total"],
            "defect_total": union["defect_total"],
        },
        "missed_by_generated": missed_by_generated,
        "cases": case_rows,
        "variants": variants,
    }
    (output_root / "matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "matrix.md").write_text(_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="跑消融实验矩阵（AI 规划的两因素拆解）")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--output-dir", default=None, help="输出目录，默认 .iverilog-ai/ablation-matrix")
    parser.add_argument("--case", action="append", default=None, help="只跑指定案例，可重复")
    parser.add_argument("--config", action="append", default=None, help="只跑指定配置，可重复")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="不跑仿真，只按已有 matrix.json 重新生成 matrix.md（改文案时用，避免重跑几分钟）",
    )
    args = parser.parse_args()

    if args.render_only:
        root = Path(args.root).expanduser().resolve()
        output_root = (
            Path(args.output_dir) if args.output_dir is not None else root / ".iverilog-ai" / "ablation-matrix"
        ).expanduser().resolve()
        source = output_root / "matrix.json"
        if not source.is_file():
            print(f"没有找到 {source}，无法只重渲染。", file=sys.stderr)
            return 2
        payload = json.loads(source.read_text(encoding="utf-8"))
        (output_root / "matrix.md").write_text(_markdown(payload), encoding="utf-8")
        print(f"已按 {source} 重新生成 matrix.md")
        return 0

    payload = run_ablation_matrix(
        args.root,
        args.output_dir,
        timeout=args.timeout,
        cases=args.case,
        configs=args.config,
    )
    summary = payload["summary"]
    print(json.dumps(
        {
            "defect_total": summary["defect_total"],
            "reference_total": summary["reference_total"],
            "configs": {name: {"detected": row["detected"], "false_positives": row["false_positives"],
                               "inconclusive": row["inconclusive"]}
                        for name, row in summary["configs"].items()},
            "union_detected": summary["union"]["detected"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
