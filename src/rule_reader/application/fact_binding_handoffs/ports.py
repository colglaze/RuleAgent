"""Ports and immutable records for MongoDB fact binding handoffs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from rule_reader.domain.rules.bindings_v2 import FactBindingRequestV2


class FactBindingHandoffError(RuntimeError):
    """Base error with a stable, sanitized code for the explicit CLI."""

    code = "FACT_BINDING_HANDOFF_FAILED"
    retryable = False


class FactBindingHandoffRuleNotFoundError(FactBindingHandoffError):
    code = "RULE_VERSION_NOT_FOUND"


class FactBindingHandoffSchemaUnsupportedError(FactBindingHandoffError):
    code = "RULE_SCHEMA_UNSUPPORTED_FOR_HANDOFF"


class FactBindingHandoffContractError(FactBindingHandoffError):
    code = "FACT_BINDING_HANDOFF_CONTRACT_INVALID"


class FactBindingHandoffConflictError(FactBindingHandoffError):
    code = "FACT_BINDING_HANDOFF_HASH_CONFLICT"


class FactBindingHandoffVerificationError(FactBindingHandoffError):
    code = "FACT_BINDING_HANDOFF_VERIFICATION_FAILED"


class FactBindingHandoffPersistenceError(FactBindingHandoffError):
    code = "FACT_BINDING_HANDOFF_PERSISTENCE_UNAVAILABLE"
    retryable = True


@dataclass(frozen=True, slots=True)
class PreparedFactBindingHandoff:
    request_id: str
    rule_version: str
    fact_code: str
    contract_version: Literal["2.0.0"]
    payload_sha256: str
    payload: FactBindingRequestV2


@dataclass(frozen=True, slots=True)
class StoredFactBindingHandoff:
    request_id: str
    rule_version: str
    fact_code: str
    contract_version: Literal["2.0.0"]
    payload_sha256: str
    created_at: datetime
    payload: FactBindingRequestV2


@dataclass(frozen=True, slots=True)
class SavedFactBindingHandoff:
    record: StoredFactBindingHandoff
    inserted: bool


@dataclass(frozen=True, slots=True)
class PersistedFactBindingHandoffs:
    rule_version: str
    records: tuple[StoredFactBindingHandoff, ...]
    inserted_count: int
    blocking_request_count: int
    source_rule_unchanged: bool

    @property
    def existing_count(self) -> int:
        return len(self.records) - self.inserted_count


class FactBindingHandoffRepository(Protocol):
    async def save_many(
        self,
        records: Sequence[PreparedFactBindingHandoff],
    ) -> tuple[SavedFactBindingHandoff, ...]: ...

    async def list_by_rule_version(
        self,
        rule_version: str,
    ) -> tuple[StoredFactBindingHandoff, ...]: ...
