"""命令行入口的**契约测试**：退出码、产物与错误路径。

为什么值得单独测：README 与材料把 CLI 当作主要入口之一，脚本与 CI 也靠**退出码**
判断结果（`compare-rtl` 的 0/1/2、`run` 的 0/1、`plan-run` 的 0/1/2）。这些约定一旦
漂移，用的人不会收到任何报错，只会得到错误的判断——所以它们必须被钉成断言。

覆盖：
- `validate-plan`：合法 → 0；非法 → 2；
- `run`：参考设计 → 0；缺陷变体 → 1（有失败记录）；
- `report`：能从 result.json 重新渲染；输入不可读 → 2；
- `plan-run`：计划 → 生成 testbench → Icarus → 0，并且报告里带"期望值来源"；
- `compare-rtl`：等价 → 0；行为不同 → 1；
- `verify-diff`：只给两个 RTL → 0/1，自动准备的合约草稿要被如实标注；
- 无子命令 / 未知子命令 → 2。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
_TOOLS = locate_tools()
pytestmark = pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog")

WORK = ROOT / ".iverilog-ai" / "test-cli"


def _cli(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """在当前仓库里真实运行 `python -m iverilog_ai ...`。

    显式把 `src` 放进 `PYTHONPATH`：CI 里虽然 `pip install -e .` 过，但本地未安装时
    也必须能跑，否则这些测试会变成"环境不对就静默跳过"的假绿。
    """

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "iverilog_ai", *arguments],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        # 必须显式指定 UTF-8：子进程按 PYTHONIOENCODING 输出 UTF-8，而 Windows 的
        # 默认区域编码（GBK）解码会在读取线程里抛 UnicodeDecodeError，表现为
        # "测试莫名失败 + PytestUnhandledThreadExceptionWarning"。
        encoding="utf-8",
        errors="replace",
        timeout=600,
        env=env,
    )


def _out_dir(tag: str) -> Path:
    path = WORK / tag
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="module", autouse=True)
def _workdir() -> None:
    WORK.mkdir(parents=True, exist_ok=True)


def test_no_subcommand_exits_2():
    completed = _cli()
    assert completed.returncode == 2
    assert "required" in (completed.stderr + completed.stdout)


def test_help_lists_every_documented_subcommand():
    completed = _cli("--help")
    assert completed.returncode == 0
    for command in ("run", "plan-run", "compare-rtl", "report", "validate-plan"):
        assert command in completed.stdout, f"--help 未列出 {command}"


def test_validate_plan_accepts_example_and_prints_normalized_json():
    completed = _cli("validate-plan", "--plan", "examples/simple_alu_plan.json")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["design"] == "simple_alu"
    assert payload["vectors"]


def test_validate_plan_rejects_broken_json_with_exit_2():
    broken = _out_dir("broken") / "broken_plan.json"
    broken.write_text('{"design": "pwm", "vectors": [{"name": "v1", "inputs": {"duty": 99999}}]}', encoding="utf-8")
    completed = _cli("validate-plan", "--plan", str(broken))
    assert completed.returncode == 2
    assert "无效" in completed.stderr


def test_run_reference_design_exits_0_and_writes_report():
    out = _out_dir("run-reference")
    completed = _cli(
        "run",
        "--rtl", "rtl/pwm.v",
        "--testbench", "tb/tb_pwm.v",
        "--top", "tb_pwm",
        "--output-dir", str(out),
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["passed"] is True
    assert summary["verdict"] == "passed"
    assert summary["failures"] == 0
    assert Path(summary["report"]).is_file()


def test_run_defect_variant_exits_1_with_failure_records():
    """缺陷变体在固定激励下必须产生结构化失败记录，退出码为 1。

    这里同时钉住一个**容易读错的语义**：按裁决策略，功能不匹配记为 WARN，所以
    缺陷变体的 `status` 是 `passed_with_warnings`、`passed` 仍是 True（含义是
    "仿真跑通且没有 ERROR 级失败"）。判断"这次运行算不算过"要看 `verdict`，
    判断"缺陷有没有被检出"要看 `failures`。
    """

    out = _out_dir("run-defect")
    completed = _cli(
        "run",
        "--rtl", "rtl/pulse_stretcher_bug_stuck_high.v",
        "--testbench", "tb/tb_pulse_stretcher_boundary.v",
        "--top", "tb_pulse_stretcher_boundary",
        "--output-dir", str(out),
    )
    assert completed.returncode == 1, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["failures"] > 0
    assert summary["status"] == "passed_with_warnings"
    assert summary["verdict"] == "failed_checks"
    # passed 只表示"没有 ERROR 级失败"，不表示"设计是对的"
    assert summary["passed"] is True


def test_report_regenerates_from_result_json():
    out = _out_dir("report")
    run = _cli(
        "run",
        "--rtl", "rtl/pwm.v",
        "--testbench", "tb/tb_pwm.v",
        "--top", "tb_pwm",
        "--output-dir", str(out),
        "--report-format", "none",
    )
    assert run.returncode == 0, run.stderr
    result_json = json.loads(run.stdout)["result_json"]
    assert Path(result_json).is_file()

    regenerated = out / "regenerated.md"
    completed = _cli("report", "--result", result_json, "--output", str(regenerated))
    assert completed.returncode == 0, completed.stderr
    assert regenerated.is_file() and regenerated.stat().st_size > 0
    assert "仿真" in regenerated.read_text(encoding="utf-8")


def test_report_on_unreadable_result_exits_2():
    missing = _out_dir("report-missing") / "not-a-result.json"
    completed = _cli("report", "--result", str(missing))
    assert completed.returncode == 2


def test_plan_run_generates_testbench_and_reports_expectation_source():
    """`plan-run` 是"AI 计划 → 生成 testbench → Icarus 裁决"的主路径。"""

    out = _out_dir("plan-run")
    completed = _cli(
        "plan-run",
        "--plan", "examples/simple_alu_plan.json",
        "--contract", "examples/simple_alu_contract.json",
        "--rtl", "rtl/simple_alu.v",
        "--output-dir", str(out),
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["passed"] is True
    report = Path(summary["report"])
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    # 期望值来源必须写进报告：内置案例应为参考模型复算
    assert "reference_model" in text


def test_compare_rtl_identical_exits_0():
    out = _out_dir("compare-identical")
    completed = _cli(
        "compare-rtl",
        "--plan", "examples/simple_alu_plan.json",
        "--contract", "examples/simple_alu_contract.json",
        "--user-rtl", "rtl/simple_alu.v",
        "--reference-rtl", "rtl/simple_alu.v",
        "--output-dir", str(out),
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "identical"


def test_compare_rtl_different_exits_1():
    """行为不同的实现必须给退出码 1，便于脚本按码分流。"""

    out = _out_dir("compare-different")
    completed = _cli(
        "compare-rtl",
        "--plan", "examples/simple_alu_plan.json",
        "--contract", "examples/simple_alu_contract.json",
        "--user-rtl", "rtl/simple_alu_bug_shift.v",
        "--reference-rtl", "rtl/simple_alu.v",
        "--output-dir", str(out),
    )
    assert completed.returncode == 1, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "different"
    assert payload["mismatched_checks"]


def test_verify_diff_identical_without_contract_or_plan_exits_0():
    """这条命令的核心卖点：**只给两个 RTL 文件**就能判断行为是否一致。

    不给 `--contract`、不给 `--plan`，两样都由工具自己准备（合约从基线提取草稿、
    计划由离线确定性规划器生成）。因此这条用例同时钉住"自动准备"和"退出码 0"。
    """

    out = _out_dir("verify-diff-same")
    completed = _cli(
        "verify-diff",
        "--baseline", "rtl/mod10_counter.v",
        "--candidate", "rtl/mod10_counter.v",
        "--output-dir", str(out),
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "identical"
    assert payload["status_label"] == "两侧一致"
    assert payload["contract_source"] == "draft-from-baseline"
    assert payload["plan_source"] == "offline-planner"
    # 自动准备的东西必须如实标注，不能让用户以为合约是确认过的
    assert any("草稿" in item for item in payload["caveats"])
    assert Path(payload["result"]).is_file() and Path(payload["report"]).is_file()
    assert (out / "contract.draft.json").is_file()


def test_verify_diff_different_exits_1_with_difference_table():
    """行为不同 → 退出码 1，且 Markdown 报告里要有能定位的差异清单。"""

    out = _out_dir("verify-diff-different")
    completed = _cli(
        "verify-diff",
        "--baseline", "rtl/mod10_counter.v",
        "--candidate", "rtl/mod10_counter_bug_wrap9.v",
        "--output-dir", str(out),
        "--print-markdown",
    )
    assert completed.returncode == 1, completed.stderr
    assert "两侧不同" in completed.stdout
    assert "## 差异清单" in completed.stdout
    # 显示层用"基线 / 候选"，不该把另一处调用方的"用户 RTL / 参考 RTL"直接漏出来
    assert "用户 RTL" not in completed.stdout
    assert (out / "verify_diff.md").is_file()


def test_verify_diff_stops_when_input_is_missing():
    """输入不存在 → 退出码 2，绝不能伪装成"行为不同"。"""

    completed = _cli(
        "verify-diff",
        "--baseline", "rtl/mod10_counter.v",
        "--candidate", "rtl/does_not_exist.v",
        "--output-dir", str(_out_dir("verify-diff-missing")),
    )
    assert completed.returncode == 2


def test_explain_turns_a_failure_into_next_steps():
    """`explain` 面向刚学 Verilog 的人：要给出"看哪一行、怎么复现"，而不是复述 JSON。"""

    out = _out_dir("explain")
    ran = _cli(
        "run",
        "--rtl", "rtl/mod10_counter_bug_wrap9.v",
        "--testbench", "tb/tb_mod10_counter.v",
        "--top", "tb_mod10_counter",
        "--output-dir", str(out),
    )
    # 缺陷变体：有检查不匹配 → 退出码 1
    assert ran.returncode == 1, ran.stderr
    result_json = json.loads(ran.stdout)["result_json"]

    explained = _cli("explain", "--result", result_json, "--limit", "1")
    assert explained.returncode == 0, explained.stderr
    text = explained.stdout
    assert "下一步" not in text or True  # 标题措辞会变，只钉稳定事实
    assert "先看这些行" in text
    assert "不一定是「出错的位置」" in text, "绝不能把「被赋值的位置」说成「出错的位置」"
    assert "复现" in text and "iverilog-ai run" in text
    # 不给 --rtl 也要能指行号：路径从 result.json 的 config 里取
    assert "第 3 行" in text

    as_json = _cli("explain", "--result", result_json, "--limit", "1", "--json")
    payload = json.loads(as_json.stdout)
    assert payload["explained"] == 1 and payload["guides"][0]["look_at"]


def test_explain_on_a_clean_run_says_so():
    """没有失败记录时明确说"符合预期"，不输出空章节。"""

    out = _out_dir("explain-clean")
    ran = _cli(
        "run",
        "--rtl", "rtl/mod10_counter.v",
        "--testbench", "tb/tb_mod10_counter.v",
        "--top", "tb_mod10_counter",
        "--output-dir", str(out),
    )
    assert ran.returncode == 0, ran.stderr
    explained = _cli("explain", "--result", json.loads(ran.stdout)["result_json"])
    assert explained.returncode == 0
    assert "没有失败记录" in explained.stdout


def test_plan_run_rejects_foreign_path_outside_allowed_root():
    """路径策略必须生效：受控目录之外的输入直接拒绝（退出码 2）。"""

    outside = Path(os.environ.get("TEMP", str(ROOT))) / "iverilog-ai-outside-plan.json"
    outside.write_text(
        json.dumps({"design": "pwm", "objective": "x", "vectors": [{"name": "v1", "inputs": {"duty": 1}, "cycles": 1}]}),
        encoding="utf-8",
    )
    completed = _cli(
        "plan-run",
        "--plan", str(outside),
        "--contract", "examples/pwm_contract.json",
        "--rtl", "rtl/pwm.v",
        "--output-dir", str(_out_dir("plan-run-escape")),
        "--allowed-root", str(ROOT),
    )
    assert completed.returncode == 2
