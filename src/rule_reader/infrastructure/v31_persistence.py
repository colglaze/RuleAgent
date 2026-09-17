"""MongoDB adapter for complete 3.1.0 deliveries on existing V3 collections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from rule_reader.application.v3_persistence.canonical import (
    batch_sha256_v3,
    canonical_payload_sha256,
)
from rule_reader.application.v3_persistence.ports import (
    PreparedV3HandoffBatch,
    PreparedV3RequestWrapper,
    SavedV3HandoffBatch,
    StoredV3HandoffBatch,
    V3PersistenceConflictError,
    V3PersistenceUnavailableError,
    V3PersistenceVerificationError,
)
from rule_reader.application.v31_persistence.ports import (
    PreparedV31RuleVersion,
    SavedV31RuleVersion,
    StoredV31RuleVersion,
)
from rule_reader.domain.rules.bindings_v31 import FactBindingRequestV31
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.result_v31 import RuleParseResultV31
from rule_reader.domain.rules.v31 import RuleStructureCandidateV31
from rule_reader.infrastructure.migrations import (
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
)

Document = dict[str, Any]
Database = AsyncDatabase[Document]
UTC_OFFSET = timedelta(0)


class MongoV31PersistenceRepository:
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

    async def save_rule(self, prepared: PreparedV31RuleVersion) -> SavedV31RuleVersion:
        stored_at = _mongodb_datetime(self._clock())
        document: Document = {
            "_id": prepared.rule_version,
            "rule_version": prepared.rule_version,
            "rule_set_id": prepared.rule_set_id,
            "schema_version": prepared.schema_version,
            "source_sha256": prepared.source_sha256,
            "source_file_sha256": prepared.source_file_sha256,
            "parse_input_sha256": prepared.parse_input_sha256,
            "catalog_digest": prepared.catalog_digest,
            "candidate_payload_sha256": prepared.candidate_payload_sha256,
            "catalog_payload_sha256": prepared.catalog_payload_sha256,
            "payload_sha256": prepared.payload_sha256,
            "status": prepared.status,
            "executable": prepared.executable,
            "purpose": prepared.purpose,
            "stored_at": stored_at,
            "payload": prepared.payload,
            "catalog_payload": prepared.catalog_payload,
            "candidate_payload": prepared.candidate_payload,
        }
        try:
            await self._database[RULE_VERSIONS_V3_COLLECTION].insert_one(document)
        except DuplicateKeyError:
            existing = await self.get_rule(prepared.rule_version)
            if existing is None:
                raise V3PersistenceConflictError(
                    "3.1.0 rule version identity is already in use but could not be read"
                ) from None
            if existing.record != prepared:
                raise V3PersistenceConflictError(
                    "3.1.0 rule version already exists with a different payload hash"
                ) from None
            return SavedV31RuleVersion(record=existing, inserted=False)
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("3.1.0 rule version could not be saved") from error
        return SavedV31RuleVersion(
            record=StoredV31RuleVersion(record=prepared, stored_at=stored_at),
            inserted=True,
        )

    async def get_rule(self, rule_version: str) -> StoredV31RuleVersion | None:
        try:
            document = await self._database[RULE_VERSIONS_V3_COLLECTION].find_one(
                {"_id": rule_version}
            )
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("3.1.0 rule version could not be read") from error
        if document is None:
            return None
        schema_version = document.get("schema_version")
        if schema_version != "3.1.0":
            return None
        return _parse_stored_rule(document)

    async def save_batch(self, prepared: PreparedV3HandoffBatch) -> SavedV3HandoffBatch:
        created_at = _mongodb_datetime(self._clock())
        document: Document = {
            "_id": prepared.rule_version,
            "rule_version": prepared.rule_version,
            "contract_version": prepared.contract_version,
            "request_count": prepared.request_count,
            "request_ids": list(prepared.request_ids),
            "batch_sha256": prepared.batch_sha256,
            "created_at": created_at,
            "requests": [
                {
                    "request_id": wrapper.request_id,
                    "rule_version": wrapper.rule_version,
                    "fact_code": wrapper.fact_code,
                    "contract_version": wrapper.contract_version,
                    "payload_sha256": wrapper.payload_sha256,
                    "created_at": created_at,
                    "payload": wrapper.payload,
                }
                for wrapper in prepared.wrappers
            ],
        }
        try:
            await self._database[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].insert_one(document)
        except DuplicateKeyError:
            existing = await self.get_batch(prepared.rule_version)
            if existing is None:
                raise V3PersistenceConflictError(
                    "3.1.0 handoff batch identity is already in use but could not be read"
                ) from None
            if existing.record != prepared:
                raise V3PersistenceConflictError(
                    "3.1.0 handoff batch already exists with a different content hash"
                ) from None
            return SavedV3HandoffBatch(record=existing, inserted=False)
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("3.1.0 handoff batch could not be saved") from error
        return SavedV3HandoffBatch(
            record=StoredV3HandoffBatch(record=prepared, created_at=created_at),
            inserted=True,
        )

    async def get_batch(self, rule_version: str) -> StoredV3HandoffBatch | None:
        try:
            document = await self._database[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].find_one(
                {"_id": rule_version}
            )
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("3.1.0 handoff batch could not be read") from error
        if document is None:
            return None
        if document.get("contract_version") != "3.1.0":
            return None
        return _parse_stored_batch(document)

    async def count(self, collection_name: str) -> int:
        try:
            return await self._database[collection_name].count_documents({})
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("Collection count could not be read") from error


def _require_str(document: Document, key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise V3PersistenceVerificationError("Stored 3.1.0 document wrapper field is invalid")
    return value


def _require_bool(document: Document, key: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise V3PersistenceVerificationError("Stored 3.1.0 document wrapper field is invalid")
    return value


def _require_datetime(document: Document, key: str) -> datetime:
    value = document.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC_OFFSET:
        raise V3PersistenceVerificationError("Stored 3.1.0 document time must be UTC")
    return value


def _hash(payload: dict[str, Any]) -> str:
    try:
        return canonical_payload_sha256(payload)
    except (TypeError, ValueError) as error:
        raise V3PersistenceVerificationError("Stored 3.1.0 payload cannot be hashed") from error


def _parse_stored_rule(document: Document) -> StoredV31RuleVersion:
    try:
        payload = RuleParseResultV31.model_validate(document["payload"])
        catalog = BusinessConfirmedFactCatalogV3.model_validate(document["catalog_payload"])
        candidate = RuleStructureCandidateV31.model_validate(document["candidate_payload"])
    except (KeyError, TypeError, ValidationError) as error:
        raise V3PersistenceVerificationError(
            "Stored 3.1.0 rule payloads failed to parse"
        ) from error
    record = PreparedV31RuleVersion(
        rule_version=_require_str(document, "rule_version"),
        rule_set_id=_require_str(document, "rule_set_id"),
        schema_version=_require_str(document, "schema_version"),
        source_sha256=_require_str(document, "source_sha256"),
        source_file_sha256=_require_str(document, "source_file_sha256"),
        parse_input_sha256=_require_str(document, "parse_input_sha256"),
        catalog_digest=_require_str(document, "catalog_digest"),
        candidate_payload_sha256=_require_str(document, "candidate_payload_sha256"),
        catalog_payload_sha256=_require_str(document, "catalog_payload_sha256"),
        payload_sha256=_require_str(document, "payload_sha256"),
        status=_require_str(document, "status"),
        executable=_require_bool(document, "executable"),
        purpose=_require_str(document, "purpose"),
        payload=payload.model_dump(mode="json", by_alias=True),
        catalog_payload=catalog.model_dump(mode="json", by_alias=True),
        candidate_payload=candidate.model_dump(mode="json", by_alias=True),
    )
    if (
        record.rule_version != payload.rule_version
        or record.payload_sha256 != _hash(record.payload)
        or record.catalog_payload_sha256 != _hash(record.catalog_payload)
        or record.candidate_payload_sha256 != _hash(record.candidate_payload)
        or document.get("_id") != record.rule_version
    ):
        raise V3PersistenceVerificationError("Stored 3.1.0 rule identity or hash is inconsistent")
    return StoredV31RuleVersion(record=record, stored_at=_require_datetime(document, "stored_at"))


def _parse_stored_batch(document: Document) -> StoredV3HandoffBatch:
    raw_requests = document.get("requests")
    request_ids = document.get("request_ids")
    request_count = document.get("request_count")
    if not isinstance(raw_requests, list) or not isinstance(request_ids, list):
        raise V3PersistenceVerificationError("Stored 3.1.0 batch collections are invalid")
    if not isinstance(request_count, int) or isinstance(request_count, bool):
        raise V3PersistenceVerificationError("Stored 3.1.0 batch request count is invalid")
    created_at = _require_datetime(document, "created_at")
    contract_version = _require_str(document, "contract_version")
    rule_version = _require_str(document, "rule_version")
    wrappers: list[PreparedV3RequestWrapper] = []
    for raw_wrapper in raw_requests:
        if not isinstance(raw_wrapper, dict):
            raise V3PersistenceVerificationError("Stored 3.1.0 request wrapper is invalid")
        try:
            payload = FactBindingRequestV31.model_validate(raw_wrapper["payload"])
        except (KeyError, TypeError, ValidationError) as error:
            raise V3PersistenceVerificationError(
                "Stored 3.1.0 request payload failed to parse"
            ) from error
        wrapper = PreparedV3RequestWrapper(
            request_id=_require_str(raw_wrapper, "request_id"),
            rule_version=_require_str(raw_wrapper, "rule_version"),
            fact_code=_require_str(raw_wrapper, "fact_code"),
            contract_version=_require_str(raw_wrapper, "contract_version"),
            payload_sha256=_require_str(raw_wrapper, "payload_sha256"),
            payload=payload.model_dump(mode="json", by_alias=True),
        )
        if (
            wrapper.request_id != payload.request_id
            or wrapper.payload_sha256 != _hash(wrapper.payload)
            or wrapper.contract_version != contract_version
            or _require_datetime(raw_wrapper, "created_at") != created_at
        ):
            raise V3PersistenceVerificationError("Stored 3.1.0 request wrapper is inconsistent")
        wrappers.append(wrapper)
    stored_order = [wrapper.request_id for wrapper in wrappers]
    expected_hash = batch_sha256_v3(
        (wrapper.request_id, wrapper.payload_sha256) for wrapper in wrappers
    )
    if (
        stored_order != request_ids
        or request_count != len(wrappers)
        or expected_hash != _require_str(document, "batch_sha256")
        or document.get("_id") != rule_version
        or contract_version != "3.1.0"
    ):
        raise V3PersistenceVerificationError("Stored 3.1.0 batch identity or hash is inconsistent")
    return StoredV3HandoffBatch(
        record=PreparedV3HandoffBatch(
            rule_version=rule_version,
            contract_version=contract_version,
            request_count=request_count,
            request_ids=tuple(stored_order),
            batch_sha256=expected_hash,
            wrappers=tuple(wrappers),
        ),
        created_at=created_at,
    )


def _mongodb_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise V3PersistenceUnavailableError("3.1.0 persistence clock must be timezone-aware")
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=(utc_value.microsecond // 1000) * 1000)
