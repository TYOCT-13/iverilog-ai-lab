"""价格与费用估算的回归测试。

核心是三条**不能妥协**的口径：

1. 未核验的价格不给金额——`null` 不等于 0，用 0 顶替会让读者以为"免费"；
2. 缺字段、缺模型、表损坏都要如实说明原因，不静默返回 0；
3. 金额只在核验状态与新鲜度都满足时给出，且必须带上核验日期与来源。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from iverilog_ai.core.pricing import PricingTable, estimate_cost, load_pricing

ROOT = Path(__file__).parents[2]


def _table(rows: list[dict], stale_after_days: int = 90) -> PricingTable:
    return PricingTable({"stale_after_days": stale_after_days, "prices": rows})


def test_unverified_price_yields_no_amount():
    """未核验时必须报原因，而不是 0。"""

    table = _table([{
        "model": "m1", "provider": "p", "verified": False,
        "price_usd_per_million": {"prompt": None, "completion": None},
        "source": "https://example.invalid/pricing",
    }])
    estimate = table.estimate("m1", prompt_tokens=1000, completion_tokens=2000)
    assert estimate.amount is None
    assert estimate.reason == "价格未核验"
    assert estimate.prompt_tokens == 1000 and estimate.completion_tokens == 2000
    # 描述里不得出现金额
    assert "≈" not in estimate.describe()
    assert "未估算" in estimate.describe()


def test_unknown_model_is_reported_not_zeroed():
    estimate = _table([]).estimate("ghost", prompt_tokens=10, completion_tokens=10)
    assert estimate.amount is None
    assert estimate.reason == "价格表中没有该模型"


def test_missing_price_field_is_reported():
    table = _table([{
        "model": "m1", "verified": True, "verified_on": "2026-09-01",
        "price_usd_per_million": {"prompt": 1.0, "completion": None},
        "source": "https://example.invalid",
    }])
    estimate = table.estimate("m1", prompt_tokens=1000, completion_tokens=1000)
    assert estimate.amount is None
    assert estimate.reason == "价格字段缺失"


def test_verified_price_computes_amount_with_provenance():
    table = _table([{
        "model": "m1", "verified": True, "verified_on": "2026-09-01",
        "price_usd_per_million": {"prompt": 2.0, "completion": 8.0},
        "source": "https://example.invalid/pricing",
    }], stale_after_days=3650)
    estimate = table.estimate("m1", prompt_tokens=1_000_000, completion_tokens=500_000)
    assert estimate.amount == 2.0 + 4.0
    assert estimate.prompt_amount == 2.0
    assert estimate.completion_amount == 4.0
    assert estimate.verified is True
    assert estimate.verified_on == "2026-09-01"
    assert "example.invalid" in (estimate.source or "")
    # 描述里必须带核验日期与来源
    described = estimate.describe()
    assert "2026-09-01" in described and "example.invalid" in described


def test_stale_price_is_flagged_but_still_reported():
    """价格过期不是"不给金额"，而是"给了金额并提示复核"。"""

    table = _table([{
        "model": "m1", "verified": True, "verified_on": "2020-01-01",
        "price_usd_per_million": {"prompt": 1.0, "completion": 1.0},
        "source": "https://example.invalid",
    }], stale_after_days=90)
    assert table.is_stale("m1", today=date(2026, 9, 11)) is True
    estimate = table.estimate("m1", prompt_tokens=1000, completion_tokens=1000)
    assert estimate.amount is not None
    assert estimate.reason and "复核" in estimate.reason


def test_free_local_models_report_zero_not_unknown():
    """本机离线模型确实免费，应给出 0 而不是"未核验"——两者含义不同。"""

    table = load_pricing(ROOT)
    estimate = table.estimate("mock", prompt_tokens=1000, completion_tokens=1000)
    assert estimate.verified is True
    assert estimate.amount == 0.0


def test_verified_price_reports_its_basis_when_given():
    """单价有口径时必须报出来。

    真实情况：官方定价分高峰/非高峰（差一倍）且输入分 cache hit/miss，而用量记录里没有
    这两个维度。此时表里给的只能是一个**上界**；不写清口径，读者会把上界当精确值。
    """

    table = _table([{
        "model": "m1", "verified": True, "verified_on": "2026-09-01",
        "price_usd_per_million": {"prompt": 1.0, "completion": 2.0},
        "source": "https://example.invalid/pricing",
        "basis": "上界：高峰 + 输入按 cache miss",
    }], stale_after_days=3650)
    estimate = table.estimate("m1", prompt_tokens=1000, completion_tokens=1000)
    assert estimate.basis == "上界：高峰 + 输入按 cache miss"
    assert "口径" in estimate.describe()
    assert estimate.to_dict()["basis"].startswith("上界")
    # 没给口径时不能凭空编一个
    plain = _table([{
        "model": "m2", "verified": True, "verified_on": "2026-09-01",
        "price_usd_per_million": {"prompt": 1.0, "completion": 1.0},
        "source": "https://example.invalid",
    }], stale_after_days=3650).estimate("m2", prompt_tokens=1, completion_tokens=1)
    assert plain.basis is None
    assert "口径" not in plain.describe()


def test_repository_pricing_covers_the_models_the_experiments_used():
    """实验用过的两个真实模型必须在表里，且已核验——否则汇总只能报 token 量。"""

    table = load_pricing(ROOT)
    for model in ("deepseek-flash", "deepseek-v4-pro"):
        row = table.lookup(model)
        assert row is not None, f"价格表缺少实验用过的模型 {model}"
        assert row.get("verified") is True, f"{model} 仍未核验"
        assert row.get("verified_on"), f"{model} 缺少核验日期"
        assert row.get("basis"), f"{model} 缺少计价口径说明"
        estimate = table.estimate(model, prompt_tokens=1_000_000, completion_tokens=0)
        assert estimate.amount is not None and estimate.amount > 0


def test_repository_pricing_table_is_wellformed():
    """仓库里的价格表必须结构完整：每行都有来源，未核验的行必须没有数值。"""

    payload = json.loads((ROOT / "data" / "model_pricing.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["stale_after_days"] > 0
    assert payload["prices"], "价格表不应为空"
    for row in payload["prices"]:
        assert row.get("provider") and row.get("model")
        assert str(row.get("source", "")).strip(), f"{row.get('model')} 缺少来源"
        prices = row.get("price_usd_per_million") or {}
        assert set(prices) == {"prompt", "completion"}
        if row.get("verified"):
            assert row.get("verified_on"), f"{row['model']} 核验状态为真但没有核验日期"
            assert all(isinstance(value, (int, float)) for value in prices.values())
        else:
            assert all(value is None for value in prices.values()), (
                f"{row['model']} 未核验却填了数值——未核验的行必须为 null"
            )


def test_estimate_cost_aggregates_only_rows_with_usage():
    """没有 usage 的运行不计入，也不推测。"""

    rows = [
        {"usage": {"prompt_tokens": 100, "completion_tokens": 200}},
        {"usage": None},
        {"usage": {}},
        {"usage": {"prompt_tokens": 50, "completion_tokens": 50}},
    ]
    estimate = estimate_cost("mock", rows, root=ROOT)
    assert estimate.prompt_tokens == 150
    assert estimate.completion_tokens == 250
    assert estimate.amount == 0.0
