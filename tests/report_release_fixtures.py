"""Fixtures for the immutable 2026-08-24 report-release draft.

The historical draft is already persisted, so tests that exercise read-side handoff
behaviour must reconstruct that exact object without sending it through the current
write-time semantic gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.reviewed_report_release_all_001 import (
    AUTHORING_MODEL,
    build_candidate_payload,
)

from rule_reader.domain.rules.models import ParserMetadata, ParserProvider, SourceMetadata
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import enrich_candidate_v2

HISTORICAL_RULE_VERSION = "REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a"
HISTORICAL_SOURCE_SHA256 = "562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d"


def historical_persisted_report_release_rule() -> RuleParseResultV2:
    """Reconstruct the exact immutable object already stored on 2026-08-24."""

    candidate = RuleCandidateV2.model_validate(build_candidate_payload())
    generated_at = datetime(2026, 8, 24, 8, 7, 26, 492666, tzinfo=UTC)
    return RuleParseResultV2(
        rule_version=HISTORICAL_RULE_VERSION,
        generated_at=generated_at,
        parser=ParserMetadata(
            parser_version="0.7.0",
            prompt_version="reviewed-import-v1",
            provider=ParserProvider.REVIEWED_IMPORT,
            model=AUTHORING_MODEL,
        ),
        source=SourceMetadata(
            source_name="项目报告释放规则.md",
            relative_path="项目报告释放规则.md",
            sha256=HISTORICAL_SOURCE_SHA256,
            character_count=7501,
        ),
        rule=enrich_candidate_v2(candidate),
    )
