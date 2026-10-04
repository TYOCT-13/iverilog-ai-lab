"""参考模型的一致性诊断与权威预言机门控。

需要区分两件事：

- ``check_plan_consistency`` 是**诊断**：对所有已建模案例比较 AI 期望值与模型复算值。
- ``reference_expectations`` 是**权威预言机**：只对已与 RTL 逐项核对过的
  ``AUTHORITATIVE`` 设计返回值，用来覆盖 AI 期望值。
"""

from iverilog_ai.core.reference_model import (
    AUTHORITATIVE,
    SUPPORTED,
    check_plan_consistency,
    reference_expectations,
)


def _check(design, vectors):
    result = check_plan_consistency({"design": design, "vectors": vectors})
    assert result["status"] == "passed", result
    assert result["checked_expected"] > 0
    assert result["consistency_rate"] == 1.0


def test_common_case_reference_models():
    _check("sync_fifo", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"empty": 1}},
        {"name": "write", "inputs": {"rst_n": 1, "wr_en": 1, "wr_data": 165}, "expected": {"empty": 0}},
        {"name": "read", "inputs": {"wr_en": 0, "rd_en": 1}, "expected": {"empty": 1}},
    ])
    _check("uart_tx", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"tx": 1, "busy": 0}},
        {"name": "start", "inputs": {"rst_n": 1, "start": 1, "data_in": 85}, "expected": {"tx": 0, "busy": 1}},
    ])
    _check("spi_master", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"sclk": 0, "busy": 0, "done": 0}},
        {"name": "start", "inputs": {"rst_n": 1, "start": 1, "data_in": 165}, "expected": {"sclk": 0, "mosi": 1, "busy": 1}},
    ])
    _check("handshake_stage", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"out_valid": 0}},
        {"name": "hold", "inputs": {"rst_n": 1, "in_valid": 1, "in_ready": 1, "in_data": 60, "out_ready": 0}, "expected": {"out_valid": 1, "out_data": 60}},
    ])
    _check("debounce", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"key_state": 1}},
        {"name": "stable", "inputs": {"rst_n": 1, "key_in": 0}, "cycles": 3, "expected": {"key_state": 0}},
    ])
    _check("pwm", [
        {"name": "reset", "inputs": {"rst_n": 0, "duty": 0}, "expected": {"pwm_out": 0}},
        {"name": "full", "inputs": {"rst_n": 1, "duty": 255}, "expected": {"pwm_out": 1}},
    ])
    _check("mux4", [
        {"name": "select", "inputs": {"d0": 16, "d1": 32, "d2": 48, "d3": 64, "sel": 2}, "expected": {"y": 48}},
    ])
    _check("sync_reset", [
        {"name": "assert", "inputs": {"ext_rst_n": 0}, "expected": {"rst_n": 0}},
        {"name": "release", "inputs": {"ext_rst_n": 1}, "cycles": 2, "expected": {"rst_n": 1}},
    ])


def test_reference_model_uses_contract_parameters():
    result = check_plan_consistency(
        {"design": "sync_fifo", "vectors": [
            {"name": "fill", "inputs": {"wr_en": 1, "wr_data": 1}, "cycles": 2, "expected": {"full": 1}},
        ]},
        contract={"parameters": {"DEPTH": 2}},
    )
    assert result["status"] == "passed", result


# --------------------------------------------------------------------------
# 权威预言机门控
# --------------------------------------------------------------------------
def test_authoritative_expectations_only_for_validated_designs():
    """只有已验证的模型才能决定期望值；其余设计必须返回空字典。"""

    assert AUTHORITATIVE <= SUPPORTED
    counter = {"design": "mod10_counter", "vectors": [
        {"name": "v", "inputs": {"enable": 1}, "cycles": 1, "expected": {"count": 1}},
    ]}
    assert reference_expectations(counter, "mod10_counter") == {"v": {"count": 1}}

    for design in sorted(SUPPORTED - AUTHORITATIVE):
        plan = {"design": design, "vectors": [{"name": "v", "inputs": {}, "cycles": 1, "expected": {}}]}
        assert reference_expectations(plan, design) == {}, design


def test_unvalidated_designs_fall_back_to_ai_expectations():
    """未验证案例回退为 AI 期望值，而不是被模型改写。

    内置案例现已全部逐拍对齐并进入 ``AUTHORITATIVE``，因此"未验证"的情形用
    尚未建模的自定义设计来验证：它既不在 ``SUPPORTED`` 也不在
    ``AUTHORITATIVE``，必须原样保留 AI 期望值。
    """

    from iverilog_ai.ai.schema import TestPlan
    from iverilog_ai.core.reference_model import override_plan_expectations

    design = "custom_shift_register"
    assert design not in SUPPORTED and design not in AUTHORITATIVE
    plan = TestPlan.model_validate({
        "design": design,
        "objective": "fallback",
        "vectors": [{"name": "v", "inputs": {"clk_en": 1, "d": 85}, "expected": {"q": 85}}],
    })
    expectations = reference_expectations(plan, design)
    assert expectations == {}
    authoritative = override_plan_expectations(plan, expectations)
    assert authoritative.vectors[0].expected == {"q": 85}


def test_every_supported_design_is_authoritative():
    """建模覆盖与权威集合必须一致：建模了却未对齐的设计只能是"待办"。

    这条断言把"未对齐的设计"变成一个显式的、必须立刻处理的失败，而不是悄悄
    退回 AI 期望值。新增内置案例时，要么同步完成逐拍对齐，要么先不加进
    ``SUPPORTED``。
    """

    assert SUPPORTED == set(AUTHORITATIVE)


def test_input_defaults_cover_every_input_port():
    """每个内置案例的**非时钟输入端口**都必须在默认值表里出现。

    默认值表是"向量未列出某个输入时该取什么值"的唯一事实来源：模型用它复算，
    实验激励生成器用它补全向量。缺一个端口，模型与测试台就会对同一拍取到不同
    的值——实测中 debounce 因此产生过 25 条伪失败。时钟端口由测试台自动产生，
    不需要默认值。
    """

    import json
    from pathlib import Path

    from iverilog_ai.core.reference_model import INPUT_DEFAULTS

    root = Path(__file__).parents[2]
    assert set(INPUT_DEFAULTS) == SUPPORTED
    for case in sorted(SUPPORTED):
        contract = json.loads((root / f"examples/{case}_contract.json").read_text(encoding="utf-8"))
        clock = (contract.get("clock") or {}).get("signal")
        expected = {
            port["name"]
            for port in contract["ports"]
            if port["direction"] == "input" and port["name"] != clock
        }
        assert set(INPUT_DEFAULTS[case]) == expected, case


def test_completed_inputs_fills_only_missing_ports():
    """补全只填空缺，不覆盖向量里已经给出的值。"""

    from iverilog_ai.core.reference_model import completed_inputs

    assert completed_inputs("debounce", {"key_in": 1}) == {"rst_n": 1, "key_in": 1}
    assert completed_inputs("debounce", {"rst_n": 0}) == {"rst_n": 0, "key_in": 0}
    # 未建模的设计原样返回，不做猜测
    assert completed_inputs("custom_dut", {"x": 3}) == {"x": 3}
