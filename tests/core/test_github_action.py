"""GitHub Action 定义（`action.yml`）的静态门禁。

为什么值得测：Action 是给别人用的交付物，而它**在本机跑不起来**（需要 GitHub 的 runner）。
一旦写错，我们这里全是绿的、用户那边一步就炸——这类"只有用户会遇到的错"必须靠静态检查兜住：
语法、必填输入、每个 `run:` 是否带 `shell:`、产物路径与输出是否对得上。
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="未安装 PyYAML")

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "action.yml"


@pytest.fixture(scope="module")
def action() -> dict:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def test_action_file_is_valid_yaml(action: dict) -> None:
    assert isinstance(action, dict) and action.get("name") and action.get("description")


def test_action_is_composite_with_required_inputs(action: dict) -> None:
    """用 composite 而不是 Docker：调用方不必构建镜像，Icarus 走系统包管理器最省事。"""

    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert inputs["baseline"]["required"] is True
    assert inputs["candidate"]["required"] is True
    # 合约与计划必须是**可选**的——这正是这条命令存在的理由
    assert not inputs["contract"].get("required", False)
    assert not inputs["plan"].get("required", False)


def test_every_run_step_declares_a_shell(action: dict) -> None:
    """composite action 里每个 `run` 都必须显式给 `shell`，否则 GitHub 直接报错。"""

    for index, step in enumerate(action["runs"]["steps"]):
        if "run" in step:
            assert step.get("shell"), f"第 {index} 步有 run 但没有 shell：{step.get('name')}"


def test_pipeline_uses_verify_diff_with_optional_flags(action: dict) -> None:
    """核心步骤必须真的调 `verify-diff`，且可选参数只在非空时追加。"""

    body = "\n".join(step.get("run", "") for step in action["runs"]["steps"])
    assert "python -m iverilog_ai verify-diff" in body
    for flag in ("--baseline", "--candidate", "--output-dir", "--print-markdown"):
        assert flag in body, flag
    # 退出码是**结论**不是脚本错误：不能开 set -e，否则 1/2 会直接中断，报告写不出来
    assert "set +e" in body
    assert "set -e" not in body.replace("set +e", "")
    for flag in ("--contract", "--plan", "--module"):
        assert f'[ -n "${{{{ inputs.{flag[2:]} }}}}" ] && args+=({flag}' in body, flag


def test_nonzero_exit_still_writes_the_summary(action: dict) -> None:
    """结论为"不同/未取得可比证据"时也要写 job summary——那正是最需要看报告的时候。"""

    steps = action["runs"]["steps"]
    summary = next(step for step in steps if "summary" in step.get("name", "").lower() or "job summary" in step.get("name", ""))
    assert summary.get("if") == "always()"
    assert "GITHUB_STEP_SUMMARY" in summary["run"]


def test_outputs_are_wired_to_the_compare_step(action: dict) -> None:
    """outputs 必须指向真实存在的 step id，否则调用方拿到的是空字符串。"""

    ids = {step.get("id") for step in action["runs"]["steps"] if step.get("id")}
    assert "compare" in ids
    for name, spec in action["outputs"].items():
        value = spec["value"]
        assert "steps.compare.outputs." in value, (name, value)
        assert spec.get("description"), name


def test_artifacts_cover_the_report_and_the_contract_draft(action: dict) -> None:
    """上传的产物要包含报告与合约草稿：草稿是用户确认合约的唯一依据。"""

    upload = next(
        step for step in action["runs"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    )
    paths = upload["with"]["path"]
    assert "verify_diff.md" in paths
    assert "verify_diff.json" in paths
    assert "contract.draft.json" in paths
    assert upload["with"]["if-no-files-found"] == "warn"


def test_action_defines_no_write_scopes_by_itself(action: dict) -> None:
    """Action 自己不申请任何权限——需要写 PR 评论的调用方自己开 `pull-requests: write`。"""

    assert "permissions" not in action


def test_pr_comment_step_is_opt_in_and_never_fails_the_build(action: dict) -> None:
    """评论 PR 必须是**可选**的，且失败只警告。

    理由：`pull-requests: write` 要由调用方显式授予；没给就失败会让一个只想看结论的人
    连带把构建弄红——而结论本来就已经在 Job Summary 与 Artifacts 里了。
    """

    comment = next(
        step for step in action["runs"]["steps"]
        if "评论" in str(step.get("name", "")) and "run" in step
    )
    condition = str(comment["if"])
    assert "inputs.comment-on-pr == 'true'" in condition
    assert condition.startswith("${{ always()")
    assert comment.get("continue-on-error") is True
    assert comment.get("env", {}).get("GH_TOKEN") == "${{ github.token }}"
    # 原地更新而不是每次刷一条：靠固定标记找自己上一条评论
    assert "iverilog-ai-verify-diff" in comment["run"]
    assert "PATCH" in comment["run"]
    # 失败只警告
    assert "::warning::" in comment["run"]


def test_documented_example_matches_the_action_inputs(action: dict) -> None:
    """文档里的用法示例必须与 action 的真实输入名一致（示例写错等于没有文档）。"""

    doc = ROOT / "docs" / "upstream" / "verify-diff-action.md"
    assert doc.is_file(), "缺少用法文档"
    text = doc.read_text(encoding="utf-8")
    assert "uses:" in text
    for name in action["inputs"]:
        assert name in text, f"文档里没提到输入 {name}"
    for name in action["outputs"]:
        assert name in text, f"文档里没提到输出 {name}"
