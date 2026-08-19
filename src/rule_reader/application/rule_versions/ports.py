"""Ports owned by the immutable rule version application layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rule_reader.domain.rules.versioned import RuleDocument


class RuleVersionPersistenceError(RuntimeError):
    """A sanitized persistence failure safe for API and CLI responses."""

    code = "RULE_PERSISTENCE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class StoredRuleVersion:
    document: RuleDocument
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class SavedRuleVersion:
    record: StoredRuleVersion
    inserted: bool


class RuleVersionRepository(Protocol):
    async def save(self, result: RuleDocument) -> SavedRuleVersion: ...

    async def get(self, rule_version: str) -> StoredRuleVersion | None: ...
