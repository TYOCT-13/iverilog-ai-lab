"""本地调试模型服务的回归测试：完全离线、不需要任何 API Key。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from iverilog_ai.ai.debug_provider import DeterministicLocalProvider, bundled_contract, known_designs
from iverilog_ai.ai.debug_server import build_plan_response, create_server, extract_request
from iverilog_ai.ai.provider import OpenAICompatibleProvider
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.rules import rules_context

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


def test_chat_endpoint_returns_real_stimulus_for_the_real_prompt_shape(debug_server):
    """真实提示词形状下，HTTP 端点也必须返回**带激励**的计划。

    这是网页"本地调试模型"走的路径：以前合约解析失败会导致每条向量 inputs 为空，
    生成的 testbench 什么都不驱动，仿真却报"通过"。
    """

    port = debug_server.server_address[1]
    body = _post(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        {"model": "debug-local", "messages": [{"role": "user", "content": _realistic_prompt("mod10_counter")}]},
    )
    plan = TestPlan.model_validate(json.loads(body["choices"][0]["message"]["content"]))
    assert plan.design == "mod10_counter"
    assert plan.vectors
    assert all(vector.inputs for vector in plan.vectors), "端到端返回的计划里存在无激励向量"


# --------------------------------------------------------------------------
# 真实提示词形状：离线路径必须真的驱动 DUT
#
# 上面那些用例喂的是 `DUT context: {json} Schema:` 这种**简化**形状，而真实调用方
# （网页、实验脚本、run_pipeline_matrix）传给 `plan_tests` 的 context 是
# `rules_context(...)` 的产物：规则文本在前，合约以 `--- DUT contract ---` 标记附在
# 末尾。旧实现只用非贪婪正则匹配前者，于是真实路径上合约解析为 `{}`——生成出来的
# 计划每条向量的 `inputs` 都是空的：计划合法、仿真"通过"，但**什么都没测**。
# 下面这些用例把"真实形状"钉死。
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]

#: 自定义设计（不在内置案例里）的合约：用于验证"显式合约仍然可生成计划"。
CUSTOM_CONTRACT = {
    "module": "wide_enable",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "enable", "direction": "input", "width": 8},
        {"name": "count", "direction": "output", "width": 8},
    ],
    "clock": {"signal": "clk", "period_ns": 10},
    "reset": {"signal": "rst_n", "active_level": 0, "synchronous": False, "assert_cycles": 2},
}


def _realistic_prompt(case: str) -> str:
    """按 `plan_tests` 的真实拼法构造提示词（规则文本 + 末尾合约 + Schema）。"""

    contract = bundled_contract(case)
    assert contract.get("module") == case
    context, _manifest = rules_context(ROOT, case, contract)
    return (
        "Return JSON only. No markdown, commands, paths, or executable code. "
        "Design: %s Objective: cover reset and boundaries DUT context: %s Schema: {\"type\": \"object\"}"
        % (case, context)
    )


def test_extract_request_reads_contract_appended_after_rules():
    """合约附在规则文本之后时也必须解析出来（嵌套对象不能靠非贪婪正则）。"""

    design, contract = extract_request(_realistic_prompt("mod10_counter"))
    assert design == "mod10_counter"
    assert contract["module"] == "mod10_counter"
    assert len(contract["ports"]) == 4


def test_provider_without_explicit_fields_uses_the_prompt():
    """最自然的用法：只给 provider，别的都从提示词里取。"""

    provider = DeterministicLocalProvider(seed=0)
    plan = TestPlan.model_validate(json.loads(provider.generate(_realistic_prompt("mod10_counter"))))
    assert plan.design == "mod10_counter"
    assert plan.vectors
    # 每条向量都必须真的驱动端口，否则激励形同虚设
    assert all(vector.inputs for vector in plan.vectors), "存在没有任何激励的向量"
    assert any(vector.inputs.get("enable") == 1 for vector in plan.vectors)


def test_provider_falls_back_to_the_bundled_contract():
    """提示词里完全没有合约时，退回仓库自带的 `examples/<case>_contract.json`。"""

    provider = DeterministicLocalProvider(seed=0)
    payload = json.loads(provider.generate("Design: pwm Objective: duty boundaries Schema: {}"))
    assert payload["design"] == "pwm"
    assert all(vector["inputs"] for vector in payload["vectors"])


def test_debug_server_serves_static_review_advice_offline():
    """"本地调试模型"也要能回答静态审查复核请求（离线确定性建议）。

    否则网页在「本地调试模型」模式下点「让 AI 复核并给修复建议」会看到一条严格校验失败——
    而这件事本可以离线确定性完成。服务返回的建议必须**自报"非 AI 输出"**，
    并且只引用真实存在的规则 ID。
    """

    from iverilog_ai.ai.debug_server import build_advice_response
    from iverilog_ai.ai.review_advisor import StaticReviewAdvice, build_review_prompt
    from iverilog_ai.core.static_review import review_rtl_source

    review = review_rtl_source(
        "module m(input wire clk, input wire rst_n, output reg q);\n"
        "  always @(posedge clk or negedge rst_n) q = 1'b0;\n"
        "endmodule\n",
        filename="m.v",
    )
    prompt = build_review_prompt(review, include_snippets=False, design="m")
    payload = build_advice_response(prompt)
    advice = StaticReviewAdvice.model_validate(payload)  # 必须能过与真实模型同一套严格 Schema

    assert advice.assumptions and "非 AI" in advice.assumptions[0]
    assert advice.priorities, "有命中时必须给出优先级列表"
    known = {str(item["rule_id"]) for item in review["findings"]}
    assert {item.rule_id for item in advice.priorities} <= known
    # 未命中任何规则的文件也要能回答
    clean = review_rtl_source("`timescale 1ns/1ps\nmodule m(input wire clk); endmodule\n", filename="clean.v")
    clean_advice = StaticReviewAdvice.model_validate(
        build_advice_response(build_review_prompt(clean, design="m"))
    )
    assert clean_advice.priorities == []


def test_debug_server_rejects_a_prompt_without_advice_payload():
    """不是复核请求的提示词不能瞎答，要明确报错。"""

    from iverilog_ai.ai.debug_server import build_advice_response

    with pytest.raises(ValueError, match="not a static review advice request"):
        build_advice_response("Design: mod10_counter Objective: x Schema: {}")


def test_provider_rejects_an_unknown_design_loudly():
    """既没有合约、设计名也不在内置案例里时，必须报错。

    生成"合法但端口全空"的计划比报错危险得多：它会一路通过仿真，却什么都没测。
    反过来，只要调用方给了带输入端口的合约，就允许生成随机激励（下面的自定义
    合约用例正是这种用法）。
    """

    provider = DeterministicLocalProvider(seed=0)
    with pytest.raises(ValueError, match="cannot drive design"):
        provider.generate("Design: not_bundled DUT context: {} Schema: {}")


def test_custom_contract_without_bundled_case_is_allowed():
    """自定义设计 + 显式合约：依然可以生成计划（走随机激励路径）。"""

    provider = DeterministicLocalProvider(contract=CUSTOM_CONTRACT, design="wide_enable", seed=1)
    payload = json.loads(provider.generate(""))
    assert payload["design"] == "wide_enable"
    assert all(vector["inputs"] for vector in payload["vectors"])


@pytest.mark.parametrize("case", sorted(known_designs()))
def test_every_bundled_case_gets_real_stimulus_from_a_bare_provider(case):
    """15 个内置案例逐个验证：预算内必须有驱动真实端口名的激励。"""

    contract = bundled_contract(case)
    assert contract.get("module") == case
    input_ports = {
        str(port["name"]) for port in contract["ports"] if str(port.get("direction")) == "input"
    }
    clock = str((contract.get("clock") or {}).get("signal", ""))
    driveable = input_ports - {clock}

    provider = DeterministicLocalProvider(seed=0)
    plan = TestPlan.model_validate(json.loads(provider.generate(_realistic_prompt(case))))
    assert plan.design == case
    used: set[str] = set()
    for vector in plan.vectors:
        assert vector.inputs, f"{case} 存在无激励向量 {vector.name}"
        used |= set(vector.inputs)
    assert used, f"{case} 的激励没有驱动任何端口"
    assert used <= input_ports, f"{case} 的激励出现了非输入端口：{sorted(used - input_ports)}"
    assert used & driveable, f"{case} 的激励只碰了时钟"

