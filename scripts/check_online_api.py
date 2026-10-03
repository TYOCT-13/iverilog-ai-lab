"""Preflight or run a bounded API smoke check; default mode never connects."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from iverilog_ai.ai import MockProvider, OpenAICompatibleProvider, plan_tests
from iverilog_ai.ai.provider import ProviderConnectionError, ProviderHTTPError
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.rules import rules_context

ROOT = Path(__file__).resolve().parents[1]


class _PromptProbe:
    """Build the exact planner prompt offline, without another prompt template."""

    prompt = ""

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return MockProvider().generate(prompt)


def _safe_endpoint(value: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    # Custom gateway paths can contain tenant credentials. Only show the origin.
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}" + ("/<path>" if parsed.path.strip("/") else "")


def _safe_failure(exc: Exception) -> dict[str, object]:
    # Never persist arbitrary provider/validation exception strings: they may
    # contain response text, proxy URLs, or the key echoed by a broken gateway.
    if isinstance(exc, ProviderHTTPError):
        return {"type": "http_error", "status": exc.status}
    if isinstance(exc, ProviderConnectionError):
        return {"type": "connection_error", "hint": "check endpoint, network and timeout"}
    return {"type": type(exc).__name__, "hint": "plan validation or local execution failed"}


def _usage(provider: OpenAICompatibleProvider) -> dict[str, int] | None:
    if not provider.last_usage:
        return None
    return {
        key: value for key, value in provider.last_usage.items()
        if key in {"prompt_tokens", "completion_tokens", "input_tokens", "output_tokens", "total_tokens"}
        and isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="offline preflight (the default)")
    mode.add_argument("--execute", action="store_true", help="explicitly send the displayed small batch")
    parser.add_argument("--endpoint", default=os.getenv("IVERILOG_AI_BASE_URL") or os.getenv("IVERILOG_AI_ENDPOINT", ""))
    parser.add_argument("--model", default=os.getenv("IVERILOG_AI_MODEL", ""))
    parser.add_argument("--api-key-env", default="IVERILOG_AI_API_KEY")
    parser.add_argument("--wire-api", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--cases", nargs="+", default=["simple_alu"])
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--max-requests", type=int, choices=range(1, 10), default=1)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--stream", choices=["on", "off"], default="off", help="no automatic compatibility fallback")
    parser.add_argument("--simulate", action="store_true", help="also run each valid plan on its reference RTL")
    parser.add_argument("--iverilog", default=None)
    parser.add_argument("--vvp", default=None)
    parser.add_argument("--output-dir", default=None, help="new directory only; historical results are never overwritten")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.api_key_env):
        parser.error("--api-key-env must name an environment variable")
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 180:
        parser.error("--timeout must be between 1 and 180 seconds")
    if not 256 <= args.max_output_tokens <= 32768:
        parser.error("--max-output-tokens must be between 256 and 32768")
    cases = list(dict.fromkeys(args.cases))
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text(encoding="utf-8"))
    if len(cases) > 3 or any(case not in manifest["categories"] for case in cases):
        parser.error("choose 1 to 3 known benchmark cases")
    planned = len(cases) * args.repeats
    if planned > args.max_requests:
        parser.error(f"planned requests ({planned}) exceed --max-requests ({args.max_requests})")
    secret = os.getenv(args.api_key_env, "").strip()
    if args.endpoint:
        try:
            parsed = urlsplit(args.endpoint)
            _ = parsed.port
        except ValueError:
            parser.error("invalid endpoint hostname or port")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("endpoint must not contain credentials, query parameters or fragments")
    try:
        provider = OpenAICompatibleProvider(
            endpoint=args.endpoint, model=args.model, api_key="preflight-no-secret",
            timeout=args.timeout, wire_api=args.wire_api, reasoning_effort=None,
            max_output_tokens=args.max_output_tokens, force_output_limit=True,
            request_limit=args.max_requests,
            allow_network=args.execute, store=False, stream=args.stream == "on",
        )
    except ValueError:
        parser.error("invalid endpoint; use HTTPS or a loopback HTTP debug server")
    # Do not inherit another key through the provider's fallback environment names.
    provider.api_key = secret if secret else ("debug-local-no-key" if provider.is_loopback else "")
    missing = []
    if not args.endpoint:
        missing.append("endpoint")
    if not args.model.strip():
        missing.append("model")
    if not secret and not provider.is_loopback:
        missing.append(f"environment variable {args.api_key_env}")
    report: dict[str, Any] = {
        "schema_version": "1.0", "purpose": "api_smoke_check_not_benchmark",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry_run", "endpoint": _safe_endpoint(args.endpoint),
        "model": args.model or None, "wire_api": args.wire_api,
        "key_env": args.api_key_env, "has_api_key": bool(secret), "missing": missing,
        "cases": cases, "repeats": args.repeats, "planned_requests": planned,
        "request_limit": args.max_requests, "automatic_retries": 0,
        "max_output_tokens_per_request": args.max_output_tokens,
        "max_output_tokens_for_batch": planned * args.max_output_tokens,
        "timeout_seconds_per_request": args.timeout, "stream": args.stream,
        "billing_cap": None, "billing_note": "Request/output limits are not a monetary billing cap; input tokens also cost money.",
        "simulate": args.simulate, "inputs": [], "runs": [],
    }
    prepared: dict[str, tuple[dict[str, Any], str]] = {}
    for case in cases:
        contract = json.loads((ROOT / f"examples/{case}_contract.json").read_text(encoding="utf-8"))
        context, rules = rules_context(ROOT, case, contract)
        objective = f"bounded verification for {case}; return at most 12 concrete vectors"
        probe = _PromptProbe()
        plan_tests(objective, case, probe, max_retries=0, context=context)
        prepared[case] = (contract, context)
        report["inputs"].append({
            "case": case, "prompt_sha256": hashlib.sha256(probe.prompt.encode()).hexdigest(),
            "prompt_utf8_bytes": len(probe.prompt.encode()), "rules": rules,
        })
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if missing:
        parser.error("missing configuration: " + ", ".join(missing))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output_dir).expanduser().resolve() if args.output_dir else ROOT / ".iverilog-ai/api-checks" / f"{stamp}-{uuid4().hex[:8]}"
    if output.exists():
        parser.error("--output-dir already exists; choose a new directory")
    output.mkdir(parents=True)
    report_path = output / "api_check.json"

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    for case in cases:
        contract, context = prepared[case]
        for repeat in range(args.repeats):
            row: dict[str, Any] = {"case": case, "repeat": repeat, "status": "running"}
            report["runs"].append(row)
            try:
                provider.last_usage = None
                plan = plan_tests(
                    f"bounded verification for {case}; return at most 12 concrete vectors",
                    case, provider, max_retries=0, context=context,
                )
                plan_dir = output / case / str(repeat)
                plan_dir.mkdir(parents=True)
                plan_text = plan.model_dump_json(indent=2)
                # A gateway could echo the bearer token inside a schema-valid string.
                if secret and secret in plan_text:
                    raise ValueError("provider echoed a credential")
                (plan_dir / "plan.json").write_text(plan_text + "\n", encoding="utf-8")
                row.update(status="plan_valid", vectors=len(plan.vectors), usage=_usage(provider))
                if args.simulate:
                    result = VerificationPipeline().run(
                        plan, DutContract.from_dict(contract), ROOT / f"rtl/{case}.v",
                        plan_dir / "simulation", allowed_roots=(ROOT, output),
                        iverilog_path=args.iverilog, vvp_path=args.vvp,
                    )
                    row.update(simulation_status=result.status.value, checks=result.simulation.check_count, failures=len(result.failures))
                    if result.status.value not in {"passed", "passed_with_warnings"} or result.failures:
                        row["status"] = "simulation_needs_review"
            except Exception as exc:
                row.update(status="failed", error=_safe_failure(exc), usage=_usage(provider))
            report["request_attempts"] = provider.request_count
            save()
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if row["status"] != "plan_valid":
                print(f"Stopped after a failed check. Report: {report_path}", flush=True)
                return 1
    print(f"Report: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
