"""MongoDB adapter for immutable V3 rule versions and handoff batches (Schema v5)."""

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
    PreparedV3RuleVersion,
    SavedV3HandoffBatch,
    SavedV3RuleVersion,
    StoredV3HandoffBatch,
    StoredV3RuleVersion,
    V3PersistenceConflictError,
    V3PersistenceUnavailableError,
    V3PersistenceVerificationError,
)
from rule_reader.domain.rules.bindings_v3 import FactBindingRequestV3
from rule_reader.domain.rules.result_v3 import RuleParseResultV3
from rule_reader.infrastructure.migrations import (
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
)

Document = dict[str, Any]
Database = AsyncDatabase[Document]
UTC_OFFSET = timedelta(0)


class MongoV3PersistenceRepository:
    """Insert-only repository for one rule document and one single-document batch."""

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

    async def save_rule(self, prepared: PreparedV3RuleVersion) -> SavedV3RuleVersion:
        stored_at = _mongodb_datetime(self._clock())
        document: Document = {
            "_id": prepared.rule_version,
            "rule_version": prepared.rule_version,
            "rule_set_id": prepared.rule_set_id,
            "schema_version": prepared.schema_version,
            "source_sha256": prepared.source_sha256,
            "catalog_digest": prepared.catalog_digest,
            "candidate_payload_sha256": prepared.candidate_payload_sha256,
            "payload_sha256": prepared.payload_sha256,
            "status": prepared.status,
            "executable": prepared.executable,
            "stored_at": stored_at,
            "payload": prepared.payload,
        }
        try:
            await self._database[RULE_VERSIONS_V3_COLLECTION].insert_one(document)
        except DuplicateKeyError:
            existing = await self.get_rule(prepared.rule_version)
            if existing is None:
                raise V3PersistenceConflictError(
                    "V3 rule version identity is already in use but could not be read"
                ) from None
            if existing.record != prepared:
                raise V3PersistenceConflictError(
                    "V3 rule version already exists with a different payload hash"
                ) from None
            return SavedV3RuleVersion(record=existing, inserted=False)
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("V3 rule version could not be saved") from error
        return SavedV3RuleVersion(
            record=StoredV3RuleVersion(record=prepared, stored_at=stored_at),
            inserted=True,
        )

    async def get_rule(self, rule_version: str) -> StoredV3RuleVersion | None:
        try:
            document = await self._database[RULE_VERSIONS_V3_COLLECTION].find_one(
                {"_id": rule_version}
            )
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("V3 rule version could not be read") from error
        return None if document is None else _parse_stored_rule(document)

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
                    "V3 handoff batch identity is already in use but could not be read"
                ) from None
            if existing.record != prepared:
                raise V3PersistenceConflictError(
                    "V3 handoff batch already exists with a different content hash"
                ) from None
            return SavedV3HandoffBatch(record=existing, inserted=False)
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("V3 handoff batch could not be saved") from error
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
            raise V3PersistenceUnavailableError("V3 handoff batch could not be read") from error
        return None if document is None else _parse_stored_batch(document)

    async def count(self, collection_name: str) -> int:
        try:
            return await self._database[collection_name].count_documents({})
        except PyMongoError as error:
            raise V3PersistenceUnavailableError("Collection count could not be read") from error


def _require_str(document: Document, key: str) -> str:
    try:
        value = document[key]
    except KeyError as error:
        raise V3PersistenceVerificationError(
            "Stored V3 document is missing a wrapper field"
        ) from error
    if not isinstance(value, str):
        raise V3PersistenceVerificationError("Stored V3 document wrapper field has an invalid type")
    return value


def _require_bool(document: Document, key: str) -> bool:
    try:
        value = document[key]
    except KeyError as error:
        raise V3PersistenceVerificationError(
            "Stored V3 document is missing a wrapper field"
        ) from error
    if not isinstance(value, bool):
        raise V3PersistenceVerificationError("Stored V3 document wrapper field has an invalid type")
    return value


def _require_datetime(document: Document, key: str) -> datetime:
    try:
        value = document[key]
    except KeyError as error:
        raise V3PersistenceVerificationError(
            "Stored V3 document is missing a wrapper field"
        ) from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC_OFFSET:
        raise V3PersistenceVerificationError(
            "Stored V3 document time must be a timezone-aware UTC datetime"
        )
    return value


def _parse_stored_rule(document: Document) -> StoredV3RuleVersion:
    try:
        payload = RuleParseResultV3.model_validate(document["payload"])
    except (KeyError, TypeError, ValidationError) as error:
        raise V3PersistenceVerificationError("Stored V3 rule payload failed to parse") from error
    mongo_id = _require_str(document, "_id")
    rule_version = _require_str(document, "rule_version")
    rule_set_id = _require_str(document, "rule_set_id")
    schema_version = _require_str(document, "schema_version")
    source_sha256 = _require_str(document, "source_sha256")
    catalog_digest = _require_str(document, "catalog_digest")
    candidate_payload_sha256 = _require_str(document, "candidate_payload_sha256")
    payload_sha256 = _require_str(document, "payload_sha256")
    status = _require_str(document, "status")
    executable = _require_bool(document, "executable")
    stored_at = _require_datetime(document, "stored_at")
    expected_hash = _verified_hash(payload.model_dump(mode="json", by_alias=True))
    if (
        mongo_id != payload.rule_version
        or rule_version != payload.rule_version
        or rule_set_id != payload.rule_set_id
        or schema_version != payload.schema_version
        or source_sha256 != payload.source.source_sha256
        or catalog_digest != payload.catalog_ref.catalog_digest
        or candidate_payload_sha256 != payload.candidate_ref.payload_sha256
        or status != payload.status
        or executable != payload.executable
        or payload_sha256 != expected_hash
    ):
        raise V3PersistenceVerificationError(
            "Stored V3 rule identity or payload hash is inconsistent"
        )
    return StoredV3RuleVersion(
        record=PreparedV3RuleVersion(
            rule_version=rule_version,
            rule_set_id=rule_set_id,
            schema_version=schema_version,
            source_sha256=source_sha256,
            catalog_digest=catalog_digest,
            candidate_payload_sha256=candidate_payload_sha256,
            payload_sha256=payload_sha256,
            status=status,
            executable=executable,
            payload=payload.model_dump(mode="json", by_alias=True),
        ),
        stored_at=stored_at,
    )


def _parse_stored_batch(document: Document) -> StoredV3HandoffBatch:
    try:
        raw_requests = document["requests"]
        request_ids = document["request_ids"]
        request_count = document["request_count"]
    except (KeyError, TypeError) as error:
        raise V3PersistenceVerificationError(
            "Stored V3 batch document is missing batch fields"
        ) from error
    if not isinstance(raw_requests, list) or not isinstance(request_ids, list):
        raise V3PersistenceVerificationError(
            "Stored V3 batch document has invalid collection types"
        )
    if not isinstance(request_count, int) or isinstance(request_count, bool):
        raise V3PersistenceVerificationError("Stored V3 batch request count has an invalid type")
    mongo_id = _require_str(document, "_id")
    rule_version = _require_str(document, "rule_version")
    contract_version = _require_str(document, "contract_version")
    batch_sha256 = _require_str(document, "batch_sha256")
    created_at = _require_datetime(document, "created_at")

    # Parse wrappers in stored order; ordering, duplication, and identity are verified
    # before anything is sorted so stored corruption is never masked.
    wrappers: list[PreparedV3RequestWrapper] = []
    for raw_wrapper in raw_requests:
        if not isinstance(raw_wrapper, dict):
            raise V3PersistenceVerificationError("Stored V3 request wrapper has an invalid type")
        wrapper = _parse_stored_wrapper(raw_wrapper, created_at, contract_version)
        if wrapper.rule_version != rule_version:
            raise V3PersistenceVerificationError(
                "Stored V3 request wrapper does not close to the batch rule version"
            )
        wrappers.append(wrapper)

    stored_order = [wrapper.request_id for wrapper in wrappers]
    if request_ids != stored_order or request_count != len(wrappers):
        raise V3PersistenceVerificationError(
            "Stored V3 batch request count or ordering is inconsistent"
        )
    if len(set(stored_order)) != len(stored_order):
        raise V3PersistenceVerificationError("Stored V3 batch contains duplicate request IDs")
    if any(
        stored_order[index] >= stored_order[index + 1] for index in range(len(stored_order) - 1)
    ):
        raise V3PersistenceVerificationError(
            "Stored V3 batch requests are not in strictly ascending request_id order"
        )
    fact_codes = [wrapper.fact_code for wrapper in wrappers]
    if len(set(fact_codes)) != len(fact_codes):
        raise V3PersistenceVerificationError("Stored V3 batch contains duplicate fact codes")
    expected_hash = batch_sha256_v3(
        (wrapper.request_id, wrapper.payload_sha256) for wrapper in wrappers
    )
    if mongo_id != rule_version or batch_sha256 != expected_hash:
        raise V3PersistenceVerificationError("Stored V3 batch identity or hash is inconsistent")
    if contract_version != "3.0.0":
        raise V3PersistenceVerificationError("Stored V3 batch contract version is invalid")
    return StoredV3HandoffBatch(
        record=PreparedV3HandoffBatch(
            rule_version=rule_version,
            contract_version=contract_version,
            request_count=request_count,
            request_ids=tuple(stored_order),
            batch_sha256=batch_sha256,
            wrappers=tuple(wrappers),
        ),
        created_at=created_at,
    )


def _parse_stored_wrapper(
    raw_wrapper: Document,
    batch_created_at: datetime,
    batch_contract_version: str,
) -> PreparedV3RequestWrapper:
    try:
        payload = FactBindingRequestV3.model_validate(raw_wrapper["payload"])
    except (KeyError, TypeError, ValidationError) as error:
        raise V3PersistenceVerificationError("Stored V3 request payload failed to parse") from error
    request_id = _require_str(raw_wrapper, "request_id")
    rule_version = _require_str(raw_wrapper, "rule_version")
    fact_code = _require_str(raw_wrapper, "fact_code")
    contract_version = _require_str(raw_wrapper, "contract_version")
    payload_sha256 = _require_str(raw_wrapper, "payload_sha256")
    wrapper_created_at = _require_datetime(raw_wrapper, "created_at")
    if wrapper_created_at != batch_created_at:
        raise V3PersistenceVerificationError(
            "Stored V3 request wrapper created_at does not match the batch created_at"
        )
    if contract_version != batch_contract_version or contract_version != payload.contract_version:
        raise V3PersistenceVerificationError(
            "Stored V3 request wrapper contract version is inconsistent"
        )
    expected_hash = _verified_hash(payload.model_dump(mode="json", by_alias=True))
    if (
        request_id != payload.request_id
        or rule_version != payload.rule_ref.rule_version
        or fact_code != payload.fact.fact_code
        or contract_version != payload.contract_version
        or payload_sha256 != expected_hash
    ):
        raise V3PersistenceVerificationError(
            "Stored V3 request wrapper identity or payload hash is inconsistent"
        )
    return PreparedV3RequestWrapper(
        request_id=request_id,
        rule_version=rule_version,
        fact_code=fact_code,
        contract_version=contract_version,
        payload_sha256=payload_sha256,
        payload=payload.model_dump(mode="json", by_alias=True),
    )


def _verified_hash(payload: dict[str, Any]) -> str:
    try:
        return canonical_payload_sha256(payload)
    except (TypeError, ValueError) as error:
        raise V3PersistenceVerificationError(
            "Stored V3 payload cannot be canonically serialized"
        ) from error


def _mongodb_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise V3PersistenceUnavailableError("V3 persistence clock must be timezone-aware")
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=(utc_value.microsecond // 1000) * 1000)
