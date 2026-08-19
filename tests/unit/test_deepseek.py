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
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": candidate}}]},
        )

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-test",
    )
    model = DeepSeekChatModel(settings, transport=httpx.MockTransport(handler))
    await model.start()

    content = await model.generate_candidate(
        text="规则文本",
        candidate_schema={"type": "object"},
        field_catalog={},
        feedback=(),
    )
    await model.close()

    assert content == candidate


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
        )

    assert caught.value.issue.code is ParseErrorCode.PROVIDER_RATE_LIMITED
    assert caught.value.issue.retryable is True
