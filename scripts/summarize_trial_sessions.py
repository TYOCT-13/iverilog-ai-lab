"""Validate v2 trial sessions and summarize assigned tasks without inventing data."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import glob
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

TASKS = {f"T{number:02d}" for number in range(1, 13)}
ROLES = {"novice", "developer", "reviewer", "reproducer", "api_user", "mobile_reader"}
STATUSES = ("completed", "partial", "blocked", "skipped", "missing_record")


class SessionError(ValueError):
    """Invalid or ambiguous session data; do not emit a partial success report."""


def _require(condition: bool, field: str, message: str) -> None:
    if not condition:
        raise SessionError(f"{field}: {message}")


def _object(parent: dict, key: str) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise SessionError(f"{key}: 必须是对象")
    return value


def _text(parent: dict, key: str, prefix: str = "", *, required: bool = True) -> None:
    value = parent.get(key)
    _require(isinstance(value, str) and (not required or bool(value.strip())), prefix + key, "必须是文本" + ("且非空" if required else ""))


def validate(payload: Any) -> None:
    """Validate one record explicitly marked human; missing assigned records remain unknown."""
    _require(isinstance(payload, dict), "record", "必须是对象")
    _require(payload.get("schema_version") == "2.0", "schema_version", "必须为 2.0")
    _require(payload.get("record_kind") == "human", "record_kind", "必须标记为 human")
    session = _object(payload, "session")
    for key in ("session_id", "date", "participant_alias"):
        _text(session, key, "session.")
    try:
        parsed_date = date.fromisoformat(session["date"])
        _require(parsed_date.isoformat() == session["date"], "session.date", "必须使用 YYYY-MM-DD 格式")
    except ValueError as exc:
        raise SessionError("session.date: 必须为有效的 YYYY-MM-DD 日期") from exc
    roles = session.get("roles")
    _require(isinstance(roles, list) and bool(roles) and all(isinstance(role, str) and role in ROLES for role in roles), "session.roles", "必须包含有效角色")
    assert isinstance(roles, list)
    _require(len(set(roles)) == len(roles), "session.roles", "不能重复")
    _require(session.get("development_relation") in ("external", "contributor", "team_member"), "session.development_relation", "取值非法")
    _require(session.get("visit") in ("first", "retest"), "session.visit", "取值非法")
    if session["visit"] == "retest":
        _text(session, "previous_session_id", "session.")
        _require(session["previous_session_id"] != session["session_id"], "session.previous_session_id", "不能指向本次会话")
    else:
        _require(session.get("previous_session_id") is None, "session.previous_session_id", "首次试用应为 null")
    _require(session.get("recording_basis") in ("contemporaneous", "retrospective"), "session.recording_basis", "取值非法")
    _text(session, "recording_note", "session.", required=session["recording_basis"] == "retrospective")
    build = _object(payload, "build")
    for key in ("version", "commit"):
        _text(build, key, "build.")
    _require(type(build.get("dirty")) is bool, "build.dirty", "必须是布尔值")
    environment = _object(payload, "environment")
    for key in ("os", "python_version", "iverilog_version", "browser", "viewport"):
        _text(environment, key, "environment.")
    for key, choices in {
        "device": {"desktop", "tablet", "mobile"},
        "execution_mode": {"independent_machine", "shared_host"},
        "entry": {"ui", "cli", "mixed"},
    }.items():
        _require(isinstance(environment.get(key), str) and environment[key] in choices, "environment." + key, "取值非法")
    consent = _object(payload, "consent")
    for key in ("anonymous_quote", "screen_recording"):
        _require(type(consent.get(key)) is bool, "consent." + key, "必须分别填写 true 或 false")
    assigned = payload.get("assigned_tasks")
    _require(isinstance(assigned, list) and bool(assigned) and all(isinstance(task, str) and task in TASKS for task in assigned), "assigned_tasks", "必须包含有效任务 ID")
    _require(len(set(assigned)) == len(assigned), "assigned_tasks", "不能重复")
    records = payload.get("task_records")
    _require(isinstance(records, list), "task_records", "必须是数组")
    seen = set()
    for index, task in enumerate(records):
        prefix = f"task_records[{index}]."
        _require(isinstance(task, dict), prefix, "必须是对象")
        task_id = task.get("task_id")
        _require(isinstance(task_id, str) and task_id in assigned, prefix + "task_id", "必须属于本次分配任务")
        _require(task_id not in seen, prefix + "task_id", "不能重复")
        seen.add(task_id)
        status = task.get("status")
        _require(status in STATUSES[:-1], prefix + "status", "取值非法")
        _text(task, "objective_result", prefix, required=status != "skipped")
        _text(task, "subjective_feedback", prefix, required=False)
        _text(task, "reason", prefix, required=status != "completed")
        duration = task.get("duration_seconds")
        method = task.get("duration_method")
        _require("duration_seconds" in task and method in ("measured", "estimated", "not_recorded"), prefix + "duration_method", "计时方式与用时字段必须明确")
        if duration is None:
            _require(method == "not_recorded", prefix + "duration_method", "没有用时时必须为 not_recorded")
        else:
            _require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0, prefix + "duration_seconds", "必须是大于零的有限数值或 null")
            _require(method in ("measured", "estimated") and status != "skipped", prefix + "duration_method", "已计时任务应注明 measured/estimated，skipped 不填执行用时")
        prompts = task.get("prompt_count")
        _require("prompt_count" in task and (prompts is None or type(prompts) is int and prompts >= 0), prefix + "prompt_count", "必须为非负整数或 null")
        assistance = task.get("assistance")
        _require(isinstance(assistance, list), prefix + "assistance", "必须是数组")
        for help_index, help_item in enumerate(assistance):
            _require(isinstance(help_item, dict), prefix + "assistance", "每条必须是对象")
            _require(help_item.get("kind") in ("hint", "explanation", "operator_action"), prefix + "assistance.kind", "取值非法")
            _text(help_item, "detail", prefix + f"assistance[{help_index}].")
        _require(prompts is None or prompts >= sum(item["kind"] == "hint" for item in assistance), prefix + "prompt_count", "不能少于已记录的提示条数")
        evidence = task.get("evidence")
        _require(isinstance(evidence, list) and all(isinstance(item, str) and bool(item.strip()) for item in evidence), prefix + "evidence", "必须是非空路径字符串组成的数组，也可留空数组")
    _text(payload, "overall_feedback", required=False)


def _task_summary(payloads: list[dict], task_id: str) -> dict[str, Any]:
    assigned = [payload for payload in payloads if task_id in payload["assigned_tasks"]]
    counts: Counter[str] = Counter()
    measured: list[float] = []
    estimated = missing_time = independent = assisted = unknown_help = 0
    for payload in assigned:
        task = next((row for row in payload["task_records"] if row["task_id"] == task_id), None)
        if task is None:
            counts["missing_record"] += 1
            continue
        counts[task["status"]] += 1
        if task["status"] != "completed":
            continue
        if task["duration_method"] == "measured":
            measured.append(float(task["duration_seconds"]))
        elif task["duration_method"] == "estimated":
            estimated += 1
        else:
            missing_time += 1
        if task["assistance"] or (task["prompt_count"] is not None and task["prompt_count"] > 0):
            assisted += 1
        elif task["prompt_count"] == 0:
            independent += 1
        else:
            unknown_help += 1
    return {
        "assigned_sessions": len(assigned),
        "assigned_people": len({p["session"]["participant_alias"] for p in assigned}),
        **{status: counts[status] for status in STATUSES},
        "completed_without_assistance": independent,
        "completed_with_assistance": assisted,
        "completed_assistance_unknown": unknown_help,
        "completed_measured_duration_samples": len(measured),
        "completed_measured_duration_median_seconds": statistics.median(measured) if measured else None,
        "completed_estimated_duration_samples": estimated,
        "completed_duration_missing": missing_time,
    }


def summarize(payloads: list[dict], *, public: bool = False) -> dict[str, Any]:
    eligible = []
    excluded = 0
    session_ids = set()
    for payload in payloads:
        _require(isinstance(payload, dict), "record", "必须是对象")
        kind = payload.get("record_kind")
        if kind in ("template", "synthetic"):
            excluded += 1
            continue
        validate(payload)
        session_id = payload["session"]["session_id"]
        _require(session_id not in session_ids, "session.session_id", "输入中存在重复会话，不能重复计数")
        session_ids.add(session_id)
        eligible.append(payload)
    withheld = sum(not p["consent"]["anonymous_quote"] for p in eligible) if public else 0
    selected = [p for p in eligible if not public or p["consent"]["anonymous_quote"]]
    people = {p["session"]["participant_alias"] for p in selected}
    feedback = []
    if public:
        for payload in selected:
            session = payload["session"]
            for task in payload["task_records"]:
                if task["subjective_feedback"].strip():
                    feedback.append({"participant_alias": session["participant_alias"], "session_id": session["session_id"], "task_id": task["task_id"], "text": task["subjective_feedback"]})
            if payload["overall_feedback"].strip():
                feedback.append({"participant_alias": session["participant_alias"], "session_id": session["session_id"], "task_id": "overall", "text": payload["overall_feedback"]})
    return {
        "schema_version": "2.0", "audience": "public_consented_only" if public else "internal",
        "record_basis": "validated_records_marked_human; not independent proof of participation",
        "people": len(people), "sessions": len(selected), "excluded_nonhuman_records": excluded,
        "withheld_without_quote_consent": withheld,
        "visits": {visit: sum(p["session"]["visit"] == visit for p in selected) for visit in ("first", "retest")},
        "development_relations_sessions": dict(Counter(p["session"]["development_relation"] for p in selected)),
        "execution_modes_sessions": dict(Counter(p["environment"]["execution_mode"] for p in selected)),
        "retrospective_sessions": sum(p["session"]["recording_basis"] == "retrospective" for p in selected),
        "task_denominator": "assigned session-task pairs, including partial, blocked, skipped and missing records",
        "duration_definition": "completed tasks with measured wall-clock seconds, including help/waits and excluding breaks between tasks; estimates and missing times excluded",
        "tasks": {task_id: _task_summary(selected, task_id) for task_id in sorted(TASKS)},
        "tasks_by_visit": {visit: {task_id: _task_summary([p for p in selected if p["session"]["visit"] == visit], task_id) for task_id in sorted(TASKS)} for visit in ("first", "retest")},
        "public_feedback": feedback,
    }


def markdown(summary: dict) -> str:
    lines = ["# 试用会话汇总", "", f"范围：{'仅同意匿名引用的记录，可供公开材料复核' if summary['audience'] != 'internal' else '内部统计，不包含反馈引文'}。", "", f"标记为真人且结构有效：{summary['people']} 人，{summary['sessions']} 次会话；首次 {summary['visits']['first']} 次，复测 {summary['visits']['retest']} 次，事后补填 {summary['retrospective_sessions']} 次。", "", f"模板 / 合成记录排除 {summary['excluded_nonhuman_records']} 份；公开模式因未同意引用而排除 {summary['withheld_without_quote_consent']} 份。", "", "人数按匿名代号去重；任务分母是分配到的会话任务数。未分配不计，部分完成、卡住、跳过、缺记录均保留。该脚本验证结构与标记，不替代真人参与的来源核对。"]
    for label, tasks in [("全部会话", summary["tasks"]), ("首次试用", summary["tasks_by_visit"]["first"]), ("复测", summary["tasks_by_visit"]["retest"])]:
        lines += ["", f"## {label}", "", "| 任务 | 分配次数 / 人数 | 完成 | 部分 | 卡住 | 跳过 | 缺记录 | 无协助完成 / 有协助 / 未知 | 完成实测秒数中位数（样本数） | 完成估计 / 缺时长 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for task_id, row in tasks.items():
            if not row["assigned_sessions"]:
                continue
            median = row["completed_measured_duration_median_seconds"]
            value = "—" if median is None else f"{median:g}"
            lines.append(f"| {task_id} | {row['assigned_sessions']} / {row['assigned_people']} | {row['completed']} | {row['partial']} | {row['blocked']} | {row['skipped']} | {row['missing_record']} | {row['completed_without_assistance']} / {row['completed_with_assistance']} / {row['completed_assistance_unknown']} | {value}（{row['completed_measured_duration_samples']}） | {row['completed_estimated_duration_samples']} / {row['completed_duration_missing']} |")
    lines += ["", "计时仅统计完成且使用实际计时的样本，包含求助和工具等待，不含任务间休息。估计、缺时长与未完成任务不混入完成耗时中位数；缺失不填零。首次和复测分别展示，不能把复测次数当作新增人数。", "", "开发关系（会话数）：" + json.dumps(summary["development_relations_sessions"], ensure_ascii=False), "", "运行模式（会话数）：" + json.dumps(summary["execution_modes_sessions"], ensure_ascii=False)]
    if summary["audience"] != "internal":
        lines += ["", "## 已授权的匿名反馈原文", ""]
        for feedback in summary["public_feedback"]:
            lines += [f"{feedback['participant_alias']} / {feedback['session_id']} / {feedback['task_id']}：", ""]
            # Quote each line so supplied Markdown cannot become report structure.
            lines += ["> " + line for line in feedback["text"].splitlines()] + [""]
        if not summary["public_feedback"]:
            lines.append("无可引用的反馈记录。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--public", action="store_true", help="exclude records without anonymous-quote consent")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=Path, help="new file only; otherwise write stdout")
    args = parser.parse_args(argv)
    try:
        paths: list[Path] = []
        seen_paths: set[Path] = set()
        for pattern in args.files:
            matches = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else [pattern]
            if not matches:
                raise SessionError(f"文件匹配为空：{pattern}")
            for name in matches:
                path = Path(name).resolve()
                if path not in seen_paths:
                    paths.append(path)
                    seen_paths.add(path)
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        summary = summarize(payloads, public=args.public)
        rendered = json.dumps(summary, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else markdown(summary)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, json.JSONDecodeError, SessionError) as exc:
        print(f"未生成汇总：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
