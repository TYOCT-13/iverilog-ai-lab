"""流式（SSE）请求路径的回归测试。

背景：部分 OpenAI 兼容网关**只**接受流式请求——非流式 POST 会被对端在返回
响应前直接断连。provider 的 ``stream="auto"`` 需要先试非流式、再自动回退到
SSE。这里用一个本地假网关验证三条路径，全部离线、不访问真实服务。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from iverilog_ai.ai.provider import (
    OpenAICompatibleProvider,
    ProviderConnectionError,
    _sse_text,
)


# --------------------------------------------------------------------------
# SSE 解析
# --------------------------------------------------------------------------
def test_sse_text_parses_chat_completions_deltas():
    raw = (
        b'data: {"choices":[{"delta":{"content":"{\\"a\\":"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"1}"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert _sse_text(raw, wire_api="chat_completions") == '{"a":1}'


def test_sse_text_parses_responses_deltas():
    raw = b'data: {"delta":"hel"}\ndata: {"delta":"lo"}\ndata: [DONE]\n'
    assert _sse_text(raw, wire_api="responses") == "hello"


def test_sse_text_ignores_comments_blank_lines_and_bad_json():
    raw = b": keep-alive\n\ndata: not-json\n\ndata: {\"delta\":\"ok\"}\n\n"
    assert _sse_text(raw, wire_api="responses") == "ok"


def test_sse_text_handles_crlf_and_streaming_text_choice():
    raw = b'data: {"choices":[{"text":"abc"}]}\r\n\r\ndata: [DONE]\r\n\r\n'
    assert _sse_text(raw, wire_api="chat_completions") == "abc"


# --------------------------------------------------------------------------
# 请求构造
# --------------------------------------------------------------------------
def test_build_body_sets_stream_flag_per_mode():
    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1", model="m", api_key="k", wire_api="chat_completions"
    )
    assert provider._build_body("p", streaming=False)["stream"] is False
    assert provider._build_body("p", streaming=True)["stream"] is True
    responses = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1", model="m", api_key="k", wire_api="responses"
    )
    assert responses._build_body("p", streaming=True)["stream"] is True


def test_stream_argument_is_validated():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(endpoint="https://example.invalid/v1", model="m", api_key="k", stream="sometimes")


# --------------------------------------------------------------------------
# 本地假网关：非流式断连、流式返回 SSE
# --------------------------------------------------------------------------
class _FakeStreamingGateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen_stream_flags: list[bool] = []
    require_stream = True

    def log_message(self, *args):  # pragma: no cover - 静默
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        streaming = bool(body.get("stream"))
        type(self).seen_stream_flags.append(streaming)
        if type(self).require_stream and not streaming:
            # 模拟"网关只接受流式"：不给任何响应就断开连接
            self.wfile.flush()
            self.connection.close()
            return
        if streaming:
            chunks = [
                'data: {"choices":[{"delta":{"content":"{\\"schema_version\\":"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"\\"1.0\\"}"}}]}\n\n',
                "data: [DONE]\n\n",
            ]
            payload = "".join(chunks).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps({"choices": [{"message": {"content": '{"schema_version":"1.0"}'}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def gateway():
    _FakeStreamingGateway.seen_stream_flags = []
    _FakeStreamingGateway.require_stream = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeStreamingGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_auto_stream_falls_back_when_gateway_requires_streaming(gateway):
    provider = OpenAICompatibleProvider(
        endpoint=gateway, model="fake", api_key="k", wire_api="chat_completions", timeout=10, stream="auto"
    )
    text = provider.generate("hello")
    assert text == '{"schema_version":"1.0"}'
    # 先试非流式、再回退流式，因此网关应看到 [False, True]
    assert _FakeStreamingGateway.seen_stream_flags == [False, True]
    assert provider.last_stream_fallback is True


def test_non_streaming_mode_still_reports_connection_error(gateway):
    """默认模式不得悄悄改变行为：非流式失败仍然抛连接错误。"""

    provider = OpenAICompatibleProvider(
        endpoint=gateway, model="fake", api_key="k", wire_api="chat_completions", timeout=10
    )
    with pytest.raises(ProviderConnectionError):
        provider.generate("hello")
    assert _FakeStreamingGateway.seen_stream_flags == [False]


def test_explicit_streaming_mode_skips_the_probe(gateway):
    provider = OpenAICompatibleProvider(
        endpoint=gateway, model="fake", api_key="k", wire_api="chat_completions", timeout=10, stream=True
    )
    assert provider.generate("hello") == '{"schema_version":"1.0"}'
    assert _FakeStreamingGateway.seen_stream_flags == [True]
    assert provider.last_stream_fallback is False


def test_auto_stream_does_not_retry_when_non_streaming_works(gateway):
    _FakeStreamingGateway.require_stream = False
    provider = OpenAICompatibleProvider(
        endpoint=gateway, model="fake", api_key="k", wire_api="chat_completions", timeout=10, stream="auto"
    )
    assert provider.generate("hello") == '{"schema_version":"1.0"}'
    assert _FakeStreamingGateway.seen_stream_flags == [False]
    assert provider.last_stream_fallback is False
