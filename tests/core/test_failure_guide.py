"""面向学习者的失败解读（`core/failure_guide.py`）回归测试。

这一层的风险不是"算错"，而是**说错话**：如果它把"信号被赋值的位置"暗示成"出错的位置"，
用户会照着改一个正确的模块；如果它对不认识的输入硬猜，就会编出不存在的行号。
所以下面的用例主要钉措辞与诚实性边界。
"""
from __future__ import annotations

from pathlib import Path

from iverilog_ai.core.failure_guide import (
    build_failure_guide,
    locate_signal,
    render_failure_guides,
    reproduce_command,
)
from iverilog_ai.core.models import FailureRecord

ROOT = Path(__file__).resolve().parents[2]
BUG_RTL = ROOT / "rtl" / "mod10_counter_bug_wrap9.v"


def _failure(**overrides) -> FailureRecord:
    payload = {
        "test_id": "count_11",
        "cycle": 11,
        "signal": "count",
        "expected": "<1001>",
        "actual": "<0000>",
        "message": "mismatch",
    }
    payload.update(overrides)
    return FailureRecord(**payload)  # type: ignore[arg-type]


def test_locate_signal_finds_assignments_before_declarations() -> None:
    """赋值行要排在声明行前面——先看"谁在写它"，再看"它是什么"。"""

    source = BUG_RTL.read_text(encoding="utf-8")
    hits = locate_signal(source, "count")
    assert hits, "在真实 RTL 上必须找到 count 的赋值处"
    assert hits[0].kind == "drives"
    assert any(item.kind == "declares" for item in hits)
    for item in hits:
        assert item.line >= 1 and item.code


def test_locate_signal_rejects_junk_signal_names() -> None:
    """奇形怪状的"信号名"要直接返回空，不能拿去正则里乱匹配。"""

    source = "module m; reg a; always @* a = 1; endmodule\n"
    for junk in ("", "a; rm -rf /", "a[", "a b", "1abc", "*"):
        assert locate_signal(source, junk) == ()


def test_locate_signal_returns_empty_when_absent() -> None:
    """RTL 里没有这个信号就返回空——调用方据此说"没找到"，而不是编一行出来。"""

    assert locate_signal("module m; reg a; endmodule\n", "nonexistent") == ()


def test_guide_never_claims_a_line_is_the_bug() -> None:
    """**关键措辞**：只能写"被赋值的位置，不一定是出错的位置"。"""

    guide = build_failure_guide(_failure(), source=BUG_RTL.read_text(encoding="utf-8"))
    markdown = guide.to_markdown()
    assert "不一定是「出错的位置」" in markdown
    assert "就是错" not in markdown
    assert "错误在" not in markdown


def test_guide_points_at_real_lines() -> None:
    """给的行号必须真的是那个信号的赋值处（对着源码核）。"""

    source = BUG_RTL.read_text(encoding="utf-8")
    guide = build_failure_guide(_failure(), source=source)
    lines = source.splitlines()
    driven = [item for item in guide.look_at if item.kind == "drives"]
    assert driven
    for item in driven:
        assert lines[item.line - 1].strip() == item.code
        assert "count" in item.code


def test_guide_without_source_degrades_honestly() -> None:
    """没给源码时不指行号，并明说原因是"没给 RTL"。"""

    guide = build_failure_guide(_failure())
    assert guide.look_at == ()
    assert any("确认你给的是**被测模块**的源码" in step for step in guide.next_steps)


def test_undefined_value_is_explained_as_not_driven() -> None:
    """x/z 要说成"没有被确定地驱动"，而不是"算错了"。"""

    guide = build_failure_guide(_failure(expected="<0001>", actual="<00x1>"))
    assert "没有被确定地驱动" in guide.means
    assert any("出现不定值" in step for step in guide.next_steps)


def test_off_by_one_is_called_out() -> None:
    """差 1 是最常见的边界错，要点出来并给方向。"""

    guide = build_failure_guide(_failure(expected="<0000>", actual="<0001>"))
    assert any("差 1" in step for step in guide.next_steps)
    assert "大 1" in guide.means


def test_width_mismatch_is_called_out() -> None:
    guide = build_failure_guide(_failure(expected="<01>", actual="<0001>"))
    assert "位宽" in guide.means


def test_headline_strips_structural_brackets() -> None:
    """结构化记录里的 `<0001>` 包装不该出现在给人看的标题里。"""

    guide = build_failure_guide(_failure())
    assert "<1001>" not in guide.headline
    assert "期望 1001，实际 0000" in guide.headline


def test_reproduce_command_is_built_from_the_result() -> None:
    """复现命令要真的能重跑，缺字段时返回空串而不是拼一条假的。"""

    class _Result:
        config = {"rtl_path": "rtl/a.v", "testbench_path": "tb/a.v", "top_module": "tb_a"}

    command = reproduce_command(_Result())
    assert command.startswith("iverilog-ai run --rtl")
    assert "--testbench" in command and "--top tb_a" in command
    assert reproduce_command(type("R", (), {"config": {}})()) == ""
    assert reproduce_command(type("R", (), {"config": None})()) == ""


def test_render_failure_guides_uses_the_result_own_rtl_path() -> None:
    """不给 --rtl 时，要从结果自己的 config 里取源码——用户刚跑完不该再写一遍路径。"""

    class _Result:
        config = {"rtl_path": str(BUG_RTL), "testbench_path": "tb/x.v", "top_module": "tb_x"}
        failures = (_failure(),)

    guides = render_failure_guides(_Result())
    assert len(guides) == 1
    assert "第 3 行" in guides[0]
    assert "iverilog-ai run" in guides[0]


def test_render_failure_guides_caps_and_says_so() -> None:
    """只讲前 N 条时必须说明还有多少条，别让用户以为是全部。"""

    class _Result:
        config = {}
        failures = tuple(_failure(test_id=f"t{i}") for i in range(9))

    guides = render_failure_guides(_Result(), limit=3)
    assert len(guides) == 4
    assert "另有 6 条" in guides[-1]


def test_render_failure_guides_on_clean_run() -> None:
    class _Result:
        config = {}
        failures = ()

    assert render_failure_guides(_Result()) == ()
