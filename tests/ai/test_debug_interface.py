"""本地调试模型服务的回归测试：完全离线、不需要任何 API Key。"""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from iverilog_ai.ai.debug_provider import DeterministicLocalProvider
from iverilog_ai.ai.debug_server import build_plan_response, create_server, extract_request
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan

CONTRACT = {
    "module": "mod10_counter",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "enable", "direction": "input", "width": 1},
        {"name": "count", "direction": "output", "width": 4, "initial": 0},
    ],
    "clock": {"signal": "clk", "period_ns": 10},
    "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
}

PROMPT = (
    "Return JSON only. Design: mod10_counter Objective: offline debug "
    "DUT context: " + json.dumps(CONTRACT) + " Schema: {}"
)


# --------------------------------------------------------------------------
# 计划生成
# --------------------------------------------------------------------------
def test_debug_plan_is_schema_valid_and_reaches_wraparound():
    plan = TestPlan.model_validate(build_plan_response(PROMPT, vector_count=24, seed=0))
    assert plan.design == "mod10_counter"
    # 24 个向量 + 复位向量 + 4 个边界向量
    assert len(plan.vectors) == 29
    # 复位前观测由 contract 的 initial 启用
    assert plan.sample_before_reset is True
    assert plan.pre_reset_expected == {"count": 0}
    # 必须存在 enable=1 的连续周期，否则计数器永远走不到回绕点
    assert sum(1 for vector in plan.vectors if vector.inputs.get("enable") == 1) >= 15


RANDOM_CONTRACT = {
    # enable 声明为 8 位：没有候选取值表，只能走随机路径，因此对种子敏感。
    "module": "wide_enable",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "enable", "direction": "input", "width": 8},
        {"name": "count", "direction": "output", "width": 8, "initial": 0},
    ],
    "clock": {"signal": "clk", "period_ns": 10},
    "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
}

RANDOM_PROMPT = "Design: mod10_counter DUT context: " + json.dumps(CONTRACT) + " Schema: {}"


def test_debug_plan_is_deterministic_for_same_seed():
    """同一 seed 必须产生逐字节相同的计划；时钟绝不进入激励。"""

    first = build_plan_response(RANDOM_PROMPT, vector_count=8, seed=3)
    second = build_plan_response(RANDOM_PROMPT, vector_count=8, seed=3)
    assert first == second, "same seed must produce byte-identical plans"
    for vector in first["vectors"]:
        assert "clk" not in vector["inputs"]


def test_debug_provider_seed_changes_random_stimulus():
    """没有候选取值表的端口走随机路径，必须对种子敏感。"""

    contract = {
        "module": "wide_enable",
        "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst_n", "direction": "input", "width": 1},
            {"name": "enable", "direction": "input", "width": 8},
            {"name": "count", "direction": "output", "width": 8},
        ],
        "clock": {"signal": "clk", "period_ns": 10},
    }
    first = json.loads(DeterministicLocalProvider(contract=contract, design="wide_enable", seed=3).generate(""))
    second = json.loads(DeterministicLocalProvider(contract=contract, design="wide_enable", seed=4).generate(""))
    assert first["vectors"] != second["vectors"]


def test_out_of_range_mode_never_drives_the_clock():
    provider = DeterministicLocalProvider(contract=CONTRACT, design="mod10_counter", mode="out_of_range")
    payload = json.loads(provider.generate(""))
    driven = payload["vectors"][0]["inputs"]
    assert "clk" not in driven
    assert all(value > 1 for value in driven.values())


def test_debug_provider_negative_modes_are_schema_invalid_or_out_of_range():
    provider = DeterministicLocalProvider(contract=CONTRACT, design="mod10_counter", mode="invalid_json")
    with pytest.raises(json.JSONDecodeError):
        json.loads(provider.generate(""))
    provider = DeterministicLocalProvider(contract=CONTRACT, design="mod10_counter", mode="out_of_range")
    payload = json.loads(provider.generate(""))
    assert payload["vectors"][0]["inputs"]["enable"] > 1

    provider = DeterministicLocalProvider(contract=CONTRACT, design="mod10_counter", mode="empty")
    assert provider.generate("") == ""


def test_extract_request_reads_design_and_contract():
    design, contract = extract_request(PROMPT)
    assert design == "mod10_counter"
    assert contract["module"] == "mod10_counter"


def test_unknown_design_is_rejected():
    with pytest.raises(ValueError):
        build_plan_response("Design: not_a_real_design DUT context: {} Schema: {}", vector_count=4, seed=0)
    with pytest.raises(ValueError):
        build_plan_response("no design field here", vector_count=4, seed=0)


# --------------------------------------------------------------------------
# HTTP 服务与真实客户端对接
# --------------------------------------------------------------------------
@pytest.fixture()
def debug_server():
    server = create_server("127.0.0.1", 0, vector_count=6)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url: str, payload: dict) -> dict:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def test_chat_completions_endpoint_returns_schema_valid_plan(debug_server):
    port = debug_server.server_address[1]
    body = _post(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        {"model": "debug-local", "messages": [{"role": "user", "content": PROMPT}]},
    )
    content = body["choices"][0]["message"]["content"]
    plan = TestPlan.model_validate(json.loads(content))
    assert plan.design == "mod10_counter"
    assert body["usage"]["debug_local"] is True


def test_responses_endpoint_returns_output_text(debug_server):
    port = debug_server.server_address[1]
    body = _post(
        f"http://127.0.0.1:{port}/v1/responses",
        {"model": "debug-local", "input": PROMPT},
    )
    assert isinstance(body["output_text"], str)
    TestPlan.model_validate(json.loads(body["output_text"]))


def test_models_endpoint_lists_debug_models(debug_server):
    port = debug_server.server_address[1]
    with urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert {item["id"] for item in payload["data"]} >= {"debug-local", "debug-local-invalid-json"}


def test_health_endpoint_is_offline(debug_server):
    port = debug_server.server_address[1]
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "ok"
    assert payload["offline"] is True


def test_unknown_design_returns_http_400(debug_server):
    port = debug_server.server_address[1]
    with pytest.raises(HTTPError) as excinfo:
        _post(f"http://127.0.0.1:{port}/v1/chat/completions", {"model": "debug-local", "messages": [{"role": "user", "content": "Design: nope DUT context: {} Schema: {}"}]})
    assert excinfo.value.code == 400


def test_provider_reaches_debug_server_without_api_key(debug_server):
    """关键能力：不需要 API Key，也不需要允许出站网络。"""

    port = debug_server.server_address[1]
    provider = OpenAICompatibleProvider(
        endpoint=f"http://127.0.0.1:{port}/v1",
        model="debug-local",
        wire_api="chat_completions",
        reasoning_effort=None,
        timeout=10,
        allow_network=False,
    )
    assert provider.is_loopback is True
    raw = provider.generate(PROMPT)
    plan = TestPlan.model_validate(json.loads(raw))
    assert plan.vectors
    assert provider.last_usage is not None


def test_provider_still_requires_key_and_https_for_remote_hosts():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(endpoint="http://example.com/v1", model="m", api_key="k", allow_network=True)
    remote = OpenAICompatibleProvider(endpoint="https://example.com/v1", model="m", allow_network=False)
    with pytest.raises(RuntimeError):
        remote.generate("hello")


def test_debug_server_refuses_non_loopback_bind():
    with pytest.raises(ValueError):
        create_server("0.0.0.0", 0)
