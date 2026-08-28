"""MongoDB adapter for immutable FactBindingRequest handoffs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from rule_reader.application.fact_binding_handoffs.canonical import (
    canonical_payload_sha256,
    fact_binding_payload,
)
from rule_reader.application.fact_binding_handoffs.ports import (
    FactBindingHandoffConflictError,
    FactBindingHandoffContractError,
    FactBindingHandoffPersistenceError,
    PreparedFactBindingHandoff,
    SavedFactBindingHandoff,
    StoredFactBindingHandoff,
)
from rule_reader.domain.rules.bindings_v2 import FactBindingRequestV2
from rule_reader.infrastructure.migrations import FACT_BINDING_HANDOFFS_COLLECTION

Document = dict[str, Any]
Database = AsyncDatabase[Document]


class MongoFactBindingHandoffRepository:
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

    async def save_many(
        self,
        records: Sequence[PreparedFactBindingHandoff],
    ) -> tuple[SavedFactBindingHandoff, ...]:
        request_ids = [record.request_id for record in records]
        if len(request_ids) != len(set(request_ids)):
            raise FactBindingHandoffContractError(
                "Fact binding handoff batch contains duplicate request IDs"
            )
        for record in records:
            self._validate_prepared(record)

        collection = self._database[FACT_BINDING_HANDOFFS_COLLECTION]
        try:
            cursor = collection.find({"_id": {"$in": request_ids}})
            existing_documents = [document async for document in cursor]
        except PyMongoError as error:
            raise FactBindingHandoffPersistenceError(
                "Existing fact binding handoffs could not be read"
            ) from error

        existing = {
            item.request_id: item
            for item in (self._parse_stored(document) for document in existing_documents)
        }
        prepared_by_id = {record.request_id: record for record in records}
        for request_id, stored in existing.items():
            prepared = prepared_by_id.get(request_id)
            if prepared is None:
                raise FactBindingHandoffConflictError(
                    "Stored fact binding handoff identity is inconsistent"
                )
            self._assert_exact_match(prepared, stored)

        saved_by_id: dict[str, SavedFactBindingHandoff] = {
            request_id: SavedFactBindingHandoff(record=stored, inserted=False)
            for request_id, stored in existing.items()
        }
        created_at = _mongodb_datetime(self._clock())
        for prepared in records:
            if prepared.request_id in saved_by_id:
                continue
            document = self._to_document(prepared, created_at)
            try:
                await collection.insert_one(document)
            except DuplicateKeyError:
                concurrent = await self._find_one(prepared.request_id)
                if concurrent is None:
                    raise FactBindingHandoffConflictError(
                        "Fact binding handoff unique identity is already in use"
                    ) from None
                self._assert_exact_match(prepared, concurrent)
                saved_by_id[prepared.request_id] = SavedFactBindingHandoff(
                    record=concurrent,
                    inserted=False,
                )
            except PyMongoError as error:
                raise FactBindingHandoffPersistenceError(
                    "Fact binding handoff could not be saved"
                ) from error
            else:
                saved_by_id[prepared.request_id] = SavedFactBindingHandoff(
                    record=self._parse_stored(document),
                    inserted=True,
                )

        return tuple(saved_by_id[request_id] for request_id in request_ids)

    async def list_by_rule_version(
        self,
        rule_version: str,
    ) -> tuple[StoredFactBindingHandoff, ...]:
        try:
            cursor = self._database[FACT_BINDING_HANDOFFS_COLLECTION].find(
                {"rule_version": rule_version},
                sort=[("fact_code", 1)],
            )
            documents = [document async for document in cursor]
        except PyMongoError as error:
            raise FactBindingHandoffPersistenceError(
                "Fact binding handoffs could not be read"
            ) from error
        return tuple(self._parse_stored(document) for document in documents)

    async def _find_one(self, request_id: str) -> StoredFactBindingHandoff | None:
        try:
            document = await self._database[FACT_BINDING_HANDOFFS_COLLECTION].find_one(
                {"_id": request_id}
            )
        except PyMongoError as error:
            raise FactBindingHandoffPersistenceError(
                "Fact binding handoff could not be confirmed"
            ) from error
        return None if document is None else self._parse_stored(document)

    @staticmethod
    def _validate_prepared(record: PreparedFactBindingHandoff) -> None:
        payload = fact_binding_payload(record.payload)
        expected_request_id = f"{record.rule_version}#{record.fact_code}"
        if (
            record.request_id != expected_request_id
            or record.payload.request_id != record.request_id
            or record.payload.rule_ref.rule_version != record.rule_version
            or record.payload.fact.fact_code != record.fact_code
            or record.payload.contract_version != record.contract_version
            or canonical_payload_sha256(payload) != record.payload_sha256
        ):
            raise FactBindingHandoffContractError(
                "Prepared fact binding handoff identity or hash is invalid"
            )

    @staticmethod
    def _assert_exact_match(
        prepared: PreparedFactBindingHandoff,
        stored: StoredFactBindingHandoff,
    ) -> None:
        if (
            stored.request_id != prepared.request_id
            or stored.rule_version != prepared.rule_version
            or stored.fact_code != prepared.fact_code
            or stored.contract_version != prepared.contract_version
            or stored.payload_sha256 != prepared.payload_sha256
            or stored.payload != prepared.payload
        ):
            raise FactBindingHandoffConflictError(
                "Fact binding request ID already exists with a different payload hash"
            )

    @staticmethod
    def _to_document(
        record: PreparedFactBindingHandoff,
        created_at: datetime,
    ) -> Document:
        return {
            "_id": record.request_id,
            "request_id": record.request_id,
            "rule_version": record.rule_version,
            "fact_code": record.fact_code,
            "contract_version": record.contract_version,
            "payload_sha256": record.payload_sha256,
            "created_at": created_at,
            "payload": fact_binding_payload(record.payload),
        }

    @staticmethod
    def _parse_stored(document: Document) -> StoredFactBindingHandoff:
        try:
            payload = FactBindingRequestV2.model_validate(document["payload"])
            request_id = document["request_id"]
            rule_version = document["rule_version"]
            fact_code = document["fact_code"]
            contract_version = document["contract_version"]
            payload_sha256 = document["payload_sha256"]
            created_at = document["created_at"]
            mongo_id = document["_id"]
        except (KeyError, TypeError, ValidationError) as error:
            raise FactBindingHandoffPersistenceError(
                "Stored fact binding handoff is invalid"
            ) from error
        if not all(
            isinstance(value, str)
            for value in (
                mongo_id,
                request_id,
                rule_version,
                fact_code,
                contract_version,
                payload_sha256,
            )
        ) or not isinstance(created_at, datetime):
            raise FactBindingHandoffPersistenceError(
                "Stored fact binding handoff wrapper is invalid"
            )
        if contract_version != "2.0.0":
            raise FactBindingHandoffPersistenceError(
                "Stored fact binding handoff contract version is invalid"
            )
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        typed_contract_version = cast(Literal["2.0.0"], contract_version)
        payload_hash = canonical_payload_sha256(fact_binding_payload(payload))
        if (
            mongo_id != request_id
            or request_id != f"{rule_version}#{fact_code}"
            or payload.request_id != request_id
            or payload.rule_ref.rule_version != rule_version
            or payload.fact.fact_code != fact_code
            or payload.contract_version != typed_contract_version
            or payload_sha256 != payload_hash
        ):
            raise FactBindingHandoffConflictError(
                "Stored fact binding handoff identity or payload hash is inconsistent"
            )
        return StoredFactBindingHandoff(
            request_id=request_id,
            rule_version=rule_version,
            fact_code=fact_code,
            contract_version=typed_contract_version,
            payload_sha256=payload_sha256,
            created_at=created_at,
            payload=payload,
        )


def _mongodb_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise FactBindingHandoffContractError(
            "Fact binding handoff clock must return a timezone-aware datetime"
        )
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=(utc_value.microsecond // 1000) * 1000)
