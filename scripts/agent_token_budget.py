"""Shared per-study API token accounting; never treat unknown usage as zero."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock

from iverilog_ai.ai.provider import OpenAICompatibleProvider


class TokenBudgetExceeded(RuntimeError):
    pass


class TokenUsageViolation(RuntimeError):
    pass


class TokenBudget:
    """Single-process journal, saved before HTTP; pending attempts survive restart.

    Input reservation is deliberately conservative, not an exact tokenizer claim.
    Charge only total_tokens, not cache-hit/miss fields in addition to the total.
    """
    def __init__(self, limit: int, journal: Path):
        if type(limit) is not int or limit < 1:
            raise ValueError("positive token cap required")
        self.journal = Path(journal)
        self.lock = RLock()
        self.data = {"schema": "agent-round-token-budget-v1", "limit": limit,
                     "scope": "one_registered_batch_input_plus_output",
                     "reservation_rule": "2 * serialized UTF-8 request bytes + 4096 framing margin + max_tokens",
                     "reservation_is_tokenizer_proof": False, "halted": False, "records": []}
        if self.journal.exists():
            saved = json.loads(self.journal.read_text(encoding="utf-8"))
            if (saved.get("schema") != self.data["schema"] or type(saved.get("limit")) is not int
                    or saved["limit"] != limit or type(saved.get("halted")) is not bool):
                raise ValueError("existing journal cap or schema mismatch")
            for index, record in enumerate(saved["records"]):
                if (record["id"] != index or type(record["reserved_tokens"]) is not int
                        or record["reserved_tokens"] < 1
                        or record["status"] not in {"pending", "known_usage", "unknown_usage", "not_sent"}
                        or type(record["charged_tokens"]) is not int or record["charged_tokens"] < 0):
                    raise ValueError("invalid persisted token record")
                if record["status"] != "known_usage" and record["charged_tokens"] != 0:
                    raise ValueError("unconfirmed usage cannot release a reservation")
                if ("uncertain_charge_tokens" in record and (type(record["uncertain_charge_tokens"]) is not int
                        or record["uncertain_charge_tokens"] < record["reserved_tokens"])):
                    raise ValueError("invalid uncertain usage reservation")
                if record["status"] == "known_usage" and (type(record.get("prompt_tokens")) is not int
                        or record["prompt_tokens"] < 1 or type(record.get("completion_tokens")) is not int
                        or record["completion_tokens"] < 0
                        or record["charged_tokens"] != record["prompt_tokens"] + record["completion_tokens"]):
                    raise ValueError("persisted confirmed usage is inconsistent")
            self.data = saved

    def totals(self) -> dict:
        known = sum(r["charged_tokens"] for r in self.data["records"] if r["status"] == "known_usage")
        unknown = sum(r.get("uncertain_charge_tokens", r["reserved_tokens"])
                      for r in self.data["records"] if r["status"] in {"pending", "unknown_usage"})
        return {"reported_tokens": known, "unknown_reserved_tokens": unknown,
                "conservative_total": known + unknown,
                "remaining_tokens": max(0, self.data["limit"] - known - unknown),
                "requests_known_usage": sum(r["status"] == "known_usage" for r in self.data["records"]),
                "requests_unknown_usage": sum(r["status"] in {"pending", "unknown_usage"} for r in self.data["records"])}

    def save(self) -> None:
        self.data["totals"] = self.totals()
        temporary = self.journal.with_name(self.journal.name + ".pending-write")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(self.journal)

    def reserve(self, body: dict) -> int:
        if (not isinstance(body, dict) or body.get("stream") is not False
                or body.get("thinking") != {"type": "disabled"}
                or type(body.get("max_tokens")) is not int or not 256 <= body["max_tokens"] <= 8192
                or not isinstance(body.get("messages"), list) or not body["messages"]
                or any(not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}
                       or not isinstance(m.get("content"), str) for m in body["messages"])):
            raise ValueError("budgeted study requires bounded text chat with thinking disabled")
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        reservation = 2 * len(encoded) + 4096 + body["max_tokens"]
        with self.lock:
            if self.data["halted"] or self.totals()["conservative_total"] + reservation > self.data["limit"]:
                raise TokenBudgetExceeded("remaining study tokens cannot reserve the next request")
            identifier = len(self.data["records"])
            self.data["records"].append({"id": identifier, "status": "pending", "reserved_tokens": reservation,
                                         "charged_tokens": 0, "request_sha256": hashlib.sha256(encoded).hexdigest(),
                                         "request_bytes": len(encoded), "output_cap": body["max_tokens"]})
            self.save()
            return identifier

    def settle(self, identifier: int, usage: dict | None, *, attempted: bool) -> None:
        with self.lock:
            if type(identifier) is not int or not 0 <= identifier < len(self.data["records"]):
                raise ValueError("invalid reservation identifier")
            record = self.data["records"][identifier]
            if record["status"] != "pending":
                raise ValueError("request already settled")
            if not attempted:
                record["status"] = "not_sent"
                self.save()
                return
            valid = (isinstance(usage, dict)
                     and all(type(usage.get(k)) is int and usage[k] >= 0
                             for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
                     and usage["prompt_tokens"] > 0
                     and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"])
            if not valid:
                record["status"] = "unknown_usage"
                record["usage_status"] = "missing" if usage is None else "invalid"
                if usage is not None:
                    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
                    numeric = {k: usage[k] for k in fields
                               if isinstance(usage, dict) and type(usage.get(k)) is int and usage[k] >= 0}
                    record["numeric_usage_fields"] = numeric
                    record["usage_type_diagnostics"] = {k: type(usage.get(k)).__name__ for k in fields} if isinstance(usage, dict) else {"usage":type(usage).__name__}
                    record["uncertain_charge_tokens"] = max(record["reserved_tokens"], numeric.get("total_tokens",0),
                                                            numeric.get("prompt_tokens",0)+numeric.get("completion_tokens",0))
                    self.data["halted"] = True
                self.save()
                if usage is not None:
                    raise TokenUsageViolation("invalid reported token usage")
                return
            record.update(status="known_usage", charged_tokens=usage["total_tokens"],
                          prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"])
            violated = (usage["total_tokens"] > record["reserved_tokens"]
                        or usage["completion_tokens"] > record["output_cap"]
                        or self.totals()["conservative_total"] > self.data["limit"])
            if violated:
                self.data["halted"] = True
                record["usage_status"] = "reservation_or_output_cap_exceeded"
            self.save()
            if violated:
                raise TokenUsageViolation("reported usage exceeded the reserved allowance")


class BudgetedProvider(OpenAICompatibleProvider):
    """All message and legacy generation paths pass the final HTTP payload gate."""
    def __init__(self, *, token_budget: TokenBudget, **kwargs):
        self.token_budget = token_budget
        super().__init__(**kwargs)

    def _request(self, path: str, *, body: dict | None = None, streaming: bool = False) -> object:
        if streaming:
            raise ValueError("usage accounting requires nonstreaming requests")
        identifier = self.token_budget.reserve(body)
        before = self.request_count
        try:
            return super()._request(path, body=body, streaming=False)
        finally:
            self.token_budget.settle(identifier, self.last_usage, attempted=self.request_count > before)
