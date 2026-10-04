"""运行 API 验证 Agent；默认只检查配置，--execute 才发送请求。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import uuid

from iverilog_ai.ai.agent import AgentLimits, STOP_LABELS, run_verification_agent
from iverilog_ai.ai.local_api_profile import read_key_file
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.benchmark_cases import CASE_TABLE
from iverilog_ai.core.contracts import DutContract

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--case", choices=sorted(CASE_TABLE), default="mod10_counter")
    parser.add_argument("--rtl", type=Path, help="同接口的实际 DUT；不会修改该文件")
    parser.add_argument("--plan", type=Path, help="已有计划；省略时由 API 生成第一批输入")
    parser.add_argument("--objective", default="检查复位、正常行为与边界条件，寻找可复现反例")
    parser.add_argument("--spec", type=Path, help="可选的人工规格文本，将随请求发送")
    parser.add_argument("--endpoint", default=os.getenv("IVERILOG_AI_BASE_URL") or os.getenv("IVERILOG_AI_ENDPOINT", ""))
    parser.add_argument("--model", default=os.getenv("IVERILOG_AI_MODEL", ""))
    credential = parser.add_mutually_exclusive_group()
    credential.add_argument("--api-key-env", default="IVERILOG_AI_API_KEY")
    credential.add_argument("--api-key-file", type=Path, help="读取本机的单行密钥文件，不复制密钥到项目中")
    parser.add_argument("--wire-api", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--thinking-mode", choices=["enabled", "disabled"], default=None)
    parser.add_argument("--agent-plan-mode", choices=["append", "independent"], default="append")
    parser.add_argument("--reference-sampling", choices=["vector_end", "per_cycle"], default="vector_end")
    parser.add_argument("--stream", choices=["on", "off"], default="off")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--max-total-cycles", type=int, default=1000)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--iverilog", default=os.getenv("IVERILOG_PATH") or (r"D:\iverilog\bin\iverilog.exe" if Path(r"D:\iverilog\bin\iverilog.exe").is_file() else "iverilog"))
    parser.add_argument("--vvp", default=os.getenv("VVP_PATH") or (r"D:\iverilog\bin\vvp.exe" if Path(r"D:\iverilog\bin\vvp.exe").is_file() else "vvp"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.thinking_mode is not None and args.wire_api != "chat_completions":
            raise ValueError("explicit thinking mode requires chat_completions")
        limits = AgentLimits(max_rounds=args.max_rounds, max_requests=args.max_requests,
                             max_total_cycles=args.max_total_cycles, max_output_tokens=args.max_output_tokens,
                             request_timeout_seconds=args.timeout)
        contract = DutContract.from_dict(json.loads((ROOT / f"examples/{args.case}_contract.json").read_text(encoding="utf-8")))
        source = args.rtl or ROOT / CASE_TABLE[args.case]["rtl"]
        if not source.is_file():
            raise ValueError("RTL file missing")
        initial = TestPlan.model_validate_json(args.plan.read_text(encoding="utf-8")) if args.plan else None
        spec_path = args.spec or ROOT / f"spec/{args.case}_spec.md"
        if args.spec and not spec_path.is_file():
            raise ValueError("requested specification file missing")
        spec = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        key = read_key_file(args.api_key_file) if args.api_key_file else os.getenv(args.api_key_env, "").strip()
        url = urlsplit(args.endpoint)
        if args.endpoint and (url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment):
            raise ValueError("invalid endpoint")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("external endpoint must use HTTPS")
        missing = [name for name, value in [("endpoint", args.endpoint), ("model", args.model), ("api_key", key)] if not value]
        if url.hostname in {"localhost", "127.0.0.1", "::1"}:
            missing = [name for name in missing if name != "api_key"]
        # 不显示自定义端点路径、凭据或完整环境变量。
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "case": args.case,
                          "endpoint_host": url.hostname, "model": args.model, "missing": missing,
                          "thinking_mode": args.thinking_mode, "agent_plan_mode": args.agent_plan_mode,
                          "reference_sampling": args.reference_sampling,
                          "limits": limits.model_dump(), "initial_plan": "provided" if initial else "api"}, ensure_ascii=False))
        if not args.execute:
            return 0
        if missing:
            raise ValueError("API configuration missing; inspect dry-run missing fields")
        if not key and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("API credential missing")
        provider = OpenAICompatibleProvider(
            endpoint=args.endpoint, model=args.model, api_key=key or "local-no-key",
            wire_api=args.wire_api, reasoning_effort=None, allow_network=True, store=False,
            thinking_mode=args.thinking_mode,
            timeout=args.timeout, stream=args.stream == "on", request_limit=limits.max_requests,
            max_output_tokens=limits.max_output_tokens, force_output_limit=True,
        )
        output = args.output_dir or ROOT / ".iverilog-ai/agent-runs" / uuid.uuid4().hex[:16]
        result = run_verification_agent(
            provider=provider, contract=contract, rtl_path=source, output_dir=output,
            objective=args.objective, specification=spec, initial_plan=initial, limits=limits,
            agent_plan_mode=args.agent_plan_mode,
            execution_options={"allowed_roots": (ROOT, source.resolve().parent),
                               "iverilog_path": args.iverilog, "vvp_path": args.vvp,
                               "reference_sampling": args.reference_sampling},
            on_round=lambda row: print(json.dumps({"round": row["round"], **row["observation"]}, ensure_ascii=False), flush=True),
        )
        print(STOP_LABELS[result.stop_reason])
        print(f"Trajectory: {result.trajectory_path}")
        # 0 只代表流程完成；有反例与未见反例必须查看 stop_reason，不把两者混为通过。
        return 0 if result.stop_reason in {"counterexample_found", "model_stopped", "round_budget", "request_budget", "cycle_budget", "vector_budget"} else 1
    except Exception as exc:
        print(f"Agent failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
