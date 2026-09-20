"""Read the frozen optimization-plan Markdown from an explicit source root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rule_reader.domain.optimization_plan import OPTIMIZATION_PLAN_RELATIVE_PATH
from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError

_MAX_SOURCE_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class OptimizationPlanSourceFile:
    file_bytes: bytes
    source_text: str
    relative_path: str


def read_optimization_plan_source(source_root: Path) -> OptimizationPlanSourceFile:
    try:
        root = source_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise RuleParsingError(
            ParseIssue(ParseErrorCode.DOCUMENT_NOT_FOUND, "Optimization-plan source root does not exist")
        ) from error
    if not root.is_dir():
        raise RuleParsingError(
            ParseIssue(ParseErrorCode.DOCUMENT_NOT_FOUND, "Optimization-plan source root is not a directory")
        )

    relative = Path(*OPTIMIZATION_PLAN_RELATIVE_PATH.split("/"))
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.DOCUMENT_OUTSIDE_ROOT,
                "Optimization-plan document is outside the source root",
            )
        )
    if not candidate.is_file():
        raise RuleParsingError(
            ParseIssue(ParseErrorCode.DOCUMENT_NOT_FOUND, "Optimization-plan document does not exist")
        )
    if candidate.suffix.lower() != ".md":
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.DOCUMENT_TYPE_UNSUPPORTED,
                "Only Markdown (.md) optimization-plan documents are supported",
            )
        )
    if candidate.stat().st_size > _MAX_SOURCE_BYTES:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.INPUT_TOO_LARGE,
                f"Optimization-plan document exceeds the {_MAX_SOURCE_BYTES} byte limit",
            )
        )
    try:
        file_bytes = candidate.read_bytes()
        source_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.DOCUMENT_ENCODING_INVALID,
                "Optimization-plan document must use UTF-8 encoding",
            )
        ) from error
    if not source_text.strip():
        raise RuleParsingError(
            ParseIssue(ParseErrorCode.INPUT_EMPTY, "Optimization-plan document cannot be empty")
        )
    return OptimizationPlanSourceFile(
        file_bytes=file_bytes,
        source_text=source_text,
        relative_path=OPTIMIZATION_PLAN_RELATIVE_PATH,
    )
