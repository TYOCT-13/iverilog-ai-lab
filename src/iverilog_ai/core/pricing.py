"""把实验的 token 用量换算成费用，并如实标注价格的核验状态。

设计原则（与项目其它部分一致）：

1. **价格表是数据，不是代码里的常量。** 价格会变动，硬编码在代码里必然过期且无人察觉；
2. **未核验就不给金额。** `price_usd_per_million` 为 null 时输出"未核验"，绝不用 0 顶替——
   0 会让读者以为"免费"，与"不知道"是完全不同的结论；
3. **带核验日期与来源。** 金额只在 `verified=true` 且未过期时给出，并附上核验日期与来源链接；
4. **不推算汇率。** 原价是什么币种就报什么币种，不做汇率换算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["PricingTable", "CostEstimate", "load_pricing", "estimate_cost"]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICING_PATH = Path("data") / "model_pricing.json"


@dataclass(frozen=True)
class CostEstimate:
    """一次用量估算的结果。``amount`` 为 None 表示价格未核验或无法估算。"""

    model: str
    currency: str = "USD"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_amount: float | None = None
    completion_amount: float | None = None
    amount: float | None = None
    verified: bool = False
    verified_on: str | None = None
    source: str | None = None
    reason: str | None = None
    #: 这个单价是什么口径（例如"上界：高峰 + 输入按 cache miss"）。
    #: 官方定价分时段、分 cache 命中，而用量记录里没有这两个维度；不写清口径，
    #: 读者会把一个上界当成精确值——差一倍。
    basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "currency": self.currency,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "prompt_amount": self.prompt_amount,
            "completion_amount": self.completion_amount,
            "amount": self.amount,
            "verified": self.verified,
            "verified_on": self.verified_on,
            "source": self.source,
            "reason": self.reason,
            "basis": self.basis,
        }

    def describe(self) -> str:
        tokens = f"{self.prompt_tokens:,} prompt + {self.completion_tokens:,} completion"
        if self.amount is None:
            return f"{self.model}: {tokens} tokens；费用未估算（{self.reason}）"
        basis = f"；口径：{self.basis}" if self.basis else ""
        return (
            f"{self.model}: {tokens} tokens ≈ {self.amount:.4f} {self.currency}"
            f"（价格核验于 {self.verified_on}，来源 {self.source}{basis}）"
        )


class PricingTable:
    """价格表：按 provider/model 查询单价，并记录核验状态与新鲜度。"""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.stale_after_days = int(payload.get("stale_after_days", 90) or 90)
        self._prices: dict[str, dict[str, Any]] = {}
        for row in payload.get("prices", []) or []:
            key = str(row.get("model", ""))
            if key:
                self._prices[key] = dict(row)

    def lookup(self, model: str) -> dict[str, Any] | None:
        return self._prices.get(model)

    def is_stale(self, model: str, *, today: date | None = None) -> bool:
        row = self.lookup(model) or {}
        verified_on = row.get("verified_on")
        if not verified_on:
            return True
        try:
            verified = datetime.strptime(str(verified_on), "%Y-%m-%d").date()
        except ValueError:
            return True
        reference = today or datetime.now(timezone.utc).date()
        return (reference - verified).days > self.stale_after_days

    def estimate(self, model: str, *, prompt_tokens: int, completion_tokens: int) -> CostEstimate:
        row = self.lookup(model)
        if row is None:
            return CostEstimate(
                model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                reason="价格表中没有该模型",
            )
        if not row.get("verified"):
            return CostEstimate(
                model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                source=row.get("source"), reason="价格未核验",
            )
        prices = row.get("price_usd_per_million") or {}
        prompt_price, completion_price = prices.get("prompt"), prices.get("completion")
        if prompt_price is None or completion_price is None:
            return CostEstimate(
                model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                source=row.get("source"), reason="价格字段缺失",
            )
        prompt_amount = prompt_tokens / 1_000_000 * float(prompt_price)
        completion_amount = completion_tokens / 1_000_000 * float(completion_price)
        stale = self.is_stale(model)
        basis = str(row.get("basis")) if row.get("basis") else None
        return CostEstimate(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_amount=round(prompt_amount, 6),
            completion_amount=round(completion_amount, 6),
            amount=round(prompt_amount + completion_amount, 6),
            verified=True,
            verified_on=str(row.get("verified_on")),
            source=str(row.get("source")) if row.get("source") else None,
            reason="价格核验已超过新鲜期，建议复核" if stale else None,
            basis=basis,
        )


def load_pricing(root: str | Path | None = None, path: str | Path | None = None) -> PricingTable:
    """读取价格表；缺失时返回空表（调用方会得到"价格表中没有该模型"）。"""

    if path is not None:
        target = Path(path)
    else:
        base = Path(root).expanduser().resolve() if root else ROOT
        target = base / DEFAULT_PRICING_PATH
    if not target.is_file():
        return PricingTable({"prices": []})
    try:
        return PricingTable(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return PricingTable({"prices": []})


def estimate_cost(model: str, usage_rows: list[Mapping[str, Any]], *,
                  root: str | Path | None = None) -> CostEstimate:
    """把若干条 usage 记录累加后估算费用。

    只统计带 usage 的记录；服务商没返回 usage 的部分不计入，也不推测。
    """

    prompt = completion = 0
    for row in usage_rows:
        usage = row.get("usage") if isinstance(row, Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        prompt_value = usage.get("prompt_tokens")
        completion_value = usage.get("completion_tokens")
        if isinstance(prompt_value, int):
            prompt += prompt_value
        if isinstance(completion_value, int):
            completion += completion_value
    return load_pricing(root).estimate(model, prompt_tokens=prompt, completion_tokens=completion)
