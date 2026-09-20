"""`verify_diff` 的回归测试：一条命令回答"两份 RTL 行为一致吗"。

这一层最容易出的错不是"算错了"，而是**把没有证据的结果说成一致**：
离线规划器生成的计划只有激励、没有期望值，两侧因此只会产出数量相同的观察记录，
逐项比对会"全等"——但一次比较都没发生。下面有专门的用例钉住这一条。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.labels import DIFF_LABELS, diff_label
from iverilog_ai.core.verify_diff import (
    CONTRACT_FROM_DRAFT,
    CONTRACT_PROVIDED,
    PLAN_FROM_OFFLINE,
    PLAN_PROVIDED,
    STATUS_DIFFERENT,
    STATUS_IDENTICAL,
    STATUS_INCONCLUSIVE,
    verify_diff,
)

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "rtl" / "mod10_counter.v"
BUG = ROOT / "rtl" / "mod10_counter_bug_wrap9.v"
CONTRACT = ROOT / "examples" / "mod10_counter_contract.json"

pytestmark = pytest.mark.skipif(
    not BASELINE.is_file() or not BUG.is_file(),
    reason="需要仓库内的参考 RTL",
)


@pytest.fixture(scope="module")
def same(tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("vd-same")
    return verify_diff(BASELINE, BASELINE, out)


@pytest.fixture(scope="module")
def different(tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("vd-different")
    return verify_diff(BASELINE, BUG, out, contract=DutContract.from_json(CONTRACT.read_text(encoding="utf-8")))


def test_identical_rtl_is_reported_identical(same) -> None:
    """同一份文件对比自己：必须是"两侧一致"，且退出码为 0。"""

    assert same.status == STATUS_IDENTICAL
    assert same.label == DIFF_LABELS[STATUS_IDENTICAL]
    assert same.exit_code == 0
    assert same.differences == ()


def test_defect_variant_is_reported_different_with_evidence(different) -> None:
    """缺陷变体必须被检出，且差异清单要能定位到"哪一拍、哪个信号"。"""

    assert different.status == STATUS_DIFFERENT
    assert different.exit_code == 1
    assert different.differences, "报了不同却没有差异清单，等于没说"
    kinds = {item["kind"] for item in different.differences}
    assert kinds & {"waveform_difference", "record_mismatch"}, kinds
    for item in different.differences:
        assert item["where"] and item["message"]


def test_draft_contract_is_disclosed_and_dumped(same) -> None:
    """自动提合约是允许的，但**必须如实标注**，并把草稿落盘供用户确认。"""

    assert same.contract_source == CONTRACT_FROM_DRAFT
    assert same.contract_draft["module"] == "mod10_counter"
    assert any("草稿" in item for item in same.caveats)
    # 草稿要落盘，否则用户想"确认一下"都没有对象可确认
    assert Path(same.artifacts["dir"], "contract.draft.json").is_file()


def test_provided_contract_removes_the_draft_caveat(different) -> None:
    """给了确认过的合约，就不该再出现"草稿"保留意见。"""

    assert different.contract_source == CONTRACT_PROVIDED
    assert not any("草稿" in item for item in different.caveats)


def test_offline_plan_is_labelled_with_its_source_and_evidence(same) -> None:
    """没给计划时用离线规划器，且来源与证据等级都要写进结论。"""

    assert same.plan_source == PLAN_FROM_OFFLINE
    # mod10_counter 已与 RTL 逐拍对齐，所以期望值证据等级是 reference_model，
    # 而**不是**因为"离线规划器生成的"就降级。
    assert same.plan_evidence_level == "reference_model"
    assert same.comparable_checks > 0
    assert same.waveform_compared


def test_provided_plan_is_recorded_as_provided(tmp_path: Path) -> None:
    """给了计划就用给定的，来源标注为 provided，且不生成草稿合约文件。"""

    from iverilog_ai.ai.debug_provider import offline_provider
    from iverilog_ai.ai.planner import plan_tests

    contract = DutContract.from_json(CONTRACT.read_text(encoding="utf-8"))
    plan = plan_tests(
        "cover reset release and counter wrap", "mod10_counter",
        offline_provider(contract, design="mod10_counter"), max_retries=0,
    )
    result = verify_diff(BASELINE, BASELINE, tmp_path / "out", contract=contract, plan=plan)
    assert result.plan_source == PLAN_PROVIDED
    assert result.contract_source == CONTRACT_PROVIDED
    assert not (tmp_path / "out" / "contract.draft.json").exists()


def test_same_output_dir_can_be_reused(tmp_path: Path) -> None:
    """同一个 output_dir 跑第二次必须仍然成功。

    真实缺陷：`VerificationPipeline` 把"输出目录最近的已存在祖先"当信任根，而第一次运行
    会创建 `user/`、`reference/`，第二次那个祖先就变成了子目录，输出反而落在它外面，
    安全检查报 `output parent is outside allowed roots` —— 也就是"这条路只能走一次"。
    """

    out = tmp_path / "reuse"
    first = verify_diff(BASELINE, BASELINE, out)
    second = verify_diff(BASELINE, BUG, out)
    assert first.status == STATUS_IDENTICAL
    assert second.status == STATUS_DIFFERENT
    assert Path(out, "verify_diff.json").is_file()


def test_missing_file_fails_loudly(tmp_path: Path) -> None:
    """路径写错要抛错，不能伪装成"行为不同"。"""

    with pytest.raises(ValueError):
        verify_diff(BASELINE, tmp_path / "nope.v", tmp_path / "out")


def test_result_files_are_written(same) -> None:
    """JSON 与 Markdown 都要落盘，Markdown 要能直接贴进 PR。"""

    json_path = Path(same.artifacts["json"])
    md_path = Path(same.artifacts["markdown"])
    assert json_path.is_file() and md_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == same.status
    assert payload["status_label"] == same.label
    assert payload["exit_code"] == same.exit_code
    markdown = md_path.read_text(encoding="utf-8")
    for heading in ("## 凭什么这么说", "## 差异清单", "## 这次没覆盖到什么"):
        assert heading in markdown, heading
    assert "从基线 RTL 自动提取的**草稿**" in markdown


def test_exit_code_mapping_is_total() -> None:
    """退出码语义要覆盖三态：一致 0 / 不同 1 / 没比出结论 2。"""

    assert {STATUS_IDENTICAL, STATUS_DIFFERENT, STATUS_INCONCLUSIVE} == set(DIFF_LABELS)
    assert diff_label(STATUS_INCONCLUSIVE) == "未取得可比证据"


def test_no_comparable_evidence_is_not_reported_as_identical() -> None:
    """**关键规则一**：没有可比证据时不许说"一致"。

    离线规划器对未建模的设计只生成激励、没有期望值，两侧因此只会产出数量相同的观察记录，
    逐项比对会"全等"——但那是一次比较都没发生的假通过。判定规则是：说"一致"必须有证据，
    要么有带期望值的可比检查项，要么逐拍波形真的比过。
    """

    from iverilog_ai.core.verify_diff import _decide_status

    assert _decide_status("identical", 0, False) == STATUS_INCONCLUSIVE
    assert _decide_status("identical", 0, True) == STATUS_IDENTICAL
    assert _decide_status("identical", 5, False) == STATUS_IDENTICAL
    # "不同"永远可信：在共享测试台上观测到了真实差异，与覆盖范围无关。
    assert _decide_status("different", 0, False) == STATUS_DIFFERENT
    assert _decide_status("records_identical_waveform_unavailable", 9, True) == STATUS_INCONCLUSIVE


def test_a_side_that_did_not_run_is_not_a_behaviour_difference() -> None:
    """**关键规则二**：候选没跑起来（编译失败）不许报成"两侧不同"。

    候选编译不过时一条记录都产不出来，逐项比对会把基线每一条检查都记成"候选缺失"，
    于是结论显示"两侧不同"。但真实情况是候选根本没跑起来——批改场景里这个区别要命：
    学生看到的会是"你的逻辑和标准不一致"，而实际上他的代码连编译都没过。
    """

    from iverilog_ai.core.verify_diff import _decide_status

    # 底层给的是 different（记录缺失），但只要有一侧没产出记录，就必须降级成"没结论"
    assert _decide_status("different", 0, False, both_sides_ran=False) == STATUS_INCONCLUSIVE
    assert _decide_status("identical", 29, True, both_sides_ran=False) == STATUS_INCONCLUSIVE
    assert _decide_status("different", 0, False, both_sides_ran=True) == STATUS_DIFFERENT


def test_inconclusive_result_carries_reasons() -> None:
    """判成"未取得可比证据"时必须写清为什么，否则用户只会看到一句"不知道"。"""

    from typing import cast

    from iverilog_ai.core.behavior_compare import BehaviorCompareResult
    from iverilog_ai.core.verify_diff import _collect_caveats

    class _Stub:
        """只实现 `_collect_caveats` 真正读到的字段，用于构造"最坏情况"。"""

        class waveform:  # noqa: N801 - 模拟返回结构
            status = "not_available"

            @staticmethod
            def get(key: str, default=None):
                return {"reason": "任一侧没有生成 VCD"}.get(key, default)

        _empty = type("S", (), {"config": {}, "records": ()})()
        reference = user = type("R", (), {"simulation": _empty})()
        status = "records_identical_waveform_unavailable"

    caveats = _collect_caveats(cast(BehaviorCompareResult, _Stub()), CONTRACT_FROM_DRAFT, 0, False)
    joined = " ".join(caveats)
    assert "没有产生任何带期望值的检查项" in joined
    assert "逐拍波形没有比对成功" in joined
    assert "任一侧没有生成 VCD" in joined
    assert "草稿" in joined
