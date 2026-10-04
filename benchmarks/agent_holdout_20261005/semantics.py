"""留出模块的独立算术语义；不读取 RTL、缺陷清单或 Agent 响应。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def credit_transition(credits: int, acquire: int, release_req: int, rst_n: int = 1) -> int:
    """以事件差值和范围夹紧表达信用计数，与 RTL 条件分支实现独立。"""
    if rst_n == 0:
        return 3
    delta = {(1, 0): -1, (0, 1): 1}.get((acquire, release_req), 0)
    return min(7, max(0, credits + delta))


def arbiter_transition(pointer: int, request: int, advance: int, rst_n: int = 1) -> tuple[int, int]:
    """以模距离最小值选择请求，与 RTL 四组显式优先级和循环参考独立。"""
    if rst_n == 0:
        return 0, 0
    active = [index for index in range(4) if request & (1 << index)]
    if not active:
        return 0, pointer
    selected = min(active, key=lambda index: (index - pointer) % 4)
    return 1 << selected, (selected + 1) % 4 if advance == 1 else pointer


def expected_outputs(case: str, steps: Iterable[Mapping[str, int]]) -> list[int]:
    """每次调用从一次完成的自动复位开始，返回每个刺激拍后的输出。"""
    values: list[int] = []
    credits, pointer = 3, 0
    for step in steps:
        if case == "credit_guard":
            credits = credit_transition(credits, step["acquire"], step["release_req"], step.get("rst_n", 1))
            values.append(credits)
        elif case == "rotating_arbiter":
            grant, pointer = arbiter_transition(pointer, step["request"], step["advance"], step.get("rst_n", 1))
            values.append(grant)
        else:
            raise ValueError("unknown_holdout_case")
    return values
