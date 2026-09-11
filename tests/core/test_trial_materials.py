"""本地试用材料的回归测试。

覆盖两件事：
1. 反馈模板本身结构合法（否则试用者填完却汇总不了）；
2. 汇总脚本能正确校验与汇总，并且**不会**把不完整的反馈混进统计。

注意：这里用的样例反馈是**测试构造的假数据**，写进 `tests/` 而不是
`docs/trial/`，以免与真人试用结果混在一起。真实结果见 `docs/trial/results.md`。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "docs" / "trial" / "feedback_template.json"
SUMMARIZER = ROOT / "scripts" / "summarize_trial_feedback.py"


def _template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_template_is_valid_json_with_expected_shape():
    payload = _template()
    assert payload["schema_version"] == "1.0"
    for key in ("trial", "environment", "task_1_benchmark", "task_2_ai_pipeline", "task_3_custom_rtl", "overall", "problems"):
        assert key in payload, key
    # 三个任务都必须有 status 字段，否则汇总脚本无法判断是否完成
    for key in ("task_1_benchmark", "task_2_ai_pipeline", "task_3_custom_rtl"):
        assert "status" in payload[key], key


def test_template_does_not_ask_for_credentials():
    """反馈表绝不能引导试用者粘贴密钥。"""

    text = TEMPLATE.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "不要在本文件中粘贴任何 API 密钥" in text


def test_results_doc_stays_empty_until_real_trials():
    """在真人试用之前，结果文档不得出现编造的结论。"""

    text = (ROOT / "docs" / "trial" / "results.md").read_text(encoding="utf-8")
    assert "待收集" in text
    # 不得出现"反馈良好/一致好评"这类自说自话
    for forbidden in ("反馈良好", "一致好评", "用户满意度很高"):
        assert forbidden not in text, forbidden


def _filled_template(*, trial_id: str, install_issues: str = "") -> dict:
    """把模板补成一份"结构上填完了"的反馈，作为各用例的基线。

    模板本身各任务 `status` 为空占位，校验器会直接拒绝——所以任何用例都必须先
    走这一步，否则测的就不是自己那条规则了。
    """

    payload = _template()
    payload["trial"].update(
        {"trial_id": trial_id, "date": "2026-09-11", "tester_alias": trial_id, "verilog_experience": "beginner"}
    )
    payload["environment"].update(
        {"os": "Windows 11", "python_version": "3.12.7", "iverilog_version": "12.0", "install_issues": install_issues}
    )
    for key in ("task_1_benchmark", "task_2_ai_pipeline", "task_3_custom_rtl"):
        payload[key].update({"status": "completed", "duration_minutes": 8})
    payload["task_1_benchmark"].update({"q2_do_you_trust_it": "是"})
    payload["task_3_custom_rtl"].update({"q1_result_agree": "是"})
    payload["problems"] = []
    return payload


def _write_feedback(directory: Path, name: str, *, trial_id: str, skip_task: str | None = None,
                    severity: str = "major") -> Path:
    payload = _filled_template(trial_id=trial_id)
    payload["problems"] = [{"severity": severity, "task": "task_1_benchmark",
                            "what_happened": "矩阵耗时比预期久", "expected": "更快",
                            "workaround": "无", "reproducible": True}]
    if skip_task:
        payload[skip_task].update({"status": "skipped", "problems": [
            {"severity": "blocker", "task": skip_task, "what_happened": "环境装不上",
             "expected": "一键安装", "workaround": "放弃", "reproducible": True}]})
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run(paths: list[Path]) -> subprocess.CompletedProcess:
    """跑汇总脚本。

    必须固定子进程的输出编码：脚本打印中文，而 Windows 上子进程默认用本地代码页
    （GBK）编码，读回来按 UTF-8 解码会直接抛 UnicodeDecodeError。
    """

    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(SUMMARIZER), *[str(item) for item in paths]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=120,
    )


def test_summarizer_counts_completed_tasks(tmp_path):
    one = _write_feedback(tmp_path, "feedback-A.json", trial_id="A")
    two = _write_feedback(tmp_path, "feedback-B.json", trial_id="B", skip_task="task_3_custom_rtl")
    result = _run([one, two])
    assert result.returncode == 0, result.stderr
    assert "试用份数：**2**" in result.stdout
    assert "任务 1（基准矩阵）完成 | 2/2" in result.stdout
    assert "任务 3（自定义 RTL）完成 | 1/2" in result.stdout


def test_summarizer_rejects_malformed_feedback(tmp_path):
    path = tmp_path / "feedback-bad.json"
    payload = _filled_template(trial_id="bad")
    payload["trial"]["verilog_experience"] = "expert"          # 非法取值
    payload["task_1_benchmark"]["status"] = "done"             # 非法取值
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run([path])
    assert result.returncode == 1
    assert "结构错误" in result.stderr
    # 无效份数不得计入统计
    assert "试用份数" not in result.stdout


def test_summarizer_requires_reason_for_skipped_task(tmp_path):
    """跳过任务必须说明原因——否则"没做"会被静默算成"做了但没记"。"""

    path = tmp_path / "feedback-skip.json"
    payload = _filled_template(trial_id="C")
    payload["task_2_ai_pipeline"]["status"] = "skipped"        # 没填 problems
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run([path])
    assert result.returncode == 1
    assert "必须说明原因" in result.stderr


def test_summarizer_sorts_problems_by_severity(tmp_path):
    path = _write_feedback(tmp_path, "feedback-D.json", trial_id="D", severity="minor")
    result = _run([path])
    assert result.returncode == 0, result.stderr
    assert "严重度分布" in result.stdout
    assert "minor 1" in result.stdout
