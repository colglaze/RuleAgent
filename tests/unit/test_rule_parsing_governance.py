from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest
from tests.support import QueueModel, valid_candidate_v2

from rule_reader.application.rule_parsing.ports import CandidateGeneration
from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.domain.rules.audit import ProviderTokenUsage
from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError


class RecordingSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class BlockingQueueModel(QueueModel):
    def __init__(self, response: str) -> None:
        super().__init__([response])
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.provider_entries = 0

    async def generate_candidate(
        self,
        *,
        text: str,
        candidate_schema: dict[str, Any],
        field_catalog: dict[str, Any],
        feedback: tuple[str, ...],
        previous_candidate: str | None,
    ) -> CandidateGeneration:
        self.provider_entries += 1
        self.entered.set()
        await self.release.wait()
        return await super().generate_candidate(
            text=text,
            candidate_schema=candidate_schema,
            field_catalog=field_catalog,
            feedback=feedback,
            previous_candidate=previous_candidate,
        )


@pytest.mark.asyncio
async def test_retry_backoff_is_exponential_capped_and_audited() -> None:
    timeout = ParseIssue(
        ParseErrorCode.PROVIDER_TIMEOUT,
        "timeout",
        retryable=True,
    )
    model = QueueModel(
        [
            timeout,
            timeout,
            timeout,
            timeout,
            json.dumps(valid_candidate_v2(), ensure_ascii=False),
        ]
    )
    sleeper = RecordingSleeper()
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=4,
        retry_base_delay_seconds=0.5,
        retry_max_delay_seconds=1.0,
        sleeper=sleeper,
    )

    result = await service.parse_text("有效规则", source_name="test.md")

    assert sleeper.calls == [0.5, 1.0, 1.0, 1.0]
    assert result.parser.audit is not None
    audit = result.parser.audit
    assert audit.attempt_count == 5
    assert audit.total_backoff_seconds == 3.5
    assert [item.outcome_code for item in audit.attempts] == [
        "PROVIDER_TIMEOUT",
        "PROVIDER_TIMEOUT",
        "PROVIDER_TIMEOUT",
        "PROVIDER_TIMEOUT",
        "SUCCESS",
    ]
    assert [item.backoff_seconds for item in audit.attempts] == [
        0.0,
        0.5,
        1.0,
        1.0,
        1.0,
    ]


@pytest.mark.asyncio
async def test_non_retryable_error_never_sleeps_or_calls_again() -> None:
    model = QueueModel(
        [
            ParseIssue(
                ParseErrorCode.PROVIDER_AUTH_FAILED,
                "auth failed",
                retryable=False,
            )
        ]
    )
    sleeper = RecordingSleeper()
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=3,
        sleeper=sleeper,
    )

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text("有效规则", source_name="test.md")

    assert model.calls == 1
    assert sleeper.calls == []
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 1


@pytest.mark.asyncio
async def test_final_retryable_failure_does_not_schedule_extra_backoff() -> None:
    timeout = ParseIssue(
        ParseErrorCode.PROVIDER_TIMEOUT,
        "timeout",
        retryable=True,
    )
    model = QueueModel([timeout])
    sleeper = RecordingSleeper()
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=2,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=8.0,
        sleeper=sleeper,
    )

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text("有效规则", source_name="test.md")

    assert model.calls == 3
    assert sleeper.calls == [1.0, 2.0]
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 3


@pytest.mark.asyncio
async def test_token_usage_includes_invalid_candidate_attempts() -> None:
    first_usage = ProviderTokenUsage(
        prompt_tokens=100,
        completion_tokens=10,
        total_tokens=110,
        prompt_cache_hit_tokens=25,
    )
    second_usage = ProviderTokenUsage(
        prompt_tokens=80,
        completion_tokens=20,
        total_tokens=100,
        prompt_cache_hit_tokens=30,
        reasoning_tokens=4,
    )
    model = QueueModel(
        [
            CandidateGeneration(
                content="not-json",
                provider_request_id="provider-invalid-json",
                token_usage=first_usage,
            ),
            CandidateGeneration(
                content=json.dumps(valid_candidate_v2(), ensure_ascii=False),
                provider_request_id="provider-success",
                token_usage=second_usage,
            ),
        ]
    )
    sleeper = RecordingSleeper()
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=1,
        retry_base_delay_seconds=0.25,
        retry_max_delay_seconds=1.0,
        sleeper=sleeper,
    )

    result = await service.parse_text("有效规则", source_name="test.md")

    assert result.parser.audit is not None
    audit = result.parser.audit
    assert [item.outcome_code for item in audit.attempts] == [
        "CANDIDATE_JSON_INVALID",
        "SUCCESS",
    ]
    assert [item.provider_request_id for item in audit.attempts] == [
        "provider-invalid-json",
        "provider-success",
    ]
    assert audit.total_token_usage == ProviderTokenUsage(
        prompt_tokens=180,
        completion_tokens=30,
        total_tokens=210,
        prompt_cache_hit_tokens=55,
        reasoning_tokens=4,
    )


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_exact_success() -> None:
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)
    key = "parse-request-0001"

    first = await service.parse_text(
        "有效规则",
        source_name="test.md",
        idempotency_key=key,
    )
    second = await service.parse_text(
        "有效规则",
        source_name="test.md",
        idempotency_key=key,
    )

    assert model.calls == 1
    assert second is first
    assert second.rule_version == first.rule_version
    assert first.parser.audit is not None
    assert (
        first.parser.audit.idempotency_key_sha256 == hashlib.sha256(key.encode("ascii")).hexdigest()
    )
    assert key not in first.to_json()


@pytest.mark.asyncio
async def test_requests_without_idempotency_key_remain_independent() -> None:
    candidate = json.dumps(valid_candidate_v2(), ensure_ascii=False)
    model = QueueModel([candidate, candidate])
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)

    first = await service.parse_text("有效规则", source_name="test.md")
    second = await service.parse_text("有效规则", source_name="test.md")

    assert model.calls == 2
    assert first.parser.audit is not None
    assert second.parser.audit is not None
    assert first.parser.audit.request_id != second.parser.audit.request_id


@pytest.mark.asyncio
async def test_same_idempotency_key_with_different_request_conflicts() -> None:
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)
    key = "parse-request-0002"
    await service.parse_text(
        "第一条规则",
        source_name="test.md",
        idempotency_key=key,
    )

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text(
            "第二条规则",
            source_name="test.md",
            idempotency_key=key,
        )

    assert caught.value.issue.code is ParseErrorCode.IDEMPOTENCY_KEY_CONFLICT
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 0
    assert model.calls == 1


@pytest.mark.asyncio
async def test_failed_idempotent_request_can_be_retried() -> None:
    model = QueueModel(
        [
            ParseIssue(
                ParseErrorCode.PROVIDER_UNAVAILABLE,
                "unavailable",
                retryable=True,
            ),
            json.dumps(valid_candidate_v2(), ensure_ascii=False),
        ]
    )
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)
    key = "parse-request-0003"

    with pytest.raises(RuleParsingError):
        await service.parse_text(
            "有效规则",
            source_name="test.md",
            idempotency_key=key,
        )
    result = await service.parse_text(
        "有效规则",
        source_name="test.md",
        idempotency_key=key,
    )

    assert result.rule.rule_id == "TEST_RELEASE_002"
    assert model.calls == 2


@pytest.mark.asyncio
async def test_idempotency_cache_uses_bounded_lru() -> None:
    candidate = json.dumps(valid_candidate_v2(), ensure_ascii=False)
    model = QueueModel([candidate, candidate, candidate])
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=0,
        idempotency_cache_max_entries=1,
    )

    await service.parse_text(
        "第一条规则",
        source_name="test.md",
        idempotency_key="parse-request-lru-1",
    )
    await service.parse_text(
        "第二条规则",
        source_name="test.md",
        idempotency_key="parse-request-lru-2",
    )
    await service.parse_text(
        "第一条规则",
        source_name="test.md",
        idempotency_key="parse-request-lru-1",
    )

    assert model.calls == 3


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_shares_inflight_provider_call() -> None:
    model = BlockingQueueModel(json.dumps(valid_candidate_v2(), ensure_ascii=False))
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)
    key = "parse-request-concurrent"

    first = asyncio.create_task(
        service.parse_text(
            "有效规则",
            source_name="test.md",
            idempotency_key=key,
        )
    )
    await model.entered.wait()
    second = asyncio.create_task(
        service.parse_text(
            "有效规则",
            source_name="test.md",
            idempotency_key=key,
        )
    )
    await asyncio.sleep(0)
    assert model.provider_entries == 1

    model.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert model.calls == 1
    assert first_result is second_result


@pytest.mark.asyncio
async def test_inflight_idempotency_key_rejects_different_request() -> None:
    model = BlockingQueueModel(json.dumps(valid_candidate_v2(), ensure_ascii=False))
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)
    key = "parse-request-inflight-conflict"
    first = asyncio.create_task(
        service.parse_text(
            "第一条规则",
            source_name="test.md",
            idempotency_key=key,
        )
    )
    await model.entered.wait()

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text(
            "第二条规则",
            source_name="test.md",
            idempotency_key=key,
        )

    assert caught.value.issue.code is ParseErrorCode.IDEMPOTENCY_KEY_CONFLICT
    assert model.provider_entries == 1
    model.release.set()
    await first


@pytest.mark.asyncio
async def test_invalid_idempotency_key_fails_before_provider_call() -> None:
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text(
            "有效规则",
            source_name="test.md",
            idempotency_key="bad key",
        )

    assert caught.value.issue.code is ParseErrorCode.IDEMPOTENCY_KEY_INVALID
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 0
    assert model.calls == 0
    assert "bad key" not in json.dumps(caught.value.issue.to_dict())
