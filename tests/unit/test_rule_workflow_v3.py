from __future__ import annotations

import json

import pytest
from tests.v3_fixtures import (
    blocked_rule_structure_candidate_v3,
    valid_fact_catalog_v3,
    valid_rule_structure_candidate_v3,
)

from rule_reader.application.rule_parsing.ports import CandidateGeneration
from rule_reader.application.rule_parsing.prompt_v3 import PROMPT_VERSION_V3, SYSTEM_PROMPT_V3
from rule_reader.application.rule_parsing.source_v3 import (
    extract_delimited_rule_source_block_v3,
    extract_rule_source_block_v3,
)
from rule_reader.application.rule_parsing.workflow_v3 import RuleStructureParsingServiceV3
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError


class QueueV3Model:
    model_name = "fake-deepseek-v3"

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def generate_rule_structure_v3(
        self, *, system_prompt: str, user_payload: dict[str, object]
    ) -> CandidateGeneration:
        assert system_prompt == SYSTEM_PROMPT_V3
        self.calls.append(user_payload)
        payload = self.payloads.pop(0)
        return CandidateGeneration(
            content=json.dumps(payload, ensure_ascii=False),
            provider_request_id=f"fake-{len(self.calls)}",
        )


def _catalog() -> BusinessConfirmedFactCatalogV3:
    return BusinessConfirmedFactCatalogV3.model_validate(valid_fact_catalog_v3())


def test_v3_source_selector_extracts_only_requested_rule() -> None:
    source = "REPORT_RELEASE_ALL_001\n第一条规则。\n\nRAW_DATA_RELEASE_ALL_001\n第二条规则。"
    block = extract_rule_source_block_v3(source, rule_set_id="REPORT_RELEASE_ALL_001")
    assert block.text == "REPORT_RELEASE_ALL_001\n第一条规则。"
    assert block.character_count == len(block.text)
    assert len(block.sha256) == 64


def test_v3_source_selector_rejects_duplicate_named_blocks() -> None:
    source = "REPORT_RELEASE_ALL_001\n规则一。\nREPORT_RELEASE_ALL_001\n规则二。"
    with pytest.raises(RuleParsingError, match="exactly once"):
        extract_rule_source_block_v3(source, rule_set_id="REPORT_RELEASE_ALL_001")


def test_v3_source_selector_extracts_ordered_delimited_block() -> None:
    source = "说明\n=== REPORT START ===\nR0 > R1\n```\n=== DATA START ===\nD0"
    block = extract_delimited_rule_source_block_v3(
        source,
        rule_set_id="REPORT_RELEASE_ALL_001",
        start_marker="=== REPORT START ===",
        end_marker="=== DATA START ===",
    )
    assert block.text == "=== REPORT START ===\nR0 > R1"


@pytest.mark.asyncio
async def test_v3_workflow_corrects_schema_error_with_shared_budget() -> None:
    model = QueueV3Model([{}, valid_rule_structure_candidate_v3()])
    service = RuleStructureParsingServiceV3(model, _catalog(), max_attempts=2)
    result = await service.parse_rule_structure("REPORT_RELEASE_ALL_001\n合成规则。")
    assert result.candidate.rule_set_id == "SYNTHETIC_REPORT_RELEASE"
    assert result.audit.attempt_count == 2
    assert [item.outcome_code for item in result.audit.attempts] == [
        "CANDIDATE_SCHEMA_INVALID",
        "SUCCESS",
    ]
    assert model.calls[0]["retryFeedback"] == []
    assert model.calls[1]["retryFeedback"]
    assert "previousCandidate" in model.calls[1]
    assert PROMPT_VERSION_V3 == "rule-structure-v3.1"


@pytest.mark.asyncio
async def test_v3_business_gap_stops_without_consuming_remaining_budget() -> None:
    model = QueueV3Model(
        [blocked_rule_structure_candidate_v3(), valid_rule_structure_candidate_v3()]
    )
    service = RuleStructureParsingServiceV3(model, _catalog(), max_attempts=3)
    with pytest.raises(RuleParsingError) as caught:
        await service.parse_rule_structure("REPORT_RELEASE_ALL_001\n合成规则。")
    assert caught.value.issue.code is ParseErrorCode.BUSINESS_CONFIRMATION_REQUIRED
    assert caught.value.issue.retryable is False
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 1
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_v3_schema_failures_never_exceed_hard_budget() -> None:
    model = QueueV3Model([{}, {}, valid_rule_structure_candidate_v3()])
    service = RuleStructureParsingServiceV3(model, _catalog(), max_attempts=2)
    with pytest.raises(RuleParsingError) as caught:
        await service.parse_rule_structure("REPORT_RELEASE_ALL_001\n合成规则。")
    assert caught.value.issue.code is ParseErrorCode.CANDIDATE_SCHEMA_INVALID
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempt_count == 2
    assert len(model.calls) == 2
