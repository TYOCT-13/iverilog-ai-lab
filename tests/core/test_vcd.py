from pathlib import Path

from iverilog_ai.core.vcd import analyze_vcd_file


def test_vcd_parser_reads_signals_timescale_and_window(tmp_path: Path):
    vcd = tmp_path / "waveform.vcd"
    vcd.write_text("""$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 1 \" data $end
$upscope $end
$enddefinitions $end
#0
0!
0\"
#5
1!
#10
1\"
""", encoding="ascii")
    result = analyze_vcd_file(vcd, start_ns=5, end_ns=10)
    assert result["timescale_ns"] == 1.0
    assert result["signal_count"] == 2
    assert result["total_changes"] == 2
    assert {item["signal"] for item in result["changes"]} == {"tb.clk", "tb.data"}
