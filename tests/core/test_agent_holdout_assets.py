"""新模块资产的独立语义、单点来源和真实 Icarus 离线验收。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import random
import socket

import pytest

from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "benchmarks/agent_holdout_20261005"
MANIFEST = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
CASES = tuple(MANIFEST["cases"])


def load_asset_helper(name):
    """载入公开资产辅助文件，避免依赖任何上轮私有实验目录。"""
    spec = importlib.util.spec_from_file_location(f"holdout_asset_{name}", ASSETS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEMANTICS = load_asset_helper("semantics")
VALIDATION = load_asset_helper("validation")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """任何意外网络访问都使验收失败；Icarus 子进程只运行本地文件。"""
    def forbidden(*args, **kwargs):
        raise AssertionError("holdout_asset_tests_are_offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def icarus():
    if not VALIDATION.find_tool("iverilog") or not VALIDATION.find_tool("vvp"):
        pytest.skip("local Icarus is unavailable; no toolchain pass may be claimed")


def assert_observations(case, rtl, steps, directory):
    """比较实际端口与独立判据，同时检查逐拍数量及无时钟等待的异步复位。"""
    actual = VALIDATION.observe(case, rtl, steps, directory)
    expected = SEMANTICS.expected_outputs(case, steps)
    assert actual["compile"]["returncode"] == actual["execution"]["returncode"] == 0
    assert [item["index"] for item in actual["observations"]] == list(range(len(steps)))
    assert [item["value"] for item in actual["observations"]] == expected
    reset_value = MANIFEST["cases"][case]["reset_outputs"].values()
    assert actual["reset_value"] == next(iter(reset_value))
    assert all(item["value"] == actual["reset_value"] for item in actual["asynchronous_resets"])
    assert actual["api_calls"] == 0 and actual["network_used"] is False
    return actual


@pytest.mark.parametrize("case", CASES)
def test_interface_budget_and_model_visibility(case):
    entry = MANIFEST["cases"][case]
    contract = DutContract.from_dict(json.loads((ROOT / entry["contract_path"]).read_text(encoding="utf-8")))
    assert MANIFEST["schema"] == "agent-holdout-modules-v1"
    assert contract.module == case and contract.parameters == {}
    assert contract.clock.signal == "clk" and contract.clock.edge == "posedge" and contract.clock.period_ns == 10
    assert contract.reset.signal == "rst_n" and contract.reset.active_level == 0 and contract.reset.synchronous is False
    assert entry["cycle_budget"] == MANIFEST["cycle_budget"] == 16
    assert entry["max_vectors_per_proposal"] == MANIFEST["max_vectors_per_proposal"] == 12
    assert entry["max_accepted_vectors_total"] == MANIFEST["max_accepted_vectors_total"] == 64
    assert "max_vectors" not in entry and "max_vectors" not in MANIFEST
    assert MANIFEST["reference_sampling"] == "per_cycle" and MANIFEST["sample_phase"] == "after"
    assert MANIFEST["agent_plan_mode"] == "independent"
    assert all(port.initial is None for port in contract.ports)
    assert {port.name: port.width for port in contract.ports if port.is_output} == ({"credits": 3} if case == "credit_guard" else {"grant": 4})
    text = (ROOT / entry["spec_path"]).read_text(encoding="utf-8")
    assert "English" in text and "```wavedrom" in text and "sample_phase=after" in text
    for target in entry["targets"]:
        if target["variant"] != "reference":
            assert target["metadata"]["private_mutation_id"] not in text
    for forbidden in ("mutation_b", "mutation_c", "witness", "缺陷", "反例", "B.v", "C.v"):
        assert forbidden not in text
    assert "不添加统计字段" in text and "每个新 episode 都独立自动复位" in text
    assert "每次提案 / 每个 episode 计划最多 12 个向量" in text
    assert "所有实际执行的 episode 合计最多" in text
    assert "内部安全上限，不是单次提案额度" in text


@pytest.mark.parametrize("case", CASES)
def test_sha_binding_and_exact_single_point_mutations(case):
    entry = MANIFEST["cases"][case]
    baseline = (ROOT / entry["reference_rtl"]).read_bytes()
    assert hashlib.sha256(baseline).hexdigest() == entry["reference_sha256"]
    assert len(entry["targets"]) == 3
    for field in ("contract", "spec"):
        assert hashlib.sha256((ROOT / entry[f"{field}_path"]).read_bytes()).hexdigest() == entry[f"{field}_sha256"]
    for target in entry["targets"]:
        source = (ROOT / target["rtl"]).read_bytes()
        assert hashlib.sha256(source).hexdigest() == target["sha256"]
        assert Path(target["rtl"]).name in {"A.v", "B.v", "C.v"}
        assert b"module " + case.encode() in source
        if target["variant"] == "reference":
            assert source == baseline
        else:
            operator = target["metadata"]["operator"]
            anchor, replacement = operator["anchor"].encode(), operator["replacement"].encode()
            assert baseline.count(anchor) == operator["expected_occurrences"] == 1
            assert source == baseline.replace(anchor, replacement, 1)
            assert baseline.index(anchor) == operator["byte_offset"]
            assert baseline[:operator["byte_offset"]].count(b"\n") + 1 == operator["source_line"]
            assert target["metadata"]["private_mutation_id"].encode() not in source


def test_manual_golden_counter_sequences_are_not_derived_from_rtl():
    down = [{"acquire": 1, "release_req": 0}] * 5
    up = [{"acquire": 0, "release_req": 1}] * 6
    assert SEMANTICS.expected_outputs("credit_guard", down) == [2, 1, 0, 0, 0]
    assert SEMANTICS.expected_outputs("credit_guard", up) == [4, 5, 6, 7, 7, 7]
    assert SEMANTICS.expected_outputs("credit_guard", [{"acquire": 1, "release_req": 1}, {"acquire": 0, "release_req": 0}]) == [3, 3]
    assert SEMANTICS.credit_transition(0, 1, 1) == 0
    assert SEMANTICS.credit_transition(7, 1, 1) == 7
    assert SEMANTICS.credit_transition(0, 1, 0, rst_n=0) == 3


def test_manual_golden_arbiter_selection_and_old_pointer_sequences():
    assert SEMANTICS.expected_outputs("rotating_arbiter", [{"request": 15, "advance": 1}] * 6) == [1, 2, 4, 8, 1, 2]
    assert SEMANTICS.expected_outputs("rotating_arbiter", [{"request": 15, "advance": 0}] * 4) == [1, 1, 1, 1]
    # 起点3时先选bit3；仅bit0/bit1有效时从3环回到bit0。
    assert SEMANTICS.arbiter_transition(3, 9, 0) == (8, 3)
    assert SEMANTICS.arbiter_transition(3, 3, 1) == (1, 1)
    assert SEMANTICS.arbiter_transition(2, 0, 1) == (0, 2)
    assert SEMANTICS.arbiter_transition(3, 15, 1, rst_n=0) == (0, 0)


def exhaustive_steps(case):
    """每个状态输入项都由复位和普通操作准备，不窥探 DUT 内部寄存器。"""
    steps = []
    if case == "credit_guard":
        for state in range(8):
            for acquire in range(2):
                for release_req in range(2):
                    episode = [{"rst_n": 0, "acquire": 0, "release_req": 0}]
                    setup = {"acquire": int(state < 3), "release_req": int(state > 3)}
                    episode.extend([setup] * abs(state - 3))
                    episode.extend([{"acquire": acquire, "release_req": release_req}, {"acquire": 0, "release_req": 0}])
                    assert len(episode) <= 16
                    steps.extend(episode)
    else:
        for pointer in range(4):
            for request in range(16):
                for advance in range(2):
                    episode = [
                        {"rst_n": 0, "request": 0, "advance": 0},
                        {"request": 1 << ((pointer - 1) % 4), "advance": 1},
                        {"request": request, "advance": advance},
                        {"request": 15, "advance": 0},
                    ]
                    steps.extend(episode)
    return steps


@pytest.mark.parametrize("case", CASES)
def test_actual_icarus_all_state_and_input_transitions(case, tmp_path, icarus):
    steps = exhaustive_steps(case)
    actual = assert_observations(case, ROOT / MANIFEST["cases"][case]["reference_rtl"], steps, tmp_path / case)
    values = [item["value"] for item in actual["observations"]]
    if case == "credit_guard":
        assert set(values) == set(range(8))
    else:
        assert set(values) == {0, 1, 2, 4, 8}
        assert all(value == 0 or value & (value - 1) == 0 for value in values)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("seed", (0, 1, 2, 20261005))
def test_actual_icarus_seeded_inputs_reset_and_hold(case, seed, tmp_path, icarus):
    rng = random.Random(seed)
    steps = []
    for index in range(192):
        step = ({"acquire": rng.randrange(2), "release_req": rng.randrange(2)} if case == "credit_guard"
                else {"request": rng.randrange(16), "advance": rng.randrange(2)})
        if index % 31 == 15:
            step["rst_n"] = 0
        steps.append(step)
    assert_observations(case, ROOT / MANIFEST["cases"][case]["reference_rtl"], steps, tmp_path / f"{case}-{seed}")


MUTATIONS = [(case, target) for case, entry in MANIFEST["cases"].items() for target in entry["targets"] if target["variant"] != "reference"]


@pytest.mark.parametrize("case,target", MUTATIONS, ids=[f"{case}-{target['variant']}" for case, target in MUTATIONS])
def test_manual_mutation_witness_is_real_and_single(case, target, tmp_path, icarus):
    witness = target["metadata"]["witness"]
    inputs, expected = witness["inputs"], witness["reference_after"]
    assert len(inputs) == witness["budget_cycles"] <= 16
    assert SEMANTICS.expected_outputs(case, inputs) == expected
    reference = assert_observations(case, ROOT / MANIFEST["cases"][case]["reference_rtl"], inputs, tmp_path / "reference")
    mutant = VALIDATION.observe(case, ROOT / target["rtl"], inputs, tmp_path / "mutant")
    mutant_values = [item["value"] for item in mutant["observations"]]
    assert mutant_values == witness["mutant_after"]
    assert mutant_values != [item["value"] for item in reference["observations"]]


@pytest.mark.parametrize("case,target", MUTATIONS, ids=[f"{case}-{target['variant']}" for case, target in MUTATIONS])
def test_mutation_non_target_scenarios_remain_unchanged(case, target, tmp_path, icarus):
    variant = target["variant"]
    if case == "credit_guard" and variant == "mutation_b":
        inputs = [{"acquire": 0, "release_req": 1}] * 8 + [{"acquire": 1, "release_req": 0}] * 3 + [{"acquire": 1, "release_req": 1}, {"acquire": 0, "release_req": 0}]
    elif case == "credit_guard":
        inputs = [{"acquire": 1, "release_req": 0}] * 5 + [{"acquire": 0, "release_req": 1}] * 6 + [{"acquire": 0, "release_req": 0}]
    elif variant == "mutation_b":
        inputs = [{"request": request, "advance": 1} for request in (15, 6, 13, 15, 0, 15, 3, 12, 15)] + [{"request": 0, "advance": 0}]
    else:
        inputs = [{"request": request, "advance": advance} for request, advance in ((1, 1), (2, 1), (4, 0), (0, 1), (8, 1), (1, 0), (4, 1), (8, 0))]
    assert len(inputs) <= 16
    assert_observations(case, ROOT / target["rtl"], inputs, tmp_path / "non-target")


@pytest.mark.parametrize("case", CASES)
def test_published_normal_timing_example_is_not_a_mutation_witness(case, tmp_path, icarus):
    inputs = ([{"acquire": acquire, "release_req": release_req} for acquire, release_req in ((0, 0), (1, 0), (0, 1), (0, 0))]
              if case == "credit_guard" else [{"request": request, "advance": advance} for request, advance in ((2, 1), (4, 1), (0, 1), (8, 0), (8, 1))])
    for target in MANIFEST["cases"][case]["targets"]:
        assert_observations(case, ROOT / target["rtl"], inputs, tmp_path / target["variant"])


@pytest.mark.parametrize("case", CASES)
def test_harness_rejects_out_of_range_inputs_before_writing(case):
    inputs = [{"acquire": 2, "release_req": 0}] if case == "credit_guard" else [{"request": 16, "advance": 0}]
    with pytest.raises(ValueError, match="invalid_known_width_input"):
        VALIDATION.testbench_text(case, inputs)
