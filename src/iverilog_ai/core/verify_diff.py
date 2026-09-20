"""一条命令回答一个问题：**候选 RTL 的行为和基线一致吗？**

为什么单独做这个模块：能力早就有（`behavior_compare` 能跑两份 RTL 的同一份 TestPlan），
但要用它得先自己准备 ``--contract`` 和 ``--plan`` 两个文件、四个参数。对真正想用它的两类人
来说这是硬门槛：

- **用 AI 重写了某个模块的人**——"我只想让 AI 帮我改这个文件，为什么还要我先造合约和计划？"
- **开源项目维护者**——"我要判断一个 PR 有没有改行为，但上游项目根本没有 testbench。"

本模块把四步压成一步：**从基线 RTL 自动提取合约草稿 → 用离线确定性规划器生成测试计划 →
把同一份计划喂给两份 RTL → 比对逐项记录与逐拍波形 → 给出结论句与可贴进 PR 的报告。**

三条不可动摇的口径（与项目其他部分一致）：

1. **自动提取的合约是草稿，不假装是确认过的。** 端口/位宽从 `module` 头解析，通常可信；
   但"复位是高有效还是低有效""同步还是异步"是**猜的**（见 `rtl_import.extract_contract_draft`）。
   草稿会让两侧跑在同一套（可能不精确的）测试台下——所以它**削弱的是灵敏度，不是可比性**：
   `different` 永远是可信的（在共享测试台上观测到了真实差异），`identical` 的覆盖范围则可能
   因此变窄。结论里必须写明这一点，因此 :class:`VerifyDiffResult` 有 `caveats`。
2. **没有可比证据就不许说"一致"。** 计划里没有 `expected`、波形也没比成时，两份 RTL 只会
   产出数量相同的**观察记录**，逐项比对会"全等"——这是个假通过。这里显式判成
   `证据不足`，见 :func:`_decide_status`。
3. **结论句用项目统一的措辞表。** 这一层回答的是"两份 RTL 一样吗"，与"这份设计对不对"
   是不同的问题，所以用 `core.labels` 里独立的 `DIFF_LABELS`，不共用"符合预期"那套词。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ai.debug_provider import offline_provider
from ..ai.planner import plan_tests
from ..ai.schema import TestPlan as AITestPlan
from .behavior_compare import BehaviorCompareResult, compare_rtl_behavior
from .contracts import DutContract
from .labels import diff_label
from .reference_model import AUTHORITATIVE, SUPPORTED
from .rtl_import import extract_contract_draft

__all__ = [
    "CONTRACT_FROM_DRAFT",
    "CONTRACT_PROVIDED",
    "PLAN_FROM_OFFLINE",
    "PLAN_PROVIDED",
    "STATUS_DIFFERENT",
    "STATUS_IDENTICAL",
    "STATUS_INCONCLUSIVE",
    "VerifyDiffResult",
    "verify_diff",
]

STATUS_IDENTICAL = "identical"
STATUS_DIFFERENT = "different"
STATUS_INCONCLUSIVE = "inconclusive"

CONTRACT_PROVIDED = "provided"
CONTRACT_FROM_DRAFT = "draft-from-baseline"

PLAN_PROVIDED = "provided"
PLAN_FROM_OFFLINE = "offline-planner"

#: 离线规划器生成的计划只有激励、没有期望值；用它可以比波形，但逐项检查是空的。
_DEFAULT_OBJECTIVE = (
    "compare the observable behaviour of two RTL implementations under the same stimulus: "
    "cover reset release, the primary counting or data path, and at least one boundary value"
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class VerifyDiffResult:
    """两份 RTL 同一测试计划下的对比结论（含"这份结论凭什么成立"）。"""

    status: str
    module: str
    baseline: str
    candidate: str
    contract_source: str
    plan_source: str
    plan_evidence_level: str
    comparable_checks: int
    waveform_compared: bool
    comparison: BehaviorCompareResult
    contract_draft: dict[str, Any] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """结论层措辞（两侧一致 / 两侧不同 / 未取得可比证据）。"""

        return diff_label(self.status)

    @property
    def exit_code(self) -> int:
        """0 = 一致（可合并）、1 = 不同（要人看）、2 = 没比出结论（别当成通过）。"""

        return {
            STATUS_IDENTICAL: 0,
            STATUS_DIFFERENT: 1,
        }.get(self.status, 2)

    @property
    def differences(self) -> tuple[dict[str, Any], ...]:
        """面向人的差异清单：先是逐检查项差异，再是逐拍波形差异。

        底层 `behavior_compare` 用的是"用户 RTL / 参考 RTL"这套词（它同时服务网页上的
        行为对比页），而这条命令的场景是"基线 vs 候选"。这里做一次**显示层**的改写——
        贴进 PR 时"候选"才说得通，而且不必为此改动另一处调用方的措辞。
        """

        def _for_humans(message: str) -> str:
            return (
                str(message)
                .replace("用户 RTL", "候选")
                .replace("参考 RTL", "基线")
                .replace("用户侧", "候选")
                .replace("参考侧", "基线")
            )

        items: list[dict[str, Any]] = []
        for mismatch in self.comparison.mismatches:
            items.append(
                {
                    "kind": mismatch.get("kind", "record_mismatch"),
                    "where": f"{mismatch.get('test_id') or '未命名测试'} / {mismatch.get('signal') or '整条记录'}",
                    "message": _for_humans(mismatch.get("message", "")),
                    "expected": (mismatch.get("reference") or {}).get("actual")
                    if isinstance(mismatch.get("reference"), Mapping)
                    else None,
                    "actual": (mismatch.get("user") or {}).get("actual")
                    if isinstance(mismatch.get("user"), Mapping)
                    else None,
                }
            )
        for item in self.comparison.waveform.get("dut_differences", []) or []:
            items.append(
                {
                    "kind": "waveform_difference",
                    "where": f"t={item.get('time_ns', '?')}ns / {item.get('signal', '')}",
                    "message": "同一时刻两侧可观测值不同",
                    "expected": item.get("expected", item.get("reference")),
                    "actual": item.get("actual", item.get("user")),
                }
            )
        return tuple(items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": self.status,
            "status_label": self.label,
            "exit_code": self.exit_code,
            "module": self.module,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "contract_source": self.contract_source,
            "contract_draft": dict(self.contract_draft),
            "plan_source": self.plan_source,
            "plan_evidence_level": self.plan_evidence_level,
            "comparable_checks": self.comparable_checks,
            "waveform_compared": self.waveform_compared,
            "comparison": self.comparison.to_dict(),
            "differences": [dict(item) for item in self.differences],
            "caveats": list(self.caveats),
            "artifacts": dict(self.artifacts),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def to_markdown(self) -> str:
        """可直接贴进 PR / Issue 的对比报告。

        结构固定为"结论 → 凭什么这么说 → 差异清单 → 这次没覆盖到什么"：
        评审最常问的三件事按这个顺序答完，省掉一轮往返。
        """

        lines = [
            f"# 行为对比：{self.module}",
            "",
            f"- **{self.label}**（`{self.status}`，退出码 {self.exit_code}）",
            f"- 基线：`{self.baseline}`",
            f"- 候选：`{self.candidate}`",
            "",
            "## 凭什么这么说",
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| 测试计划来源 | {'命令行提供' if self.plan_source == PLAN_PROVIDED else '离线确定性规划器生成'} |",
            f"| 期望值证据等级 | {self.plan_evidence_level} |",
            f"| 合约来源 | {'命令行提供（已确认）' if self.contract_source == CONTRACT_PROVIDED else '从基线 RTL 自动提取的**草稿**'} |",
            f"| 两侧可比的检查项 | {self.comparable_checks} |",
            f"| 逐拍波形是否比对 | {'是' if self.waveform_compared else '否'} |",
            "",
            "裁决只来自两次真实 Icarus 仿真：同一份测试计划、同一份合约，任何一个检查项或"
            "任何一个 DUT 可观测信号不同，就是行为差异。",
            "",
        ]
        differences = self.differences
        if differences:
            lines.extend(["## 差异清单", "", "| 类型 | 位置 | 基线 | 候选 | 说明 |", "|---|---|---|---|---|"])
            for item in differences[:50]:
                lines.append(
                    f"| {item['kind']} | {item['where']} | {item['expected']} | {item['actual']} | {item['message']} |"
                )
            if len(differences) > 50:
                lines.append(f"| … | 另有 {len(differences) - 50} 处 | | | 见 result.json |")
            lines.append("")
        else:
            lines.extend(["## 差异清单", "", "没有观测到差异。", ""])

        lines.extend(["## 这次没覆盖到什么", ""])
        if self.caveats:
            lines.extend(f"- {item}" for item in self.caveats)
        else:
            lines.append("- 无额外保留意见。")
        lines.extend(["", self.comparison.disclaimer, ""])
        return "\n".join(lines)


def _read_rtl(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"RTL 文件是空的：{path}")
    return text


def _resolve_module(explicit: str | None, baseline_text: str, contract: DutContract) -> str:
    """确定要比对的模块名；显式给了就用，否则用合约里的模块名。"""

    if explicit:
        if not _IDENTIFIER.match(explicit):
            raise ValueError(f"模块名不合法：{explicit!r}")
        return explicit
    return contract.module


def _resolve_contract(
    baseline_text: str,
    contract: DutContract | Mapping[str, Any] | None,
    module: str | None,
) -> tuple[DutContract, str, dict[str, Any], list[str]]:
    """合约：给了解析给定的，没给就从基线 RTL 提一份**草稿**（并如实标注）。"""

    if contract is not None:
        resolved = contract if isinstance(contract, DutContract) else DutContract.from_dict(dict(contract))
        return resolved, CONTRACT_PROVIDED, resolved.to_dict(), []
    _, draft, warnings = extract_contract_draft(baseline_text, module_name=module)
    resolved = DutContract.from_dict(draft)
    return resolved, CONTRACT_FROM_DRAFT, draft, list(warnings)


def _resolve_plan(
    plan: Any,
    contract: DutContract,
    module: str,
    *,
    vector_count: int | None,
) -> tuple[AITestPlan, str]:
    """计划：给了解析给定的，没给就用离线确定性规划器按合约生成。"""

    if plan is not None:
        if isinstance(plan, AITestPlan):
            return plan, PLAN_PROVIDED
        return AITestPlan.model_validate(plan), PLAN_PROVIDED
    provider = offline_provider(contract, design=module, **({} if vector_count is None else {"vector_count": vector_count}))
    # max_retries=0：离线规划器是确定性的，重试没有意义，失败就是真失败。
    return plan_tests(_DEFAULT_OBJECTIVE, module, provider, max_retries=0), PLAN_FROM_OFFLINE


def _plan_evidence_level(plan: AITestPlan, module: str) -> str:
    """这一轮的期望值是谁给的——口径与 `core/pipeline.py` 完全一致。"""

    if module in AUTHORITATIVE:
        return "reference_model"
    if any(getattr(vector, "expected", None) for vector in plan.vectors):
        return "ai_generated"
    if module in SUPPORTED:
        # 已建模但未逐拍对齐：只做诊断，不覆盖 AI 数字。
        return "ai_generated" if any(getattr(v, "expected", None) for v in plan.vectors) else "none_given"
    return "none_given"


def _decide_status(comparison_status: str, comparable_checks: int, waveform_compared: bool) -> str:
    """把底层对比状态翻译成三态结论，**重点是挡住"没有证据的一致"**。

    为什么需要这一步：离线规划器生成的计划只有激励、没有期望值，两侧因此只会产出数量相同的
    观察记录（`signal` 为空）。逐项比对会把它们判成"全等"，但一次比较都没发生——这是假通过。
    所以"一致"必须有证据支撑：要么有带期望值的可比检查项，要么逐拍波形真的比过。

    只吃一个状态字符串（而不是整个对比对象），是为了让这条规则能被单独钉住——
    它是本模块最容易被改错、也最容易造成假通过的一处。
    """

    if comparison_status == "different":
        return STATUS_DIFFERENT
    if comparison_status != "identical":
        return STATUS_INCONCLUSIVE
    if comparable_checks > 0 or waveform_compared:
        return STATUS_IDENTICAL
    return STATUS_INCONCLUSIVE


def _collect_caveats(
    comparison: BehaviorCompareResult,
    contract_source: str,
    comparable_checks: int,
    waveform_compared: bool,
) -> list[str]:
    caveats: list[str] = []
    if contract_source == CONTRACT_FROM_DRAFT:
        caveats.append(
            "**合约是从基线 RTL 自动提取的草稿**：端口与位宽来自 `module` 头，通常可信；"
            "复位极性、同步/异步是猜的。两侧跑在同一套草稿测试台下，因此"
            "「两侧不同」仍然可信，而「两侧一致」的覆盖范围可能因此变窄——"
            "要提高置信度请用 `--contract` 提供确认过的合约。"
        )
    if comparable_checks == 0:
        caveats.append(
            "**测试计划没有产生任何带期望值的检查项**（本轮只有激励与波形），"
            "因此逐项比对是空的，结论完全依赖逐拍波形。"
        )
    if not waveform_compared:
        reason = comparison.waveform.get("reason") or comparison.waveform.get("error") or "未知原因"
        caveats.append(f"**逐拍波形没有比对成功**（{reason}），本次只有逐检查项比对。")

    truncated = [
        side
        for side, result in (("基线", comparison.reference), ("候选", comparison.user))
        if (result.simulation.config.get("vcd_analysis") or {}).get("truncated")
    ]
    if truncated:
        caveats.append(
            "**波形记录被截断**（" + "、".join(truncated) + "）：变化数超过采样上限，"
            "靠后的时间点没有参与比对，可能漏掉差异。"
        )

    waveform = comparison.waveform
    if not waveform.get("signal_sets_match", True) and not waveform.get("extra_signals_are_internal_only", False):
        caveats.append(
            "**两侧可观测信号集合不同**："
            + (", ".join(waveform.get("reference_only_signals", [])) or "无")
            + " / "
            + (", ".join(waveform.get("user_only_signals", [])) or "无")
            + "。端口层面的差异会直接影响可用性。"
        )
    if comparison.status == "records_identical_waveform_unavailable":
        caveats.append("逐检查项一致，但波形不可用，因此不能排除波形层面的差异。")
    return caveats


def _count_comparable(comparison: BehaviorCompareResult) -> int:
    """两侧都带 `signal` 的记录才是"真的比对过"的检查（与页面/报告同口径）。"""

    user = sum(1 for record in comparison.user.simulation.records if getattr(record, "signal", None))
    reference = sum(1 for record in comparison.reference.simulation.records if getattr(record, "signal", None))
    return min(user, reference)


def verify_diff(
    baseline_rtl: str | Path,
    candidate_rtl: str | Path,
    output_dir: str | Path,
    *,
    contract: DutContract | Mapping[str, Any] | None = None,
    plan: Any = None,
    module: str | None = None,
    allowed_roots: Sequence[str | Path] | None = None,
    iverilog_path: str | Path | None = None,
    vvp_path: str | Path | None = None,
    include_dirs: Sequence[str | Path] = (),
    defines: Sequence[str] = (),
    timeout_seconds: float = 30.0,
    language: str = "2012",
    emit_vcd: bool = True,
    vector_count: int | None = None,
) -> VerifyDiffResult:
    """把"两份 RTL 行为是否一致"四步压成一步。

    参数里 ``contract`` 与 ``plan`` 都可选：不给就分别从基线 RTL 提取草稿、用离线确定性
    规划器生成。两条回退路径都会写进结论的"凭什么这么说"与 ``caveats``，不会静默降级。
    """

    baseline = Path(baseline_rtl)
    candidate = Path(candidate_rtl)
    if not baseline.is_file():
        raise ValueError(f"基线 RTL 不存在：{baseline}")
    if not candidate.is_file():
        raise ValueError(f"候选 RTL 不存在：{candidate}")

    baseline_text = _read_rtl(baseline)
    _read_rtl(candidate)  # 候选也要能读、非空，否则失败原因会伪装成"行为不同"

    resolved_contract, contract_source, draft, draft_warnings = _resolve_contract(
        baseline_text, contract, module
    )
    resolved_module = _resolve_module(module, baseline_text, resolved_contract)
    resolved_plan, plan_source = _resolve_plan(plan, resolved_contract, resolved_module, vector_count=vector_count)

    root = Path(output_dir)
    comparison = compare_rtl_behavior(
        resolved_plan,
        resolved_contract,
        candidate,
        baseline,
        root,
        allowed_roots=allowed_roots,
        iverilog_path=iverilog_path,
        vvp_path=vvp_path,
        include_dirs=include_dirs,
        defines=defines,
        timeout_seconds=timeout_seconds,
        language=language,
        emit_vcd=emit_vcd,
    )

    comparable_checks = _count_comparable(comparison)
    waveform_compared = comparison.waveform.get("status") in {"identical", "different"}
    status = _decide_status(comparison.status, comparable_checks, waveform_compared)
    caveats = list(_collect_caveats(comparison, contract_source, comparable_checks, waveform_compared))
    caveats.extend(f"合约草稿提示：{item}" for item in draft_warnings if "draft only" not in item)

    result = VerifyDiffResult(
        status=status,
        module=comparison.module,
        baseline=str(baseline),
        candidate=str(candidate),
        contract_source=contract_source,
        plan_source=plan_source,
        plan_evidence_level=_plan_evidence_level(resolved_plan, resolved_module),
        comparable_checks=comparable_checks,
        waveform_compared=waveform_compared,
        comparison=comparison,
        contract_draft=draft,
        caveats=tuple(caveats),
        artifacts={
            "dir": str(root),
            "json": str(root / "verify_diff.json"),
            "markdown": str(root / "verify_diff.md"),
            "baseline_run": str(comparison.reference.simulation.artifacts.get("run_dir", "")),
            "candidate_run": str(comparison.user.simulation.artifacts.get("run_dir", "")),
        },
    )

    root.mkdir(parents=True, exist_ok=True)
    (root / "verify_diff.json").write_text(result.to_json() + "\n", encoding="utf-8")
    (root / "verify_diff.md").write_text(result.to_markdown() + "\n", encoding="utf-8")
    if contract_source == CONTRACT_FROM_DRAFT:
        # 草稿单独落盘，方便用户改完再用 --contract 回灌——不这样做的话，草稿只存在于
        # 内存里，用户想"确认一下"都没有对象可确认。
        (root / "contract.draft.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return result
