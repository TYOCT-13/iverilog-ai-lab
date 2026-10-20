"""Explicit historical inputs for tests of archived experiment admission.

Only tests requesting this fixture use Git-pinned Agent bytes. Production
admission and its source-drift rejection are left unchanged.
"""
import hashlib
import importlib.util
import sys

import pytest


@pytest.fixture
def frozen_v8_test_inputs(monkeypatch, tmp_path):
    from scripts import run_agent_new_holdout_study as holdout
    from scripts import run_agent_feedback_study as feedback
    from scripts import run_agent_comparison as comparison

    live_source, live_sha = comparison.registered_source_path, comparison.sha
    copies = {}
    for relative, expected in holdout.FROZEN_SOURCES.items():
        raw = holdout._git("show", holdout.FROZEN_REVISION + ":" + relative)
        assert hashlib.sha256(raw).hexdigest() == expected
        path = tmp_path / "historical-agent-inputs" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        copies[relative] = path
    def historical_source(relative):
        return copies[relative] if relative in copies else live_source(relative)
    live_paths = {holdout.ROOT / relative: path for relative, path in copies.items()}
    def historical_sha(path):
        return live_sha(live_paths.get(path, path))

    alias = "iverilog_ai.ai._historical_agent_test_fixture"
    spec = importlib.util.spec_from_file_location(alias, copies["src/iverilog_ai/ai/agent.py"])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, alias, module)
    spec.loader.exec_module(module)
    for owner in (holdout, feedback, comparison):
        monkeypatch.setattr(owner, "registered_source_path", historical_source)
        monkeypatch.setattr(owner, "sha", historical_sha)
        monkeypatch.setattr(owner, "PROMPT_VERSION", module.PROMPT_VERSION)
        monkeypatch.setattr(owner, "SYSTEM_PROMPT", module.SYSTEM_PROMPT)
    return {"live_source": live_source, "live_sha": live_sha, "snapshot_source": historical_source}
