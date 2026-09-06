"""MongoDB adapter for immutable V3 rule-structure recovery records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from rule_reader.application.v3_recovery.ports import (
    SavedV3Recovery,
    StoredV3Recovery,
    V3RecoveryConflictError,
    V3RecoveryPersistenceError,
)
from rule_reader.domain.rules.recovery_v3 import (
    V3RecoveryPayload,
    recovery_payload_dict_v3,
    recovery_payload_sha256_v3,
)
from rule_reader.infrastructure.migrations import V3_RECOVERIES_COLLECTION

Document = dict[str, Any]
Database = AsyncDatabase[Document]


class MongoV3RecoveryRepository:
    def __init__(
        self,
        database_provider: Callable[[], Database],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database_provider = database_provider
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def _database(self) -> Database:
        return self._database_provider()

    async def save(self, payload: V3RecoveryPayload) -> SavedV3Recovery:
        payload_dict = recovery_payload_dict_v3(payload)
        payload_sha256 = recovery_payload_sha256_v3(payload_dict)
        stored_at = _mongodb_datetime(self._clock())
        document: Document = {
            "_id": payload.candidate_id,
            "candidate_id": payload.candidate_id,
            "rule_set_id": payload.candidate.rule_set_id,
            "contract_version": payload.contract_version,
            "catalog_digest": payload.catalog.catalog_digest,
            "rule_block_sha256": payload.source.rule_block_sha256,
            "payload_sha256": payload_sha256,
            "status": payload.status,
            "executable": payload.executable,
            "stored_at": stored_at,
            "payload": payload_dict,
        }
        try:
            await self._database[V3_RECOVERIES_COLLECTION].insert_one(document)
        except DuplicateKeyError:
            existing = await self.get(payload.candidate_id)
            if existing is None:
                raise V3RecoveryConflictError(
                    "V3 recovery identity is already in use but could not be read"
                ) from None
            self._assert_exact(payload, payload_sha256, existing)
            return SavedV3Recovery(record=existing, inserted=False)
        except PyMongoError as error:
            raise V3RecoveryPersistenceError("V3 recovery candidate could not be saved") from error
        return SavedV3Recovery(
            record=StoredV3Recovery(
                payload=payload,
                payload_sha256=payload_sha256,
                stored_at=stored_at,
            ),
            inserted=True,
        )

    async def get(self, candidate_id: str) -> StoredV3Recovery | None:
        try:
            document = await self._database[V3_RECOVERIES_COLLECTION].find_one(
                {"_id": candidate_id}
            )
        except PyMongoError as error:
            raise V3RecoveryPersistenceError("V3 recovery candidate could not be read") from error
        return None if document is None else self._parse_stored(document)

    @staticmethod
    def _assert_exact(
        payload: V3RecoveryPayload,
        payload_sha256: str,
        existing: StoredV3Recovery,
    ) -> None:
        if existing.payload != payload or existing.payload_sha256 != payload_sha256:
            raise V3RecoveryConflictError(
                "V3 recovery candidate ID already exists with different content"
            )

    @staticmethod
    def _parse_stored(document: Document) -> StoredV3Recovery:
        try:
            payload = V3RecoveryPayload.model_validate(document["payload"])
            mongo_id = document["_id"]
            candidate_id = document["candidate_id"]
            rule_set_id = document["rule_set_id"]
            contract_version = document["contract_version"]
            catalog_digest = document["catalog_digest"]
            rule_block_sha256 = document["rule_block_sha256"]
            payload_sha256 = document["payload_sha256"]
            status = document["status"]
            executable = document["executable"]
            stored_at = document["stored_at"]
        except (KeyError, TypeError, ValidationError) as error:
            raise V3RecoveryPersistenceError("Stored V3 recovery candidate is invalid") from error
        if (
            not all(
                isinstance(value, str)
                for value in (
                    mongo_id,
                    candidate_id,
                    rule_set_id,
                    contract_version,
                    catalog_digest,
                    rule_block_sha256,
                    payload_sha256,
                    status,
                )
            )
            or not isinstance(executable, bool)
            or not isinstance(stored_at, datetime)
        ):
            raise V3RecoveryPersistenceError("Stored V3 recovery wrapper is invalid")
        expected_hash = recovery_payload_sha256_v3(payload)
        if (
            mongo_id != payload.candidate_id
            or candidate_id != payload.candidate_id
            or rule_set_id != payload.candidate.rule_set_id
            or contract_version != payload.contract_version
            or catalog_digest != payload.catalog.catalog_digest
            or rule_block_sha256 != payload.source.rule_block_sha256
            or payload_sha256 != expected_hash
            or status != payload.status
            or executable != payload.executable
        ):
            raise V3RecoveryConflictError(
                "Stored V3 recovery identity or payload hash is inconsistent"
            )
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=UTC)
        return StoredV3Recovery(
            payload=payload,
            payload_sha256=payload_sha256,
            stored_at=stored_at,
        )


def _mongodb_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise V3RecoveryPersistenceError("V3 recovery clock must be timezone-aware")
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=(utc_value.microsecond // 1000) * 1000)
