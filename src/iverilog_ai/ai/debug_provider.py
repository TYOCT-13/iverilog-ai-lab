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
import re
from dataclasses import dataclass, field
from pathlib import Path
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
    "pulse_stretcher": [
        # 单拍脉冲 → 长间隔 → 展宽期内再次触发（覆盖"重触发是否重新装载计数"）。
        {"pulse_in": [1, 0, 0, 0, 0, 0, 1, 0, 0, 0]},
    ],
    # New holdout entries are offline regression inputs from the public
    # contracts, without expected outputs or defect labels.
    "credit_guard": [
        {"acquire": [1, 1, 1, 1, 0, 0, 0, 0, 1, 0],
         "release_req": [0, 0, 0, 0, 1, 1, 1, 1, 1, 0]},
    ],
    "rotating_arbiter": [
        {"request": [15, 15, 15, 15, 0, 5, 10, 9, 2, 8],
         "advance": [1, 1, 1, 1, 1, 0, 1, 1, 0, 1]},
    ],
    "valid_data_pipeline": [
        # Correct public interface operations: consecutive transfers, bubbles,
        # and flush. This offline table is not an API or capability baseline.
        {"i_valid": [1, 1, 0, 1, 1, 0, 1, 0],
         "i_data": [0, 165, 60, 255, 1, 128, 126, 0],
         "i_flush": [0, 0, 0, 0, 1, 0, 0, 0]},
    ],
    "event_accumulator": [
        # Sustained accepted events, disabled hold, and independent clear
        # follow the correct specification without consulting mutations.
        {"i_enable": [1] * 18 + [0, 0, 0, 1, 1, 0],
         "i_event": [1] * 18 + [1, 0, 1, 1, 0, 0],
         "i_clear": [0] * 20 + [1, 0, 0, 0]},
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
    "pulse_stretcher": [
        # 展宽长度必须真的被观测到：单拍脉冲后连续保持低电平足够久，
        # 覆盖"输出是否按 WIDTH 拍回落"（WIDTH 缺省 4）。
        ({"pulse_in": 1}, 1),
        ({"pulse_in": 0}, 8),
        # 展宽期内再次触发：覆盖"重触发是否重新装载计数"。
        ({"pulse_in": 1}, 1),
        ({"pulse_in": 0}, 1),
        ({"pulse_in": 1}, 1),
        ({"pulse_in": 0}, 8),
    ],
}


def known_designs() -> frozenset[str]:
    """本 Provider 能生成有意义激励的设计集合。

    调试服务用它来判断"是否服务这个设计"，避免再维护一份手写名单：
    两份名单一旦漂移，要么服务端拒绝一个已支持的案例，要么为一个没有激励表的
    设计生成空计划。`tests/core/test_debug_provider_coverage.py` 把两边钉在一起。
    """

    return frozenset(_INPUT_STEPS)


#: 从提示词里取设计名与 DUT contract（真实提示词的形状见 `plan_tests`）。
_DESIGN_RE = re.compile(r"Design:\s*([A-Za-z_][A-Za-z0-9_$]*)")
#: contract 在真实提示词里的两种落点：`rules_context` 会把它附在规则文本末尾，
#: 标记为 `--- DUT contract ---`；早期/简化调用则直接写在 `DUT context:` 之后。
_CONTRACT_MARKERS = ("--- DUT contract ---", "DUT context:")
#: 仓库内自带的合约目录（`examples/<case>_contract.json`）。
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADDITIONAL_CONTRACTS = {
    "valid_data_pipeline": "benchmarks/agent_new_holdout_20261005/contracts/valid_data_pipeline_contract.json",
    "event_accumulator": "benchmarks/agent_new_holdout_20261005/contracts/event_accumulator_contract.json",
}


def _json_object_at(text: str, start: int) -> dict[str, Any] | None:
    """从 ``text[start]``（必须是 ``{``）开始按括号配对切出第一个 JSON 对象。

    不能用非贪婪正则 ``\\{.*?\\}``：contract 里还有嵌套对象（clock/reset/ports），
    非贪婪会在第一个内层 ``}`` 处收尾，解析必然失败。
    """

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def extract_request(
    text: str,
    *,
    default_design: str | None = None,
    default_contract: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """从提示词中提取设计名与 DUT contract；缺失时回退到提供的默认值。

    这是**离线路径能否真正驱动 DUT 的关键**：contract 提取失败时端口列表为空，
    生成出来的计划里每条向量的 ``inputs`` 都是 ``{}``——计划"合法"、仿真"通过"，
    但什么都没测。因此这里对每个标记都尝试括号配对解析，而不是只认一种写法。
    """

    design_match = _DESIGN_RE.search(text or "")
    design = design_match.group(1) if design_match else (default_design or "")
    for marker in _CONTRACT_MARKERS:
        position = (text or "").find(marker)
        while position != -1:
            brace = text.find("{", position)
            if brace != -1:
                parsed = _json_object_at(text, brace)
                if parsed and ("ports" in parsed or "module" in parsed):
                    return design, parsed
            position = text.find(marker, position + 1)
    return design, dict(default_contract or {})


def bundled_contract(design: str) -> dict[str, Any]:
    """读取内置案例或显式登记的新模块合约；不存在时返回空字典。

    离线路径需要端口方向与位宽才能施加激励。提示词没带 contract 时（例如调用方
    只传了规则文本），就从仓库里取该案例的合约——调试服务的定位就是"服务内置案例"。
    """

    if not isinstance(design, str) or not design or any(ch in design for ch in "/\\:*?\"<>|"):
        return {}
    path = _REPO_ROOT / _ADDITIONAL_CONTRACTS.get(design, f"examples/{design}_contract.json")
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


@dataclass(frozen=True)
class _ResetSpec:
    """合约里声明的复位语义（信号名、有效电平、保持周期）。"""

    signal: str
    active_level: int
    assert_cycles: int

    @property
    def inactive_level(self) -> int:
        return 1 - self.active_level


def _reset_spec(contract: Mapping[str, Any] | None) -> _ResetSpec | None:
    """取复位语义；**极性缺失时报错，而不是默认低有效**。

    旧实现把 `active_low` 写死成 True、把复位向量写死成 0/1，于是遇到高有效复位的
    DUT 时：复位向量给的是"无效"电平（等于没复位），而其余所有向量把复位**一直摁在有效**。
    结果是一个被永久复位的 DUT——它的输出恒定不变，缺陷版本和正确版本看起来"完全一致"，
    一个假阴性。所以这里宁可报错。
    """

    if not isinstance(contract, Mapping):
        return None
    reset = contract.get("reset")
    if not isinstance(reset, Mapping):
        return None
    signal = reset.get("signal")
    if not isinstance(signal, str) or not signal:
        return None
    level = reset.get("active_level")
    if level is None and isinstance(reset.get("active_low"), bool):
        level = 0 if reset["active_low"] else 1
    if level not in (0, 1) or isinstance(level, bool):
        raise ValueError(
            f"复位 {signal!r} 的有效电平未在合约里明确（active_level 必须是 0 或 1）："
            "没有它就无法生成正确的复位/释放激励。请先在合约里确认复位极性。"
        )
    cycles = reset.get("assert_cycles", 2)
    if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 10_000:
        cycles = 2
    return _ResetSpec(signal=signal, active_level=int(level), assert_cycles=cycles)


def _boundary_values(width: int) -> list[int]:
    """宽输入必须真正走到的边界值。

    为什么需要：旧实现对宽端口只随机 `0 .. 2**min(width,8)-1`，于是 16/32 位输入的
    **高字节永远恒为 0**。一个只在最高位或全 1 上暴露的缺陷因此永远测不到，
    而报告会显示"通过"。这里显式列出 0、全 1、最高位、次高位、1、全 1-1。
    """

    limit = (1 << width) - 1
    values = [0, limit, 1 << (width - 1), limit >> 1, 1, limit - 1]
    seen: list[int] = []
    for value in values:
        if 0 <= value <= limit and value not in seen:
            seen.append(value)
    return seen


def _generic_value(width: int, index: int, rng: random.Random) -> int:
    """通用激励取值：先按顺序覆盖边界，然后用**全位宽**随机。"""

    if width == 1:
        return rng.randint(0, 1)
    boundaries = _boundary_values(width)
    if index < len(boundaries):
        return boundaries[index]
    return rng.randint(0, (1 << width) - 1)


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

    #: `generate()` 解析出的实际请求（私有状态，不参与 dataclass 比较/序列化）。
    _active_design: str | None = field(default=None, init=False, repr=False, compare=False)
    _resolved_contract: Mapping[str, Any] | None = field(default=None, init=False, repr=False, compare=False)

    def generate(self, prompt: str) -> str:
        """按"自身字段优先、提示词兜底"的顺序解析请求后生成计划。

        早期实现直接 `del prompt`，只用构造时传入的 `design` / `contract`。于是
        `plan_tests(objective, case, provider=DeterministicLocalProvider())` 这种
        最自然的用法会得到 `design="design"`、端口全空的计划：轨迹"合法"、仿真
        "通过"，但既没有激励也没有参考模型期望值——一个静默失效的假通过。
        现在：能从提示词解析就用提示词，仍然拿不到 contract 就取仓库自带合约，
        设计名不在内置案例里则**直接报错**，不生成无效计划。
        """

        design, contract = self._resolve_request(prompt)
        inputs, _outputs, clock, _reset = _port_summary(contract)
        driveable = [name for name in inputs if name != clock]
        if not design:
            raise ValueError("request does not name a Design; the deterministic local provider cannot build a plan")
        # 判据是"能不能真的施加激励"，而不是"设计名认不认识"：调用方完全可以带一份
        # 自定义合约来生成随机激励（单元测试就这么用）。但如果既没有合约、设计名也不在
        # 内置案例里，生成出来的会是一份端口全空的计划——那比报错危险得多。
        if not driveable:
            raise ValueError(
                f"cannot drive design {design!r}: no DUT contract with input ports in the request, "
                "and it is not a bundled example. Bundled examples: "
                + ", ".join(sorted(known_designs()))
            )
        self._active_design = design
        self._resolved_contract = contract
        if self.mode == "invalid_json":
            return "{ this is deliberately not valid JSON"
        if self.mode == "empty":
            return ""
        if self.mode == "out_of_range":
            return json.dumps(self._out_of_range_plan(), ensure_ascii=False)
        return json.dumps(self._plan(), ensure_ascii=False)

    def _resolve_request(self, prompt: str) -> tuple[str, dict[str, Any]]:
        """解析本次请求的设计名与合约（自身字段 → 提示词 → 仓库内置合约）。"""

        design = str(self.design or "")
        contract: dict[str, Any] = dict(self.contract or {}) if isinstance(self.contract, Mapping) else {}
        if not design or not contract.get("ports"):
            extracted_design, extracted_contract = extract_request(
                prompt or "", default_design=design or None, default_contract=contract or None
            )
            design = design or extracted_design
            if not contract.get("ports") and extracted_contract:
                contract = dict(extracted_contract)
        if design and not contract.get("ports"):
            bundled = bundled_contract(design)
            if bundled:
                contract = bundled
        return design, contract

    # ------------------------------------------------------------------
    def _out_of_range_plan(self) -> dict[str, Any]:
        inputs, _outputs, clock, reset = _port_summary(self._active_contract())
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
        out_of_range_spec = _reset_spec(self._active_contract())
        return {
            "schema_version": "1.0",
            "design": self._design_name(),
            "objective": "negative test: value outside the port width",
            "clock_period_ns": 10,
            "reset": {"active_low": (out_of_range_spec.active_level == 0) if out_of_range_spec is not None else True},
            "vectors": vectors,
        }

    def _design_name(self) -> str:
        return str(self._active_design if self._active_design is not None else (self.design or "design"))

    def _active_contract(self) -> Mapping[str, Any]:
        """本次请求实际使用的合约（`generate` 解析后写入）。"""

        return self._resolved_contract if self._resolved_contract is not None else (self.contract or {})

    def _plan(self) -> dict[str, Any]:
        inputs, _outputs, clock, reset = _port_summary(self._active_contract())
        driveable = [name for name in inputs if name != clock]
        rng = random.Random(f"{self._design_name()}:{self.seed}")
        steps = _INPUT_STEPS.get(self._design_name())
        extra = _EXTRA_CYCLES.get(self._design_name(), 0)
        vectors: list[dict[str, Any]] = []
        spec = _reset_spec(self._active_contract())
        reset_signal = spec.signal if spec is not None else None
        inactive = spec.inactive_level if spec is not None else 1

        if spec is not None and spec.signal in driveable:
            vectors.append(
                {
                    "name": "debug_reset",
                    "inputs": {spec.signal: spec.active_level},
                    "cycles": spec.assert_cycles,
                    "sample_phase": "after",
                    "expected": {},
                    # 电平来自合约的 active_level：低有效写 0、高有效写 1。
                    "rationale": f"hold {spec.signal} at its active level ({spec.active_level}) to drive the DUT into a known state",
                }
            )

        for index in range(self.vector_count):
            payload: dict[str, Any] = {}
            for name in driveable:
                if name == reset_signal:
                    # 释放复位：写**无效**电平，也就是 1 - active_level。
                    # 旧实现写死 1，高有效复位下等于把 DUT 一直摁在复位里。
                    payload[name] = inactive
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
                else:
                    payload[name] = _generic_value(width, index, rng)
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
            if reset_signal and reset_signal not in stimulus and reset_signal in driveable:
                stimulus[reset_signal] = inactive
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
            # active_low 由合约推导，不再写死 True。
            "reset": {"active_low": (spec.active_level == 0) if spec is not None else True},
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


def offline_provider(
    contract: Any,
    *,
    design: str | None = None,
    vector_count: int = _DEFAULT_VECTOR_COUNT,
    seed: int = 0,
) -> DeterministicLocalProvider:
    """按 DUT contract 构建**进程内**的离线规划器（不需要密钥，也不联网）。

    为什么要有这个函数：网页的「离线」模式曾经接到 ``MockProvider()`` 的默认返回
    值上，而那份写死的演示计划固定驱动 ``rst_n``。对任何**组合逻辑**案例
    （``simple_alu``、``mux4`` 的合约里没有时钟、也没有复位）而言，这份计划在生成
    testbench 时必然报 ``vectors[0].inputs contains unknown port 'rst_n'``——用户看到
    的是"离线模式坏了、真实仿真却能过"。

    离线路径的正确做法是按**当前合约**生成激励，也就是本地调试模型服务
    （``debug_server``）用的同一个引擎，区别只是不经 HTTP：
    同一条确定性规则，同一个 ``seed``，永远得到同一份计划。
    它不代表任何模型能力，也不能作为 AI 效果数据。
    """

    if hasattr(contract, "to_dict"):
        payload = dict(contract.to_dict())
    elif isinstance(contract, Mapping):
        payload = dict(contract)
    else:
        raise TypeError("offline_provider requires a DutContract or a contract mapping")
    name = design or payload.get("module") or ""
    if not isinstance(name, str) or not name:
        raise ValueError("offline_provider could not determine a design name from the contract")
    return DeterministicLocalProvider(
        contract=payload,
        design=name,
        vector_count=int(vector_count),
        seed=int(seed),
    )


__all__ = ["DeterministicLocalProvider", "offline_provider"]
