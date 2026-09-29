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
