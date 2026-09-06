"""Ports for immutable V3 candidate recovery records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rule_reader.domain.rules.recovery_v3 import V3RecoveryPayload


class V3RecoveryPersistenceError(RuntimeError):
    code = "V3_RECOVERY_PERSISTENCE_UNAVAILABLE"


class V3RecoveryConflictError(V3RecoveryPersistenceError):
    code = "V3_RECOVERY_HASH_CONFLICT"


@dataclass(frozen=True, slots=True)
class StoredV3Recovery:
    payload: V3RecoveryPayload
    payload_sha256: str
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class SavedV3Recovery:
    record: StoredV3Recovery
    inserted: bool


class V3RecoveryRepository(Protocol):
    async def save(self, payload: V3RecoveryPayload) -> SavedV3Recovery: ...

    async def get(self, candidate_id: str) -> StoredV3Recovery | None: ...
