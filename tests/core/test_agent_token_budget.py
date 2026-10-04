"""Failures, restart and alternate generation paths cannot evade token charging."""
import json

import pytest

from scripts.agent_token_budget import BudgetedProvider, TokenBudget, TokenBudgetExceeded, TokenUsageViolation
from iverilog_ai.ai.provider import OpenAICompatibleProvider, ProviderMessage


def body():
    return {"model": "deepseek-flash", "stream": False, "thinking": {"type": "disabled"},
            "max_tokens": 4096, "messages": [{"role": "user", "content": "测试预算"}]}


def usage(tokens=100):
    return {"prompt_tokens": tokens-10, "completion_tokens": 10, "total_tokens": tokens,
            "prompt_cache_hit_tokens": tokens-10, "prompt_cache_miss_tokens": 0}


def test_exact_allowance_and_insufficient_cap_are_checked_before_transport(tmp_path):
    request = body()
    exact = 2 * len(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()) + 4096 + 4096
    low = TokenBudget(exact-1, tmp_path/'low.json')
    with pytest.raises(TokenBudgetExceeded):
        low.reserve(request)
    assert not low.data["records"] and not low.journal.exists()
    allowed = TokenBudget(exact, tmp_path/'allowed.json')
    identifier = allowed.reserve(request)
    assert allowed.totals()["conservative_total"] == exact
    allowed.settle(identifier, usage(), attempted=True)
    assert allowed.totals()["reported_tokens"] == 100
    assert allowed.totals()["unknown_reserved_tokens"] == 0


def test_pending_and_timeout_usage_are_not_refunded_on_restart(tmp_path):
    book = TokenBudget(1000000, tmp_path/'journal.json')
    first = book.reserve(body())
    pending = book.totals()["conservative_total"]
    restored = TokenBudget(1000000, book.journal)
    assert restored.totals()["conservative_total"] == pending
    restored.settle(first, None, attempted=True)
    assert restored.data["records"][0]["status"] == "unknown_usage"
    assert TokenBudget(1000000, book.journal).totals()["conservative_total"] == pending
    with pytest.raises(ValueError, match="already settled"):
        restored.settle(first, usage(), attempted=True)


@pytest.mark.parametrize("bad", [False, {}, {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
                                 {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
                                 {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 99}])
def test_invalid_usage_retains_reservation_and_halts(bad, tmp_path):
    book=TokenBudget(1000000,tmp_path/'journal.json')
    request=book.reserve(body())
    upper=book.totals()["conservative_total"]
    with pytest.raises(TokenUsageViolation):
        book.settle(request,bad,attempted=True)
    assert book.data["halted"] and book.totals()["conservative_total"] == upper
    with pytest.raises(TokenBudgetExceeded):
        book.reserve(body())


def test_over_reservation_is_reported_without_truncation(tmp_path):
    book=TokenBudget(1000000,tmp_path/'journal.json')
    request=book.reserve(body())
    reported=book.data["records"][request]["reserved_tokens"]+1
    with pytest.raises(TokenUsageViolation):
        book.settle(request,usage(reported),attempted=True)
    assert book.totals()["reported_tokens"] == reported and book.data["halted"]


def test_inconsistent_large_usage_keeps_numeric_evidence_and_uncertain_charge(tmp_path):
    book=TokenBudget(1000000,tmp_path/'journal.json')
    request=book.reserve(body())
    with pytest.raises(TokenUsageViolation):
        book.settle(request,{"prompt_tokens":900000,"completion_tokens":200000,"total_tokens":1},attempted=True)
    assert book.data["records"][0]["numeric_usage_fields"]["prompt_tokens"] == 900000
    assert book.totals()["unknown_reserved_tokens"] == 1100000
    assert book.totals()["remaining_tokens"] == 0 and book.data["halted"]
    assert TokenBudget(1000000,book.journal).totals()["unknown_reserved_tokens"] == 1100000


def test_failure_with_usage_is_charged_and_both_generation_interfaces_share_gate(monkeypatch,tmp_path):
    book=TokenBudget(1000000,tmp_path/'journal.json')
    def fake_request(self,path,**kwargs):
        # Represents the existing provider after a real transport attempt.
        self.request_count += 1
        self.last_usage = usage()
        assert book.journal.exists() and book.data["records"][-1]["status"] == "pending"
        return {"choices":[{"message":{"content":"{}"}}]}
    monkeypatch.setattr(OpenAICompatibleProvider,"_request",fake_request)
    provider=BudgetedProvider(token_budget=book,endpoint="https://api.deepseek.com",model="deepseek-flash",
                              api_key="unit_fixture",allow_network=False,stream=False,thinking_mode="disabled",
                              wire_api="chat_completions",force_output_limit=True,max_output_tokens=4096,request_limit=3)
    provider.generate("test")
    provider.generate_messages([ProviderMessage("user","test")])
    assert len(book.data["records"]) == provider.request_count == 2
    assert book.totals()["reported_tokens"] == 200
    def failed_request(self,path,**kwargs):
        self.request_count += 1
        self.last_usage=usage(150)
        raise RuntimeError("test transport failure with usage")
    monkeypatch.setattr(OpenAICompatibleProvider,"_request",failed_request)
    with pytest.raises(RuntimeError,match="transport failure"):
        provider.generate("third")
    assert book.totals()["reported_tokens"] == 350
