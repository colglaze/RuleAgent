"""Controlled local Markdown reader for the CLI adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rule_reader.domain.rules.errors import (
    ParseErrorCode,
    ParseIssue,
    RuleParsingError,
)


@dataclass(frozen=True, slots=True)
class LocalDocument:
    text: str
    source_name: str
    relative_path: str


class LocalDocumentReader:
    def __init__(self, root: Path, *, max_characters: int) -> None:
        self._root = root
        self._max_characters = max_characters

    def read(self, requested_path: Path) -> LocalDocument:
        try:
            root = self._root.expanduser().resolve(strict=True)
        except OSError as error:
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.DOCUMENT_NOT_FOUND,
                    "Configured document root does not exist",
                )
            ) from error

        candidate = requested_path.expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise RuleParsingError(
                ParseIssue(ParseErrorCode.DOCUMENT_NOT_FOUND, "Rule document does not exist")
            ) from error

        if not resolved.is_file():
            raise RuleParsingError(
                ParseIssue(ParseErrorCode.DOCUMENT_NOT_FOUND, "Rule document is not a file")
            )
        if not resolved.is_relative_to(root):
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.DOCUMENT_OUTSIDE_ROOT,
                    "Rule document is outside the configured document root",
                )
            )
        if resolved.suffix.lower() != ".md":
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.DOCUMENT_TYPE_UNSUPPORTED,
                    "Only Markdown (.md) rule documents are supported",
                )
            )
        if resolved.stat().st_size > self._max_characters * 4:
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.INPUT_TOO_LARGE,
                    f"Rule document exceeds the {self._max_characters} character limit",
                )
            )

        try:
            text = resolved.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.DOCUMENT_ENCODING_INVALID,
                    "Rule document must use UTF-8 encoding",
                )
            ) from error
        if not text.strip():
            raise RuleParsingError(
                ParseIssue(ParseErrorCode.INPUT_EMPTY, "Rule document cannot be empty")
            )
        if len(text) > self._max_characters:
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.INPUT_TOO_LARGE,
                    f"Rule document exceeds the {self._max_characters} character limit",
                )
            )

        return LocalDocument(
            text=text,
            source_name=resolved.name,
            relative_path=resolved.relative_to(root).as_posix(),
        )
