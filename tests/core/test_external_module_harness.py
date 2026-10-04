"""外部模块验证夹具（P0-D）的离线回归。

只测**不依赖网络、不依赖上游文件**的部分：合约与激励计划必须能被项目的严格校验接受。
真正的对比运行需要先抓取上游 RTL（`.iverilog-ai/external/`，不进版本库），
在 CI 里没有网络也能跑的就到这里为止——与其写一个"网络不通就 skip"的假回归，
不如把能离线钉住的部分钉死。

为什么值得钉：这份合约里的 `reset.active_level = 1`（高有效）与 `prescale` 的 16 位宽
正是本轮 A 修掉的两类静默猜测。如果哪天夹具被"顺手"改成低有效或把 prescale 写成 8 位，
这个测试会红——而线上跑的时候不会有任何报错，只会得出错误的结论。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_check_external_module", ROOT / "scripts" / "check_external_module.py"
)
assert _SPEC and _SPEC.loader
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)


def test_contract_is_accepted_and_states_reset_semantics_explicitly():
    contract = DutContract.from_dict(harness.CONTRACT)
    assert contract.module == "uart_rx"
    # 高有效 + 同步：这两条在源码里有依据（always @(posedge clk) if (rst)），必须显式写出
    assert contract.reset is not None
    assert contract.reset.active_level == 1
    assert contract.reset.synchronous is True
    assert contract.clock is not None and contract.clock.edge == "posedge"
    # 16 位输入：宽端口是"最高位必须被驱动"那条修复的现场
    assert contract.port_map["prescale"].width == 16
    assert contract.port_map["m_axis_tdata"].width == 8


def test_plan_is_schema_valid_and_covers_a_bad_stop_bit():
    plan = TestPlan.model_validate(harness.build_plan())
    names = [vector.name for vector in plan.vectors]
    assert any("bad_stop" in name for name in names), "停止位为 0 的那一帧是检出该变体的唯一依据"
    # 计划只含激励：外部模块的判据是"与基线行为一致"，不臆造期望值
    assert all(not vector.expected for vector in plan.vectors)
    # 同一份计划会同时跑基线与候选，因此必须驱动全部输入端口
    driven = {signal for vector in plan.vectors for signal in vector.inputs}
    assert {"rxd", "prescale", "m_axis_tready"} <= driven


def test_test_byte_is_not_a_bit_palindrome():
    """测试字节必须是位序非回文，否则"位序写反"的变体在行为上与基线一模一样。"""

    byte = harness.BYTE
    reversed_byte = int(f"{byte:08b}"[::-1], 2)
    assert byte != reversed_byte, f"0x{byte:02X} 是位序回文，检不出位序类缺陷"
    bits = harness.BITS
    assert len(bits) == 8 and bits == [(byte >> i) & 1 for i in range(8)]


@pytest.mark.parametrize("name", list(harness.VARIANTS))
def test_every_variant_has_a_real_source_anchor(name: str):
    """每个变体的锚点都必须能在上游源码里找到——否则"变异"会静默地什么都没改。"""

    description, old, new = harness.VARIANTS[name]
    assert description and old and new
    assert old != new


@pytest.mark.parametrize("name", list(harness.TX_VARIANTS))
def test_every_tx_variant_has_a_real_source_anchor(name: str):
    description, old, new = harness.TX_VARIANTS[name]
    assert description and old and new
    assert old != new, "变体的替换文本与原文相同 = 没有变异，却会被记成'未检出'"


@pytest.mark.parametrize("name", list(harness.PE_VARIANTS))
def test_every_priority_encoder_variant_has_a_real_source_anchor(name: str):
    description, old, new = harness.PE_VARIANTS[name]
    assert description and old and new
    assert old != new


def test_priority_encoder_contract_is_parameterised_and_clockless():
    """参数化 + 无时钟的合约必须被校验接受：不写 clock/reset 就是"没有"，不是"猜一个"。"""

    contract = DutContract.from_dict(harness.PE_CONTRACT)
    assert contract.parameters == {"WIDTH": 4, "LSB_HIGH_PRIORITY": 0}
    assert contract.clock is None and contract.reset is None
    # $clog2(4) = 2：编码输出只有 2 位，写错会让测试台接错线
    assert contract.port_map["output_encoded"].width == 2
    assert contract.port_map["input_unencoded"].width == 4


def test_priority_encoder_plan_sweeps_the_whole_input_space():
    plan = TestPlan.model_validate(harness.build_pe_plan())
    driven = [vector.inputs["input_unencoded"] for vector in plan.vectors]
    assert driven == list(range(16)), "组合逻辑的激励必须穷举输入空间，否则覆盖率没有依据"


def _manifest(tmp_path):
    import hashlib
    import json
    root = tmp_path / "source"
    root.mkdir()
    modules = {}
    for name in harness.MODULES:
        data = f"frozen source {name}".encode()
        (root / f"{name}.v").write_bytes(data)
        modules[name] = {"local": f"{name}.v", "sha256": hashlib.sha256(data).hexdigest()}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "external-inputs-v1", "modules": modules}))
    return manifest


def test_freeze_copies_verified_inputs_and_refuses_existing_run(tmp_path):
    manifest = _manifest(tmp_path)
    work = tmp_path / "run"
    records = harness.freeze_inputs(manifest, work)
    assert len(records) == 3
    assert (work / "inputs/uart_rx.v").read_bytes() == b"frozen source uart_rx"
    with pytest.raises(FileExistsError):
        harness.freeze_inputs(manifest, work)


def test_changed_input_fails_before_creating_output(tmp_path):
    manifest = _manifest(tmp_path)
    (manifest.parent / "uart_rx.v").write_bytes(b"modified")
    work = tmp_path / "run"
    with pytest.raises(ValueError, match="hash mismatch"):
        harness.freeze_inputs(manifest, work)
    assert not work.exists()


def test_manifest_cannot_escape_bundle_directory(tmp_path):
    import json
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["modules"]["uart_rx"]["local"] = "../outside.v"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="escapes"):
        harness.freeze_inputs(manifest, tmp_path / "run")


def test_check_requires_explicit_paths():
    with pytest.raises(SystemExit) as error:
        harness.main([])
    assert error.value.code == 2


def test_fetch_registry_matches_checked_modules_and_rejects_wrong_hash(tmp_path):
    spec = importlib.util.spec_from_file_location("external_fetch", ROOT / "scripts/fetch_external_modules.py")
    fetcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetcher)
    assert set(fetcher.SOURCES) == set(harness.MODULES)
    item = fetcher.SOURCES["uart_rx"]
    wrong = tmp_path / item["legacy_local"]
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(b"wrong source")
    with pytest.raises(ValueError, match="hash differs"):
        fetcher.freeze(tmp_path / "output", tmp_path)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("summary,exit_code,complete", [
    ("", 0, False), ("SPEC_SUMMARY checks=0 failures=0", 0, False),
    ("SPEC_SUMMARY checks=11 failures=0", 1, False),
    ("SPEC_SUMMARY checks=11 failures=2", 0, True),
])
def test_missing_or_crashed_spec_run_is_not_reported_as_pass(tmp_path, monkeypatch, summary, exit_code, complete):
    from subprocess import CompletedProcess
    calls = iter([CompletedProcess([], 0, "", ""), CompletedProcess([], exit_code, summary, "")])
    monkeypatch.setattr(harness, "WORK", tmp_path)
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: next(calls))
    monkeypatch.setattr(harness, "run_verify_diff", lambda *a: {"status": "identical", "exit": 0})
    result = harness.run_case_generic(tmp_path / "x.v", "baseline", "", "uart_rx",
                                      tmp_path / "contract.json", tmp_path / "plan.json")
    assert result["spec_complete"] is complete
