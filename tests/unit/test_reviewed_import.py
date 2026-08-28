from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from tests.support import valid_candidate_v2

from rule_reader.application.rule_parsing.reviewed_import import (
    REVIEWED_IMPORT_VERSION,
    build_reviewed_rule_result,
)
from rule_reader.domain.rules.models import ParserProvider
from rule_reader.domain.rules.v2 import RuleCandidateV2


def test_reviewed_import_uses_explicit_provenance_and_normalized_source() -> None:
    candidate = RuleCandidateV2.model_validate(valid_candidate_v2())
    source_text = "\ufeff# 受控规则\r\n\r\n正文\r\n"
    normalized = "# 受控规则\n\n正文"
    generated_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

    result = build_reviewed_rule_result(
        candidate,
        source_text=source_text,
        source_name="reviewed.md",
        relative_path="reviewed.md",
        authoring_model="codex-gpt-5",
        max_characters=10_000,
        clock=lambda: generated_at,
    )

    assert result.schema_version == "2.0.0"
    assert result.status == "draft"
    assert result.executable is False
    assert result.parser.provider is ParserProvider.REVIEWED_IMPORT
    assert result.parser.prompt_version == REVIEWED_IMPORT_VERSION
    assert result.parser.model == "codex-gpt-5"
    assert result.source.sha256 == hashlib.sha256(normalized.encode()).hexdigest()
    assert result.source.character_count == len(normalized)
    assert result.rule_version.startswith("TEST_RELEASE_002@20260824T120000000000Z-")
    assert all(
        "sourceExpression" not in mapping.model_dump(by_alias=True)
        for mapping in result.rule.field_mappings
    )


def test_reviewed_import_accepts_explicit_governance_version() -> None:
    candidate = RuleCandidateV2.model_validate(valid_candidate_v2())

    result = build_reviewed_rule_result(
        candidate,
        source_text="# reviewed v2 source",
        source_name="reviewed-v2.md",
        relative_path="reviewed-v2.md",
        authoring_model="codex-gpt-5",
        max_characters=10_000,
        reviewed_import_version="reviewed-import-v2",
        clock=lambda: datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
    )

    assert result.parser.prompt_version == "reviewed-import-v2"
