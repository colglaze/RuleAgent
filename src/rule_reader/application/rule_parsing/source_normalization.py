"""Canonical source normalization shared by generated and reviewed rule imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError


@dataclass(frozen=True, slots=True)
class NormalizedRuleSource:
    text: str
    sha256: str


def normalize_rule_source(text: str, *, max_characters: int) -> NormalizedRuleSource:
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").strip()
    if not normalized:
        raise RuleParsingError(ParseIssue(ParseErrorCode.INPUT_EMPTY, "Rule text cannot be empty"))
    if len(normalized) > max_characters:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.INPUT_TOO_LARGE,
                f"Rule text exceeds the {max_characters} character limit",
            )
        )
    return NormalizedRuleSource(
        text=normalized,
        sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )
