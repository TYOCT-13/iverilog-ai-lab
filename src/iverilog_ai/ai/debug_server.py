"""本地调试模型服务：OpenAI 兼容接口，仅监听回环地址，不需要 API Key。

它把 :class:`DeterministicLocalProvider` 包成一个 HTTP 服务，让网页、CLI 和
实验脚本可以像访问真实模型一样访问它：

``http://127.0.0.1:11434/v1``

服务**只**绑定回环地址，不转发任何出站流量，也不读取任何密钥。它存在的意义
是让整条流水线（含"在线"代码路径）在没有凭据的情况下可测试、可复现；
它不代表任何真实模型能力，不能用于宣称 AI 效果。

用法::

    python -m iverilog_ai.ai.debug_server --port 11434
    # 另一个终端
    python -m iverilog_ai plan-run --debug-local --plan-from-contract \\
        --contract examples/mod10_counter_contract.json --rtl rtl/mod10_counter.v
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .debug_provider import (
    _DEFAULT_VECTOR_COUNT,
    DeterministicLocalProvider,
    extract_request,
    known_designs,
)

_DEBUG_BASE_URL = "http://127.0.0.1"
SERVER_NAME = "iverilog-ai-lab debug model (deterministic, offline)"

# 调试服务只服务这些内置案例；未知设计返回 400，避免被当成通用模型。
# 名单直接取自 Provider 的激励表（而不是再手写一份），避免两份名单漂移。
KNOWN_DESIGNS = known_designs()


def build_plan_response(text: str, *, vector_count: int, seed: int) -> dict[str, Any]:
    """把一次"模型请求"映射为确定性 TestPlan（字典形式）。"""

    design, contract = extract_request(text)
    if not design:
        raise ValueError("request does not name a Design; the debug server only serves bundled examples")
    if design not in KNOWN_DESIGNS:
        raise ValueError(f"unknown design {design!r}; the debug server only serves bundled examples")
    provider = DeterministicLocalProvider(contract=contract, design=design, vector_count=vector_count, seed=seed)
    plan = json.loads(provider.generate(""))
    return plan


#: 静态审查复核请求的标识（`ai/review_advisor.py` 的提示词里固定带这一句）。
_ADVICE_MARKER = "Required JSON shape: {\"summary\""


def _advice_request_payload(text: str) -> dict[str, Any] | None:
    """从静态审查复核提示词里取出输入载荷（``Input:`` 之后那个 JSON 对象）。

    为什么调试服务也要认这种请求：网页的「本地调试模型」是"整条链路可离线演示"的入口，
    如果它只会答测试计划，用户点了「让 AI 复核并给修复建议」就会看到一条校验失败——
    而离线模式下这件事本可以确定性完成（按规则表排序）。因此这里让服务返回**离线建议**，
    内容与 `offline_review_advice()` 同源，并在 assumptions 里写明"非 AI 输出"。
    """

    marker = text.find("Input:")
    while marker != -1:
        brace = text.find("{", marker)
        if brace != -1:
            depth = 0
            in_string = False
            escaped = False
            for index in range(brace, len(text)):
                char = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[brace : index + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict) and "rule_hits" in parsed:
                            return parsed
                        break
        marker = text.find("Input:", marker + 1)
    return None


def build_advice_response(text: str) -> dict[str, Any]:
    """把一次静态审查复核请求映射为确定性建议（离线，不调用任何模型）。"""

    from pydantic import ValidationError

    from .review_advisor import _LEVEL_BY_SEVERITY, ReviewPriority, StaticReviewAdvice  # noqa: PLC0415

    payload = _advice_request_payload(text)
    if payload is None:
        raise ValueError("request is not a static review advice request")
    hits = [item for item in (payload.get("rule_hits") or []) if isinstance(item, dict)]
    counts = payload.get("counts") or {}
    ordered = sorted(hits, key=lambda item: ({"error": 0, "warn": 1, "info": 2}.get(str(item.get("severity")), 3), int(item.get("line") or 0)))
    priorities = [
        ReviewPriority(
            rule_id=str(item.get("rule_id")),
            line=int(item["line"]) if item.get("line") else None,
            level=_LEVEL_BY_SEVERITY.get(str(item.get("severity")), "consider"),
            why=f"规则 `{item.get('rule_id')}` 在本次审查中命中（严重度 {item.get('severity')}）",
            fix="按该规则的说明修改；具体做法见规则表与页面上的问题描述。",
        )
        for item in ordered[:20]
    ]
    advice = StaticReviewAdvice(
        summary=(
            f"离线复核：共 {len(hits)} 条命中（错误 {counts.get('error', 0)} / 警告 {counts.get('warn', 0)} / "
            f"提示 {counts.get('info', 0)}），按严重度从高到低排列。"
            if hits
            else "离线复核：当前规则集没有命中任何问题。"
        ),
        priorities=priorities,
        assumptions=["本建议由本地调试服务的确定性规则生成（非 AI 输出）：不做跨条目归纳，也不判断误报。"],
    )
    try:
        advice = StaticReviewAdvice.model_validate(advice.model_dump(mode="json"))
    except ValidationError as exc:  # pragma: no cover - 结构固定，仅在字段契约变化时触发
        raise ValueError(f"offline advice payload is invalid: {exc}") from exc
    return advice.model_dump(mode="json")


class _Handler(BaseHTTPRequestHandler):
    server_version = "iverilog-ai-debug/0.1"
    protocol_version = "HTTP/1.1"

    # 由 create_server 注入
    vector_count = 12
    seed = 0

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - 仅终端噪声控制
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------
    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Debug-Model", SERVER_NAME)
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 2_000_000:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _prompt_text(body: dict[str, Any]) -> str:
        """兼容 Responses（``input``）与 Chat Completions（``messages``）两种请求形状。"""

        data = body.get("input")
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            parts = []
            for item in data:
                if isinstance(item, dict):
                    content = item.get("content")
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for chunk in content:
                            if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                                parts.append(chunk["text"])
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "\n".join(parts)
        messages = body.get("messages")
        if isinstance(messages, list):
            parts = []
            for item in messages:
                if isinstance(item, dict) and isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif isinstance(item, dict) and isinstance(item.get("content"), list):
                    for chunk in item["content"]:
                        if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                            parts.append(chunk["text"])
            if parts:
                return "\n".join(parts)
        return ""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/health", "/healthz"):
            self._send(200, {"status": "ok", "model": SERVER_NAME, "offline": True})
            return
        if path.endswith("/models"):
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "debug-local", "object": "model", "owned_by": "iverilog-ai-lab"},
                        {"id": "debug-local-invalid-json", "object": "model", "owned_by": "iverilog-ai-lab"},
                    ],
                },
            )
            return
        self._send(404, {"error": {"message": f"unsupported path {self.path}", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        path = self.path.split("?", 1)[0].rstrip("/")
        if not (path.endswith("/chat/completions") or path.endswith("/responses")):
            self._send(404, {"error": {"message": f"unsupported path {self.path}", "type": "invalid_request_error"}})
            return
        body = self._read_json()
        model = str(body.get("model") or "debug-local")
        text = self._prompt_text(body)
        mode = "invalid_json" if model.endswith("invalid-json") else "plan"
        try:
            if mode == "invalid_json":
                content = "{ this is deliberately not valid JSON"
            elif _ADVICE_MARKER in text:
                # 静态审查复核请求：确定性离线建议（见 build_advice_response 的说明）
                content = json.dumps(build_advice_response(text), ensure_ascii=False)
            else:
                plan = build_plan_response(text, vector_count=self.vector_count, seed=self.seed)
                content = json.dumps(plan, ensure_ascii=False)
        except ValueError as exc:
            self._send(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return
        usage = {
            "prompt_tokens": max(1, len(text) // 4),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": max(1, (len(text) + len(content)) // 4),
            "debug_local": True,
        }
        if path.endswith("/responses"):
            self._send(
                200,
                {
                    "id": "debug-local-response",
                    "object": "response",
                    "model": model,
                    "output_text": content,
                    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]}],
                    "usage": usage,
                },
            )
            return
        self._send(
            200,
            {
                "id": "debug-local-completion",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": usage,
            },
        )


class DebugModelServer(ThreadingHTTPServer):
    """带诊断开关的线程化 HTTP 服务。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, vector_count: int = _DEFAULT_VECTOR_COUNT, seed: int = 0, verbose: bool = False) -> None:
        self.vector_count = vector_count
        self.seed = seed
        self.verbose = verbose
        handler = type("_BoundHandler", (_Handler,), {"vector_count": vector_count, "seed": seed})
        super().__init__(address, handler)


def create_server(host: str = "127.0.0.1", port: int = 11434, *, vector_count: int = _DEFAULT_VECTOR_COUNT, seed: int = 0, verbose: bool = False) -> DebugModelServer:
    """创建（但不启动）调试模型服务；仅允许回环地址。"""

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("the debug model server may only bind to a loopback address")
    if not 0 <= port <= 65535:
        raise ValueError("port must be in [0, 65535]")
    if not 1 <= vector_count <= 200:
        raise ValueError("vector_count must be in [1, 200]")
    return DebugModelServer((host, port), vector_count=vector_count, seed=seed, verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline debug model server (no API key required).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--vector-count", type=int, default=_DEFAULT_VECTOR_COUNT, help="vectors per generated plan (1-200)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port, vector_count=args.vector_count, seed=args.seed, verbose=args.verbose)
    # server_address 的元素类型在 typeshed 里是宽松的（可能是 bytes），
    # 显式 str() 一次，避免 f-string 打出 b'127.0.0.1' 这种噪音。
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    base = f"http://{host}:{port}/v1"
    print(f"{SERVER_NAME}")
    print(f"listening on {base}")
    print("offline only: no outbound requests, no API key, deterministic plans")
    print("press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - 交互式中断
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
