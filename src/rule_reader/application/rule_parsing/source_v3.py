"""Controlled extraction of one named V3 rule block from supplied text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rule_reader.application.rule_parsing.source_normalization import normalize_rule_source
from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError

_RULE_ID_LINE = re.compile(r"^(?:#{1,6}\s*)?([A-Z][A-Z0-9_]{2,119})\s*$")


@dataclass(frozen=True, slots=True)
class RuleSourceBlockV3:
    rule_set_id: str
    text: str
    sha256: str
    character_count: int


def extract_rule_source_block_v3(
    source_text: str,
    *,
    rule_set_id: str,
    max_characters: int = 100_000,
) -> RuleSourceBlockV3:
    """Extract exactly one top-level rule block; never scan files or infer a rule ID."""

    normalized = normalize_rule_source(source_text, max_characters=max_characters).text
    lines = normalized.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if (matched := _RULE_ID_LINE.fullmatch(line.strip())) and matched.group(1) == rule_set_id
    ]
    if len(starts) != 1:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                "The requested V3 rule block must appear exactly once",
                details=(f"ruleSetId={rule_set_id}, matches={len(starts)}",),
            )
        )
    start = starts[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _RULE_ID_LINE.fullmatch(lines[index].strip()):
            end = index
            break
    block = "\n".join(lines[start:end]).strip()
    if len(block.splitlines()) < 2:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.INPUT_EMPTY,
                "The requested V3 rule block has no rule body",
            )
        )
    return RuleSourceBlockV3(
        rule_set_id=rule_set_id,
        text=block,
        sha256=hashlib.sha256(block.encode("utf-8")).hexdigest(),
        character_count=len(block),
    )


def extract_delimited_rule_source_block_v3(
    source_text: str,
    *,
    rule_set_id: str,
    start_marker: str,
    end_marker: str,
    max_characters: int = 200_000,
) -> RuleSourceBlockV3:
    """Extract one ordered block between exact markers, excluding Markdown fences."""

    normalized = normalize_rule_source(source_text, max_characters=max_characters).text
    if normalized.count(start_marker) != 1 or normalized.count(end_marker) != 1:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                "The ordered V3 rule markers must each appear exactly once",
            )
        )
    start = normalized.index(start_marker)
    end = normalized.index(end_marker, start)
    block = normalized[start:end].strip().removesuffix("```").strip()
    if not block.startswith(start_marker):
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                "The ordered V3 rule block could not be isolated",
            )
        )
    return RuleSourceBlockV3(
        rule_set_id=rule_set_id,
        text=block,
        sha256=hashlib.sha256(block.encode("utf-8")).hexdigest(),
        character_count=len(block),
    )
