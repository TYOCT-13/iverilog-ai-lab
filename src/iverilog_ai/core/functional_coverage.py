"""确定性功能场景覆盖：只消费执行器逐周期的真实端口采样。

覆盖项描述输入尝试、输出状态或具备证据的协议序列，不是代码覆盖率或
正确性判据。VCD 的时间戳末值、模型计划说明和模型返回文字均不参与命中。
沿前寄存状态只可来自连续、无复位的上一沿后采样；首拍不猜测复位结果。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .contracts import DutContract
from .models import ProcessResult, ProcessStatus
from .observations import collect_observed_samples
from .pipeline import PipelineResult
from .testbench import _encode_value


PROFILE_VERSION = "builtin-functional-scenarios-v1"
DISCLAIMER = (
    "功能场景覆盖只描述本次计划中实际观察到的有限场景，不是代码覆盖率，"
    "不证明功能正确、所有协议路径已覆盖或模型提高了检出率。输入尝试不等于操作被接受。"
)

_PARAMETERS = {
    "sync_fifo": {"DATA_WIDTH": 8, "DEPTH": 4},
    "uart_tx": {"CLKS_PER_BIT": 4},
    "spi_master": {"WIDTH": 8},
    "handshake_stage": {"WIDTH": 8},
}
_PORTS = {
    "sync_fifo": {"clk": ("input", 1), "rst_n": ("input", 1),
                  "wr_en": ("input", 1), "wr_data": ("input", 8),
                  "rd_en": ("input", 1), "rd_data": ("output", 8),
                  "full": ("output", 1), "empty": ("output", 1)},
    "uart_tx": {"clk": ("input", 1), "rst_n": ("input", 1),
                "start": ("input", 1), "data_in": ("input", 8),
                "tx": ("output", 1), "busy": ("output", 1)},
    "spi_master": {"clk": ("input", 1), "rst_n": ("input", 1),
                   "start": ("input", 1), "data_in": ("input", 8),
                   "sclk": ("output", 1), "mosi": ("output", 1),
                   "busy": ("output", 1), "done": ("output", 1)},
    "handshake_stage": {"clk": ("input", 1), "rst_n": ("input", 1),
                        "in_valid": ("input", 1), "in_ready": ("output", 1),
                        "in_data": ("input", 8), "out_valid": ("output", 1),
                        "out_ready": ("input", 1), "out_data": ("output", 8)},
}
# 每项定义均是可执行的有限条件；参数范围只开放已经审计的固定配置。
_DEFINITIONS = {
    "sync_fifo": [
        ("fifo.empty", "output_observation", "非复位沿后 empty=1 且 full=0"),
        ("fifo.full", "output_observation", "非复位沿后 full=1 且 empty=0"),
        ("fifo.read_request", "input_attempt", "非复位采样中 rd_en=1；不声称已接受"),
        ("fifo.write_request", "input_attempt", "非复位采样中 wr_en=1；不声称已接受"),
        ("fifo.read_empty_attempt", "input_attempt", "上一非复位采样 empty=1，本拍 rd_en=1；前态来自连续实测寄存状态"),
        ("fifo.write_full_attempt", "input_attempt", "上一非复位采样 full=1，本拍 wr_en=1；前态来自连续实测寄存状态"),
        ("fifo.simultaneous_request", "input_attempt", "同一非复位采样 wr_en=1 且 rd_en=1；不声称同时接受"),
    ],
    "uart_tx": [
        ("uart.request", "input_attempt", "非复位采样 start=1；不声称已接受"),
        ("uart.idle", "output_observation", "非复位沿后 busy=0 且 tx=1"),
        ("uart.busy", "output_observation", "非复位沿后 busy=1"),
        ("uart.frame_start", "protocol_sequence", "上一实测 busy=0，本拍 start=1，沿后 busy=1 且 tx=0"),
        ("uart.busy_request_attempt", "input_attempt", "上一非复位采样 busy=1，本拍 start=1；不声称忽略机制正确"),
        ("uart.complete_frame", "protocol_sequence", "从实测接收开始连续41拍：8N1十位各4拍，与请求数据相符，末拍 busy=0、tx=1"),
    ],
    "spi_master": [
        ("spi.request", "input_attempt", "非复位采样 start=1；不声称已接受"),
        ("spi.busy", "output_observation", "非复位沿后 busy=1"),
        ("spi.busy_request_attempt", "input_attempt", "上一非复位采样 busy=1，本拍 start=1；不声称忽略机制正确"),
        ("spi.clock_transition", "output_observation", "连续非复位采样中 busy前态=1 且 SCLK发生已知0/1切换"),
        ("spi.done", "output_observation", "上一采样 busy=1，本拍 busy=0、done=1、sclk=1"),
        ("spi.complete_transfer", "protocol_sequence", "从实测请求开始连续16拍：SCLK交替切换15次、MOSI各拍已知，最后 busy=0、done=1；不评价MOSI数据正确性"),
    ],
    "handshake_stage": [
        ("handshake.request", "input_attempt", "非复位采样 in_valid=1；不声称已接受"),
        ("handshake.backpressure", "output_observation", "非复位沿后 out_valid=1 且真实输入 out_ready=0"),
        ("handshake.stalled_pair", "protocol_sequence", "相邻两次非复位采样 out_valid=1、out_ready=0 且 out_data为相同已知值"),
        ("handshake.output_transfer_condition", "protocol_condition", "上一实测 out_valid=1且data已知，本拍 out_ready=1；在内置寄存输出契约下满足出端传输条件"),
        ("handshake.refill_condition", "protocol_condition", "出端传输条件同时本拍 in_valid=1且in_data已知；不声称数据转交正确"),
    ],
}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def functional_coverage_profile(contract: DutContract) -> str | None:
    """只识别经过审计的合约形状；调用方还必须明确选择内置证据策略。"""
    if not isinstance(contract, DutContract) or contract.module not in _PORTS:
        return None
    if {p.name: (p.direction.value, p.width) for p in contract.ports} != _PORTS[contract.module]:
        return None
    if any(port.signed for port in contract.ports):
        return None
    parameters = {**_PARAMETERS[contract.module], **contract.parameters}
    if parameters != _PARAMETERS[contract.module]:
        return None
    clock, reset = contract.clock, contract.reset
    if (clock is None or clock.signal != "clk" or clock.edge != "posedge"
            or clock.period_ns <= 2 or reset is None or reset.signal != "rst_n"
            or reset.active_level != 0 or reset.synchronous or reset.assert_cycles < 1):
        return None
    return f"{PROFILE_VERSION}:{contract.module}"


@dataclass(frozen=True)
class _Sample:
    raw: dict[str, Any]

    def value(self, group: str, signal: str) -> int | None:
        bits = self.raw[group][signal]
        return None if "x" in bits or "z" in bits else int(bits, 2)

    @property
    def active(self) -> bool | None:
        return _eq(self.value("inputs", "rst_n"), 1)


def _eq(actual: int | None, expected: int) -> bool | None:
    return None if actual is None else actual == expected


def _all(*conditions: bool | None) -> bool | None:
    # 已知条件为假时不需要猜测其余未知条件。
    return False if False in conditions else None if None in conditions else True


def _previous(previous: _Sample | None, signal: str, expected: int) -> bool | None:
    return None if previous is None else _all(previous.active, _eq(previous.value("outputs", signal), expected))


def _evidence(*samples: _Sample, rule: str) -> dict[str, Any]:
    return {
        "source": "testbench_sample_statement", "rule": rule,
        "first_cycle": samples[0].raw["cycle"], "last_cycle": samples[-1].raw["cycle"],
        "samples": [sample.raw for sample in samples],
        "pre_state_source": "previous_after_sample" if len(samples) > 1 else None,
    }


def _validate_samples(result: PipelineResult, payload: Mapping[str, Any]) -> list[_Sample]:
    if (payload.get("schema_version") != "1.0" or payload.get("source") != "testbench_sample_statement"
            or payload.get("status") != "complete" or payload.get("errors")):
        raise ValueError("incomplete_or_unknown_observations")
    expected = [(vector.name, vector) for vector in result.plan.vectors for _ in range(vector.cycles)]
    rows = payload.get("samples")
    if (not expected or not isinstance(rows, list) or len(rows) != len(expected)
            or payload.get("expected_cycles") != len(expected) or payload.get("observed_cycles") != len(expected)):
        raise ValueError("sample_count_mismatch")
    held = {port.name: "0" * port.width for port in result.contract.ports if port.is_input}
    held["rst_n"], held["clk"] = "1", "1"
    last_time = -1.0
    samples: list[_Sample] = []
    for cycle, (raw, (test_id, vector)) in enumerate(zip(rows, expected)):
        if not isinstance(raw, dict) or set(raw) != {"cycle", "time_ns", "test_id", "sample_phase", "inputs", "outputs"}:
            raise ValueError("sample_fields_mismatch")
        if (isinstance(raw["cycle"], bool) or not isinstance(raw["cycle"], int)
                or raw["cycle"] != cycle or raw["test_id"] != test_id
                or raw["sample_phase"] != "after" or vector.sample_phase != "after"):
            raise ValueError("sample_order_or_phase_mismatch")
        at = raw["time_ns"]
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or at <= last_time:
            raise ValueError("sample_time_mismatch")
        if cycle and result.contract.clock is not None and abs(float(at) - last_time - result.contract.clock.period_ns) > 0.0011:
            raise ValueError("sample_time_gap_mismatch")
        last_time = float(at)
        normalized = {**raw}
        for group, direction in (("inputs", "input"), ("outputs", "output")):
            actual = raw[group]
            ports = {p.name: p for p in result.contract.ports if p.direction.value == direction}
            if not isinstance(actual, dict) or set(actual) != set(ports):
                raise ValueError("sample_port_mismatch")
            normalized[group] = {}
            for name, port in ports.items():
                bits = actual[name]
                if not isinstance(bits, str) or len(bits) != port.width or any(c not in "01xXzZ" for c in bits):
                    raise ValueError("sample_bits_mismatch")
                normalized[group][name] = bits.lower()
        for name, value in vector.inputs.items():
            held[name] = _encode_value(result.contract.port_map[name], value, context="coverage.inputs").bits
        if normalized["inputs"] != held:
            raise ValueError("observed_inputs_do_not_match_held_plan")
        samples.append(_Sample(normalized))
    return samples


def _conditions(module: str, sample: _Sample, previous: _Sample | None) -> dict[str, bool | None]:
    inp = lambda name, value: _eq(sample.value("inputs", name), value)
    out = lambda name, value: _eq(sample.value("outputs", name), value)
    active = sample.active
    if module == "sync_fifo":
        return {
            "fifo.empty": _all(active, out("empty", 1), out("full", 0)),
            "fifo.full": _all(active, out("full", 1), out("empty", 0)),
            "fifo.read_request": _all(active, inp("rd_en", 1)),
            "fifo.write_request": _all(active, inp("wr_en", 1)),
            "fifo.read_empty_attempt": _all(active, inp("rd_en", 1), _previous(previous, "empty", 1)),
            "fifo.write_full_attempt": _all(active, inp("wr_en", 1), _previous(previous, "full", 1)),
            "fifo.simultaneous_request": _all(active, inp("wr_en", 1), inp("rd_en", 1)),
        }
    if module == "uart_tx":
        return {
            "uart.request": _all(active, inp("start", 1)),
            "uart.idle": _all(active, out("busy", 0), out("tx", 1)),
            "uart.busy": _all(active, out("busy", 1)),
            "uart.frame_start": _all(active, inp("start", 1), _previous(previous, "busy", 0), out("busy", 1), out("tx", 0)),
            "uart.busy_request_attempt": _all(active, inp("start", 1), _previous(previous, "busy", 1)),
        }
    if module == "spi_master":
        old_sclk = previous.value("outputs", "sclk") if previous else None
        sclk = sample.value("outputs", "sclk")
        different = None if old_sclk is None or sclk is None else old_sclk != sclk
        return {
            "spi.request": _all(active, inp("start", 1)),
            "spi.busy": _all(active, out("busy", 1)),
            "spi.busy_request_attempt": _all(active, inp("start", 1), _previous(previous, "busy", 1)),
            "spi.clock_transition": _all(active, _previous(previous, "busy", 1), different),
            "spi.done": _all(active, _previous(previous, "busy", 1), out("busy", 0), out("done", 1), out("sclk", 1)),
        }
    old_data = previous.value("outputs", "out_data") if previous else None
    data = sample.value("outputs", "out_data")
    stable = None if old_data is None or data is None else old_data == data
    transfer = _all(active, inp("out_ready", 1), _previous(previous, "out_valid", 1),
                    None if old_data is None else True)
    return {
        "handshake.request": _all(active, inp("in_valid", 1)),
        "handshake.backpressure": _all(active, inp("out_ready", 0), out("out_valid", 1)),
        "handshake.stalled_pair": _all(active, inp("out_ready", 0), out("out_valid", 1),
                                      _previous(previous, "out_valid", 1),
                                      None if previous is None else _eq(previous.value("inputs", "out_ready"), 0), stable),
        "handshake.output_transfer_condition": transfer,
        "handshake.refill_condition": _all(transfer, inp("in_valid", 1),
                                          None if sample.value("inputs", "in_data") is None else True),
    }


def _frame(samples: list[_Sample], start: int, module: str) -> tuple[bool | None, list[_Sample]]:
    length = 41 if module == "uart_tx" else 16
    window = samples[start:start + length]
    if len(window) != length:
        return None, window
    data = window[0].value("inputs", "data_in")
    checks: list[bool | None] = []
    for offset, sample in enumerate(window):
        checks.append(sample.active)
        if module == "uart_tx":
            position = offset // 4
            bit = 0 if position == 0 else 1 if position >= 9 else None if data is None else (data >> (position - 1)) & 1
            tx = sample.value("outputs", "tx")
            checks.extend([_eq(sample.value("outputs", "busy"), int(offset < 40)),
                           None if bit is None else _eq(tx, bit)])
        else:
            checks.extend([None if data is None or sample.value("outputs", "mosi") is None else True,
                           _eq(sample.value("outputs", "sclk"), offset % 2),
                           _eq(sample.value("outputs", "busy"), int(offset < 15)),
                           _eq(sample.value("outputs", "done"), int(offset == 15))])
    return _all(*checks), window


def _measure(module: str, samples: list[_Sample], bins: list[dict[str, Any]]) -> None:
    by_id = {item["id"]: item for item in bins}
    unknown: set[str] = set()
    for index, sample in enumerate(samples):
        previous = samples[index - 1] if index else None
        conditions = _conditions(module, sample, previous)
        if module in {"uart_tx", "spi_master"}:
            key = "uart.complete_frame" if module == "uart_tx" else "spi.complete_transfer"
            begin = conditions["uart.frame_start"] if module == "uart_tx" else _all(
                sample.active, _eq(sample.value("inputs", "start"), 1),
                _previous(previous, "busy", 0), _eq(sample.value("outputs", "busy"), 1),
                _eq(sample.value("outputs", "sclk"), 0))
            window: list[_Sample] = []
            complete = begin
            if begin:
                complete, window = _frame(samples, index, module)
            conditions[key] = complete
            if complete and by_id[key]["first_evidence"] is None:
                by_id[key]["first_evidence"] = _evidence(*window, rule=key)
        for key, condition in conditions.items():
            item = by_id[key]
            if condition is None:
                unknown.add(key)
            elif condition and item["first_evidence"] is None:
                use_previous = key in {"fifo.read_empty_attempt", "fifo.write_full_attempt",
                    "uart.frame_start", "uart.busy_request_attempt", "spi.busy_request_attempt",
                    "spi.clock_transition", "spi.done", "handshake.stalled_pair",
                    "handshake.output_transfer_condition", "handshake.refill_condition"}
                evidence_samples = [previous, sample] if use_previous and previous is not None else [sample]
                item["first_evidence"] = _evidence(*evidence_samples, rule=key)
    for item in bins:
        item["status"] = "observed" if item["first_evidence"] else "unknown" if item["id"] in unknown else "missing"


def _finish_report(report: dict[str, Any]) -> dict[str, Any]:
    for status in ("observed", "missing", "unknown"):
        report[status] = [item["id"] for item in report["bins"] if item["status"] == status]
    report["counts"] = {status: len(report[status]) for status in ("observed", "missing", "unknown")}
    # 完整证据只存轨迹；API只需场景缺口与首次命中周期。
    report["compact_model_feedback"] = {
        key: report[key] for key in ("schema_version", "coverage_type", "status", "profile", "profile_sha256",
                                    "expected_cycles", "observed_cycles", "counts", "observed", "missing", "unknown",
                                    "reason", "disclaimer")
    }
    report["compact_model_feedback"]["bins"] = [
        {**{key: item[key] for key in ("id", "kind", "definition", "status")},
         "first_cycle": item["first_evidence"]["first_cycle"] if item["first_evidence"] else None,
         "last_cycle": item["first_evidence"]["last_cycle"] if item["first_evidence"] else None}
        for item in report["bins"]
    ]
    return report


def analyze_functional_coverage(
    result: PipelineResult, *, rtl_sha256: str, builtin_profile: bool = False,
) -> dict[str, Any]:
    """验证工件与输入保持语义，返回当前执行范围的功能场景事实。

    ``builtin_profile`` 必须由可信调用方选择；外部 qualified differential
    observer 不得因模块同名而启用内置协议。模型不能提供或覆盖此参数。
    """
    contract = getattr(result, "contract", None)
    profile = functional_coverage_profile(contract) if isinstance(contract, DutContract) else None
    supported = builtin_profile is True and profile is not None
    definitions = _DEFINITIONS.get(contract.module, []) if supported and isinstance(contract, DutContract) else []
    bins = [{"id": key, "kind": kind, "definition": definition, "status": "unknown", "first_evidence": None}
            for key, kind, definition in definitions]
    profile_payload = {"profile": profile, "parameters": _PARAMETERS.get(getattr(contract, "module", ""), {}),
                       "definitions": definitions}
    report: dict[str, Any] = {
        "schema_version": "1.0", "coverage_type": "functional_scenarios",
        "scope": "current_execution_plan", "status": "unknown" if supported else "unsupported",
        "profile": profile if supported else None,
        "profile_sha256": _hash(json.dumps(profile_payload, ensure_ascii=False, sort_keys=True).encode()) if supported else None,
        "bins": bins, "observed": [], "missing": [], "unknown": [item["id"] for item in bins],
        "expected_cycles": sum(v.cycles for v in result.plan.vectors), "observed_cycles": 0,
        "provenance": {}, "reason": "unsupported_or_unqualified_contract" if not supported else None,
        "disclaimer": DISCLAIMER,
        "limitations": ["沿前寄存状态仅采用连续非复位的上一沿后采样；首拍不推定状态",
                        "仅审计四类内置固定参数，外部模块、变参、before采样不套用",
                        "没有记录、缺行、乱序、相同采样时刻或工件不匹配则整体未知",
                        "含X/Z的必要条件为未知；只有已知条件的实测命中才有首次证据"],
    }
    if not supported or not isinstance(contract, DutContract):
        return _finish_report(report)
    try:
        run = result.simulation.run
        if (not isinstance(run, ProcessResult) or run.status is not ProcessStatus.PASSED
                or isinstance(run.returncode, bool) or run.returncode != 0
                or run.timed_out or run.output_truncated or run.error is not None
                or not isinstance(run.stdout, str) or not run.stdout):
            raise ValueError("execution_not_complete")
        artifacts = result.artifacts
        path = Path(artifacts["observed_samples"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000_000:
            raise ValueError("observations_unavailable_or_oversized")
        raw = path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid_observation_document")
        saved_digest = result.simulation.config.get("observed_samples", {}).get("sha256")
        if not isinstance(saved_digest, str) or saved_digest != _hash(raw):
            raise ValueError("observed_samples_digest_mismatch")
        hashes = {"rtl_sha256": rtl_sha256}
        for name, key in (("plan_sha256", "testplan"), ("contract_sha256", "dut_contract"),
                          ("testbench_sha256", "testbench")):
            artifact = Path(artifacts[key])
            if artifact.is_symlink() or not artifact.is_file():
                raise ValueError("provenance_artifact_unavailable")
            hashes[name] = _hash(artifact.read_bytes())
        if (len(rtl_sha256) != 64 or any(c not in "0123456789abcdef" for c in rtl_sha256)
                or payload.get("provenance") != hashes):
            raise ValueError("provenance_mismatch")
        if (json.loads(Path(artifacts["testplan"]).read_bytes()) != result.plan.model_dump(mode="json")
                or json.loads(Path(artifacts["dut_contract"]).read_bytes()) != contract.to_dict()):
            raise ValueError("provenance_semantic_mismatch")
        # 四项输入SHA只能绑定输入，不能证明有人没有修改采样输出。
        # 从本次真实进程的stdout重算原packet；只改packet或连metadata SHA一起
        # 修改都不能绕过这个绑定。功能断言失败但vvp进程正常完成仍可统计。
        from_stdout = collect_observed_samples(
            run.stdout, result.plan, contract, provenance=hashes,
            execution_complete=True, output_truncated=run.output_truncated,
        )
        if payload != from_stdout:
            raise ValueError("observed_samples_stdout_mismatch")
        samples = _validate_samples(result, payload)
        _measure(contract.module, samples, bins)
        report.update(status="measured", observed_cycles=len(samples), reason=None,
                      provenance={**hashes, "observed_samples_sha256": saved_digest,
                                  "run_stdout_sha256": _hash(run.stdout.encode("utf-8"))})
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        allowed = {"observations_unavailable_or_oversized", "invalid_observation_document",
                   "execution_not_complete", "observed_samples_digest_mismatch", "observed_samples_stdout_mismatch",
                   "provenance_artifact_unavailable", "provenance_mismatch", "provenance_semantic_mismatch",
                   "incomplete_or_unknown_observations", "sample_count_mismatch", "sample_fields_mismatch",
                   "sample_order_or_phase_mismatch", "sample_time_mismatch", "sample_time_gap_mismatch", "sample_port_mismatch",
                   "sample_bits_mismatch", "observed_inputs_do_not_match_held_plan"}
        report["reason"] = str(exc) if str(exc) in allowed else "observations_unavailable_or_invalid"
    return _finish_report(report)


__all__ = ["PROFILE_VERSION", "DISCLAIMER", "functional_coverage_profile", "analyze_functional_coverage"]
