import json
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan as Plan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools

from scripts.create_evidence_pack import create_evidence_pack
from scripts.replay_evidence_pack import replay

ROOT = Path(__file__).resolve().parents[2]
TOOLS = locate_tools()


def test_create_evidence_pack_copies_and_hashes_files(tmp_path):
    artifact = tmp_path / "report.md"
    artifact.write_text("# report\n", encoding="utf-8")
    result = tmp_path / "pipeline_result.json"
    result.write_text(json.dumps({"artifacts": {"report": str(artifact)}, "simulation": {"run_id": "abc", "status": "passed"}}), encoding="utf-8")
    manifest = create_evidence_pack(result, tmp_path / "pack")
    assert manifest["run_id"] == "abc"
    assert (tmp_path / "pack" / "evidence_manifest.json").is_file()
    assert (tmp_path / "pack" / "README.md").is_file()
    assert any(item["name"] == "report" for item in manifest["files"])
    assert Path(manifest["zip_file"]).is_file()


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_self_contained_pack_replays_original_failure_and_checks_hash(tmp_path):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text(encoding="utf-8")))
    plan = Plan.model_validate({"design": "mod10_counter", "objective": "cross wrap boundary",
                               "vectors": [{"name": f"step_{i}", "inputs": {"enable": 1}} for i in range(12)]})
    result = VerificationPipeline().run(plan, contract, ROOT / "rtl/mod10_counter_bug_wrap9.v", tmp_path / "run",
                                        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    pack = tmp_path / "pack"
    manifest = create_evidence_pack(result.artifacts["pipeline_result"], pack)
    assert manifest["replay"]["status"] == "available"
    assert (pack / "replay.py").is_file()
    actual = replay(pack, iverilog=str(TOOLS.iverilog), vvp=str(TOOLS.vvp))
    assert actual["status"] == "failed_checks" and actual["failures"] == len(result.failures)
    assert actual["api_requests"] == 0
    (pack / manifest["replay"]["rtl_file"]).write_text("tampered", encoding="ascii")
    with pytest.raises(ValueError, match="hash"):
        replay(pack, iverilog=str(TOOLS.iverilog), vvp=str(TOOLS.vvp))


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_pack_rejects_source_changed_since_original_execution(tmp_path):
    rtl = tmp_path / "counter.v"
    rtl.write_bytes((ROOT / "rtl/mod10_counter.v").read_bytes())
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text(encoding="utf-8")))
    plan = Plan.model_validate({"design": "mod10_counter", "objective": "counter",
                               "vectors": [{"name": "step", "inputs": {"enable": 1}}]})
    result = VerificationPipeline().run(plan, contract, rtl, tmp_path / "run", iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    rtl.write_text("changed", encoding="ascii")
    with pytest.raises(ValueError, match="changed"):
        create_evidence_pack(result.artifacts["pipeline_result"], tmp_path / "pack")


@pytest.mark.skipif(not TOOLS.can_simulate, reason="Icarus unavailable")
def test_pack_rejects_testbench_changed_since_original_execution(tmp_path):
    contract = DutContract.from_dict(json.loads((ROOT / "examples/mod10_counter_contract.json").read_text(encoding="utf-8")))
    plan = Plan.model_validate({"design": "mod10_counter", "objective": "counter",
                               "vectors": [{"name": "step", "inputs": {"enable": 1}}]})
    result = VerificationPipeline().run(plan, contract, ROOT / "rtl/mod10_counter.v", tmp_path / "run",
                                        iverilog_path=TOOLS.iverilog, vvp_path=TOOLS.vvp)
    result.testbench_path.write_text("tampered", encoding="ascii")
    pack = tmp_path / "pack"
    with pytest.raises(ValueError, match="testbench changed"):
        create_evidence_pack(result.artifacts["pipeline_result"], pack)
    assert not pack.exists()
