"""开源规约摄取器的回归测试。

重点覆盖三类东西：

1. **口径**：只产出聚合统计，绝不复制上游代码；
2. **探针正确性**：本模块开发过程中有两个探针写错并产生了"看着漂亮但无意义"的
   数字，这里把它们钉成回归用例；
3. **降级行为**：没有产物、关掉开关、置信度不足时都不得伪造结论。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.conventions import (
    DEFAULT_SOURCES,
    PROBES,
    ConventionSource,
    load_conventions,
    measure_source,
    render_conventions_context,
    strip_comments,
)

ROOT = Path(__file__).parents[2]
CONVENTIONS_JSON = ROOT / "data" / "opensource_conventions.json"


# --------------------------------------------------------------------------
# 探针正确性（每一个都对应一个真实踩过的坑）
# --------------------------------------------------------------------------
def _measure_one(source: str) -> dict[str, dict[str, float]]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.v"
        path.write_text(source, encoding="utf-8")
        measured = measure_source(Path(tmp))
    return {probe["probe"]: probe for probe in measured["probes"]}


def test_reset_naming_probe_is_not_fooled_by_burst():
    """`burst` 含 "rst" 子串，早期用子串匹配把复位名虚增到 491 个。

    这条用例把"词元匹配"钉死：只有真正的复位标识符才计入分母。
    """

    source = "module m(input wire clk, input wire rst_n); wire burst_start; "
    source += "reg burst_reg; always @(posedge clk) burst_reg <= burst_start; endmodule\n"
    probes = _measure_one(source)
    probe = probes["active_low_reset_naming"]
    # 只有 rst_n 一个复位类标识符，且它是 _n 结尾
    assert probe["denominator"] == 1, probe
    assert probe["numerator"] == 1, probe


def test_ansi_port_probe_handles_multiline_parameter_and_port_lists():
    """真实工程写法：参数列表与端口列表都换行，且括号另起一行。

    早期正则只覆盖"参数与端口同行"，在 83 个文件里只匹配到 4 个模块头，
    却算出"ANSI 端口 100%"。这里用真实写法钉住匹配数。
    """

    source = """module demo #
(
    parameter WIDTH = 8
)
(
    input wire clk,
    input wire [WIDTH-1:0] din,
    output wire [WIDTH-1:0] dout
);
endmodule
"""
    probes = _measure_one(source)
    probe = probes["ansi_ports"]
    assert probe["denominator"] == 1, probe
    assert probe["numerator"] == 1, probe


def test_blocking_probe_ignores_for_loop_variables():
    """`for (i = 0; ...)` 里的阻塞赋值是合法用法，不能算作"时序块用了阻塞赋值"。"""

    source = """module m(input wire clk, input wire [3:0] d, output reg [3:0] q);
  integer i;
  always @(posedge clk) begin
    for (i = 0; i < 4; i = i + 1) begin
      q[i] <= d[i];
    end
  end
endmodule
"""
    probes = _measure_one(source)
    assert probes["no_blocking_in_clocked"]["numerator"] == 1, probes["no_blocking_in_clocked"]


def test_clocked_body_extraction_does_not_leak_combinational_block():
    """组合块里的阻塞赋值不能被算进时序块——靠 begin/end 配平切块，而不是贪婪正则。"""

    source = """module m(input wire clk, input wire a, output reg q, output reg y);
  always @(posedge clk) begin
    q <= a;
  end
  always @(*) begin
    y = a;
  end
endmodule
"""
    probes = _measure_one(source)
    # 只有一个时序块，且它不含阻塞赋值
    assert probes["no_blocking_in_clocked"]["denominator"] == 1
    assert probes["no_blocking_in_clocked"]["numerator"] == 1


def test_strip_comments_keeps_timescale_but_drops_prose():
    """注释里出现 `<=` 之类的字样不能成为代码证据；但 `timescale 必须留下。"""

    raw = """`timescale 1ns/1ps
// always use <= here, never =
module m; /* comment with case(x) endcase */
endmodule
"""
    cleaned = strip_comments(raw)
    assert "`timescale" in cleaned
    assert "always use" not in cleaned
    assert "comment with" not in cleaned


# --------------------------------------------------------------------------
# 口径：产物只含统计，不含上游代码
# --------------------------------------------------------------------------
def test_measure_source_records_fingerprints_not_code():
    import tempfile

    source = "module m(input wire clk); reg q; always @(posedge clk) q <= 1'b0; endmodule\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.v"
        path.write_text(source, encoding="utf-8")
        measured = measure_source(Path(tmp))
    blob = json.dumps(measured, ensure_ascii=False)
    assert measured["file_count"] == 1
    assert len(measured["files"][0]["sha256"]) == 64
    # 不得出现源码内容
    assert "posedge clk" not in blob
    assert "endmodule" not in blob


def test_probe_registry_and_source_declarations_are_wellformed():
    for probe_id, title, fn in PROBES:
        assert probe_id and title and callable(fn)
    for source in DEFAULT_SOURCES:
        assert source.spdx, source.key
        # 固定提交而不是分支名，否则度量不可复现
        assert len(source.ref) == 40 and all(ch in "0123456789abcdef" for ch in source.ref), source.ref
        assert source.license_url.startswith("https://")


# --------------------------------------------------------------------------
# 提示片段渲染
# --------------------------------------------------------------------------
def test_render_context_labels_sources_and_licenses():
    payload = {
        "sources": [
            {
                "repository": "example/demo",
                "ref": "0" * 40,
                "spdx": "MIT",
                "file_count": 3,
                "probes": [
                    {"probe": "p", "title": "某事", "numerator": 3, "denominator": 3,
                     "ratio": 1.0, "confidence": "strong"},
                ],
            }
        ]
    }
    text = render_conventions_context(payload)
    assert "example/demo" in text
    assert "MIT" in text
    assert "不改变判定口径" in text


def test_render_context_filters_by_confidence():
    """弱置信度的探针不得出现在提示里——否则等于把个案当规范。"""

    payload = {
        "sources": [
            {
                "repository": "example/demo", "ref": "0" * 40, "spdx": "MIT", "file_count": 2,
                "probes": [
                    {"probe": "weak_one", "title": "少见的写法", "numerator": 1, "denominator": 10,
                     "ratio": 0.1, "confidence": "weak"},
                    {"probe": "strong_one", "title": "普遍的写法", "numerator": 9, "denominator": 10,
                     "ratio": 0.9, "confidence": "strong"},
                ],
            }
        ]
    }
    text = render_conventions_context(payload, min_confidence="moderate")
    assert "普遍的写法" in text
    assert "少见的写法" not in text


def test_empty_conventions_render_safely():
    text = render_conventions_context({"sources": []})
    assert "没有达到置信度阈值的约定" in text


def test_load_conventions_handles_missing_file(tmp_path):
    payload = load_conventions(tmp_path / "nope.json")
    assert payload["sources"] == []


# --------------------------------------------------------------------------
# 真实产物（若已生成）
# --------------------------------------------------------------------------
@pytest.mark.skipif(not CONVENTIONS_JSON.is_file(), reason="尚未生成实测约定产物")
def test_generated_artifact_is_consistent():
    payload = json.loads(CONVENTIONS_JSON.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["sources"], "产物里没有来源"
    assert "不含上游源代码" in payload["note"]
    for source in payload["sources"]:
        assert source["file_count"] > 0
        assert len(source["files"]) == source["file_count"]
        assert all(len(item["sha256"]) == 64 for item in source["files"])
        # 探针的分母必须自洽：命中不能超过总数
        for probe in source["probes"]:
            assert probe["numerator"] <= probe["denominator"], probe
            assert 0.0 <= probe["ratio"] <= 1.0, probe
