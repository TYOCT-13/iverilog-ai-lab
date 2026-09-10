from iverilog_ai.core.reference_model import check_plan_consistency


def _check(design, vectors):
    result = check_plan_consistency({"design": design, "vectors": vectors})
    assert result["status"] == "passed", result
    assert result["checked_expected"] > 0
    assert result["consistency_rate"] == 1.0


def test_common_case_reference_models():
    _check("sync_fifo", [
        {"name": "reset", "inputs": {"rst_n": 0}, "expected": {"empty": 1}},
        {"name": "write", "inputs": {"rst_n": 1, "wr_en": 1, "wr_data": 165}, "expected": {"empty": 0}},
        {"name": "read", "inputs": {"rd_en": 1}, "expected": {"rd_data": 165, "empty": 1}},
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
