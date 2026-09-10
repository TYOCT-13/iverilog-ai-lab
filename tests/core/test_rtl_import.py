from iverilog_ai.core.rtl_import import RTLImportError, extract_contract_draft, import_rtl_bytes
import pytest

def test_extract_ansi_and_shared_direction():
    src='module demo(input wire clk, rst_n, input wire [7:0] data, extra, output logic [3:0] y); endmodule'
    mod, contract, warnings = extract_contract_draft(src)
    assert mod == 'demo'
    assert [(p['name'], p['direction'], p['width']) for p in contract['ports']] == [('clk','input',1),('rst_n','input',1),('data','input',8),('extra','input',8),('y','output',4)]
    assert contract['clock']['signal'] == 'clk' and contract['reset']['signal'] == 'rst_n'

def test_import_hash_path_and_rejects_unsafe(tmp_path):
    result = import_rtl_bytes('demo.v', b'module demo(input a, output y); endmodule', tmp_path)
    assert result.path.parent == (tmp_path/'.iverilog-ai'/'custom_rtl').resolve()
    assert result.path.read_bytes().startswith(b'module demo')
    with pytest.raises(RTLImportError): import_rtl_bytes('../evil.v', b'x', tmp_path)
    with pytest.raises(RTLImportError): import_rtl_bytes('x.v', b'\x00', tmp_path)
