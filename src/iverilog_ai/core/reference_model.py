"""内置案例的确定性参考模型：既做一致性诊断，也提供权威期望值。

本模块有两类用途，必须区分清楚：

1. ``check_plan_consistency`` 只做**诊断**：比较 AI 计划的期望值与参考模型
   复算值，报告 ``plan_inconsistent`` 警告，不改变任何裁决结论。
2. ``reference_expectations`` / ``override_plan_expectations`` 提供**权威预言机**：
   内置案例的期望值由参考模型独立复算，覆盖 AI 给出的数字，使 AI 无法通过
   猜错期望值来"制造"失败或"掩盖"失败。

参考模型只覆盖内置案例；未建模的设计会被显式跳过，不会被推断为通过。
"""
from __future__ import annotations
from typing import Any, Iterable, Mapping

from ..ai.schema import TestPlan
from .contracts import DutContract

SUPPORTED = {
    "mod10_counter", "simple_alu", "sequence_101_overlap", "traffic_light_emergency",
    "sync_fifo", "uart_tx", "spi_master", "handshake_stage", "debounce", "pwm", "mux4", "sync_reset",
    "johnson_counter", "edge_detector", "pulse_stretcher",
    "credit_guard", "rotating_arbiter",
    "valid_data_pipeline", "event_accumulator",
}

# 可作为**权威预言机**的设计：这些模型已逐项对照参考 RTL 的手写 testbench 验证过，
# 因此可以用它们的复算值覆盖 AI 期望值。
#
# 其余案例的模型只用于**诊断**：在没有与 RTL 逐拍对齐之前，它们不应决定 PASS/FAIL，
# 否则一句错误的模型语义就会把"参考设计通过"变成 warn 失败。这类案例回退为
# AI 期望值，并在 oracle 记录里如实标注 expectation_source="ai_generated"。
#
# 放宽这个集合的方法只有一个：让模型与 RTL 逐拍对齐。可复用的做法见
# tests/core/test_reference_model_alignment.py——它把同一组向量同时喂给模型和
# RTL，逐拍比较 rd_data/empty/full 一类的可观测输出，要求零差异。
# 对齐一个才加入一个；sync_fifo 就是这样对齐后加入的。
AUTHORITATIVE: frozenset[str] = frozenset({
    "mod10_counter",
    "simple_alu",
    "sequence_101_overlap",
    "traffic_light_emergency",
    "sync_fifo",
    "uart_tx",
    "spi_master",
    "handshake_stage",
    "debounce",
    "pwm",
    "sync_reset",
    "mux4",
    "johnson_counter",
    "edge_detector",
    "pulse_stretcher",
    "credit_guard",
    "rotating_arbiter",
    "valid_data_pipeline",
    "event_accumulator",
})

# 内置案例的**输入端口默认值**：单一事实来源。
#
# 为什么需要它：测试激励经常只列出本拍关心的输入，其余端口保持上一次的值。
# 如果模型对"未列出的端口"用一套默认值、而测试台用另一套（端口初值 0），
# 两边就会算出不同的期望值——实测中 debounce 因此产生了 25 条伪失败。
# 因此这里显式声明每个输入的默认值：模型用它复算，实验激励生成器用它把
# 向量补全（见 scripts/run_strategy_experiment.py 的 _complete_inputs），
# `tests/core/test_reference_model_alignment.py` 校验"补全后的向量"与 RTL 逐拍一致。
#
# reset 字段是低有效复位端口的默认（非激活）电平，缺省为 0。
INPUT_DEFAULTS: dict[str, dict[str, Any]] = {
    "mod10_counter": {"rst_n": 1, "enable": 0},
    "simple_alu": {"a": 0, "b": 0, "op": 0},
    "sequence_101_overlap": {"rst_n": 1, "bit_in": 0},
    "traffic_light_emergency": {"rst_n": 1, "emergency": 0},
    "sync_fifo": {"rst_n": 1, "wr_en": 0, "wr_data": 0, "rd_en": 0},
    "uart_tx": {"rst_n": 1, "start": 0, "data_in": 0},
    "spi_master": {"rst_n": 1, "start": 0, "data_in": 0},
    "handshake_stage": {"rst_n": 1, "in_valid": 0, "in_data": 0, "out_ready": 0},
    "debounce": {"rst_n": 1, "key_in": 0},
    "pwm": {"rst_n": 1, "duty": 0},
    "sync_reset": {"ext_rst_n": 1},
    "mux4": {"d0": 0, "d1": 0, "d2": 0, "d3": 0, "sel": 0},
    "johnson_counter": {"rst_n": 1, "enable": 0},
    "edge_detector": {"rst_n": 1, "signal_in": 0},
    "pulse_stretcher": {"rst_n": 1, "pulse_in": 0},
    "credit_guard": {"rst_n": 1, "acquire": 0, "release_req": 0},
    "rotating_arbiter": {"rst_n": 1, "request": 0, "advance": 0},
    "valid_data_pipeline": {"i_rstn": 1, "i_flush": 0, "i_valid": 0, "i_data": 0},
    "event_accumulator": {"i_rstn": 1, "i_enable": 0, "i_event": 0, "i_clear": 0},
}

# 新增留出设计的参考值只对固定合约开放，不能只凭同名字符串把外部
# 任意接口/参数当作权威。既有十五类参考模型的兼容调用保持不变。
_NEW_INTERNAL_HOLDOUT_DESIGNS = frozenset({"valid_data_pipeline", "event_accumulator"})
_FIXED_HOLDOUT_DESIGNS = frozenset({"credit_guard", "rotating_arbiter"}) | _NEW_INTERNAL_HOLDOUT_DESIGNS


class ReferenceSamplingError(ValueError):
    """逐拍参考检查没有已验证的合约或确定性输入，不能生成权威期望值。"""


PER_CYCLE_PROFILE_VERSION = "builtin-reference-per-cycle-v1"

# 逐拍模式只开放逐拍对齐测试使用的固定配置。不能把一个同名、任意位宽
# 的外部模块或被 _clamp 修正的参数默认为已验证的参考行为。
_PER_CYCLE_PARAMETERS: dict[str, dict[str, int]] = {
    "sync_fifo": {"DATA_WIDTH": 8, "DEPTH": 4},
    "uart_tx": {"CLKS_PER_BIT": 4},
    "spi_master": {"WIDTH": 8},
    "handshake_stage": {"WIDTH": 8},
    "debounce": {"COUNT_MAX": 3},
    "pwm": {"WIDTH": 8},
    "mux4": {"WIDTH": 8},
    "pulse_stretcher": {"WIDTH": 4},
}
_PER_CYCLE_DATA_PORTS: dict[str, tuple[dict[str, int], dict[str, int]]] = {
    "mod10_counter": ({"enable": 1}, {"count": 4}),
    "simple_alu": ({"a": 8, "b": 8, "op": 3}, {"result": 8, "carry": 1, "zero": 1}),
    "sequence_101_overlap": ({"bit_in": 1}, {"detected": 1}),
    "traffic_light_emergency": ({"emergency": 1}, {"main_light": 2, "side_light": 2}),
    "sync_fifo": ({"wr_en": 1, "wr_data": 8, "rd_en": 1}, {"rd_data": 8, "full": 1, "empty": 1}),
    "uart_tx": ({"start": 1, "data_in": 8}, {"tx": 1, "busy": 1}),
    "spi_master": ({"start": 1, "data_in": 8}, {"sclk": 1, "mosi": 1, "busy": 1, "done": 1}),
    "handshake_stage": ({"in_valid": 1, "in_data": 8, "out_ready": 1}, {"in_ready": 1, "out_valid": 1, "out_data": 8}),
    "debounce": ({"key_in": 1}, {"key_state": 1}),
    "pwm": ({"duty": 8}, {"pwm_out": 1}),
    "sync_reset": ({}, {"rst_n": 1}),
    "mux4": ({"d0": 8, "d1": 8, "d2": 8, "d3": 8, "sel": 2}, {"y": 8}),
    "johnson_counter": ({"enable": 1}, {"q": 4}),
    "edge_detector": ({"signal_in": 1}, {"rising": 1}),
    "pulse_stretcher": ({"pulse_in": 1}, {"pulse_out": 1}),
    "credit_guard": ({"acquire": 1, "release_req": 1}, {"credits": 3}),
    "rotating_arbiter": ({"request": 4, "advance": 1}, {"grant": 4}),
    "valid_data_pipeline": ({"i_flush": 1, "i_valid": 1, "i_data": 8}, {"o_valid": 1, "o_data": 8}),
    "event_accumulator": ({"i_enable": 1, "i_event": 1, "i_clear": 1}, {"o_count": 4}),
}


def reference_sampling_profile(contract: DutContract) -> str | None:
    """识别已对齐的内置逐拍合约；内置/外部策略仍须由调用方明确选择。"""
    if not isinstance(contract, DutContract) or contract.module not in AUTHORITATIVE:
        return None
    shape = _PER_CYCLE_DATA_PORTS.get(contract.module)
    if shape is None or any(port.signed for port in contract.ports):
        return None
    inputs, outputs = shape
    inputs = dict(inputs)
    combinational = contract.module in {"simple_alu", "mux4"}
    if combinational:
        if contract.clock is not None or contract.reset is not None:
            return None
    else:
        new_internal = contract.module in _NEW_INTERNAL_HOLDOUT_DESIGNS
        clock_signal = "i_clk" if new_internal else "clk"
        reset_signal = "i_rstn" if new_internal else "ext_rst_n" if contract.module == "sync_reset" else "rst_n"
        inputs.update({clock_signal: 1, reset_signal: 1})
        clock, reset = contract.clock, contract.reset
        if (clock is None or clock.signal != clock_signal or clock.edge != "posedge"
                or clock.period_ns <= 2 or reset is None or reset.signal != reset_signal
                or reset.active_level != 0 or reset.synchronous):
            return None
        if new_internal and (clock.period_ns != 10 or reset.assert_cycles != 2
                             or any(port.initial is not None for port in contract.ports)):
            return None
    ports = {name: ("input", width) for name, width in inputs.items()}
    ports.update({name: ("output", width) for name, width in outputs.items()})
    defaults = _PER_CYCLE_PARAMETERS.get(contract.module, {})
    if ({port.name: (port.direction.value, port.width) for port in contract.ports} != ports
            or {**defaults, **contract.parameters} != defaults):
        return None
    return f"{PER_CYCLE_PROFILE_VERSION}:{contract.module}"


def completed_inputs(design: str, inputs: Mapping[str, Any] | None) -> dict[str, Any]:
    """把向量里未列出的输入补成该设计的默认值。

    模型与激励生成器共用这一份默认值，避免"同一拍两个默认值"造成伪失败。
    未建模的设计直接原样返回。
    """

    defaults = INPUT_DEFAULTS.get(design)
    if not defaults:
        return dict(inputs or {})
    completed = dict(defaults)
    completed.update({str(key): value for key, value in (inputs or {}).items()})
    return completed

def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)

def _vectors(plan: Any) -> Iterable[Any]:
    vectors = _get(plan, "vectors")
    if vectors is not None: return vectors
    out = []
    for case in _get(plan, "cases", ()):
        out.extend(_get(case, "steps", ()) or _get(case, "vectors", ()))
    return out


def _unsupported_sampling(plan: Any, design: str) -> bool:
    # Sequential state.step models outputs after the clock edge. A before
    # sample is taken earlier by the real TB, and needs a separate timing model.
    return design not in {"simple_alu", "mux4"} and any(
        _get(vector, "sample_phase", "after") == "before" for vector in _vectors(plan))


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


class _DesignState:
    """一次计划评估内的可变状态，覆盖所有受支持的内置案例。"""

    def __init__(self, design: str, contract: Any = None) -> None:
        self.design = design
        parameters = _get(contract, "parameters", {}) or {}
        mapping = parameters if isinstance(parameters, Mapping) else {}
        self.state, self.history, self.traffic = 0, [0, 0], 0
        self.fifo_depth = _clamp(mapping.get("DEPTH", 4), 1, 1024, 4)
        self.fifo_mem, self.fifo_wr, self.fifo_rd, self.fifo_count, self.fifo_rd_data = [0] * self.fifo_depth, 0, 0, 0, 0
        self.uart_clks_per_bit = _clamp(mapping.get("CLKS_PER_BIT", 4), 1, 65535, 4)
        self.uart_busy, self.uart_tx, self.uart_tick, self.uart_bit, self.uart_frame = 0, 1, 0, 0, 0
        self.spi_width = _clamp(mapping.get("WIDTH", 8), 2, 32, 8)
        self.spi_busy, self.spi_sclk, self.spi_mosi, self.spi_done, self.spi_count, self.spi_shift = 0, 0, 0, 0, 0, 0
        self.hs_valid, self.hs_data = 0, 0
        self.debounce_max = _clamp(mapping.get("COUNT_MAX", 3), 1, 15, 3)
        self.debounce_count, self.debounce_sample, self.debounce_state = 0, 1, 1
        self.pwm_counter, self.pwm_out = 0, 0
        self.sync_ff, self.sync_rst = 0, 0
        self.johnson_q = 0
        self.edge_prev, self.edge_rising = 0, 0
        self.pulse_width = _clamp(mapping.get("WIDTH", 4), 1, 32, 4)
        self.pulse_count, self.pulse_out = 0, 0
        self.credits = 3
        self.arbiter_pointer, self.arbiter_grant = 0, 0
        # 新内部合成模块的语义不复制 RTL 寄存器链/递加器：
        # 流水用到期令牌投递，计数用自清除以来接受事件的集合基数。
        self.new_holdout_edge = 0
        self.pipeline_due_tokens: dict[int, int] = {}
        self.pipeline_outputs = {"o_valid": 0, "o_data": 0}
        self.event_accepted_edges: set[int] = set()

    def step(self, inputs: Mapping[str, Any], cycles: int) -> dict[str, Any]:
        """把单个向量推进 ``cycles`` 个周期，返回该向量结束时的可观测输出。

        未列出的输入按 :data:`INPUT_DEFAULTS` 补全，与实验激励生成器保持同一
        口径——否则"模型认为的默认值"和"测试台端口初值"会不一致。
        """

        inputs = completed_inputs(self.design, inputs)
        design = self.design
        if design == "simple_alu":
            a, b, op = int(inputs.get("a", 0)), int(inputs.get("b", 0)), int(inputs.get("op", 0))
            if op == 0: ext = a + b; result, carry = ext & 255, int(ext > 255)
            elif op == 1: result, carry = (a - b) & 255, int(a >= b)
            elif op == 2: result, carry = a & b, 0
            elif op == 3: result, carry = a | b, 0
            elif op == 4: result, carry = a ^ b, 0
            elif op == 5: result, carry = (a << 1) & 255, 0
            elif op == 6: result, carry = a >> 1, 0
            else: result, carry = 0, 0
            return {"result": result, "carry": carry, "zero": int(result == 0)}
        if design == "mod10_counter":
            rst, enable = int(inputs.get("rst_n", inputs.get("reset", 1))), int(inputs.get("enable", 0))
            for _ in range(cycles): self.state = 0 if rst == 0 else ((self.state + 1) % 10 if enable else self.state)
            return {"count": self.state}
        if design == "valid_data_pipeline":
            rst, flush = int(inputs["i_rstn"]), int(inputs["i_flush"])
            valid, data = int(inputs["i_valid"]), int(inputs["i_data"])
            for _ in range(cycles):
                edge = self.new_holdout_edge
                if rst == 0 or flush:
                    self.pipeline_due_tokens.clear()
                    self.pipeline_outputs = {"o_valid": 0, "o_data": 0}
                else:
                    delivered = self.pipeline_due_tokens.pop(edge, None)
                    self.pipeline_outputs = {"o_valid": int(delivered is not None),
                                             "o_data": 0 if delivered is None else delivered}
                    if valid:
                        self.pipeline_due_tokens[edge + 1] = data
                self.new_holdout_edge += 1
            return dict(self.pipeline_outputs)
        if design == "event_accumulator":
            rst, clear = int(inputs["i_rstn"]), int(inputs["i_clear"])
            enabled, event = int(inputs["i_enable"]), int(inputs["i_event"])
            for _ in range(cycles):
                if rst == 0 or clear:
                    self.event_accepted_edges.clear()
                elif enabled and event:
                    self.event_accepted_edges.add(self.new_holdout_edge)
                self.new_holdout_edge += 1
            return {"o_count": len(self.event_accepted_edges) % 16}
        if design == "credit_guard":
            rst = int(inputs.get("rst_n", 1))
            acquire, release = int(inputs.get("acquire", 0)), int(inputs.get("release_req", 0))
            for _ in range(cycles):
                if rst == 0:
                    self.credits = 3
                elif bool(acquire) != bool(release):
                    # One accepted direction per cycle; equal request levels
                    # hold the state, and arithmetic saturates at both limits.
                    self.credits = max(0, self.credits - 1) if acquire else min(7, self.credits + 1)
            return {"credits": self.credits}
        if design == "rotating_arbiter":
            rst = int(inputs.get("rst_n", 1))
            request, advance = int(inputs.get("request", 0)), int(inputs.get("advance", 0))
            for _ in range(cycles):
                if rst == 0:
                    self.arbiter_pointer, self.arbiter_grant = 0, 0
                    continue
                # Pick from the old pointer. Updating the pointer after that
                # choice affects the next cycle, never this registered grant.
                priority = [(self.arbiter_pointer + offset) % 4 for offset in range(4)]
                selected = next((index for index in priority if request & (1 << index)), None)
                self.arbiter_grant = 0 if selected is None else 1 << selected
                if advance and selected is not None:
                    self.arbiter_pointer = (selected + 1) % 4
            return {"grant": self.arbiter_grant}
        if design == "sequence_101_overlap":
            bit, rst, detected = int(inputs.get("bit_in", 0)), int(inputs.get("rst_n", 1)), 0
            for _ in range(cycles):
                if rst == 0: self.history, detected = [0, 0], 0
                else: detected, self.history = int(self.history == [1, 0] and bit == 1), [self.history[1], bit]
            return {"detected": detected}
        if design == "traffic_light_emergency":
            emergency, rst = int(inputs.get("emergency", 0)), int(inputs.get("rst_n", 1))
            for _ in range(cycles): self.traffic = 0 if rst == 0 else (1 if emergency else (self.traffic + 1) % 4)
            if emergency:
                # 紧急模式是组合覆盖：主路黄灯、支路红灯，与内部状态无关。
                return {"main_light": 1, "side_light": 0}
            return [{"main_light": 2, "side_light": 0}, {"main_light": 1, "side_light": 0},
                    {"main_light": 0, "side_light": 2}, {"main_light": 0, "side_light": 1}][self.traffic]
        if design == "sync_fifo":
            rst, wr_en = int(inputs.get("rst_n", 1)), int(inputs.get("wr_en", 0))
            rd_en, wr_data = int(inputs.get("rd_en", 0)), int(inputs.get("wr_data", 0)) & 255
            # 该模型与 rtl/sync_fifo.v 逐拍对齐，并通过独立队列规格验证。关键语义：
            #   1. rd_data 是寄存器输出，读发生时在同一个时钟沿就更新为新值；
            #   2. 写判定 `!full` 与读判定 `!empty` 用的都是**时钟沿之前**的
            #      count——因为 full/empty 由 assign 组合产生，非阻塞赋值右侧
            #      读到的是旧寄存器的值；
            #   3. 同拍接受读写时占用量净变化为 0。2026-10-04 修复了旧 RTL
            #      两条 count 非阻塞赋值使最后读赋值覆盖写赋值的计数问题。
            #      历史已冻结实验仍属于旧 RTL/模型，不追溯改写其结果。
            for _ in range(cycles):
                if rst == 0:
                    self.fifo_mem, self.fifo_wr, self.fifo_rd, self.fifo_count, self.fifo_rd_data = [0] * self.fifo_depth, 0, 0, 0, 0
                    continue
                full_now = self.fifo_count == self.fifo_depth
                empty_now = self.fifo_count == 0
                do_write = bool(wr_en and not full_now)
                do_read = bool(rd_en and not empty_now)
                new_rd_data = self.fifo_mem[self.fifo_rd] if do_read else self.fifo_rd_data
                new_count = self.fifo_count + int(do_write) - int(do_read)
                if do_write:
                    self.fifo_mem[self.fifo_wr] = wr_data
                    self.fifo_wr = (self.fifo_wr + 1) % self.fifo_depth
                if do_read:
                    self.fifo_rd = (self.fifo_rd + 1) % self.fifo_depth
                self.fifo_count, self.fifo_rd_data = new_count, new_rd_data
            return {"rd_data": self.fifo_rd_data, "full": int(self.fifo_count == self.fifo_depth), "empty": int(self.fifo_count == 0)}
        if design == "uart_tx":
            rst, start, data_in = int(inputs.get("rst_n", 1)), int(inputs.get("start", 0)), int(inputs.get("data_in", 0)) & 255
            # 已与 rtl/uart_tx.v 逐拍对齐。行尾的终端拍是最容易写错的地方：
            # RTL 写的是
            #     if (tick==CLKS_PER_BIT-1) begin tick<=0; bit_idx<=bit_idx+1;
            #         if (bit_idx==9) ... else tx<=frame[bit_idx+1]; end
            # `bit_idx<=bit_idx+1` 是非阻塞赋值，因此同一时刻 tx 读到的
            # `frame[bit_idx+1]` 用的是**旧**的 bit_idx——新位要等下一拍才上线。
            def frame_bit(position: int) -> int:
                return (self.uart_frame >> position) & 1 if 0 <= position < 10 else 0

            for _ in range(cycles):
                if rst == 0:
                    self.uart_tx, self.uart_busy, self.uart_bit, self.uart_tick, self.uart_frame = 1, 0, 0, 0, 0
                elif not self.uart_busy:
                    self.uart_tx = 1
                    if start:
                        self.uart_frame = (1 << 9) | (data_in << 1); self.uart_busy = 1; self.uart_bit = 0; self.uart_tick = 0; self.uart_tx = 0
                elif self.uart_tick == self.uart_clks_per_bit - 1:
                    # 用旧 bit_idx 决定这一拍发什么，然后再推进 bit_idx
                    self.uart_tick = 0
                    if self.uart_bit == 9:
                        self.uart_busy = 0; self.uart_tx = 1
                    else:
                        self.uart_tx = frame_bit(self.uart_bit + 1)
                    self.uart_bit += 1
                else:
                    self.uart_tick += 1
            return {"tx": self.uart_tx, "busy": self.uart_busy}
        if design == "spi_master":
            rst, start, data_in = int(inputs.get("rst_n", 1)), int(inputs.get("start", 0)), int(inputs.get("data_in", 0)) & 255
            # 已与 rtl/spi_master.v 逐拍对齐。与 uart_tx 同理，sclk 翻转后同一
            # 时刻读到的 `!sclk` 是**旧**值，因此 mosi 用的是移位**之前**的
            # `shift[WIDTH-2]`；模型必须先算好这一拍要用的旧值再更新寄存器。
            def shift_bit(position: int) -> int:
                return (self.spi_shift >> position) & 1 if 0 <= position < 32 else 0

            for _ in range(cycles):
                self.spi_done = 0
                if rst == 0:
                    self.spi_sclk, self.spi_mosi, self.spi_busy, self.spi_done, self.spi_count, self.spi_shift = 0, 0, 0, 0, 0, 0
                elif not self.spi_busy:
                    self.spi_sclk = 0
                    if start:
                        self.spi_busy = 1
                        self.spi_shift = data_in
                        self.spi_count = 0
                        self.spi_mosi = (data_in >> (self.spi_width - 1)) & 1
                else:
                    was_low = self.spi_sclk == 0
                    self.spi_sclk = 1 if was_low else 0
                    if was_low:
                        if self.spi_count == self.spi_width - 1:
                            self.spi_busy = 0
                            self.spi_done = 1
                        else:
                            self.spi_count += 1
                            self.spi_mosi = shift_bit(self.spi_width - 2)
                            self.spi_shift = (self.spi_shift << 1) & 255
            return {"sclk": self.spi_sclk, "mosi": self.spi_mosi, "busy": self.spi_busy, "done": self.spi_done}
        if design == "handshake_stage":
            rst, in_valid, out_ready, in_data = int(inputs.get("rst_n", 1)), int(inputs.get("in_valid", 0)), int(inputs.get("out_ready", 0)), int(inputs.get("in_data", 0)) & 255
            for _ in range(cycles):
                in_ready = int((not self.hs_valid) or bool(out_ready))
                if rst == 0: self.hs_valid, self.hs_data = 0, 0
                elif in_ready: self.hs_valid = in_valid; self.hs_data = in_data if in_valid else self.hs_data
            return {"in_ready": int((not self.hs_valid) or bool(out_ready)), "out_valid": self.hs_valid, "out_data": self.hs_data}
        if design == "debounce":
            rst, key_in = int(inputs.get("rst_n", 1)), int(inputs.get("key_in", 0))
            # 已与 rtl/debounce.v 逐拍对齐。注意终端拍的 key_state：RTL 写的是
            #     else if (count==COUNT_MAX-1) begin sample<=key_in; key_state<=key_in; ... end
            # 三个都是非阻塞赋值，因此采样点上看到的 key_state 是**本拍新写入**的
            # key_in，而不是旧值。模型若返回赋值前的 state 就会整体晚一拍。
            for _ in range(cycles):
                if rst == 0:
                    self.debounce_count, self.debounce_sample, self.debounce_state = 0, 1, 1
                elif key_in == self.debounce_sample:
                    self.debounce_count = 0
                elif self.debounce_count == self.debounce_max - 1:
                    self.debounce_sample, self.debounce_state, self.debounce_count = key_in, key_in, 0
                else:
                    self.debounce_count += 1
            return {"key_state": self.debounce_state}
        if design == "pwm":
            rst, duty = int(inputs.get("rst_n", 1)), int(inputs.get("duty", 0)) & 255
            for _ in range(cycles):
                if rst == 0: self.pwm_counter, self.pwm_out = 0, 0
                else: self.pwm_out = int(self.pwm_counter < duty); self.pwm_counter = (self.pwm_counter + 1) & 255
            return {"pwm_out": self.pwm_out}
        if design == "mux4":
            sel = int(inputs.get("sel", 0)) & 3
            return {"y": int(inputs.get(f"d{sel}", 0)) & 255}
        if design == "sync_reset":
            ext_rst_n = int(inputs.get("ext_rst_n", 1))
            for _ in range(cycles):
                if ext_rst_n == 0: self.sync_ff, self.sync_rst = 0, 0
                else: self.sync_ff, self.sync_rst = 1, self.sync_ff
            return {"rst_n": self.sync_rst}
        if design == "johnson_counter":
            rst, enable = int(inputs.get("rst_n", 1)), int(inputs.get("enable", 0))
            # 已与 rtl/johnson_counter.v 逐拍对齐。移位串右端反馈的是最高位的
            # **反相**，所以 0000 不是吸收态，复位后 8 拍走完
            # 0000 → 0001 → 0011 → 0111 → 1111 → 1110 → 1100 → 1000 → 0000。
            for _ in range(cycles):
                if rst == 0:
                    self.johnson_q = 0
                elif enable:
                    top = (self.johnson_q >> 3) & 1
                    self.johnson_q = ((self.johnson_q << 1) | (1 - top)) & 0xF
            return {"q": self.johnson_q}
        if design == "edge_detector":
            rst, sig = int(inputs.get("rst_n", 1)), int(inputs.get("signal_in", 0)) & 1
            # 已与 rtl/edge_detector.v 逐拍对齐。两条非阻塞赋值同拍生效：本拍的
            # `rising` 用的是**上一拍**的 signal_d，因此必须先用旧的历史位算出
            # 脉冲，再更新历史位——反过来写就整体晚一拍。
            for _ in range(cycles):
                if rst == 0:
                    self.edge_prev, self.edge_rising = 0, 0
                else:
                    self.edge_rising, self.edge_prev = sig & (1 - self.edge_prev), sig
            return {"rising": self.edge_rising}
        if design == "pulse_stretcher":
            rst, pulse_in = int(inputs.get("rst_n", 1)), int(inputs.get("pulse_in", 0)) & 1
            # 已与 rtl/pulse_stretcher.v 逐拍对齐。四个分支的优先级与 RTL 一致，
            # 且全部按**非阻塞**语义：`count != 0` 读的是本拍开始时的旧值，
            # 因此脉冲输入结束后还会多保持 (WIDTH-1) 拍才回落。
            mask = (1 << max(1, self.pulse_width)) - 1
            for _ in range(cycles):
                if rst == 0:
                    self.pulse_count, self.pulse_out = 0, 0
                elif pulse_in:
                    self.pulse_count, self.pulse_out = self.pulse_width - 1, 1
                elif self.pulse_count != 0:
                    self.pulse_count = (self.pulse_count - 1) & mask
                    self.pulse_out = 1
                else:
                    self.pulse_out = 0
            return {"pulse_out": self.pulse_out}
        return {}


def reference_expectations(
    plan: Any,
    design: str | None = None,
    contract: Any = None,
    *,
    authoritative_only: bool = True,
) -> dict[str, dict[str, Any]]:
    """按向量名返回参考模型独立复算的稳态输出。

    ``authoritative_only=True``（默认）只对 :data:`AUTHORITATIVE` 中已与 RTL 核对
    过的设计返回期望值；其余设计返回空字典，调用方回退为 AI 期望值并如实标注
    来源。诊断路径（``check_plan_consistency``）传 ``False``：它只报告差异，
    不参与裁决，因此可以用上全部已建模案例。

    只返回 DUT contract 中确实存在、且参考模型确实建模了的信号，因此调用方
    可以安全地用它约束 testbench 的期望值，而不必信任模型给出的数字。
    """

    plan_design = str(design or _get(plan, "design", ""))
    if plan_design not in SUPPORTED:
        return {}
    if authoritative_only and plan_design not in AUTHORITATIVE:
        return {}
    if plan_design in _FIXED_HOLDOUT_DESIGNS and (
            not isinstance(contract, DutContract) or contract.module != plan_design
            or reference_sampling_profile(contract) is None):
        return {}
    if _unsupported_sampling(plan, plan_design):
        return {}
    if plan_design in _NEW_INTERNAL_HOLDOUT_DESIGNS:
        # 新模型的 vector_end 也沿用逐拍路径的已知位解析和完整合约约束；
        # 不凭名字、字典合约或无法解码的 X/Z 返回权威数字。
        if not isinstance(plan, TestPlan) or not isinstance(contract, DutContract):
            return {}
        try:
            cycle_table = reference_cycle_expectations(plan, contract)
        except ReferenceSamplingError:
            return {}
        return {name: dict(rows[-1]) for name, rows in cycle_table.items()}
    port_names: set[str] | None = None
    if contract is not None:
        ports = _get(contract, "ports", None)
        if isinstance(ports, (list, tuple)):
            names = {str(_get(port, "name", "")) for port in ports}
            if names:
                port_names = names
    state = _DesignState(plan_design, contract)
    held_inputs = dict(INPUT_DEFAULTS.get(plan_design, {}))
    if contract is not None:
        for port in _get(contract, "ports", ()) or ():
            direction = _get(port, "direction", "")
            if getattr(direction, "value", direction) in {"input", "inout"}:
                # The generated TB initializes driven inputs to zero, then
                # releases the explicit contract reset before the first vector.
                held_inputs[str(_get(port, "name", ""))] = 0
        reset = _get(contract, "reset", None)
        if reset is not None:
            held_inputs[str(_get(reset, "signal", ""))] = 1 - int(_get(reset, "active_level", 0))
    expectations: dict[str, dict[str, Any]] = {}
    for index, vector in enumerate(_vectors(plan)):
        name = str(_get(vector, "name", _get(vector, "id", f"vector_{index + 1}")))
        inputs = _get(vector, "inputs", {}) or {}
        if not isinstance(inputs, Mapping):
            continue
        held_inputs.update(inputs)
        cycles = int(_get(vector, "cycles", 1) or 1)
        actual = state.step(held_inputs, cycles)
        selected = {signal: value for signal, value in actual.items() if port_names is None or signal in port_names}
        expectations[name] = selected
    return expectations


def reference_cycle_expectations(
    plan: TestPlan,
    contract: DutContract,
) -> dict[str, tuple[dict[str, int], ...]]:
    """为原计划各向量逐拍复算期望值，不展开或改写 TestPlan。

    每一项来自 ``state.step(held_inputs, 1)``。未列输入保持上一驱动值；
    初始化与 testbench 相同，并明确推进合约的隐式复位。只支持已逐拍
    对齐的固定合约和 after 采样，未知输入无法生成权威数字。
    """
    # 延迟导入受控标量编码器，复用生成器的字面值/宽度解释，避免另一套解析。
    from .testbench import _encode_value, TestbenchGenerationError

    if not isinstance(plan, TestPlan) or not isinstance(contract, DutContract):
        raise ReferenceSamplingError("per_cycle requires a TestPlan and DutContract")
    if plan.design != contract.module or reference_sampling_profile(contract) is None:
        raise ReferenceSamplingError("per_cycle reference contract/profile is not supported")
    if any(vector.sample_phase != "after" for vector in plan.vectors):
        raise ReferenceSamplingError("per_cycle reference sampling supports after only")
    if sum(vector.cycles for vector in plan.vectors) > 100_000:
        raise ReferenceSamplingError("per_cycle reference exceeds 100000 cycles")
    state = _DesignState(contract.module, contract)
    held_inputs = {port.name: 0 for port in contract.inputs}
    if contract.reset is not None:
        held_inputs[contract.reset.signal] = contract.reset.active_level
        state.step(held_inputs, contract.reset.assert_cycles)
        held_inputs[contract.reset.signal] = 1 - contract.reset.active_level
    output_names = {port.name for port in contract.outputs}
    expectations: dict[str, tuple[dict[str, int], ...]] = {}
    for vector in plan.vectors:
        for signal, value in vector.inputs.items():
            port = contract.port_map.get(signal)
            if port is None or not port.is_input:
                raise ReferenceSamplingError("per_cycle input does not match contract")
            if contract.clock is not None and signal == contract.clock.signal:
                raise ReferenceSamplingError("per_cycle inputs cannot drive the generated clock")
            try:
                bits = _encode_value(port, value, context="per_cycle.inputs").bits
            except TestbenchGenerationError as exc:
                raise ReferenceSamplingError(str(exc)) from exc
            if any(bit not in "01" for bit in bits):
                raise ReferenceSamplingError("per_cycle reference input contains unknown x/z bits")
            held_inputs[signal] = int(bits, 2)
        rows: list[dict[str, int]] = []
        for _ in range(vector.cycles):
            outputs = state.step(held_inputs, 1)
            if set(outputs) != output_names:
                raise ReferenceSamplingError("per_cycle reference must model every declared output")
            rows.append({signal: int(value) for signal, value in outputs.items()})
        expectations[vector.name] = tuple(rows)
    return expectations


def override_plan_expectations(
    plan: TestPlan,
    expectations: Mapping[str, Mapping[str, Any]],
    *,
    fill_missing: bool = True,
) -> TestPlan:
    """返回用参考模型期望值替换 AI 期望值的计划副本。

    ``fill_missing=True``（默认）时，参考模型建模的**每个**输出信号都会进入
    该向量的期望值，包括 AI 没有写期望值的信号。这一点很关键：如果只覆盖
    AI 已经写过的字段，AI 只要少写期望值就能让检查静默消失，缺陷就会漏检。

    原始计划本身不被修改，便于审计 AI 与参考模型的差异。
    """

    data = plan.model_dump(mode="json")
    for vector in data.get("vectors", []):
        if not isinstance(vector, dict):
            continue
        reference = expectations.get(str(vector.get("name", "")))
        if not isinstance(reference, Mapping) or not reference:
            continue
        expected = vector.get("expected")
        if not isinstance(expected, dict):
            expected = {}
        merged = dict(expected)
        for signal, value in reference.items():
            if fill_missing or signal in merged:
                merged[signal] = value
        vector["expected"] = merged
    return TestPlan.model_validate(data)


def check_plan_consistency(
    plan: Any,
    design: str | None = None,
    contract: Any = None,
    *,
    reference_outputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """比较 AI 计划的期望值与参考模型复算值，产出诊断（不改变裁决）。"""

    design_name = str(design or _get(plan, "design", ""))
    if design_name not in SUPPORTED:
        return {"status": "skipped", "design": design_name, "warnings": [], "checked": 0,
                "reason": "reference model is only defined for bundled examples"}
    if _unsupported_sampling(plan, design_name):
        return {"status": "skipped", "design": design_name, "warnings": [], "checked": 0,
                "reason": "clocked before sampling is not supported by the independent reference model",
                "unsupported_sample_phase": "before"}
    # 诊断不做门控：它只报告差异、不参与裁决，因此可以用上全部已建模案例。
    expectations = (reference_outputs if reference_outputs is not None else
                    reference_expectations(plan, design_name, contract, authoritative_only=False))
    report_is_authoritative = design_name in AUTHORITATIVE
    warnings: list[dict[str, Any]] = []
    uncheckable: list[dict[str, str]] = []
    checked = 0
    matched = 0
    for index, vector in enumerate(_vectors(plan)):
        name = str(_get(vector, "name", _get(vector, "id", f"vector_{index + 1}")))
        expected = _get(vector, "expected", {}) or {}
        reference = expectations.get(name) or {}
        for signal, value in expected.items():
            if signal not in reference:
                continue
            if reference_outputs is not None and isinstance(contract, DutContract):
                # 逐拍参考表已经由受控输入复算；诊断 AI 末态数字时也使用
                # 同一字面值解释。AI 的 X/Z 或非法期望值不能让已完成仿真崩溃，
                # 更不能被当作一个已核对的数字。
                from .testbench import _encode_value, TestbenchGenerationError
                try:
                    bits = _encode_value(contract.port_map[signal], value, context="consistency.expected").bits
                except TestbenchGenerationError:
                    uncheckable.append({"vector": name, "signal": signal, "reason": "invalid_expected_scalar"})
                    continue
                if any(bit not in "01" for bit in bits):
                    uncheckable.append({"vector": name, "signal": signal, "reason": "unknown_expected_bits"})
                    continue
                expected_number = int(bits, 2)
            else:
                expected_number = int(value)
            checked += 1
            if expected_number == int(reference[signal]):
                matched += 1
            else:
                warnings.append({"code": "plan_inconsistent", "severity": "warn", "vector": name,
                                 "signal": signal, "expected": value, "reference": reference[signal],
                                 "reason": "expected value disagrees with deterministic reference model"})
    return {"status": "warn" if warnings else "inconclusive" if uncheckable else "passed", "design": design_name,
            "warnings": warnings, "checked": len(list(_vectors(plan))), "checked_expected": checked,
            "uncheckable_expected": uncheckable,
            "matched_expected": matched,
            "consistency_rate": round(matched / checked, 4) if checked else None,
            "evidence_level": "reference_model"}


__all__ = [
    "AUTHORITATIVE",
    "PER_CYCLE_PROFILE_VERSION",
    "ReferenceSamplingError",
    "SUPPORTED",
    "check_plan_consistency",
    "override_plan_expectations",
    "reference_cycle_expectations",
    "reference_expectations",
    "reference_sampling_profile",
]
