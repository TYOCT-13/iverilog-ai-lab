"""多模型对比脚本的回归测试（用合成数据，不联网）。

关键行为：
1. 案例集合不一致时必须**拒绝**对比，而不是把不可比的数据并排放进同一张表；
2. 逐案例的分母取自基准清单，不从运行记录反推；
3. 服务商没返回 usage 时如实标注，不推算金额。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "compare_models.py"


def _matrix(case_defects: dict[str, list[str]], *, model: str, repeats: int = 2,
            detected_ratio: float = 1.0, with_usage: bool = True) -> dict:
    runs = []
    summary_defects = total_defects = 0
    for case, defects in case_defects.items():
        for variant in defects:
            detected = (hash(variant) % 100) / 100 < detected_ratio
            total_defects += 1
            summary_defects += 1 if detected else 0
            for seed in range(repeats):
                runs.append({
                    "strategy": "online_ai", "case": case, "variant": variant, "seed": seed,
                    "defects_found": detected, "plan_valid": True,
                    # 只有在线策略会产生 token 消耗；fixed/random 的 usage 在真实数据里是 None，
                    # 夹具也必须如此，否则测不出"只汇总在线模型用量"这个行为。
                    "usage": {"prompt_tokens": 100, "completion_tokens": 900, "total_tokens": 1000}
                    if with_usage else None,
                })
        runs.append({"strategy": "fixed", "case": case, "variant": "reference", "seed": 0,
                     "defects_found": False, "usage": None})
    online_runs = sum(1 for row in runs if row["strategy"] == "online_ai")
    return {
        "runs": runs,
        "summary": {
            "online_ai": {
                "runs": online_runs, "plan_requests": len(case_defects), "request_plan_valid_rate": 1.0,
                "reference_false_positives": 0, "reference_warn_mismatches": 0,
                "defects_total": total_defects, "defects_found": summary_defects,
                "detection_rate": summary_defects / total_defects if total_defects else 0.0,
                "inconclusive_runs": 0, "mean_generation_ms": 1200, "mean_time_to_first_failure_ms": 500,
            },
            "fixed": {"defects_total": total_defects, "defects_found": total_defects // 2,
                      "detection_rate": 0.5, "reference_false_positives": 0, "inconclusive_runs": 0},
        },
        "model": model,
    }


def _write(directory: Path, name: str, payload: dict) -> Path:
    target = directory / f"model-compare-{name}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "strategy_matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return target


def _run(directories: list[Path], output: Path) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(item) for item in directories], "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=180,
    )


def test_rejects_incomparable_case_sets(tmp_path):
    """案例集合不同就不能并排比较——否则读者会以为差异来自模型。"""

    one = _write(tmp_path, "modelA", _matrix({"pwm": ["bug_a", "bug_b"]}, model="A"))
    two = _write(tmp_path, "modelB", _matrix({"pwm": ["bug_a"], "fifo": ["bug_c"]}, model="B"))
    output = tmp_path / "out.md"
    result = _run([one, two], output)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "不可比" in result.stderr
    assert not output.is_file(), "不可比时不应写出对比文档"


def test_renders_per_case_table_with_manifest_denominator(tmp_path):
    """逐案例表的分母必须等于清单里的缺陷数，而不是运行记录里的条数。"""

    cases = {"pwm": ["pwm_bug_inverted_polarity", "pwm_bug_off_by_one"]}
    one = _write(tmp_path, "modelA", _matrix(cases, model="A", detected_ratio=1.0))
    two = _write(tmp_path, "modelB", _matrix(cases, model="B", detected_ratio=0.0))
    output = tmp_path / "out.md"
    result = _run([one, two], output)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "多模型公平对比" in text
    assert "逐案例检出对比" in text
    # pwm 的缺陷数来自 benchmarks/manifest.json
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    pwm_defects = sum(1 for item in manifest["defects"] if item["type"] == "pwm")
    assert f"| pwm | {pwm_defects} |" in text


def test_marks_missing_usage_instead_of_estimating(tmp_path):
    payload = _matrix({"pwm": ["pwm_bug_off_by_one"]}, model="A", with_usage=False)
    one = _write(tmp_path, "modelA", payload)
    output = tmp_path / "out.md"
    result = _run([one], output)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "服务商未返回 usage" in text
    # 费用必须说明口径：价格表带来源与核验日期，未核验不给金额
    assert "未经核验的价格不给金额" in text
    assert "model_pricing.json" in text


def test_reports_token_totals_when_available(tmp_path):
    """有 usage 时汇总 token 总量。

    夹具里只有 `online_ai` 带 usage（真实数据里 fixed/random 的 usage 是 None），
    因此 1 个缺陷 × 2 次重复 = 2 次在线运行 → 合计 2,000 tokens。
    这条断言同时钉住"只汇总在线策略"这个行为：如果 fixed 被算进来，总量会变。
    """

    payload = _matrix({"pwm": ["pwm_bug_off_by_one"]}, model="A", with_usage=True)
    one = _write(tmp_path, "modelA", payload)
    output = tmp_path / "out.md"
    result = _run([one], output)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "token 用量" in text
    assert "2,000" in text, "应汇总 2 次在线运行各 1000 tokens"
    # 模型名取自目录名（model-compare-<name> → <name>），并只统计在线策略
    assert "| modelA | 2 |" in text


def test_missing_matrix_reports_clearly(tmp_path):
    empty = tmp_path / "model-compare-ghost"
    empty.mkdir()
    result = _run([empty], tmp_path / "out.md")
    assert result.returncode == 2
    assert "不存在" in result.stderr
