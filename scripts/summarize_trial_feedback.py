"""校验并汇总本地试用反馈，生成可直接贴进 docs/trial/results.md 的 Markdown。

用法：

    python scripts/summarize_trial_feedback.py docs/trial/feedback-*.json

为什么要有这个脚本：试用材料如果靠人工誊抄，很容易在誊抄时被"顺手美化"。
脚本只做机械汇总与结构校验——**不改措辞、不筛掉负面结果**，原始记录仍留在各份
JSON 里。校验失败会明确指出是哪份文件的哪个字段不合法。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]

TASK_KEYS = ("task_1_benchmark", "task_2_ai_pipeline", "task_3_custom_rtl")
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "docs": 3}
VALID_STATUS = {"completed", "partial", "skipped"}
VALID_SEVERITY = set(SEVERITY_ORDER)


class FeedbackError(ValueError):
    """一份反馈文件的某个字段不合法。"""


def _require(condition: bool, path: Path, message: str) -> None:
    if not condition:
        raise FeedbackError(f"{path.name}: {message}")


def validate(payload: dict, path: Path) -> None:
    """结构校验。宁可吵，也不要让半成品反馈混进汇总。"""

    _require(payload.get("schema_version") == "1.0", path, "schema_version 必须为 '1.0'")
    trial = payload.get("trial") or {}
    _require(bool(trial.get("trial_id")), path, "trial.trial_id 不能为空")
    _require(bool(trial.get("date")), path, "trial.date 不能为空")
    _require(
        trial.get("verilog_experience") in {"none", "beginner", "intermediate", "advanced"},
        path,
        "trial.verilog_experience 取值非法",
    )
    _require(bool((payload.get("environment") or {}).get("os")), path, "environment.os 不能为空")
    for key in TASK_KEYS:
        task = payload.get(key) or {}
        _require(task.get("status") in VALID_STATUS, path, f"{key}.status 取值非法")
        if task.get("status") == "skipped":
            _require(bool(task.get("problems")), path, f"{key} 标记为 skipped 时必须说明原因（填 problems）")
    for index, problem in enumerate(payload.get("problems") or []):
        _require(problem.get("severity") in VALID_SEVERITY, path, f"problems[{index}].severity 取值非法")
        _require(bool(problem.get("what_happened")), path, f"problems[{index}].what_happened 不能为空")


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def summarize(payloads: list[tuple[Path, dict]]) -> str:
    lines: list[str] = []
    completed = {key: 0 for key in TASK_KEYS}
    durations: dict[str, list[float]] = {key: [] for key in TASK_KEYS}
    setup_clean = 0
    trust_yes = trust_no = 0
    compare_agree = compare_disagree = 0
    problems: list[tuple[str, Path, dict]] = []

    for path, payload in payloads:
        environment = payload.get("environment") or {}
        if not (environment.get("install_issues") or "").strip():
            setup_clean += 1
        for key in TASK_KEYS:
            task = payload.get(key) or {}
            if task.get("status") == "completed":
                completed[key] += 1
            duration = task.get("duration_minutes")
            if isinstance(duration, (int, float)):
                durations[key].append(float(duration))
        for problem in payload.get("problems") or []:
            problems.append((str(problem.get("severity")), path, problem))
        for key in TASK_KEYS:
            for problem in (payload.get(key) or {}).get("problems") or []:
                problems.append((str(problem.get("severity")), path, problem))

        trust = str((payload.get("task_1_benchmark") or {}).get("q2_do_you_trust_it", "")).strip()
        if trust:
            if trust.lower().startswith(("y", "是", "信")):
                trust_yes += 1
            else:
                trust_no += 1
        agree = str((payload.get("task_3_custom_rtl") or {}).get("q1_result_agree", "")).strip()
        if agree:
            if agree.lower().startswith(("y", "是", "对")):
                compare_agree += 1
            else:
                compare_disagree += 1

    total = len(payloads)
    lines.append(f"试用份数：**{total}**")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 准备阶段一次成功（未记录安装问题） | {setup_clean}/{total} |")
    for key, label in (
        ("task_1_benchmark", "任务 1（基准矩阵）完成"),
        ("task_2_ai_pipeline", "任务 2（AI 流程）完成"),
        ("task_3_custom_rtl", "任务 3（自定义 RTL）完成"),
    ):
        lines.append(f"| {label} | {completed[key]}/{total} |")
        median = _median(durations[key])
        lines.append(f"| {label}耗时中位数 | {'—' if median is None else f'{median} 分钟'} |")
    lines.append(f"| 表示相信基准数字 | {trust_yes}（不信 {trust_no}） |")
    lines.append(f"| 认同行为对比结论 | {compare_agree}（不认同 {compare_disagree}） |")
    lines.append("")

    lines.append("## 问题清单（按严重度）")
    lines.append("")
    if not problems:
        lines.append("未记录任何问题。")
    else:
        lines.append("| 严重度 | 来源 | 现象 | 期望 | 绕过方式 |")
        lines.append("|---|---|---|---|---|")
        for severity, path, problem in sorted(problems, key=lambda item: SEVERITY_ORDER.get(item[0], 9)):
            lines.append(
                f"| `{severity}` | {path.name} | {problem.get('what_happened', '')} "
                f"| {problem.get('expected', '')} | {problem.get('workaround', '')} |"
            )
    lines.append("")
    counts = {key: sum(1 for severity, _path, _p in problems if severity == key) for key in SEVERITY_ORDER}
    lines.append("严重度分布：" + "、".join(f"{key} {value}" for key, value in counts.items()))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验并汇总本地试用反馈")
    parser.add_argument("files", nargs="+", help="feedback-*.json 文件")
    args = parser.parse_args()

    payloads: list[tuple[Path, dict]] = []
    failures = 0
    for name in args.files:
        path = Path(name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[结构错误] {path}: 无法读取或解析：{exc}", file=sys.stderr)
            failures += 1
            continue
        try:
            validate(payload, path)
        except FeedbackError as exc:
            print(f"[结构错误] {exc}", file=sys.stderr)
            failures += 1
            continue
        payloads.append((path, payload))

    if payloads:
        print(summarize(payloads))
        print()
    print(f"有效 {len(payloads)} 份，无效 {failures} 份", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
