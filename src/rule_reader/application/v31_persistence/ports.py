"""Ports for Schema v6 complete-delivery persistence of Rule Schema 3.1.0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from rule_reader.application.v3_persistence.ports import (
    PreparedV3HandoffBatch,
    PreparedV3RequestWrapper,
    SavedV3HandoffBatch,
    SavedV3RuleVersion,
    StoredV3HandoffBatch,
    V3HandoffBatchRepository,
    V3LegacyCollectionCounter,
    V3PersistenceConflictError,
    V3PersistenceContractError,
    V3PersistenceError,
    V3PersistenceUnavailableError,
    V3PersistenceVerificationError,
)

V31_RULE_SCHEMA_VERSION = "3.1.0"
V31_HANDOFF_CONTRACT_VERSION = "3.1.0"
V31_DELIVERY_PURPOSE = "optimization-plan-generation"


@dataclass(frozen=True, slots=True)
class PreparedV31RuleVersion:
    rule_version: str
    rule_set_id: str
    schema_version: str
    source_sha256: str
    source_file_sha256: str
    parse_input_sha256: str
    catalog_digest: str
    candidate_payload_sha256: str
    catalog_payload_sha256: str
    payload_sha256: str
    status: str
    executable: bool
    purpose: str
    payload: dict[str, Any]
    catalog_payload: dict[str, Any]
    candidate_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredV31RuleVersion:
    record: PreparedV31RuleVersion
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class SavedV31RuleVersion:
    record: StoredV31RuleVersion
    inserted: bool


@dataclass(frozen=True, slots=True)
class PersistedV31Delivery:
    rule_version: str
    rule_inserted: bool
    batch_inserted: bool
    request_count: int
    rule_payload_sha256: str
    batch_sha256: str
    catalog_payload_sha256: str
    candidate_payload_sha256: str
    request_ids: tuple[str, ...]
    consumable: bool
    missing: tuple[str, ...]
    legacy_counts_before: dict[str, int]
    legacy_counts_after: dict[str, int]


@dataclass(frozen=True, slots=True)
class CompleteDeliveryV31:
    rule_version: str
    purpose: str
    consumable: bool
    missing: tuple[str, ...]
    record: PreparedV31RuleVersion | None
    batch: PreparedV3HandoffBatch | None


class V31RuleVersionRepository(Protocol):
    async def save_rule(self, prepared: PreparedV31RuleVersion) -> SavedV31RuleVersion: ...

    async def get_rule(self, rule_version: str) -> StoredV31RuleVersion | None: ...


__all__ = [
    "V31_DELIVERY_PURPOSE",
    "V31_HANDOFF_CONTRACT_VERSION",
    "V31_RULE_SCHEMA_VERSION",
    "CompleteDeliveryV31",
    "PersistedV31Delivery",
    "PreparedV3HandoffBatch",
    "PreparedV3RequestWrapper",
    "PreparedV31RuleVersion",
    "SavedV3HandoffBatch",
    "SavedV3RuleVersion",
    "SavedV31RuleVersion",
    "StoredV3HandoffBatch",
    "StoredV31RuleVersion",
    "V3HandoffBatchRepository",
    "V3LegacyCollectionCounter",
    "V3PersistenceConflictError",
    "V3PersistenceContractError",
    "V3PersistenceError",
    "V3PersistenceUnavailableError",
    "V3PersistenceVerificationError",
    "V31RuleVersionRepository",
]
