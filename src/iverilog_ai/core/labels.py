"""三层结论口径的**唯一**中文措辞表（运行层 / 比对层 / 结论层）。

为什么需要这个模块：`SimulationResult` 上的 ``status`` / ``passed`` / ``failures`` /
``verdict`` 四个字段里，``status`` 与 ``verdict`` 的取值**同名**（都叫 ``passed``），
于是同一份 JSON 里会同时出现 ``"status": "passed_with_warnings"``、
``"passed": true``、``"verdict": "failed_checks"`` 三个看起来互相矛盾的结论。
实测中这确实让读者把"检出 3 个缺陷的正常运行"读成"通过"，或者反过来把
"没有期望值的一轮"读成"功能已验证"。

处理办法不是改机器字段名（那会破坏已发布的 JSON 合约与下游脚本），而是给**每一层**
一套互不重叠的中文措辞，并在报告与页面里始终先写层名、再写该层的说法：

===========  ==========================  ==========================================
层           这一层回答的问题            字段
===========  ==========================  ==========================================
运行层        工具跑完了吗？              ``status``
比对层        逐项检查对上了几条？        ``passed`` / ``failures``
结论层        这份设计到底对不对？        ``verdict``
===========  ==========================  ==========================================

三层刻意不共用任何词：运行层说"运行完成 / 运行失败"，比对层说"比对不一致"，
结论层说"符合预期 / 检出设计问题"。看到"符合预期"就一定是设计结论，看到
"运行完成"就一定是工具状态。
"""
from __future__ import annotations

from typing import Any

#: 三层的正式名称与它们各自回答的问题（报告、页面、手册共用同一套说法）。
LAYER_NAMES: dict[str, dict[str, str]] = {
    "run": {"zh": "运行状态", "question": "工具跑完了吗？", "field": "status"},
    "compare": {"zh": "比对情况", "question": "逐项检查对上了几条？", "field": "passed / failures"},
    "design": {"zh": "设计结果", "question": "这份设计到底对不对？", "field": "verdict"},
}

#: 运行层（``ResultStatus``）的中文说法。刻意避开"通过/失败于设计"这类词。
RUN_STATUS_LABELS: dict[str, str] = {
    "passed": "运行完成",
    "passed_with_warnings": "运行完成（有告警）",
    "failed": "运行失败",
    "compile_failed": "编译失败",
    "timeout": "超时",
    "inconclusive": "无法判定",
    "configuration_error": "配置错误",
}

#: 结论层（``SimulationResult.verdict``）的中文说法，字段名固定显示为"设计结果"。
#:
#: ``failed`` 与 ``inconclusive`` 的区别必须写清：前者是**工具**出错（编译/执行/配置），
#: 与设计好坏无关；后者是这一次**没拿到可用证据**（超时、没有结构化记录）。
VERDICT_LABELS: dict[str, str] = {
    "passed": "符合预期",
    "failed_checks": "检出设计问题",
    "failed": "未得出结论（工具出错）",
    "inconclusive": "证据不足",
}

#: 比对层的两个字段说法。``passed`` 的真实含义只有一个：**没有 ERROR 级失败记录**。
#: 它不等于"设计对了"——功能不匹配按裁决策略记 WARN，所以缺陷变体也是 ``true``。
COMPARE_LABELS: dict[str, str] = {
    "passed": "无错误级失败",
    "failures": "比对不一致",
}

#: 期望值证据等级的中文说法（决定**结论有多可信**，与上面三层正交）。
EVIDENCE_LABELS: dict[str, str] = {
    "reference_model": "参考模型复算",
    "ai_generated": "AI 生成",
    "none_given": "未给出期望值",
}

#: **第四层**：两份 RTL 的对比结论（`core/verify_diff.py`）。
#:
#: 它回答的问题与"设计结果"不同——那边问"这份设计对不对"，这边问"两份实现一不一样"，
#: 因此单独一套说法，且刻意避开前三层用过的词（"一致"不会被误读成"设计正确"）。
#: 第三态不叫"无法判定"或"证据不足"，正是为了不和运行层/结论层撞词。
DIFF_LABELS: dict[str, str] = {
    "identical": "两侧一致",
    "different": "两侧不同",
    "inconclusive": "未取得可比证据",
}

#: 证据等级的最短解释，报告与页面直接用。
EVIDENCE_NOTES: dict[str, str] = {
    "reference_model": "期望值由与 RTL 逐拍对齐的确定性模型独立复算，AI 的数字不参与裁决",
    "ai_generated": "该设计没有逐拍对齐的参考模型，用的是 AI 写的期望值，AI 猜错会直接影响结论",
    "none_given": "这一轮既没有参考模型也没有 AI 期望值，只有激励与结构化断言起作用",
}


def _label(table: dict[str, str], value: Any, unknown_prefix: str) -> str:
    """取值 → 中文说法；取值不在表里时**不静默兜底**，而是显式标出未知。"""

    text = str(getattr(value, "value", value))
    return table.get(text, f"{unknown_prefix}（{text}）")


def run_status_label(value: Any) -> str:
    """运行层：``status`` → 中文说法（如 ``passed`` → ``运行完成``）。"""

    return _label(RUN_STATUS_LABELS, value, "未收录的运行状态")


def verdict_label(value: Any) -> str:
    """结论层：``verdict`` → 中文说法（如 ``failed_checks`` → ``检出设计问题``）。"""

    return _label(VERDICT_LABELS, value, "未收录的设计结果")


def evidence_label(value: Any) -> str:
    """期望值证据等级 → 中文说法。"""

    return _label(EVIDENCE_LABELS, value, "未收录的证据等级")


def diff_label(value: Any) -> str:
    """对比层：两份 RTL 的对比结论 → 中文说法（如 ``different`` → ``两侧不同``）。"""

    return _label(DIFF_LABELS, value, "未收录的对比结论")


def layered_conclusion(status: Any, verdict: Any, mismatches: int, *, error_failures: int = 0) -> str:
    """把三层拼成一句不会读错的话，用于报告、页面与 CLI 摘要。

    例：``运行状态：运行完成（有告警）；比对情况：3 条比对不一致（无错误级失败）；
    设计结果：检出设计问题。``
    """

    compare = (
        f"{mismatches} 条{COMPARE_LABELS['failures']}"
        + ("（含错误级失败）" if error_failures else "（无错误级失败）")
    )
    return (
        f"运行状态：{run_status_label(status)}；"
        f"比对情况：{compare}；"
        f"设计结果：{verdict_label(verdict)}。"
    )
