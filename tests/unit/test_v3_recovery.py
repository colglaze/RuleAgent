from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError
from tests.v3_fixtures import (
    blocked_rule_structure_candidate_v3,
    valid_fact_catalog_v3,
)

from rule_reader.application.v3_recovery.ports import V3RecoveryConflictError
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.recovery_v3 import (
    RecoverySourceV3,
    V3RecoveryPayload,
    recovery_candidate_id_v3,
    recovery_payload_sha256_v3,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.infrastructure.v3_recovery import MongoV3RecoveryRepository

FIXED_TIME = datetime(2026, 9, 5, 8, 30, 1, 123456, tzinfo=UTC)


def _payload() -> V3RecoveryPayload:
    catalog = BusinessConfirmedFactCatalogV3.model_validate(valid_fact_catalog_v3())
    candidate = RuleStructureCandidateV3.model_validate(blocked_rule_structure_candidate_v3())
    source = RecoverySourceV3(
        bundle_id="SYNTHETIC_REFERENCE_BUNDLE",
        bundle_digest="2" * 64,
        workbook_sha256="3" * 64,
        rule_block_sha256="4" * 64,
        rule_block_characters=100,
    )
    return V3RecoveryPayload(
        contract_version="3.0.0",
        candidate_id=recovery_candidate_id_v3(
            candidate.rule_set_id, source.rule_block_sha256, catalog.catalog_digest
        ),
        status="validatedBlockedCandidate",
        executable=False,
        source=source,
        catalog=catalog,
        candidate=candidate,
    )


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, document: dict[str, Any]) -> None:
        identity = cast(str, document["_id"])
        if identity in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[identity] = deepcopy(document)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        identity = cast(str, query["_id"])
        document = self.documents.get(identity)
        return None if document is None else deepcopy(document)


class FakeDatabase:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "rule_structure_candidates_v3"
        return self.collection


def _repository(database: FakeDatabase) -> MongoV3RecoveryRepository:
    return MongoV3RecoveryRepository(
        lambda: cast(Any, database),
        clock=lambda: FIXED_TIME,
    )


def test_v3_recovery_payload_identity_and_hash_are_deterministic() -> None:
    payload = _payload()
    assert payload.candidate_id.startswith("SYNTHETIC_REPORT_RELEASE@444444444444-")
    assert recovery_payload_sha256_v3(payload) == recovery_payload_sha256_v3(
        payload.model_dump(mode="json", by_alias=True)
    )
    invalid = payload.model_dump(mode="json", by_alias=True)
    invalid["candidateId"] = "SYNTHETIC_REPORT_RELEASE@000000000000-000000000000"
    with pytest.raises(ValidationError, match="candidateId"):
        V3RecoveryPayload.model_validate(invalid)


@pytest.mark.asyncio
async def test_v3_recovery_repository_is_insert_only_and_idempotent() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    payload = _payload()
    first = await repository.save(payload)
    second = await repository.save(payload)
    stored = await repository.get(payload.candidate_id)
    assert first.inserted is True
    assert second.inserted is False
    assert stored == first.record
    assert stored is not None
    assert stored.stored_at == FIXED_TIME.replace(microsecond=123000)


@pytest.mark.asyncio
async def test_v3_recovery_same_identity_with_changed_payload_conflicts() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    payload = _payload()
    await repository.save(payload)
    changed_data = payload.model_dump(mode="json", by_alias=True)
    changed_data["source"]["bundleId"] = "DIFFERENT_REFERENCE_BUNDLE"
    changed = V3RecoveryPayload.model_validate(changed_data)
    with pytest.raises(V3RecoveryConflictError):
        await repository.save(changed)


@pytest.mark.asyncio
async def test_v3_recovery_detects_corrupted_stored_hash() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    payload = _payload()
    await repository.save(payload)
    database.collection.documents[payload.candidate_id]["payload_sha256"] = "f" * 64
    with pytest.raises(V3RecoveryConflictError):
        await repository.get(payload.candidate_id)
