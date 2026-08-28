"""Build a trusted draft from an explicitly reviewed Schema 2.0 candidate."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from rule_reader.application.rule_parsing.source_normalization import normalize_rule_source
from rule_reader.core.version import __version__
from rule_reader.domain.rules.models import ParserMetadata, ParserProvider, SourceMetadata
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import enrich_candidate_v2, validate_candidate_v2

REVIEWED_IMPORT_VERSION = "reviewed-import-v1"


def build_reviewed_rule_result(
    candidate: RuleCandidateV2,
    *,
    source_text: str,
    source_name: str,
    relative_path: str | None,
    authoring_model: str,
    max_characters: int,
    reviewed_import_version: str = REVIEWED_IMPORT_VERSION,
    clock: Callable[[], datetime] | None = None,
) -> RuleParseResultV2:
    """Validate a reviewed candidate and add trusted immutable result metadata."""

    source = normalize_rule_source(source_text, max_characters=max_characters)
    validate_candidate_v2(candidate)
    parsed_rule = enrich_candidate_v2(candidate)
    now = (clock or (lambda: datetime.now(UTC)))()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return RuleParseResultV2(
        rule_version=f"{candidate.rule_id}@{timestamp}-{source.sha256[:12]}",
        generated_at=now,
        parser=ParserMetadata(
            parser_version=__version__,
            prompt_version=reviewed_import_version,
            provider=ParserProvider.REVIEWED_IMPORT,
            model=authoring_model,
        ),
        source=SourceMetadata(
            source_name=source_name,
            relative_path=relative_path,
            sha256=source.sha256,
            character_count=len(source.text),
        ),
        rule=parsed_rule,
    )
