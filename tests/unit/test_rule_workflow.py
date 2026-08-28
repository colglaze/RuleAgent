from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from tests.support import QueueModel, valid_candidate_v2

from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError


@pytest.mark.asyncio
async def test_workflow_builds_trusted_version_and_json() -> None:
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])

    def clock() -> datetime:
        return datetime(2026, 8, 18, 1, 2, 3, 456789, tzinfo=UTC)

    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=0,
        clock=clock,
    )
    text = "  # 测试规则\r\n任务完成后释放。  "

    await service.start()
    result = await service.parse_text(text, source_name="test.md")
    await service.close()

    normalized = "# 测试规则\n任务完成后释放。"
    expected_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    assert result.source.sha256 == expected_hash
    assert result.rule_version == (f"TEST_RELEASE_002@20260818T010203456789Z-{expected_hash[:12]}")
    assert result.status == "draft"
    assert result.executable is False
    assert result.parser.parser_version == "0.10.0"
    assert result.parser.prompt_version == "rule-parser-v6"
    assert result.parser.audit is not None
    assert result.parser.audit.attempt_count == 1
    assert result.parser.audit.attempts[0].outcome_code == "SUCCESS"
    assert result.parser.audit.attempts[0].provider_request_id == "fake-request-1"
    assert json.loads(result.to_json())["ruleVersion"] == result.rule_version
    assert model.started == 1
    assert model.closed == 1


@pytest.mark.asyncio
async def test_invalid_json_is_retried_with_feedback() -> None:
    model = QueueModel(
        [
            "not-json",
            json.dumps(valid_candidate_v2(), ensure_ascii=False),
        ]
    )
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=1,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )

    result = await service.parse_text("有效规则文本", source_name="test.md")

    assert result.rule.rule_id == "TEST_RELEASE_002"
    assert model.calls == 2
    assert "complete JSON object" in model.feedback[1][0]
    assert model.previous_candidates == [None, "not-json"]


@pytest.mark.asyncio
async def test_schema_retry_feedback_includes_all_fact_parameter_errors() -> None:
    invalid = valid_candidate_v2()
    template = invalid["requiredFacts"][0]
    invalid["requiredFacts"] = [
        {
            **template,
            "factCode": f"task.missing_parameter_{index}",
            "parameters": [],
        }
        for index in range(75)
    ]
    model = QueueModel(
        [
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(valid_candidate_v2(), ensure_ascii=False),
        ]
    )
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=1,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )

    result = await service.parse_text("有效规则文本", source_name="test.md")

    assert result.rule.rule_id == "TEST_RELEASE_002"
    assert len(model.feedback[1]) == 75
    assert all("require parameters" in item for item in model.feedback[1])
    assert model.previous_candidates[0] is None
    assert model.previous_candidates[1] == json.dumps(invalid, ensure_ascii=False)


@pytest.mark.asyncio
async def test_semantic_failure_stops_after_configured_attempts() -> None:
    payload = valid_candidate_v2()
    payload["fieldMappings"] = payload["fieldMappings"][:1]
    model = QueueModel([json.dumps(payload, ensure_ascii=False)])
    service = RuleParsingService(
        model,
        max_characters=10_000,
        max_retries=1,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text("有效规则文本", source_name="test.md")

    assert caught.value.issue.code is ParseErrorCode.CANDIDATE_SEMANTIC_INVALID
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 2
    assert model.calls == 2


@pytest.mark.asyncio
async def test_empty_input_fails_before_model_call() -> None:
    model = QueueModel([json.dumps(valid_candidate_v2())])
    service = RuleParsingService(model, max_characters=10_000, max_retries=0)

    with pytest.raises(RuleParsingError) as caught:
        await service.parse_text(" \n ", source_name="test.md")

    assert caught.value.issue.code is ParseErrorCode.INPUT_EMPTY
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 0
    assert model.calls == 0
