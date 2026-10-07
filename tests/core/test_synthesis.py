"""综合证据层的回归测试。

三件事必须成立：

1. 12 个参考 RTL 全部可综合，而且能解析出单元统计；
2. **不可综合**的 RTL 必须报 ``failed``——否则这一层就只是装饰；
3. 工具缺失时必须报 ``unavailable`` 而不是把流水线判失败。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from iverilog_ai.core.benchmark_cases import case_table
from iverilog_ai.core.synthesis import (
    EVIDENCE_STAGES,
    SynthConfig,
    YosysSynthRunner,
    find_yosys,
    parse_stat_json,
)

ROOT = Path(__file__).parents[2]
YOSYS = find_yosys()

# 参考 RTL：全部必须综合通过。
# 直接从基准清单派生（而不是手抄一份名单）：新增案例时这里自动覆盖，
# 不会再出现"清单加了案例、本测试没跟上"的静默漏测。
REFERENCE_RTL = tuple(case_table(ROOT))

# 故意不可综合：变量上界的 while 循环。Yosys 明确拒绝：
# `While loops are only allowed in constant functions!`
#
# 顺带记录一个实测反直觉结论：`#5 q <= d;` 这种延时**不会**让 Yosys 报错，
# 它只是被忽略掉（综合结果与没有延时一样）。所以"综合通过"不能反过来当作
# "这段代码的时序语义被正确实现了"的证据——这正是本层只做可综合性、不做
# 时序判断的原因。
_UNSYNTHESIZABLE = """`timescale 1ns/1ps
module unsynth_dut(input wire clk, input wire [3:0] d, output reg [3:0] q);
  integer i;
  always @(posedge clk) begin
    i = 0;
    while (i < d) begin
      q <= q + 1;
      i = i + 1;
    end
  end
endmodule
"""

_STAT_JSON_SAMPLE = """\
2.22. Executing STAT pass.
=== design hierarchy ===

   top  cells
--------------------------------------------------
\\pwm     5

=== pwm ===

{
   "creator": "Yosys 0.69",
   "invocation": "stat -json ",
   "modules": {
      "\\\\pwm": {
         "num_wires":         12,
         "num_ports":         4,
         "num_memories":      0,
         "num_processes":     0,
         "num_cells":         5,
         "num_cells_by_type": {
            "$adff": 2,
            "$alu": 2,
            "$not": 1
         }
      }
   },
      "design": {
         "num_wires":         12,
         "num_ports":         4,
         "num_memories":      0,
         "num_processes":     0,
         "num_cells":         5,
         "num_cells_by_type": {
            "$adff": 2,
            "$alu": 2,
            "$not": 1
         }
      }
}
"""


def test_parse_stat_json_extracts_counts_and_cells():
    stats = parse_stat_json(_STAT_JSON_SAMPLE)
    assert stats["cell_count"] == 5
    assert stats["wire_count"] == 12
    assert stats["port_count"] == 4
    assert stats["memory_count"] == 0
    assert stats["cell_kinds"] == 3
    # 按数量降序、同数量按名字升序
    assert stats["cells"][0] == ("$adff", 2)
    assert {name for name, _ in stats["cells"]} == {"$adff", "$alu", "$not"}


def test_parse_stat_json_returns_none_instead_of_guessing():
    """解析不到就留 None——不能用 0 冒充"没有单元"。"""

    stats = parse_stat_json("ERROR: something went wrong\n")
    assert stats["cell_count"] is None
    assert stats["cells"] == ()
    assert stats["cell_kinds"] == 0


def test_evidence_stages_declare_all_five_layers():
    keys = [key for key, _, _ in EVIDENCE_STAGES]
    assert keys == ["simulation", "synthesis", "timing", "bitstream", "hardware"]


def test_missing_yosys_reports_unavailable_without_failing(tmp_path):
    """工具缺失不是错误：状态是 unavailable，并且给出可操作的提示。"""

    result = YosysSynthRunner(
        SynthConfig(
            rtl_path=ROOT / "rtl" / "pwm.v",
            top="pwm",
            work_dir=tmp_path / "synth",
            yosys_path=str(tmp_path / "definitely-not-yosys"),
        )
    ).run()
    assert result.status == "unavailable"
    assert result.synthesizable is None
    assert "yowasp-yosys" in (result.skipped_reason or "")
    assert len(result.stages) == 5


def test_missing_rtl_reports_error(tmp_path):
    result = YosysSynthRunner(
        SynthConfig(
            rtl_path=tmp_path / "nope.v",
            top="nope",
            work_dir=tmp_path / "synth",
            yosys_path=YOSYS,
        )
    ).run()
    assert result.status in {"error", "unavailable"}


@pytest.mark.skipif(not YOSYS, reason="未安装 Yosys（pip install yowasp-yosys）")
def test_every_reference_rtl_is_synthesizable(tmp_path):
    """基准清单里的每个参考 RTL 都必须可综合，且能给出单元统计。"""

    for case in REFERENCE_RTL:
        result = YosysSynthRunner(
            SynthConfig(rtl_path=ROOT / "rtl" / f"{case}.v", top=case, work_dir=tmp_path / case)
        ).run()
        assert result.status == "passed", f"{case}: {result.error}"
        assert result.synthesizable is True
        assert isinstance(result.cell_count, int) and result.cell_count > 0, case
        assert result.cell_kinds > 0, case
        assert result.log_path and Path(result.log_path).is_file(), case
        assert result.stat_path and Path(result.stat_path).is_file(), case
        # 未做的层级必须显式标 not_run
        by_stage = {item["stage"]: item["status"] for item in result.stages}
        assert by_stage["simulation"] == "provided_by_pipeline"
        assert by_stage["synthesis"] == "passed"
        assert by_stage["timing"] == "not_run"
        assert by_stage["bitstream"] == "not_run"
        assert by_stage["hardware"] == "not_run"


@pytest.mark.skipif(not YOSYS, reason="未安装 Yosys（pip install yowasp-yosys）")
def test_unsynthesizable_rtl_is_reported_as_failure(tmp_path):
    """变量上界的 while 循环无法映射到门级：这一层必须报 failed，而不是静默通过。"""

    rtl = tmp_path / "unsynth_dut.v"
    rtl.write_text(_UNSYNTHESIZABLE, encoding="utf-8")
    result = YosysSynthRunner(
        SynthConfig(rtl_path=rtl, top="unsynth_dut", work_dir=tmp_path / "synth", timeout_s=120.0)
    ).run()
    assert result.status == "failed", result.to_dict()
    assert result.synthesizable is False
    assert result.error
    # 失败的运行同样要把五层证据表带上，且综合那行必须是 failed
    by_stage = {item["stage"]: item["status"] for item in result.stages}
    assert by_stage["synthesis"] == "failed"
    assert by_stage["timing"] == "not_run"


@pytest.mark.skipif(not YOSYS, reason="未安装 Yosys（pip install yowasp-yosys）")
def test_synth_result_serializes_to_json(tmp_path):
    """证据必须能整体序列化进 result.json，不能带不可 JSON 化的对象。"""

    result = YosysSynthRunner(
        SynthConfig(rtl_path=ROOT / "rtl" / "pwm.v", top="pwm", work_dir=tmp_path / "synth")
    ).run()
    payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert payload["status"] == "passed"
    assert payload["cells"] and isinstance(payload["cells"][0], dict)
    assert "不代表时序收敛" in payload["disclaimer"]


@pytest.mark.skipif(not YOSYS, reason="未安装 Yosys")
def test_rtl_path_with_spaces_and_semicolon_is_one_filename(tmp_path):
    """仓库和上传目录含空格、分号时，实际综合仍读取同一份源码。"""

    rtl_dir = tmp_path / "RTL files ; input"
    rtl_dir.mkdir()
    rtl = rtl_dir / "pwm design.v"
    rtl.write_bytes((ROOT / "rtl" / "pwm.v").read_bytes())
    result = YosysSynthRunner(
        SynthConfig(rtl_path=rtl, top="pwm", work_dir=tmp_path / "synth output")
    ).run()
    assert result.status == "passed", result.to_dict()
    assert result.synthesizable is True
    assert result.cell_count is not None and result.cell_count > 0
