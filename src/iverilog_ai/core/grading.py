"""批量批改：一次比对一整个目录的提交，并挑出需要人看的几对。

面向：**课程教师与助教**。他们的任务是"50 份作业判定要一致、学生不服要能解释、
还要防雷同"，而这三件事恰好都能用已有的能力回答：

1. **判定一致**：每份提交与标准实现跑**同一份**测试计划（同一合约、同一激励），
   结论由两次真实 Icarus 仿真逐项 + 逐拍比对得出，不因批改人不同而变；
2. **能解释**：每份的结论带上"凭什么这么说"（可比检查项、波形是否比对、差异清单），
   学生问起来可以直接把那一节给他看；
3. **防雷同**：两两做 token n-gram 相似度，**改名抄**与**直接抄**给两种不同的信号。

三条**必须写在前面**的话（这个模块最容易被误用成"自动判抄袭"）：

- **相似度高不是抄袭的证据。** 两份作业都照着同一份实验指导写，结构自然像。
  这里只把"值得看一眼"的几对挑出来，判不判仍然由人看代码、看过程记录。
- **行为一致不等于实现相同**，**行为不同也不等于错**——标准实现自己也可能有 bug。
  本模块回答的是"与标准实现像不像"，不是"对不对"。
- **不做打分。** 分数涉及课程政策（迟交、注释分、风格分），工具不该替教师决定。
  它给的是可复核的事实表，最终分由人给。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

from .contracts import DutContract
from .labels import diff_label
from .rtl_compare import source_similarity
from .verify_diff import (
    CONTRACT_FROM_DRAFT,
    STATUS_DIFFERENT,
    STATUS_IDENTICAL,
    STATUS_INCONCLUSIVE,
    prepare_diff_inputs,
    verify_diff,
)

__all__ = ["GradeReport", "GradeRow", "SimilarPair", "collect_submissions", "grade_submissions"]

RTL_SUFFIXES = (".v", ".sv")

DISCLAIMER = (
    "本表回答的是「与标准实现像不像」，**不是「对不对」**，也不构成任何抄袭判定："
    "相似度高可能只是都照着同一份实验指导写；行为一致也不代表实现相同。"
    "结论由两次真实 Icarus 仿真得出，逐项与逐拍可比，但**最终成绩与雷同判定由人作出**。"
)


@dataclass(frozen=True)
class GradeRow:
    """一份提交的对比结果。"""

    name: str
    path: str
    status: str
    label: str
    differences: int
    comparable_checks: int
    waveform_compared: bool
    error: str | None = None

    @property
    def needs_attention(self) -> bool:
        """需要人看的两种情况：行为不同，或者根本没比出结论。"""

        return self.status != STATUS_IDENTICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "label": self.label,
            "differences": self.differences,
            "comparable_checks": self.comparable_checks,
            "waveform_compared": self.waveform_compared,
            "needs_attention": self.needs_attention,
            "error": self.error,
        }


@dataclass(frozen=True)
class SimilarPair:
    """两两相似度里被挑出来的一对。"""

    left: str
    right: str
    raw: float
    normalized: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "raw": self.raw,
            "normalized": self.normalized,
            "note": self.note,
        }


@dataclass(frozen=True)
class GradeReport:
    """一次批量批改的完整结果。"""

    golden: str
    module: str
    contract_source: str
    plan_source: str
    plan_evidence_level: str
    rows: tuple[GradeRow, ...] = ()
    pairs: tuple[SimilarPair, ...] = ()
    artifacts: dict[str, str] = field(default_factory=dict)
    disclaimer: str = DISCLAIMER

    @property
    def identical(self) -> int:
        return sum(1 for item in self.rows if item.status == STATUS_IDENTICAL)

    @property
    def different(self) -> int:
        return sum(1 for item in self.rows if item.status == STATUS_DIFFERENT)

    @property
    def inconclusive(self) -> int:
        return sum(1 for item in self.rows if item.status not in {STATUS_IDENTICAL, STATUS_DIFFERENT})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "golden": self.golden,
            "module": self.module,
            "contract_source": self.contract_source,
            "plan_source": self.plan_source,
            "plan_evidence_level": self.plan_evidence_level,
            "summary": {
                "total": len(self.rows),
                "identical": self.identical,
                "different": self.different,
                "inconclusive": self.inconclusive,
                "similar_pairs": len(self.pairs),
            },
            "rows": [item.to_dict() for item in self.rows],
            "pairs": [item.to_dict() for item in self.pairs],
            "disclaimer": self.disclaimer,
            "artifacts": dict(self.artifacts),
        }

    def to_markdown(self) -> str:
        lines = [
            "# 批量批改结果",
            "",
            f"- 标准实现：`{self.golden}`（模块 `{self.module}`）",
            f"- 提交数：**{len(self.rows)}** —— 与标准行为一致 {self.identical}、"
            f"行为不同 {self.different}、未取得可比证据 {self.inconclusive}",
            f"- 测试计划：{'命令行提供' if self.plan_source == 'provided' else '离线确定性规划器生成'}"
            f"（期望值证据等级 {self.plan_evidence_level}）",
            f"- 合约：{'命令行提供' if self.contract_source != CONTRACT_FROM_DRAFT else '从标准 RTL 自动提取的草稿'}",
            "",
            f"> {self.disclaimer}",
            "",
            "## 逐份结果",
            "",
            "| 提交 | 结论 | 差异处数 | 可比检查项 | 波形 |",
            "|---|---|---:|---:|:---:|",
        ]
        for item in self.rows:
            if item.error:
                lines.append(f"| `{item.name}` | 无法对比 | — | — | — |")
                continue
            lines.append(
                f"| `{item.name}` | {item.label} | {item.differences} | {item.comparable_checks} | "
                f"{'已比对' if item.waveform_compared else '未比对'} |"
            )
        failed = [item for item in self.rows if item.error]
        if failed:
            lines.extend(["", "### 无法对比的提交", ""])
            for item in failed:
                lines.append(f"- `{item.name}`：{item.error}")
        lines.extend(["", "## 需要人看的两两相似度", ""])
        if not self.pairs:
            lines.append("没有超过阈值的相似对。")
        else:
            lines.extend(
                [
                    "| A | B | 逐字相似 | 归一化相似 | 该看什么 |",
                    "|---|---|---:|---:|---|",
                ]
            )
            for pair in self.pairs:
                lines.append(
                    f"| `{pair.left}` | `{pair.right}` | {pair.raw:.2f} | {pair.normalized:.2f} | {pair.note} |"
                )
            lines.extend(
                [
                    "",
                    "**怎么读这两列**：归一化相似度把所有非关键字标识符折叠成同一个记号，"
                    "所以「归一化高、逐字低」= 改了变量名但结构照搬；「两列都高」= 直接相同或仅小改；"
                    "「两列都低」= 各写各的。**任何一列高都不等于抄袭**，请配合过程记录判断。",
                ]
            )
        lines.append("")
        return "\n".join(lines)


def collect_submissions(directory: str | Path, *, recursive: bool = False) -> list[Path]:
    """收集目录下的 RTL 提交，按文件名排序（保证同一批结果可复现）。"""

    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"提交目录不存在：{root}")
    pattern = "**/*" if recursive else "*"
    files = [
        item for item in sorted(root.glob(pattern))
        if item.is_file() and item.suffix.lower() in RTL_SUFFIXES
    ]
    return files


def _similarity_note(raw: float, normalized: float) -> str:
    if normalized >= 0.85 and raw < 0.6:
        return "归一化高、逐字低：结构照搬但改了标识符——**最值得看一眼**"
    if raw >= 0.85:
        return "两列都高：直接相同或仅小改"
    return "需要人工确认"


def grade_submissions(
    directory: str | Path,
    golden_rtl: str | Path,
    output_dir: str | Path,
    *,
    contract: DutContract | Mapping[str, Any] | None = None,
    plan: Any = None,
    module: str | None = None,
    threshold: float = 0.75,
    recursive: bool = False,
    iverilog_path: str | Path | None = None,
    vvp_path: str | Path | None = None,
    timeout_seconds: float = 30.0,
) -> GradeReport:
    """批量把目录里的每份提交与标准实现做行为对比，并挑出相似的几对。

    ``threshold`` 只作用于**归一化相似度**（它才是"改名抄"的信号）；超过阈值就列进
    待看清单。这个值刻意偏保守——漏掉一对只是少一条线索，多报十对会让人不再看这张表。
    """

    golden = Path(golden_rtl)
    if not golden.is_file():
        raise ValueError(f"标准实现不存在：{golden}")
    submissions = [item for item in collect_submissions(directory, recursive=recursive) if item.resolve() != golden.resolve()]
    root = Path(output_dir)
    # 先建目录：下面的 allowed_roots 校验要求每个信任根都已经存在，
    # 否则第一次运行会在"输出目录还没建"上失败——批量场景里这会一次废掉全部提交。
    root.mkdir(parents=True, exist_ok=True)

    # 合约与计划只解析一次：批量场景里"每份各生成一次计划"既慢，也会让各次结果失去可比性。
    inputs = prepare_diff_inputs(golden, contract=contract, plan=plan, module=module)

    rows: list[GradeRow] = []
    sources: dict[str, str] = {}
    for index, item in enumerate(submissions):
        try:
            sources[item.name] = item.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            rows.append(
                GradeRow(
                    name=item.name, path=str(item), status=STATUS_INCONCLUSIVE,
                    label=diff_label(STATUS_INCONCLUSIVE), differences=0,
                    comparable_checks=0, waveform_compared=False, error=f"读取失败：{exc}",
                )
            )
            continue
        try:
            result = verify_diff(
                golden,
                item,
                root / item.stem,
                contract=inputs.contract,
                plan=inputs.plan,
                module=inputs.module,
                allowed_roots=(golden.parent, item.parent, root),
                iverilog_path=iverilog_path,
                vvp_path=vvp_path,
                timeout_seconds=timeout_seconds,
            )
            rows.append(
                GradeRow(
                    name=item.name,
                    path=str(item),
                    status=result.status,
                    label=result.label,
                    differences=len(result.differences),
                    comparable_checks=result.comparable_checks,
                    waveform_compared=result.waveform_compared,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 一份提交崩掉不该中断整批
            rows.append(
                GradeRow(
                    name=item.name, path=str(item), status=STATUS_INCONCLUSIVE,
                    label=diff_label(STATUS_INCONCLUSIVE), differences=0,
                    comparable_checks=0, waveform_compared=False, error=f"{type(exc).__name__}: {exc}",
                )
            )
        _ = index

    pairs: list[SimilarPair] = []
    names = sorted(sources)
    for left, right in combinations(names, 2):
        score = source_similarity(sources[left], sources[right])
        if score["normalized"] >= threshold or score["raw"] >= threshold:
            pairs.append(
                SimilarPair(
                    left=left, right=right,
                    raw=score["raw"], normalized=score["normalized"],
                    note=_similarity_note(score["raw"], score["normalized"]),
                )
            )
    pairs.sort(key=lambda item: item.normalized, reverse=True)

    report = GradeReport(
        golden=str(golden),
        module=inputs.module,
        contract_source=inputs.contract_source,
        plan_source=inputs.plan_source,
        plan_evidence_level=inputs.evidence_level,
        rows=tuple(rows),
        pairs=tuple(pairs),
        artifacts={"dir": str(root), "json": str(root / "grade.json"), "markdown": str(root / "grade.md")},
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "grade.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "grade.md").write_text(report.to_markdown() + "\n", encoding="utf-8")
    return report


def summarise(report: GradeReport) -> str:
    """一句话摘要，便于 CLI 打印与日志。"""

    return (
        f"{len(report.rows)} 份提交：与标准行为一致 {report.identical}、"
        f"行为不同 {report.different}、未取得可比证据 {report.inconclusive}；"
        f"待人工确认的相似对 {len(report.pairs)} 组"
    )
