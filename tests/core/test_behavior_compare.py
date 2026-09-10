"""行为级对比的回归测试：同一份 TestPlan 跑两份 RTL，比对记录与波形。

三种必须成立的情形：

1. 同一份 RTL 与自己比 → ``identical``；
2. 行为不同的实现 → ``different``，并指出具体检查项与 DUT 内部信号；
3. 语义等价但写法不同（含多出内部辅助变量）→ ``identical``——对比看的是行为，
   不是文本，也不是内部信号数量。

测试用 PWM 与它的缺陷变体（已知会改变行为）与一个等价重写（行为相同），
全部离线，不需要网络或密钥。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from iverilog_ai.core.behavior_compare import compare_pipeline_behavior, compare_rtl_behavior
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).parents[2]
IVERILOG = r"D:\iverilog\bin\iverilog.exe"
VVP = r"D:\iverilog\bin\vvp.exe"
# 工件目录必须落在允许根之内（SafePathPolicy 会拒绝项目外的路径），
# 因此这里用项目内的临时目录而不是 pytest 的 tmp_path。
WORK_ROOT = ROOT / ".iverilog-ai" / "test-behavior-compare"


@pytest.fixture(autouse=True)
def _clean_work_root():
    shutil.rmtree(WORK_ROOT, ignore_errors=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(WORK_ROOT, ignore_errors=True)

# 与 rtl/pwm.v 语义等价但写法不同：多出一个组合中间量 next_count。
# 这是"内部信号多一个不代表行为不同"的回归素材。
EQUIVALENT_PWM = """`timescale 1ns/1ps
module pwm #(parameter WIDTH=8)(input wire clk, input wire rst_n, input wire [WIDTH-1:0] duty, output reg pwm_out);
  reg [WIDTH-1:0] counter;
  wire [WIDTH-1:0] next_count = counter + 1'b1;
  always @(posedge clk or negedge rst_n) begin
    if (rst_n == 1'b0) begin
      counter <= {WIDTH{1'b0}};
      pwm_out <= 1'b0;
    end else begin
      counter <= next_count;
      if (next_count > duty) pwm_out <= 1'b0;
      else pwm_out <= 1'b1;
    end
  end
endmodule
"""


def _iverilog_available() -> bool:
    return Path(IVERILOG).is_file() and Path(VVP).is_file()


def _plan(vectors: list[dict], *, design: str = "pwm"):
    from iverilog_ai.ai.schema import TestPlan

    return TestPlan.model_validate(
        {
            "design": design,
            "objective": "覆盖占空比边界与回绕",
            "vectors": vectors,
        }
    )


def _contract() -> DutContract:
    return DutContract.from_dict(json.loads((ROOT / "examples" / "pwm_contract.json").read_text(encoding="utf-8")))


#: 覆盖 0/255/中间值与回绕：极性反转与计数差一的缺陷都会在这里露出来
VECTORS = [
    {"name": "reset", "inputs": {"rst_n": 0, "duty": 0}, "cycles": 2, "expected": {"pwm_out": 0}},
    {"name": "duty_zero", "inputs": {"rst_n": 1, "duty": 0}, "cycles": 4, "expected": {"pwm_out": 0}},
    {"name": "duty_full", "inputs": {"rst_n": 1, "duty": 255}, "cycles": 4, "expected": {"pwm_out": 1}},
    {"name": "duty_half", "inputs": {"rst_n": 1, "duty": 4}, "cycles": 12, "expected": {}},
]


@pytest.mark.skipif(not _iverilog_available(), reason="Icarus Verilog 未安装在预期路径")
def test_identical_rtl_compares_identical(tmp_path):
    """同一份 RTL 与自己比：必须逐检查项一致、无波形差异。"""

    result = compare_rtl_behavior(
        _plan(VECTORS),
        _contract(),
        ROOT / "rtl" / "pwm.v",
        ROOT / "rtl" / "pwm.v",
        WORK_ROOT / "self",
        allowed_roots=(ROOT,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    assert result.status == "identical", result.to_dict()
    assert result.identical is True
    assert result.mismatches == ()
    assert result.record_summary["shared_checks"] > 0
    assert result.record_summary["mismatched_checks"] == 0
    assert result.waveform.get("status") == "identical"
    assert result.waveform.get("difference_count") == 0


@pytest.mark.skipif(not _iverilog_available(), reason="Icarus Verilog 未安装在预期路径")
def test_behavioral_defect_is_reported_different(tmp_path):
    """极性反转的缺陷必须被判定为行为不同，且指出具体检查项与信号。"""

    result = compare_rtl_behavior(
        _plan(VECTORS),
        _contract(),
        ROOT / "rtl" / "pwm_bug_inverted_polarity.v",
        ROOT / "rtl" / "pwm.v",
        WORK_ROOT / "polarity",
        allowed_roots=(ROOT,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    assert result.status == "different", result.to_dict()
    assert result.record_summary["mismatched_checks"] > 0
    assert result.mismatches
    # 差异必须定位到具体信号，而不是只说"不一样"
    assert all(item["signal"] == "pwm_out" for item in result.mismatches)
    assert result.waveform.get("status") == "different"
    assert result.waveform.get("dut_differences"), result.waveform


@pytest.mark.skipif(not _iverilog_available(), reason="Icarus Verilog 未安装在预期路径")
def test_equivalent_rewrite_compares_identical_despite_extra_signal():
    """语义等价的重写即使多出内部辅助变量，也必须判 identical。

    对比看的是行为而不是文本：``next_count`` 是实现细节，不计入差异。
    """

    # 放在项目根下才能通过 SafePathPolicy 的允许根校验
    in_scope = WORK_ROOT / "equivalent_pwm.v"
    in_scope.parent.mkdir(parents=True, exist_ok=True)
    in_scope.write_text(EQUIVALENT_PWM, encoding="utf-8")

    result = compare_rtl_behavior(
        _plan(VECTORS),
        _contract(),
        in_scope,
        ROOT / "rtl" / "pwm.v",
        WORK_ROOT / "equivalent",
        allowed_roots=(ROOT,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    assert result.status == "identical", result.to_dict()
    assert result.waveform.get("status") == "identical"
    assert result.waveform.get("difference_count") == 0
    # 信号集合确实不同（多出 next_count），但被识别为实现细节
    assert result.waveform.get("signal_sets_match") is False
    assert result.waveform.get("extra_signals_are_internal_only") is True
    assert any("实现细节" in note for note in result.notes)


@pytest.mark.skipif(not _iverilog_available(), reason="Icarus Verilog 未安装在预期路径")
def test_compare_pipeline_behavior_is_serializable(tmp_path):
    """结论必须能整体序列化（网页与报告都直接 json 化它）。"""

    result = compare_rtl_behavior(
        _plan(VECTORS),
        _contract(),
        ROOT / "rtl" / "pwm_bug_off_by_one.v",
        ROOT / "rtl" / "pwm.v",
        WORK_ROOT / "offbyone",
        allowed_roots=(ROOT,),
        iverilog_path=IVERILOG,
        vvp_path=VVP,
    )
    payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert payload["status"] == "different"
    assert payload["record_summary"]["reference_failed"] == 0
    assert payload["disclaimer"]
    # 关键：参考侧在**同一份 plan** 下不应失败，否则说明 plan 本身有问题
    assert payload["reference_status"] in {"passed", "passed_with_warnings"}


def test_compare_pipeline_behavior_reuses_given_results():
    """纯函数入口：给定两份结果即可比对，不需要重跑仿真。"""

    from iverilog_ai.core.models import SimulationResult

    user = SimulationResult.from_dict(
        {
            "run_id": "u",
            "status": "passed_with_warnings",
            "compile": {"status": "passed", "returncode": 0, "command": ["iverilog"]},
            "run": {"status": "passed", "returncode": 0, "command": ["vvp"]},
            "records": [
                {"ok": True, "test_id": "t1", "signal": "pwm_out", "actual": "0"},
                {"ok": False, "test_id": "t2", "signal": "pwm_out", "actual": "0", "expected": "1"},
            ],
        }
    )
    reference = SimulationResult.from_dict(
        {
            "run_id": "r",
            "status": "passed",
            "compile": {"status": "passed", "returncode": 0, "command": ["iverilog"]},
            "run": {"status": "passed", "returncode": 0, "command": ["vvp"]},
            "records": [
                {"ok": True, "test_id": "t1", "signal": "pwm_out", "actual": "0"},
                {"ok": True, "test_id": "t2", "signal": "pwm_out", "actual": "1", "expected": "1"},
            ],
        }
    )
    from iverilog_ai.core.pipeline import PipelineResult

    user_result = PipelineResult(
        plan=_plan(VECTORS), contract=_contract(), testbench_path=Path("tb.v"), simulation=user
    )
    reference_result = PipelineResult(
        plan=_plan(VECTORS), contract=_contract(), testbench_path=Path("tb.v"), simulation=reference
    )
    outcome = compare_pipeline_behavior(user_result, reference_result, module="pwm")
    assert outcome.status == "different"
    assert len(outcome.mismatches) == 1
    assert outcome.mismatches[0]["test_id"] == "t2"
    assert outcome.mismatches[0]["kind"] == "record"
    # 没有 VCD 时如实说明，而不是假装波形一致
    assert outcome.waveform["status"] == "not_available"
