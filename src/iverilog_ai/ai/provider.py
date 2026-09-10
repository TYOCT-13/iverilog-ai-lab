"""受控模型 Provider；网络访问必须显式开启，密钥只保存在进程内。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from http.client import RemoteDisconnected
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class Provider(Protocol):
    def generate(self, prompt: str) -> str: ...


class ProviderHTTPError(RuntimeError):
    """不包含密钥或响应正文的远程 HTTP 错误。"""

    def __init__(self, status: int, *, retry_after: str | None = None) -> None:
        self.status = status
        self.retry_after = retry_after
        if status == 429:
            detail = "API 请求过多、账户额度不足，或该模型/分组当前没有可用配额"
            if retry_after:
                detail += f"；服务端建议等待 {retry_after} 秒"
        elif status == 401:
            detail = "API Key 无效或未被服务端接受"
        elif status == 403:
            detail = "API Key 没有访问该模型或接口的权限"
        elif status == 503:
            detail = "模型上游暂时不可用或服务端过载"
        else:
            detail = "远程模型服务请求失败"
        super().__init__(f"在线 API 返回 HTTP {status}：{detail}")


class ProviderConnectionError(RuntimeError):
    """远端在返回 HTTP 响应前关闭或重置连接。"""

    def __init__(self, detail: str = "对端在返回响应前关闭了连接") -> None:
        super().__init__(f"在线 API 连接失败：{detail}；请检查 Base URL、接口格式和网络代理")


@dataclass
class MockProvider:
    response: dict | None = None

    def generate(self, prompt: str) -> str:
        del prompt
        payload = self.response or {
            "schema_version": "1.0",
            "design": "demo",
            "objective": "boundary verification",
            "clock_period_ns": 10,
            "reset": {"active_low": True},
            "vectors": [
                {
                    "name": "reset",
                    "inputs": {"rst_n": 0},
                    "cycles": 2,
                    "expected": {},
                    "rationale": "exercise reset",
                }
            ],
            "assumptions": ["offline demo"],
        }
        return json.dumps(payload, ensure_ascii=False)


def _network_enabled() -> bool:
    return os.getenv("IVERILOG_AI_ALLOW_NETWORK") == "1"


def _is_loopback(host: str) -> bool:
    """判断主机名是否为本机回环地址。"""

    lowered = host.lower()
    return lowered in {"127.0.0.1", "localhost", "::1", "[::1]"}


def _base_url(value: str) -> str:
    """规范化 Base URL，并兼容用户误填的具体 API 路径。

    允许 ``https`` 与**回环地址上的 ``http``**：前者是真实模型服务，后者是本
    项目自带的离线调试模型服务。其他明文 ``http`` 一律拒绝，避免密钥或提示词
    通过非加密链路外发。
    """

    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("provider base_url must be an absolute URL without embedded credentials")
    if parsed.scheme == "http":
        if not _is_loopback(host):
            raise ValueError("provider base_url must use https (http is only allowed for loopback debug servers)")
    elif parsed.scheme != "https":
        raise ValueError("provider base_url must use https or a loopback http URL")
    path = parsed.path.rstrip("/")
    for suffix in ("/v1/responses", "/v1/chat/completions", "/v1/models", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _response_text(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("provider response must be a JSON object")
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    output = data.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    if chunks:
        return "".join(chunks)
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") if isinstance(message, dict) else None
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("provider response contains no output text") from exc
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        content = "".join(parts)
    if not content and isinstance(data.get("choices"), list) and data["choices"]:
        choice = data["choices"][0]
        if isinstance(choice, dict) and isinstance(choice.get("text"), str):
            content = choice["text"]
    if not content:
        # A few OpenAI-compatible proxies wrap the assistant message one level
        # deeper; inspect only conventional response text keys.
        for key in ("text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                content = value
                break
    if not isinstance(content, str) or not content.strip():
        keys = ", ".join(sorted(str(key) for key in data.keys()))
        finish_reason = None
        if isinstance(data.get("choices"), list) and data["choices"] and isinstance(data["choices"][0], dict):
            finish_reason = data["choices"][0].get("finish_reason")
        suffix = f", finish_reason: {finish_reason}" if finish_reason else ""
        raise ValueError(f"provider final output text is empty (response keys: {keys}{suffix})")
    return content


class OpenAICompatibleProvider:
    """OpenAI-compatible Responses/Chat Completions 客户端。"""

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 60,
        *,
        wire_api: Literal["responses", "chat_completions"] = "responses",
        reasoning_effort: str | None = "medium",
        max_output_tokens: int = 4096,
        allow_network: bool = False,
        store: bool = False,
    ) -> None:
        raw_url = endpoint or os.getenv("IVERILOG_AI_BASE_URL") or os.getenv("IVERILOG_AI_ENDPOINT", "")
        self.base_url = _base_url(raw_url) if raw_url else ""
        self.model = (model or os.getenv("IVERILOG_AI_MODEL", "")).strip()
        # 去掉复制粘贴时常见的首尾空白；密钥只保存在当前 provider 实例内。
        self.api_key = (api_key or os.getenv("IVERILOG_AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()
        self.timeout = float(timeout)
        self.wire_api = wire_api
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = int(max_output_tokens)
        self.allow_network = bool(allow_network)
        self.store = bool(store)
        # 回环地址上的调试模型服务是本地进程，不属于"外发网络请求"。
        self.is_loopback = _is_loopback((urlsplit(self.base_url).hostname or "") if self.base_url else "")
        # Ephemeral telemetry for experiment runners; never contains the API key.
        self.last_usage: dict[str, object] | None = None
        self.last_latency_ms: int | None = None
        if wire_api not in {"responses", "chat_completions"}:
            raise ValueError("wire_api must be responses or chat_completions")
        if reasoning_effort not in {None, "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported reasoning effort")
        if not 256 <= self.max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be in [256, 32768]")

    def request_diagnostics(self) -> dict[str, object]:
        """返回不含密钥的最终请求配置，便于网页端定位网关/协议问题。"""
        path = self._endpoint_path(self.wire_api)
        fields = ["model", "input", "stream"] if self.wire_api == "responses" else ["model", "messages", "stream", "response_format"]
        if self.wire_api == "responses":
            if self.store:
                fields.append("store")
            if self.max_output_tokens != 4096:
                fields.append("max_output_tokens")
            if self.reasoning_effort is not None:
                fields.append("reasoning")
        return {
            "base_url": self.base_url or None,
            "url": (self.base_url + path) if self.base_url else None,
            "wire_api": self.wire_api,
            "model": self.model or None,
            "request_fields": fields,
            "has_api_key": bool(self.api_key),
            "timeout_seconds": self.timeout,
        }

    def _endpoint_path(self, wire_api: str | None = None) -> str:
        """Return provider endpoint path; DeepSeek's official API omits /v1."""
        api = wire_api or self.wire_api
        try:
            host = (urlsplit(self.base_url).hostname or "").lower()
        except ValueError:
            host = ""
        prefix = "" if host == "api.deepseek.com" or host.endswith(".api.deepseek.com") else "/v1"
        if api == "models":
            return prefix + "/models"
        return prefix + ("/responses" if api == "responses" else "/chat/completions")

    def _request(self, path: str, *, body: dict | None = None) -> object:
        if not (self.allow_network or self.is_loopback or _network_enabled()):
            raise RuntimeError("network disabled; set IVERILOG_AI_ALLOW_NETWORK=1 explicitly")
        if not self.base_url or not self.model:
            raise RuntimeError("IVERILOG_AI_BASE_URL and IVERILOG_AI_MODEL are required")
        if not self.api_key:
            if not self.is_loopback:
                raise RuntimeError("an API key is required")
            # 本地调试服务不需要凭据；发送一个显然不是密钥的占位值，保证
            # 调试路径与真实路径走完全相同的请求构造代码。
            self.api_key = "debug-local-no-key"
        # 某些反向代理在 keep-alive 协商上不稳定；显式关闭连接可避免
        # “对端在返回响应前关闭了连接”的伪网络错误。
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self.api_key,
            "User-Agent": "iverilog-ai-lab/0.1",
            "Connection": "close",
        }
        payload = None
        method = "GET"
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            method = "POST"
        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                self.last_latency_ms = int((time.perf_counter() - started) * 1000)
                usage = data.get("usage") if isinstance(data, dict) else None
                self.last_usage = dict(usage) if isinstance(usage, dict) else None
                return data
        except HTTPError as exc:
            retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
            raise ProviderHTTPError(exc.code, retry_after=retry_after) from exc
        except URLError as exc:
            reason = str(exc.reason).lower()
            if "closed" in reason or "reset" in reason or "without response" in reason:
                raise ProviderConnectionError(f"{exc.reason}") from exc
            raise ProviderConnectionError(f"无法连接到服务端（{exc.reason}）") from exc
        except (ConnectionError, TimeoutError, BrokenPipeError) as exc:
            raise ProviderConnectionError(str(exc) or "连接被中断") from exc
        except RemoteDisconnected as exc:
            raise ProviderConnectionError() from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("provider returned invalid JSON") from exc

    def list_models(self) -> tuple[str, ...]:
        data = self._request(self._endpoint_path("models"))
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("model list response lacks data array")
        model_ids = {
            item["id"].strip()
            for item in data["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        }
        return tuple(sorted(model_ids))

    def generate(self, prompt: str) -> str:
        if self.wire_api == "responses":
            body: dict[str, object] = {
                "model": self.model,
                "input": prompt,
                "stream": False,
            }
            # 仅在调用方明确选择时发送可选字段；默认最小请求兼容更多网关。
            if self.store:
                body["store"] = True
            if self.max_output_tokens != 4096:
                body["max_output_tokens"] = self.max_output_tokens
            if self.reasoning_effort is not None:
                body["reasoning"] = {"effort": self.reasoning_effort}
            return _response_text(self._request(self._endpoint_path("responses"), body=body))
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        # OpenAI-compatible Chat Completions providers commonly support this
        # flag and it materially reduces prose/fenced responses for TestPlan.
        body["response_format"] = {"type": "json_object"}
        # DeepSeek-compatible gateways may reject an empty/unsupported
        # parameter; only send max_tokens when explicitly non-default.
        if self.max_output_tokens != 4096:
            body["max_tokens"] = self.max_output_tokens
        return _response_text(self._request(self._endpoint_path("chat_completions"), body=body))
