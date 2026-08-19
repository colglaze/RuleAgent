"""Stable rule parsing error contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ParseErrorCode(StrEnum):
    INPUT_EMPTY = "INPUT_EMPTY"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_OUTSIDE_ROOT = "DOCUMENT_OUTSIDE_ROOT"
    DOCUMENT_TYPE_UNSUPPORTED = "DOCUMENT_TYPE_UNSUPPORTED"
    DOCUMENT_ENCODING_INVALID = "DOCUMENT_ENCODING_INVALID"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    PROVIDER_REQUEST_FAILED = "PROVIDER_REQUEST_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_EMPTY_RESPONSE = "PROVIDER_EMPTY_RESPONSE"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    CANDIDATE_JSON_INVALID = "CANDIDATE_JSON_INVALID"
    CANDIDATE_SCHEMA_INVALID = "CANDIDATE_SCHEMA_INVALID"
    CANDIDATE_SEMANTIC_INVALID = "CANDIDATE_SEMANTIC_INVALID"


@dataclass(frozen=True, slots=True)
class ParseIssue:
    code: ParseErrorCode
    message: str
    retryable: bool = False
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": list(self.details),
        }


class RuleParsingError(RuntimeError):
    """Raised when a parse run ends without a valid draft."""

    def __init__(self, issue: ParseIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue
