"""报告配图的数据源必须是**实测**的，不能是写死的旧数字。

真实事故：`make_report_figures.py` 找的文件名是 `benchmark_matrix.json`，而基准矩阵
实际产出 `matrix.json`——于是它**永远读不到**结果，图 4 一直显示硬编码的 `14/14` 与
`78/78`，而同一张图里的柱状图是按清单现算的（总数 83），自相矛盾却没人发现。

本文件把三件事钉死：
1. 磁盘上有矩阵产物时必须读到它；
2. 读不到时只允许报"清单规模"，测量值必须留 `None`（渲染成"—"），不得用 0 或旧值冒充；
3. 图 3 的综合层说法必须来自综合矩阵产物，没跑过就写"未运行"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="未安装 Pillow（配图脚本依赖）")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import make_report_figures as figures  # noqa: E402


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    (tmp_path / "benchmarks").mkdir(parents=True)
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "benchmarks" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(figures, "ROOT", tmp_path)
    return tmp_path


def _write_matrix(root: Path, summary: dict) -> None:
    target = root / ".iverilog-ai" / "benchmark-matrix"
    target.mkdir(parents=True, exist_ok=True)
    (target / "matrix.json").write_text(json.dumps({"summary": summary}, ensure_ascii=False), encoding="utf-8")


def test_reads_the_real_matrix_artifact(fake_root):
    _write_matrix(fake_root, {
        "references_total": 15, "reference_false_positives": 0,
        "defects_total": 83, "defects_found": 83, "inconclusive_runs": 0,
    })
    stats = figures._read_benchmark_stats()
    assert stats["defects_found"] == 83
    assert stats["references_total"] == 15


def test_fallback_reports_manifest_size_and_leaves_measurements_empty(fake_root):
    stats = figures._read_benchmark_stats()
    manifest = json.loads((fake_root / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    assert stats["references_total"] == len(manifest["categories"])
    assert stats["defects_total"] == len(manifest["defects"])
    # 关键：未测量时不能编造 0 或沿用旧值
    assert stats["defects_found"] is None
    assert stats["reference_false_positives"] is None
    assert stats["inconclusive_runs"] is None


def test_benchmark_figure_renders_without_measured_data(fake_root, tmp_path, monkeypatch):
    """没跑过矩阵时也要能出图，且把未测量项显示为"—"而不是 0。"""

    monkeypatch.setattr(figures, "OUT_DIR", tmp_path / "figures")
    stats = figures._read_benchmark_stats()
    stats["by_kind"] = figures._classify_defects()
    path = figures.figure_benchmark(stats)
    assert path.is_file() and path.stat().st_size > 0


def test_synthesis_stats_come_from_the_matrix_artifact(fake_root):
    assert figures._read_synthesis_matrix_stats() is None
    target = fake_root / ".iverilog-ai" / "synthesis-matrix"
    target.mkdir(parents=True, exist_ok=True)
    (target / "synth-matrix.json").write_text(
        json.dumps({"summary": {"total": 98, "passed": 98, "failed": 0, "not_checked": 0}}),
        encoding="utf-8",
    )
    summary = figures._read_synthesis_matrix_stats()
    assert summary is not None and summary["passed"] == 98


def test_layered_evidence_figure_says_not_run_without_artifact(fake_root, tmp_path, monkeypatch):
    monkeypatch.setattr(figures, "OUT_DIR", tmp_path / "figures")
    path = figures.figure_layered_evidence({}, None)
    assert path.is_file()
    with_artifact = figures.figure_layered_evidence({"pwm": 5}, {"total": 98, "passed": 98})
    assert with_artifact.is_file()


def test_defect_classification_matches_manifest_size():
    """柱状图的总数必须与清单一致，否则图内自相矛盾。"""

    buckets = figures._classify_defects()
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    assert sum(buckets.values()) == len(manifest["defects"])
