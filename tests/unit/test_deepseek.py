from __future__ import annotations

import json

import httpx
import pytest
from tests.support import valid_candidate

from rule_reader.core.config import Settings
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError
from rule_reader.infrastructure.deepseek import DeepSeekChatModel


@pytest.mark.asyncio
async def test_deepseek_adapter_requests_json_without_leaking_contract() -> None:
    candidate = json.dumps(valid_candidate(), ensure_ascii=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert "Idempotency-Key" not in request.headers
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert body["stream"] is False
        system_prompt = body["messages"][0]["content"]
        assert "互斥分支" in system_prompt
        assert "R+0.1>=F" in system_prompt
        assert "严禁猜测物理表、字段、JOIN、筛选、聚合或时间范围" in system_prompt
        assert "不生成 SQL、数据库连接串、账号、密码" in system_prompt
        assert "allowedValues 永远是 JSON 数组" in system_prompt
        assert "禁止 condition kind=exists" in system_prompt
        assert "mutuallyExclusiveBranch" in system_prompt
        user_payload = json.loads(body["messages"][1]["content"])
        assert user_payload["retryFeedback"] == ["requiredFacts.0 requires parameters"]
        assert user_payload["previousCandidate"] == '{"incomplete":true}'
        return httpx.Response(
            200,
            json={
                "id": "deepseek-response-001",
                "choices": [{"message": {"content": candidate}}],
                "usage": {
                    "prompt_tokens": 101,
                    "completion_tokens": 23,
                    "total_tokens": 124,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 61,
                    "completion_tokens_details": {"reasoning_tokens": 7},
                },
            },
        )

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=httpx.MockTransport(handler))
    await model.start()

    generation = await model.generate_candidate(
        text="规则文本",
        candidate_schema={"type": "object"},
        field_catalog={},
        feedback=("requiredFacts.0 requires parameters",),
        previous_candidate='{"incomplete":true}',
    )
    await model.close()

    assert generation.content == candidate
    assert generation.provider_request_id == "deepseek-response-001"
    assert generation.token_usage is not None
    assert generation.token_usage.prompt_tokens == 101
    assert generation.token_usage.completion_tokens == 23
    assert generation.token_usage.total_tokens == 124
    assert generation.token_usage.prompt_cache_hit_tokens == 40
    assert generation.token_usage.prompt_cache_miss_tokens == 61
    assert generation.token_usage.reasoning_tokens == 7


@pytest.mark.asyncio
async def test_deepseek_rate_limit_is_retryable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429))
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=transport)

    with pytest.raises(RuleParsingError) as caught:
        await model.generate_candidate(
            text="规则文本",
            candidate_schema={},
            field_catalog={},
            feedback=(),
            previous_candidate=None,
        )

    assert caught.value.issue.code is ParseErrorCode.PROVIDER_RATE_LIMITED
    assert caught.value.issue.retryable is True


@pytest.mark.asyncio
async def test_deepseek_response_requires_provider_request_id() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )
    )
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=transport)

    with pytest.raises(RuleParsingError) as caught:
        await model.generate_candidate(
            text="规则文本",
            candidate_schema={},
            field_catalog={},
            feedback=(),
            previous_candidate=None,
        )

    assert caught.value.issue.code is ParseErrorCode.PROVIDER_RESPONSE_INVALID
    assert caught.value.issue.retryable is True


@pytest.mark.asyncio
async def test_deepseek_invalid_usage_is_omitted_without_rejecting_candidate() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": "deepseek-response-002",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {
                    "prompt_tokens": True,
                    "completion_tokens": 1,
                    "total_tokens": 1,
                },
            },
        )
    )
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=transport)

    generation = await model.generate_candidate(
        text="规则文本",
        candidate_schema={},
        field_catalog={},
        feedback=(),
        previous_candidate=None,
    )

    assert generation.content == "{}"
    assert generation.token_usage is None


@pytest.mark.asyncio
async def test_deepseek_v3_uses_explicit_prompt_and_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "v3-system"
        assert json.loads(body["messages"][1]["content"]) == {"task": "v3"}
        return httpx.Response(
            200,
            json={
                "id": "deepseek-v3-001",
                "choices": [{"message": {"content": "{}"}}],
            },
        )

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=httpx.MockTransport(handler))
    generation = await model.generate_rule_structure_v3(
        system_prompt="v3-system", user_payload={"task": "v3"}
    )
    await model.close()
    assert generation.content == "{}"
    assert generation.provider_request_id == "deepseek-v3-001"
