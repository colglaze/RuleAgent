"""Version-aware loading for immutable rule documents."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import TypeAdapter

from rule_reader.domain.rules.models import RuleParseResult
from rule_reader.domain.rules.v2 import RuleParseResultV2

RuleDocument: TypeAlias = RuleParseResult | RuleParseResultV2
_DOCUMENT_ADAPTER: TypeAdapter[RuleDocument] = TypeAdapter(RuleDocument)


def validate_rule_document(value: object) -> RuleDocument:
    return _DOCUMENT_ADAPTER.validate_python(value)
