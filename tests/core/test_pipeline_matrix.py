"""离线 AI 路径矩阵（`scripts/run_pipeline_matrix.py`）的回归测试。

它回答的问题与基准矩阵不同：基准矩阵用手写 testbench，证明"缺陷能被检出"；
本矩阵用**生成出来的** testbench，证明"AI 路径在每个案例上都能跑通，而且期望值
来自参考模型"。两者都必须在 CI 里成立，否则"离线也能完整跑通"只是一句话。

这里只跑两个案例（完整 15 个由 CI 步骤 `run_pipeline_matrix.py` 跑），
既保证脚本本身可用，又不把单测拖慢。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from iverilog_ai.core.benchmark_cases import case_table
from iverilog_ai.core.toolchain import locate_tools

ROOT = Path(__file__).resolve().parents[2]
_TOOLS = locate_tools()
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(not _TOOLS.can_simulate, reason="未找到 Icarus Verilog")

import run_pipeline_matrix as matrix  # noqa: E402


WORK = ROOT / ".iverilog-ai" / "test-pipeline-matrix"


@pytest.fixture(scope="module")
def result() -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    return matrix.run_pipeline_matrix(
        ROOT,
        WORK,
        iverilog_path=_TOOLS.iverilog,
        vvp_path=_TOOLS.vvp,
        cases=["mod10_counter", "pulse_stretcher"],
    )


def test_output_dir_must_stay_inside_the_project(tmp_path):
    """产物目录必须在仓库内：避免脚本往仓库外写文件。"""

    with pytest.raises(ValueError, match="inside project_root"):
        matrix.run_pipeline_matrix(ROOT, tmp_path, cases=["pwm"])


def test_selection_covers_every_case_by_default():
    """不带 --case 时必须覆盖清单里的全部案例（而不是某个手抄子集）。"""

    table = case_table(ROOT)
    assert set(matrix.OBJECTIVES) == set(table), (
        "规划目标表与案例表不一致："
        f"缺少 {sorted(set(table) - set(matrix.OBJECTIVES))}，多余 {sorted(set(matrix.OBJECTIVES) - set(table))}"
    )


def test_plans_are_derived_from_the_case_table(result):
    for row in result["runs"]:
        assert Path(row["rtl"]).is_file() or (ROOT / row["rtl"]).is_file()


def test_every_selected_case_passes_with_authoritative_expectations(result):
    assert result["summary"]["total"] == 2
    assert result["summary"]["passed"] == 2, result["runs"]
    for row in result["runs"]:
        assert row["expectation_source"] == "reference_model", row
        assert row["testbench_generated"] is True, row
        assert row["coverage_present"] is True, row
        assert row["failures"] == 0, row
        assert row["records"] > 0, row
        assert row["verdict"] == "passed", row


def test_summary_is_written_to_disk(result):
    out = Path(result["output_dir"])
    assert (out / "pipeline-matrix.json").is_file()
    assert (out / "pipeline-matrix.md").is_file()
    assert "offline" in (out / "pipeline-matrix.md").read_text(encoding="utf-8").lower()
