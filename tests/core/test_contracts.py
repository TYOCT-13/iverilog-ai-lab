import pytest

from iverilog_ai.core.contracts import (
    ClockContract,
    ContractValidationError,
    DutContract,
    PortDirection,
    PortSpec,
    ResetContract,
)


def test_contract_round_trip_is_explicit_and_deterministic():
    contract = DutContract.from_dict(
        {
            "module": "alu8",
            "ports": [
                {"name": "a", "direction": "input", "width": 8},
                {"name": "y", "direction": "output", "width": 8},
                {"name": "clk", "direction": "input"},
                {"name": "rst_n", "direction": "input"},
            ],
            "clock": {"signal": "clk", "period_ns": 10, "edge": "posedge"},
            "reset": {"signal": "rst_n", "active_level": 0, "assert_cycles": 2},
        }
    )
    assert contract.port_map["a"].width == 8
    assert contract.port_map["clk"].direction is PortDirection.INPUT
    assert DutContract.from_json(contract.to_json()) == contract
    assert isinstance(contract.clock, ClockContract)
    assert isinstance(contract.reset, ResetContract)


@pytest.mark.parametrize(
    "payload",
    [
        {"module": "bad-name", "ports": [{"name": "a", "direction": "input"}]},
        {"module": "m", "ports": [{"name": "a; $finish", "direction": "input"}]},
        {"module": "m", "ports": [{"name": "a", "direction": "input", "width": 0}]},
        {"module": "m", "ports": [{"name": "a", "direction": "input", "extra": 1}]},
        {"module": "m", "ports": [{"name": "a", "direction": "input"}], "unknown": 1},
    ],
)
def test_contract_rejects_unknown_fields_and_unsafe_identifiers(payload):
    with pytest.raises(ContractValidationError):
        DutContract.from_dict(payload)


def test_direct_port_validation_normalizes_direction():
    port = PortSpec("data", "INPUT", 4)
    assert port.direction is PortDirection.INPUT
    with pytest.raises(ContractValidationError):
        PortSpec("data", "wire", 4)


def test_contract_parameters_round_trip_and_validate():
    contract = DutContract.from_dict({"module": "fifo", "parameters": {"WIDTH": 8, "DEPTH": 4}, "ports": [{"name": "clk", "direction": "input"}]})
    assert contract.parameters == {"WIDTH": 8, "DEPTH": 4}
    assert DutContract.from_json(contract.to_json()) == contract
    with pytest.raises(ContractValidationError):
        DutContract.from_dict({"module": "fifo", "parameters": {"WIDTH;bad": 8}, "ports": [{"name": "clk", "direction": "input"}]})
