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
                    # 真实记录里 request_id = strategy/case/seed：一次计划请求的计划会被
                    # 同一案例的所有变体复用，因此多行共享同一个 request_id 与同一份 usage。
                    "request_id": f"online_ai-{case}-{seed}",
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
                # 每个案例每次重复一个计划请求（真实运行里 request_id = strategy/case/seed）
                "runs": online_runs, "plan_requests": len(case_defects) * repeats,
                "request_plan_valid_rate": 1.0,
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


def test_rejects_partially_finished_run(tmp_path):
    """中途落盘的记录（partial=true）必须被拒绝。

    长跑实验会增量写 strategy_matrix.json。若把它当完整结果对比，
    分母会悄悄变小，而表格看起来完全正常——这是最危险的一种"看起来对"。
    """

    reference = _matrix({"pwm": ["bug_a", "bug_b"]}, model="A")
    partial = _matrix({"pwm": ["bug_a", "bug_b"]}, model="B")
    partial["partial"] = True
    partial["total_units"] = 100
    partial["completed_units"] = 40
    one = _write(tmp_path, "modelA", reference)
    two = _write(tmp_path, "modelB", partial)
    output = tmp_path / "out.md"
    result = _run([one, two], output)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "partial" in result.stderr or "还没结束" in result.stderr
    assert not output.is_file()


def test_rejects_unequal_repeat_counts(tmp_path):
    """重复次数不同也不能对比：那会把"多跑几次"误读成"模型更强"。"""

    one = _write(tmp_path, "modelA", _matrix({"pwm": ["bug_a"]}, model="A"))
    two = _write(tmp_path, "modelB", _matrix({"pwm": ["bug_a"]}, model="B", repeats=5))
    output = tmp_path / "out.md"
    result = _run([one, two], output)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "重复次数" in result.stderr
    assert not output.is_file()


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


def test_token_totals_are_deduplicated_per_request(tmp_path):
    """同一请求被多个变体复用时，token 只能算一次。

    真实事故：usage 挂在每个变体行上，按行相加把 token 总量放大了"该案例变体数"倍
    （本机实测 13 倍）。这种错误不会报错，只会把成本说高一个数量级。
    """

    payload = {
        "partial": False,
        "total_units": 10,
        "completed_units": 10,
        "runs": [
            # 一次请求（seed=0）产生了 4 个变体行，每行都带同一份 usage
            {
                "strategy": "online_ai", "case": "pwm", "variant": variant, "seed": 0,
                "request_id": "online_ai-pwm-0", "defects_found": True, "plan_valid": True,
                "usage": {"prompt_tokens": 100, "completion_tokens": 900, "total_tokens": 1000},
            }
            for variant in ("reference", "bug_a", "bug_b", "bug_c")
        ]
        + [
            {"strategy": "fixed", "case": "pwm", "variant": "reference", "seed": 0,
             "defects_found": False, "usage": None},
        ],
        "summary": {
            "online_ai": {
                "runs": 4, "plan_requests": 1, "request_plan_valid_rate": 1.0,
                "reference_false_positives": 0, "reference_warn_mismatches": 0,
                "defects_total": 3, "defects_found": 3, "detection_rate": 1.0,
                "inconclusive_runs": 0, "mean_generation_ms": 1000,
                "mean_time_to_first_failure_ms": 100,
            }
        },
    }
    one = _write(tmp_path, "modelA", payload)
    output = tmp_path / "out.md"
    result = _run([one], output)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "1,000" in text, "4 行共享 1 次请求，总量应为 1,000 而不是 4,000"
    assert "4,000" not in text
    assert "| modelA | 1 |" in text, "带用量的请求数应为 1"
