from pathlib import Path

from iverilog_ai.core.rules import rule_manifest, rules_context, rules_fingerprint


def test_rule_manifest_is_fingerprinted():
    root = Path(__file__).parents[2]
    manifest = rule_manifest(root, "sync_fifo")
    assert {item["file"] for item in manifest} == {"verification_rules/common.md", "verification_rules/sync_fifo.md"}
    assert all(len(item["sha256"]) == 64 for item in manifest)
    context, again = rules_context(root, "sync_fifo", {"module": "sync_fifo"})
    assert "单时钟 FIFO" in context
    assert rules_fingerprint(manifest) == rules_fingerprint(again)
