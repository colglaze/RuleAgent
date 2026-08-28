"""MongoDB adapter for immutable parsed rule versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from rule_reader.application.rule_versions.ports import (
    RuleVersionPersistenceError,
    SavedRuleVersion,
    StoredRuleVersion,
)
from rule_reader.domain.rules.versioned import RuleDocument, validate_rule_document
from rule_reader.infrastructure.migrations import RULE_VERSIONS_COLLECTION

Document = dict[str, Any]
Database = AsyncDatabase[Document]


class MongoRuleVersionRepository:
    def __init__(self, database_provider: Callable[[], Database]) -> None:
        self._database_provider = database_provider

    @property
    def _database(self) -> Database:
        return self._database_provider()

    async def save(self, result: RuleDocument) -> SavedRuleVersion:
        stored_at = _mongodb_datetime(datetime.now(UTC))
        document: Document = {
            "_id": result.rule_version,
            "rule_version": result.rule_version,
            "rule_id": result.rule.rule_id,
            "source_sha256": result.source.sha256,
            "schema_version": result.schema_version,
            "parser_version": result.parser.parser_version,
            "status": result.status,
            "executable": result.executable,
            "generated_at": result.generated_at,
            "stored_at": stored_at,
            # JSON mode preserves the exact ISO timestamp used by the public contract.
            "document": result.model_dump(by_alias=True, mode="json"),
        }
        try:
            await self._database[RULE_VERSIONS_COLLECTION].insert_one(document)
        except DuplicateKeyError:
            existing = await self.get(result.rule_version)
            if existing is None:
                raise RuleVersionPersistenceError(
                    "Rule version could not be confirmed after a duplicate write"
                ) from None
            return SavedRuleVersion(record=existing, inserted=False)
        except PyMongoError as error:
            raise RuleVersionPersistenceError("Rule version could not be saved") from error

        return SavedRuleVersion(
            record=StoredRuleVersion(document=result, stored_at=stored_at),
            inserted=True,
        )

    async def get(self, rule_version: str) -> StoredRuleVersion | None:
        try:
            stored = await self._database[RULE_VERSIONS_COLLECTION].find_one({"_id": rule_version})
        except PyMongoError as error:
            raise RuleVersionPersistenceError("Rule version could not be read") from error
        if stored is None:
            return None

        try:
            parsed = validate_rule_document(stored["document"])
            stored_at = stored["stored_at"]
        except (KeyError, TypeError, ValidationError) as error:
            raise RuleVersionPersistenceError("Stored rule version is invalid") from error
        if not isinstance(stored_at, datetime):
            raise RuleVersionPersistenceError("Stored rule version timestamp is invalid")
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=UTC)
        return StoredRuleVersion(document=parsed, stored_at=stored_at)


def _mongodb_datetime(value: datetime) -> datetime:
    """Match BSON millisecond precision so duplicate reads return the same timestamp."""

    return value.replace(microsecond=(value.microsecond // 1000) * 1000)
