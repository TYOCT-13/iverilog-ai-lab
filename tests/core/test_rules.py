import json
from pathlib import Path

import pytest

from iverilog_ai.core.rules import (
    CONVENTIONS_PATH,
    conventions_context,
    conventions_enabled,
    rule_manifest,
    rules_context,
    rules_fingerprint,
)

ROOT = Path(__file__).parents[2]


def test_rule_manifest_is_fingerprinted():
    manifest = rule_manifest(ROOT, "sync_fifo")
    assert {item["file"] for item in manifest} == {
        "verification_rules/common.md",
        "verification_rules/sync_fifo.md",
        CONVENTIONS_PATH.as_posix(),
    }
    assert all(len(item["sha256"]) == 64 for item in manifest)
    context, again = rules_context(ROOT, "sync_fifo", {"module": "sync_fifo"})
    assert "单时钟 FIFO" in context
    assert rules_fingerprint(manifest) == rules_fingerprint(again)


def test_measured_conventions_enter_the_model_context():
    """实测开源约定必须真的进入发给模型的上下文，而不是只躺在 JSON 里。"""

    context, manifest = rules_context(ROOT, "pwm", {"module": "pwm"})
    assert "实测开源约定" in context
    # 出处必须随上下文一起给出，否则模型无从判断这些约定的来源与许可
    assert "verilog-axi" in context
    assert "alexforencich/verilog-axi" in context
    # 该条目的哈希必须进入指纹，约定变了指纹就变
    assert any(item["file"] == CONVENTIONS_PATH.as_posix() for item in manifest)


def test_conventions_can_be_disabled_for_control_experiments(monkeypatch):
    """能关掉，才能做"A/B 对比有无约定注入"的对照实验。"""

    monkeypatch.setenv("IVERILOG_AI_CONVENTIONS", "0")
    assert conventions_enabled() is False
    assert conventions_context(ROOT) == ""
    context, _manifest = rules_context(ROOT, "pwm", {"module": "pwm"})
    assert "实测开源约定" not in context


def test_context_always_carries_the_dut_contract():
    """约定注入与否都不影响合约必须出现在上下文里。"""

    context, _manifest = rules_context(ROOT, "pwm", {"module": "pwm", "ports": []})
    assert "--- DUT contract ---" in context
    assert '"module": "pwm"' in context


def test_rule_manifest_rejects_unsafe_case_names():
    with pytest.raises(ValueError):
        rule_manifest(ROOT, "../escape")


def test_context_stays_within_the_planner_limit():
    """上下文必须小于 `plan_tests` 的 20000 字符上限。

    这条是真事故的回归用例：`rule_manifest` 为了指纹追溯把
    `data/opensource_conventions.json`（36KB）也列了进去，而拼接逻辑按 manifest
    逐条读原文，于是整篇 JSON 被塞进上下文，直接让 `plan_tests` 抛
    "context must be text of at most 20000 characters"——流水线在真实模型路径上
    直接报错。真实注入的应是渲染后的几百字片段。
    """

    from iverilog_ai.ai.planner import CONTEXT_LIMIT  # 上限的唯一来源

    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest["categories"]:
        contract_path = ROOT / "examples" / f"{case}_contract.json"
        if not contract_path.is_file():
            continue
        context, _manifest = rules_context(ROOT, case, contract_path.read_text(encoding="utf-8"))
        assert len(context) <= CONTEXT_LIMIT, f"{case} 的上下文 {len(context)} 字符，超过上限 {CONTEXT_LIMIT}"
        # 大数据文件的内容不得出现在上下文里
        assert "sha256" not in context.replace("sha256:", ""), f"{case} 的上下文混入了 JSON 原文"


def test_conventions_fragment_is_small_but_present():
    """约定片段应当是"几百字的事实摘要"，不是产物原文。"""

    context, _manifest = rules_context(ROOT, "pwm", {"module": "pwm"})
    start = context.find("实测开源约定")
    assert start >= 0
    fragment = context[start:]
    assert len(fragment) < 2000, f"约定片段 {len(fragment)} 字符，过大"
    assert "verilog-axi" in fragment
