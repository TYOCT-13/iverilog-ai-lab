"""独立端口语义：采样转换表与最近触发时间窗口，不读取 DUT 或标签。"""

from __future__ import annotations

from iverilog_ai.ai.schema import TestPlan


def expected_outputs(case: str, plan: TestPlan) -> list[int]:
    """从新 episode 的自动复位状态推导每个刺激边沿后的输出。"""
    if case not in {"edge_detector", "pulse_stretcher"} or plan.design != case:
        raise ValueError("semantic_case")
    data_input = "signal_in" if case == "edge_detector" else "pulse_in"
    held = {"rst_n": 1, data_input: 0}
    previous_sample = 0
    latest_trigger: int | None = None
    after: list[int] = []
    edge_index = 0
    for vector in plan.vectors:
        if vector.sample_phase != "after":
            raise ValueError("semantic_phase")
        if any(name not in held or type(value) is not int or value not in (0, 1) for name, value in vector.inputs.items()):
            raise ValueError("semantic_known_input")
        held.update({name: int(value) for name, value in vector.inputs.items()})
        for _ in range(vector.cycles):
            if held["rst_n"] == 0:
                previous_sample, latest_trigger = 0, None
                value = 0
            elif case == "edge_detector":
                # 真值表只接受采样对0/1，不复用RTL的位运算判决表达式。
                value = {(0, 0): 0, (0, 1): 1, (1, 0): 0, (1, 1): 0}[(previous_sample, held[data_input])]
                previous_sample = held[data_input]
            else:
                # 时间戳窗口避免照抄DUT及core参考的装载/递减计数器。
                if held[data_input] == 1:
                    latest_trigger = edge_index
                value = int(latest_trigger is not None and edge_index - latest_trigger < 4)
            after.append(value)
            edge_index += 1
    return after
