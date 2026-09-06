"""Ports and immutable records for Schema v5 V3 delivery persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

V3_RULE_SCHEMA_VERSION = "3.0.0"
V3_HANDOFF_CONTRACT_VERSION = "3.0.0"
V3_RULE_STATUS = "draft"


class V3PersistenceError(RuntimeError):
    """Base error with a stable, sanitized code; never carries payload or URI details."""

    code = "V3_PERSISTENCE_FAILED"
    retryable = False


class V3PersistenceContractError(V3PersistenceError):
    code = "V3_PERSISTENCE_CONTRACT_INVALID"


class V3PersistenceConflictError(V3PersistenceError):
    code = "V3_PERSISTENCE_HASH_CONFLICT"


class V3PersistenceVerificationError(V3PersistenceError):
    code = "V3_PERSISTENCE_VERIFICATION_FAILED"


class V3PersistenceUnavailableError(V3PersistenceError):
    code = "V3_PERSISTENCE_UNAVAILABLE"
    retryable = True


@dataclass(frozen=True, slots=True)
class PreparedV3RuleVersion:
    rule_version: str
    rule_set_id: str
    schema_version: str
    source_sha256: str
    catalog_digest: str
    candidate_payload_sha256: str
    payload_sha256: str
    status: str
    executable: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedV3RequestWrapper:
    request_id: str
    rule_version: str
    fact_code: str
    contract_version: str
    payload_sha256: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedV3HandoffBatch:
    rule_version: str
    contract_version: str
    request_count: int
    request_ids: tuple[str, ...]
    batch_sha256: str
    wrappers: tuple[PreparedV3RequestWrapper, ...]


@dataclass(frozen=True, slots=True)
class StoredV3RuleVersion:
    record: PreparedV3RuleVersion
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class StoredV3HandoffBatch:
    record: PreparedV3HandoffBatch
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SavedV3RuleVersion:
    record: StoredV3RuleVersion
    inserted: bool


@dataclass(frozen=True, slots=True)
class SavedV3HandoffBatch:
    record: StoredV3HandoffBatch
    inserted: bool


@dataclass(frozen=True, slots=True)
class PersistedV3Delivery:
    rule_version: str
    rule_inserted: bool
    batch_inserted: bool
    request_count: int
    rule_payload_sha256: str
    batch_sha256: str
    request_ids: tuple[str, ...]
    legacy_counts_before: dict[str, int]
    legacy_counts_after: dict[str, int]


class V3RuleVersionRepository(Protocol):
    async def save_rule(self, prepared: PreparedV3RuleVersion) -> SavedV3RuleVersion: ...

    async def get_rule(self, rule_version: str) -> StoredV3RuleVersion | None: ...


class V3HandoffBatchRepository(Protocol):
    async def save_batch(self, prepared: PreparedV3HandoffBatch) -> SavedV3HandoffBatch: ...

    async def get_batch(self, rule_version: str) -> StoredV3HandoffBatch | None: ...


class V3LegacyCollectionCounter(Protocol):
    async def count(self, collection_name: str) -> int: ...
