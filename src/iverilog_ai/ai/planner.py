"""Safe planner orchestration with bounded validation retries."""
import json
import re
from .provider import MockProvider, Provider, ProviderHTTPError, ProviderConnectionError
from .schema import TestPlan, json_schema
class PlanningError(ValueError): pass


def _failure_payload(failure: object) -> dict:
    """Return a bounded, JSON-safe failure representation for the model prompt.

    Failure records can come from either the dataclass model or the UI's plain
    dictionaries.  We deliberately copy only diagnostic fields; command lines,
    paths and raw process output are never sent to the provider.
    """
    if isinstance(failure, dict):
        source = failure
        return {
            key: source.get(key)
            for key in ("test_id", "cycle", "signal", "expected", "actual", "message", "severity")
            if key in source
        }
    result: dict = {}
    for key in ("test_id", "cycle", "signal", "expected", "actual", "message", "severity"):
        if hasattr(failure, key):
            result[key] = getattr(failure, key)
    return result


def _merge_additional_vectors(plan: TestPlan, additions: list[dict], *, max_new_vectors: int) -> TestPlan:
    """Merge model-proposed vectors while preserving existing vector names.

    New names are made unique deterministically (``foo_2``/``foo_3``), and the
    final object is passed through the same strict Pydantic validator as an
    initial plan.  This keeps the feedback loop from bypassing the TestPlan
    safety boundary.
    """
    if len(additions) > max_new_vectors:
        raise ValueError(f"model proposed {len(additions)} vectors; limit is {max_new_vectors}")
    data = plan.model_dump(mode="json")
    vectors = list(data.get("vectors", []))
    used = {item.get("name") for item in vectors if isinstance(item, dict)}
    counters: dict[str, int] = {}
    normalized: list[dict] = []
    for raw in additions:
        if not isinstance(raw, dict):
            raise TypeError("additional vector must be an object")
        item = dict(raw)
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("additional vector.name must be a non-empty string")
        base = raw_name.strip()
        candidate = base
        index = counters.get(base, 1)
        while candidate in used:
            index += 1
            candidate = f"{base}_{index}"
        counters[base] = index
        item["name"] = candidate
        used.add(candidate)
        normalized.append(item)
    data["vectors"] = vectors + normalized
    return TestPlan.model_validate(data)

def _decode_plan_json(raw: str) -> dict:
    """Decode strict JSON while tolerating a fenced JSON answer from a model."""
    candidates = [raw.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    # Some gateways prepend a short sentence despite the JSON-only instruction.
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            raise TypeError("top-level JSON must be an object")
        except (json.JSONDecodeError, TypeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error

def _unique_vector_names(data: dict) -> dict:
    """确定性修复模型常见的重复向量名，不改变激励或期望值。"""
    vectors = data.get("vectors")
    if not isinstance(vectors, list):
        return data
    seen: dict[str, int] = {}
    normalized = dict(data)
    normalized_vectors = []
    for index, raw in enumerate(vectors, start=1):
        if not isinstance(raw, dict):
            normalized_vectors.append(raw)
            continue
        item = dict(raw)
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            base = name.strip()
            count = seen.get(base, 0) + 1
            seen[base] = count
            if count > 1:
                item["name"] = f"{base}_{count}"
        normalized_vectors.append(item)
    normalized["vectors"] = normalized_vectors
    return normalized

def _normalize_reset(data: dict) -> dict:
    """Normalize common model reset shorthand into the strict reset schema."""
    reset = data.get("reset")
    if not isinstance(reset, dict):
        return data
    allowed = {"signal", "active_level", "active_low", "synchronous", "assert_cycles"}
    extra = [key for key in reset if key not in allowed]
    if not extra:
        return data
    normalized = dict(data)
    clean = {key: value for key, value in reset.items() if key in allowed}
    # Models sometimes emit {"sys_rst_n": 0, "active_level": 0, ...}.
    # Infer the signal only when exactly one safe-looking extra key exists.
    if "signal" not in clean and len(extra) == 1 and isinstance(extra[0], str):
        clean["signal"] = extra[0]
    normalized["reset"] = clean
    return normalized

def plan_tests(
    objective: str,
    design: str,
    provider: Provider | None = None,
    max_retries: int = 2,
    *,
    context: str | None = None,
) -> TestPlan:
    if max_retries < 0 or max_retries > 5: raise ValueError("max_retries must be between 0 and 5")
    if context is not None and (not isinstance(context, str) or len(context) > 20_000):
        raise ValueError("context must be text of at most 20000 characters")
    prompt=(
        "Return JSON only. No markdown, commands, paths, or executable code. "
        "Create concrete input vectors and expected outputs that obey the DUT contract. "
        "Every checked behavior must use expected output fields. "
        "Every vector.name MUST be unique; use short ASCII identifiers such as reset_1, normal_1, boundary_1. "
        "Reset MUST be an object with only signal, active_level or active_low, synchronous, and assert_cycles; "
        "put the reset port name in reset.signal (for example signal=sys_rst_n), never as a separate reset key. "
        "You may include an assertions array using only signal_equals, signal_stable, never_high, signal_sequence, or signal_implies templates; never include Verilog/SVA code. "
        "Design: %s Objective: %s DUT context: %s Schema: %s"
        % (design, objective, context or "not supplied", json.dumps(json_schema()))
    )
    errors=[]
    for attempt in range(max_retries+1):
        try:
            raw=(provider or MockProvider()).generate(prompt)
            if not isinstance(raw,str): raise TypeError("provider output must be text")
            data = _decode_plan_json(raw)
            return TestPlan.model_validate(_normalize_reset(_unique_vector_names(data)))
        except (ProviderHTTPError, ProviderConnectionError):
            # 认证、额度和限流问题不是测试计划格式错误；立即向上层报告，
            # 避免自动重试产生更多请求或费用。
            raise
        except Exception as exc: errors.append("attempt %d: %s" % (attempt+1,exc))
    raise PlanningError("模型已返回内容，但 TestPlan 严格校验失败：" + " | ".join(errors))


def supplement_tests(
    plan: TestPlan,
    failures: list[object] | tuple[object, ...],
    provider: Provider | None = None,
    *,
    context: str | None = None,
    max_new_vectors: int = 20,
    max_retries: int = 0,
) -> TestPlan:
    """Ask the model for bounded additional vectors after a failed simulation.

    This is an explicit, one-shot operation; callers decide whether to run the
    returned plan again.  No automatic pipeline retry is performed here.
    """
    if not isinstance(plan, TestPlan):
        raise TypeError("plan must be an ai.schema.TestPlan")
    if not isinstance(failures, (list, tuple)):
        raise TypeError("failures must be a list or tuple")
    if not failures:
        raise ValueError("at least one simulation failure is required")
    if len(failures) > 50:
        raise ValueError("failures must contain at most 50 records")
    if not 1 <= max_new_vectors <= 100:
        raise ValueError("max_new_vectors must be between 1 and 100")
    if not 0 <= max_retries <= 2:
        raise ValueError("max_retries must be between 0 and 2")
    failure_items = [_failure_payload(item) for item in failures]
    prompt = (
        "Return JSON only in the form {\"vectors\":[...]} with additional "
        "test vectors that target the observed failures. Do not return the full "
        "plan, prose, commands, paths, or executable code. Every vector.name "
        "must be unique and must not reuse existing names. Keep vectors within "
        f"the schema and propose at most {max_new_vectors} vectors.\n"
        "Existing TestPlan:\n" + json.dumps(plan.model_dump(mode="json"), ensure_ascii=False) +
        "\nObserved failures (diagnostic fields only):\n" + json.dumps(failure_items, ensure_ascii=False, default=str) +
        "\nAdditional DUT context:\n" + (context or "not supplied") +
        "\nVector schema:\n" + json.dumps(json_schema().get("$defs", {}).get("TestVector", {}), ensure_ascii=False)
    )
    errors: list[str] = []
    for attempt in range(max_retries + 1):
        try:
            raw = (provider or MockProvider()).generate(prompt)
            if not isinstance(raw, str):
                raise TypeError("provider output must be text")
            data = _decode_plan_json(raw)
            additions = data.get("vectors")
            if not isinstance(additions, list) or not additions:
                raise ValueError("provider response must contain a non-empty vectors array")
            return _merge_additional_vectors(plan, additions, max_new_vectors=max_new_vectors)
        except (ProviderHTTPError, ProviderConnectionError):
            raise
        except Exception as exc:
            errors.append("attempt %d: %s" % (attempt + 1, exc))
    raise PlanningError("AI 补充测试计划严格校验失败：" + " | ".join(errors))
