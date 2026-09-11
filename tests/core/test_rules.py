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
