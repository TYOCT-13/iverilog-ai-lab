"""离线调试 Provider 的激励表与基准案例必须一一对应。

三份东西必须同时存在，否则会出现"静默无效"的路径：

1. `core.reference_model.SUPPORTED`（有没有参考模型）；
2. `ai.debug_provider._INPUT_STEPS`（有没有确定性激励）；
3. `examples/<case>_contract.json` 里真实存在的输入端口名。

曾经的问题正是这一类：`KNOWN_DESIGNS` 在调试服务里另写了一份手抄名单，
而新案例只加进其中一份就会出现"服务端拒绝一个已支持的案例"或"生成空计划"。
现在服务端名单直接取自激励表，本文件再把激励表与参考模型、合约对齐。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.ai.debug_provider import (
    _EXTRA_CYCLES,
    _INPUT_STEPS,
    _TRAILING_STIMULUS,
    known_designs,
)
from iverilog_ai.core.reference_model import INPUT_DEFAULTS, SUPPORTED

ROOT = Path(__file__).resolve().parents[2]


def test_debug_provider_covers_every_supported_design():
    assert known_designs() == set(SUPPORTED), (
        "调试 Provider 的激励表与参考模型支持的设计不一致："
        f"缺少 {sorted(set(SUPPORTED) - known_designs())}，多余 {sorted(known_designs() - set(SUPPORTED))}"
    )


def _contract_inputs(case: str) -> set[str]:
    path = ROOT / "examples" / f"{case}_contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(port["name"])
        for port in payload.get("ports", [])
        if str(port.get("direction")) == "input"
    }


@pytest.mark.parametrize("case", sorted(_INPUT_STEPS))
def test_stimulus_only_names_real_contract_ports(case):
    """激励表里的信号名必须是合约里真实存在的输入端口（拼错就会静默失效）。"""

    ports = _contract_inputs(case)
    used: set[str] = set()
    for step in _INPUT_STEPS[case]:
        used |= set(step)
    for payload, _cycles in _TRAILING_STIMULUS.get(case, ()):
        used |= set(payload)
    unknown = sorted(used - ports)
    assert not unknown, f"{case} 的激励使用了合约里不存在的输入端口：{unknown}"


def test_input_defaults_cover_every_stimulus_signal():
    """激励里出现的信号都必须有默认值，否则模型与测试台的口径会分叉。"""

    for case, steps in _INPUT_STEPS.items():
        defaults = INPUT_DEFAULTS[case]
        used: set[str] = set()
        for step in steps:
            used |= set(step)
        for payload, _cycles in _TRAILING_STIMULUS.get(case, ()):
            used |= set(payload)
        missing = sorted(used - set(defaults))
        assert not missing, f"{case} 的激励信号缺少默认值：{missing}"


def test_extra_cycles_and_trailing_stimulus_reference_known_designs():
    known = known_designs()
    assert set(_EXTRA_CYCLES) <= known
    assert set(_TRAILING_STIMULUS) <= known


def test_pulse_stretcher_stimulus_exercises_a_retrigger():
    """展宽器的关键边界是"展宽期内再次触发"，激励表必须真的覆盖它。"""

    pulses = [step for step in _INPUT_STEPS["pulse_stretcher"] if "pulse_in" in step]
    assert pulses, "pulse_stretcher 缺少 pulse_in 激励"
    sequence = pulses[0]["pulse_in"]
    assert 1 in sequence and 0 in sequence
    # 至少出现两次高电平（否则只覆盖单次触发）
    assert sum(1 for value in sequence if value == 1) >= 2, sequence
