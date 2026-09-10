"""本地调试用模型 Provider：不需要 API Key，也不访问网络。

用途有三类：

1. **无密钥联调**：网页、CLI、实验脚本都可以选择 ``debug_local`` provider，
   完整体验「计划 → 严格 Schema 校验 → testbench → Icarus/vvp → 报告」链路，
   而无需任何真实模型凭据。
2. **可复现的对照**：``DeterministicLocalProvider`` 的计划完全由 DUT contract
   和固定种子决定，因此同一次输入永远得到同一份计划，适合做回归与故障复现。
3. **受控的故障注入**：``--debug-inject`` 可以要求它故意返回非法 JSON 或越界
   数值，用来验证严格校验、重试和拒绝路径真的生效，而不是只写在文档里。

它**不是**模型能力基线，也不能用来宣称任何 AI 效果：计划由本地规则生成，
不包含任何推理。真实模型实验必须使用 ``OpenAICompatibleProvider``。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Mapping

# 每个内置案例的输入步骤形状：值为候选取值列表，按顺序轮转。
# 取值顺序经过挑选，使计数器/状态机在一份计划内能真正走完状态空间并回绕
# （例如 enable 用 3 高 1 低，而不是 1 高 1 低，否则永远到不了 count=9）。
_INPUT_STEPS: dict[str, list[dict[str, list[Any]]]] = {
    "simple_alu": [
        {"a": [0, 1, 127, 128, 255], "b": [1, 15, 255], "op": [0, 1, 2, 3, 4, 5, 6, 7]},
    ],
    "mod10_counter": [
        {"enable": [1, 1, 1, 0]},
    ],
    "sequence_101_overlap": [
        {"bit_in": [1, 0, 1, 1, 0, 1, 0, 0]},
    ],
    "traffic_light_emergency": [
        {"emergency": [0, 0, 0, 0, 1, 0]},
    ],
    "sync_fifo": [
        {"wr_en": [1, 1, 1, 1, 0, 0], "rd_en": [0, 0, 1, 1, 1, 0], "wr_data": [0, 17, 255]},
    ],
    "uart_tx": [
        {"start": [1, 0, 0, 0, 0, 0, 1, 0], "data_in": [0, 85, 170, 255]},
    ],
    "spi_master": [
        {"start": [1, 0, 0, 0, 0, 0, 0, 0], "data_in": [0, 90, 255]},
    ],
    "handshake_stage": [
        {"in_valid": [1, 1, 0, 1, 0], "out_ready": [0, 1, 1, 0, 0], "in_data": [0, 33, 200]},
    ],
    "debounce": [
        {"key_in": [0, 0, 0, 0, 1, 1, 1, 1]},
    ],
    "pwm": [
        {"duty": [128, 128, 128, 0, 255]},
    ],
    "mux4": [
        {"sel": [0, 1, 2, 3], "d0": [0, 1], "d1": [0, 128], "d2": [255, 2], "d3": [3, 254]},
    ],
    "sync_reset": [
        {"ext_rst_n": [1, 1, 0, 0, 1, 1]},
    ],
    "johnson_counter": [
        # 连续 8 个使能周期正好走完 0000 → 0001 → … → 1000 → 0000，
        # 随后两拍拉低 enable 验证暂停保持。
        {"enable": [1, 1, 1, 1, 1, 1, 1, 1, 0, 0]},
    ],
    "edge_detector": [
        # 含连续高电平（只应有 1 个脉冲）与上升/下降交替。
        {"signal_in": [1, 1, 0, 1, 0, 0, 1, 1, 0, 1]},
    ],
}

# 每类案例的复位后额外稳定周期，用来让状态机推进到可观测状态。
_EXTRA_CYCLES: dict[str, int] = {
    "traffic_light_emergency": 2,
    "uart_tx": 2,
    "spi_master": 2,
    "debounce": 1,
    "pwm": 1,
    "sync_reset": 1,
}

# 默认向量数：要足够走完计数器/状态机的状态空间（含回绕与恢复），
# 否则本地调试模型会给出"看起来通过"的假阴性。
_DEFAULT_VECTOR_COUNT = 24

# 追加在通用激励之后的特征序列：每个内置案例都必须真正走到自己的边界
# （紧急抢占、101 重叠边界、FIFO 满/空、UART 帧、复位释放），否则本地
# 调试模型会因为"没测到"而漏检。这些序列是从 benchmarks/manifest.json 的
# trigger 字段直接映射过来的，不依赖任何模型推理。
_TRAILING_STIMULUS: dict[str, list[tuple[dict[str, Any], int]]] = {
    "traffic_light_emergency": [
        # 紧急窗口必须比状态机周期长：否则"紧急只改状态不改输出"的缺陷可能
        # 恰好落在输出正确的相位上，形成假阴性。
        ({"emergency": 1}, 5),
        ({"emergency": 1}, 3),
        ({"emergency": 0}, 3),
    ],
    "sequence_101_overlap": [
        ({"bit_in": 1}, 1),
        ({"bit_in": 0}, 1),
        ({"bit_in": 1}, 1),
        ({"bit_in": 0}, 1),
        ({"bit_in": 1}, 1),
    ],
    "mod10_counter": [
        ({"rst_n": 1, "enable": 1}, 1),
        ({"rst_n": 0, "enable": 1}, 1),
        ({"rst_n": 1, "enable": 1}, 9),
        ({"rst_n": 1, "enable": 1}, 2),
    ],
    "simple_alu": [
        ({"a": 255, "b": 1, "op": 0}, 1),
        ({"a": 0, "b": 0, "op": 1}, 1),
        ({"a": 255, "b": 255, "op": 0}, 1),
        ({"a": 1, "b": 0, "op": 7}, 1),
    ],
    "sync_fifo": [
        ({"wr_en": 1, "rd_en": 0, "wr_data": 7}, 5),
        ({"wr_en": 0, "rd_en": 1, "wr_data": 0}, 5),
        ({"wr_en": 1, "rd_en": 1, "wr_data": 9}, 3),
        ({"wr_en": 0, "rd_en": 0, "wr_data": 0}, 2),
    ],
    "uart_tx": [
        ({"start": 1, "data_in": 255}, 1),
        ({"start": 0, "data_in": 255}, 10),
        ({"start": 1, "data_in": 0}, 1),
        ({"start": 0, "data_in": 0}, 10),
    ],
    "spi_master": [
        ({"start": 1, "data_in": 128}, 1),
        ({"start": 0, "data_in": 128}, 18),
    ],
    "handshake_stage": [
        ({"in_valid": 1, "out_ready": 0, "in_data": 77}, 1),
        ({"in_valid": 0, "out_ready": 0, "in_data": 0}, 2),
        ({"in_valid": 0, "out_ready": 1, "in_data": 0}, 1),
    ],
    "debounce": [
        ({"key_in": 0}, 6),
        ({"key_in": 1}, 6),
    ],
    "pwm": [
        ({"duty": 1}, 4),
        ({"duty": 0}, 2),
        ({"duty": 255}, 2),
    ],
    "sync_reset": [
        ({"ext_rst_n": 0}, 4),
        ({"ext_rst_n": 1}, 4),
    ],
    "johnson_counter": [
        # 复位边界 + 复位后重新自启动 + 暂停保持，全部来自 manifest 的 trigger。
        ({"rst_n": 0, "enable": 1}, 1),
        ({"rst_n": 1, "enable": 1}, 9),
        ({"rst_n": 1, "enable": 0}, 2),
        ({"rst_n": 1, "enable": 1}, 2),
    ],
    "edge_detector": [
        # 低电平 → 上升沿 → 保持高 → 下降沿：覆盖单周期脉冲的四个相位。
        ({"signal_in": 0}, 2),
        ({"signal_in": 1}, 1),
        ({"signal_in": 1}, 3),
        ({"signal_in": 0}, 2),
    ],
}


def _port_summary(contract: Mapping[str, Any] | Any) -> tuple[dict[str, int], dict[str, int], str | None, str | None]:
    """从 DUT contract 提取输入/输出端口宽度、时钟与复位信号名。"""

    def get(value: Any, key: str, default: Any = None) -> Any:
        return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)

    inputs: dict[str, int] = {}
    outputs: dict[str, int] = {}
    for port in get(contract, "ports", ()) or ():
        name = get(port, "name")
        if not isinstance(name, str) or not name:
            continue
        width = get(port, "width", 1)
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = 1
        direction = get(port, "direction")
        direction = get(direction, "value", direction)
        if str(direction) == "input" or direction == "input":
            inputs[name] = max(1, min(width, 64))
        elif str(direction) == "output" or direction == "output":
            outputs[name] = max(1, min(width, 64))
    clock = get(get(contract, "clock", None), "signal", None)
    reset = get(get(contract, "reset", None), "signal", None)
    return inputs, outputs, clock if isinstance(clock, str) else None, reset if isinstance(reset, str) else None


def _declared_output_initials(contract: Mapping[str, Any] | None) -> dict[str, int]:
    """从 contract 取出输出端口声明的上电初值（仅用于复位前观测）。"""

    if not isinstance(contract, Mapping):
        return {}
    initials: dict[str, int] = {}
    for port in contract.get("ports", []) or []:
        if not isinstance(port, Mapping):
            continue
        name, initial = port.get("name"), port.get("initial")
        if not isinstance(name, str) or not name or initial is None:
            continue
        if str(port.get("direction")) != "output":
            continue
        try:
            initials[name] = int(initial)
        except (TypeError, ValueError):
            continue
    return initials


def _value_for(width: int, candidate: Any) -> Any:
    """把候选值裁剪到端口位宽内，保证生成的计划一定通过严格校验。"""

    if isinstance(candidate, bool):
        return candidate
    try:
        number = int(candidate)
    except (TypeError, ValueError):
        return 0
    if width == 1:
        return number & 1
    limit = (1 << width) - 1
    if number > limit:
        number = limit
    if number < 0:
        number = 0
    return number


@dataclass
class DeterministicLocalProvider:
    """按 DUT contract 生成确定性、Schema 合法 TestPlan 的本地 Provider。"""

    contract: Mapping[str, Any] | None = None
    design: str | None = None
    vector_count: int = _DEFAULT_VECTOR_COUNT
    seed: int = 0
    objective: str = "deterministic local debug plan"
    mode: str = "plan"  # plan | invalid_json | out_of_range | empty
    assertions: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def generate(self, prompt: str) -> str:
        del prompt
        if self.mode == "invalid_json":
            return "{ this is deliberately not valid JSON"
        if self.mode == "empty":
            return ""
        if self.mode == "out_of_range":
            return json.dumps(self._out_of_range_plan(), ensure_ascii=False)
        return json.dumps(self._plan(), ensure_ascii=False)

    # ------------------------------------------------------------------
    def _out_of_range_plan(self) -> dict[str, Any]:
        inputs, _outputs, clock, reset = _port_summary(self.contract or {})
        # 时钟由 contract 生成，绝不能出现在激励里。
        candidates = [name for name in inputs if name not in {clock, reset}]
        target = candidates[0] if candidates else None
        vectors = []
        if target is not None:
            vectors.append(
                {
                    "name": "out_of_range",
                    "inputs": {target: (1 << 40)},
                    "cycles": 1,
                    "sample_phase": "after",
                    "expected": {},
                    "rationale": "deliberately out-of-range value for negative testing",
                }
            )
        return {
            "schema_version": "1.0",
            "design": self._design_name(),
            "objective": "negative test: value outside the port width",
            "clock_period_ns": 10,
            "reset": {"active_low": True},
            "vectors": vectors,
        }

    def _design_name(self) -> str:
        return str(self.design or "design")

    def _plan(self) -> dict[str, Any]:
        inputs, _outputs, clock, reset = _port_summary(self.contract or {})
        driveable = [name for name in inputs if name != clock]
        rng = random.Random(f"{self._design_name()}:{self.seed}")
        steps = _INPUT_STEPS.get(self._design_name())
        extra = _EXTRA_CYCLES.get(self._design_name(), 0)
        vectors: list[dict[str, Any]] = []

        if reset and reset in driveable:
            vectors.append(
                {
                    "name": "debug_reset",
                    "inputs": {reset: 0},
                    "cycles": 2,
                    "sample_phase": "after",
                    "expected": {},
                    "rationale": "hold reset to drive the DUT into a known state",
                }
            )

        for index in range(self.vector_count):
            payload: dict[str, Any] = {}
            for name in driveable:
                if name == reset:
                    payload[name] = 1
                    continue
                width = inputs.get(name, 1)
                candidates = None
                if steps:
                    for step in steps:
                        if name in step:
                            candidates = step[name]
                            break
                if candidates:
                    payload[name] = _value_for(width, candidates[index % len(candidates)])
                elif width == 1:
                    payload[name] = rng.randint(0, 1)
                else:
                    payload[name] = rng.randint(0, (1 << min(width, 8)) - 1)
            vectors.append(
                {
                    "name": f"debug_{index + 1:02d}",
                    "inputs": payload,
                    "cycles": 1 + (extra if index == 0 else 0),
                    "sample_phase": "after",
                    # 期望值由参考模型（内置案例）或调用方提供；这里留空表示
                    # 「只施加激励并观察」，不做无依据的数值断言。
                    "expected": {},
                    "rationale": "deterministic local debug stimulus",
                }
            )

        # 观测型计划：只驱动激励，期望值交给参考模型预言机填写。
        for offset, (payload, cycles) in enumerate(_TRAILING_STIMULUS.get(self._design_name(), ())):
            stimulus = {name: _value_for(inputs.get(name, 1), value) for name, value in payload.items() if name in inputs}
            if reset and reset not in stimulus and reset in driveable:
                stimulus[reset] = 1
            vectors.append(
                {
                    "name": f"debug_edge_{offset + 1:02d}",
                    "inputs": stimulus,
                    "cycles": max(1, int(cycles)),
                    "sample_phase": "after",
                    "expected": {},
                    "rationale": "boundary stimulus derived from the bundled defect manifest",
                }
            )

        plan: dict[str, Any] = {
            "schema_version": "1.0",
            "design": self._design_name(),
            "objective": self.objective,
            "clock_period_ns": 10,
            "reset": {"active_low": True},
            "vectors": vectors,
        }
        # 复位前初值观测：只在 contract 明确声明了输出初值时启用。初值期望值
        # 直接取自 contract，不由本地规则或参考模型推断。
        initial_outputs = _declared_output_initials(self.contract)
        if initial_outputs:
            plan["sample_before_reset"] = True
            plan["pre_reset_expected"] = dict(initial_outputs)
        if self.assertions:
            plan["assertions"] = [dict(item) for item in self.assertions]
        return plan


__all__ = ["DeterministicLocalProvider"]
