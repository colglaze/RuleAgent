"""Offline tests for 3.1.0 complete-delivery persistence, isolation, and recovery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.optimization_plan_support import synthetic_source_identity
from tests.unit.test_v3_persistence import LEGACY_COLLECTIONS, NEW_COLLECTIONS, FakeDatabase

from rule_reader.application.rule_parsing.workflow_v31 import OptimizationPlanParsingService
from rule_reader.application.v3_persistence.ports import (
    V3PersistenceConflictError,
    V3PersistenceError,
)
from rule_reader.application.v31_persistence import packages as package_mod
from rule_reader.application.v31_persistence.packages import (
    load_v31_artifact_dir,
    persist_optimization_plan_output,
)
from rule_reader.application.v31_persistence.service import (
    V31PersistenceService,
    prepare_v31_delivery,
)
from rule_reader.domain.optimization_plan.profile import build_report_delivery
from rule_reader.domain.rules.purpose_v31 import (
    HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
    DeliveryPurposeDeniedError,
    DeliveryPurposeV31,
)
from rule_reader.infrastructure.optimization_plan_artifacts import (
    write_optimization_plan_packages,
)
from rule_reader.infrastructure.v31_persistence import MongoV31PersistenceRepository

FIXED_TIME = datetime(2026, 9, 17, 14, 0, 0, tzinfo=UTC)


class _FailOnceBatch(MongoV31PersistenceRepository):
    def __init__(self, database: FakeDatabase) -> None:
        super().__init__(lambda: database, clock=lambda: FIXED_TIME)  # type: ignore[arg-type]
        self._fail_batch = True

    async def save_batch(self, prepared):  # type: ignore[no-untyped-def]
        if self._fail_batch:
            self._fail_batch = False
            raise V3PersistenceConflictError("synthetic mid-write failure")
        return await super().save_batch(prepared)


def _service(database: FakeDatabase) -> V31PersistenceService:
    repository = MongoV31PersistenceRepository(
        lambda: database,  # type: ignore[arg-type]
        clock=lambda: FIXED_TIME,
    )
    return V31PersistenceService(repository, repository, repository)


def test_persist_is_idempotent_and_does_not_touch_legacy_or_old_v3() -> None:
    database = FakeDatabase()
    for name in (*LEGACY_COLLECTIONS, *NEW_COLLECTIONS):
        database.collections[name].documents["keep"] = {"_id": "keep"}
    old_version = HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION
    database.collections["rule_versions_v3"].documents[old_version] = {
        "_id": old_version,
        "schema_version": "3.0.0",
        "payload": {"schemaVersion": "3.0.0"},
    }
    identity = synthetic_source_identity()
    delivery = build_report_delivery(identity)
    service = _service(database)

    first = asyncio.run(
        service.persist(delivery.catalog, delivery.candidate, delivery.result, delivery.requests)
    )
    second = asyncio.run(
        service.persist(delivery.catalog, delivery.candidate, delivery.result, delivery.requests)
    )

    assert first.consumable is True
    assert first.rule_inserted is True
    assert second.rule_inserted is False
    assert second.batch_inserted is False
    assert old_version in database.collections["rule_versions_v3"].documents
    assert all(
        database.collections[name].documents.get("keep") is not None for name in LEGACY_COLLECTIONS
    )
    loaded = asyncio.run(
        service.get_complete_delivery(
            delivery.result.rule_version,
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        )
    )
    assert loaded.consumable is True
    assert loaded.record is not None
    assert loaded.record.catalog_payload["catalogDigest"] == delivery.catalog.catalog_digest


def test_mid_write_failure_is_not_consumable_until_retry() -> None:
    database = FakeDatabase()
    identity = synthetic_source_identity()
    delivery = build_report_delivery(identity)
    failing = _FailOnceBatch(database)
    service = V31PersistenceService(failing, failing, failing)
    with pytest.raises(V3PersistenceConflictError):
        asyncio.run(
            service.persist(
                delivery.catalog, delivery.candidate, delivery.result, delivery.requests
            )
        )
    loaded = asyncio.run(
        service.get_complete_delivery(
            delivery.result.rule_version,
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        )
    )
    assert loaded.consumable is False
    assert "batch" in loaded.missing
    recovered = asyncio.run(
        service.persist(delivery.catalog, delivery.candidate, delivery.result, delivery.requests)
    )
    assert recovered.consumable is True
    complete = asyncio.run(
        service.get_complete_delivery(
            delivery.result.rule_version,
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        )
    )
    assert complete.consumable is True


def test_historical_version_cannot_be_selected_for_generation() -> None:
    database = FakeDatabase()
    service = _service(database)
    with pytest.raises(DeliveryPurposeDeniedError):
        asyncio.run(
            service.get_complete_delivery(
                HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
                DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
            )
        )


def test_historical_audit_does_not_treat_v3_as_complete_v31_delivery() -> None:
    database = FakeDatabase()
    old_version = HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION
    database.collections["rule_versions_v3"].documents[old_version] = {
        "_id": old_version,
        "schema_version": "3.0.0",
        "payload": {"schemaVersion": "3.0.0"},
    }
    loaded = asyncio.run(
        _service(database).get_complete_delivery(
            old_version,
            DeliveryPurposeV31.HISTORICAL_AUDIT,
        )
    )
    assert loaded.consumable is False
    assert "rule" in loaded.missing


def test_conflicting_payload_hash_is_rejected() -> None:
    database = FakeDatabase()
    identity = synthetic_source_identity()
    delivery = build_report_delivery(identity)
    service = _service(database)
    asyncio.run(
        service.persist(delivery.catalog, delivery.candidate, delivery.result, delivery.requests)
    )
    prepared, _batch = prepare_v31_delivery(
        delivery.catalog, delivery.candidate, delivery.result, delivery.requests
    )
    mutated = replace(prepared, payload_sha256="f" * 64)
    repository = MongoV31PersistenceRepository(
        lambda: database,  # type: ignore[arg-type]
        clock=lambda: FIXED_TIME,
    )
    with pytest.raises(V3PersistenceConflictError, match="different payload hash"):
        asyncio.run(repository.save_rule(mutated))


def test_package_loader_rejects_synthetic_source_hash(tmp_path: Path) -> None:
    identity = synthetic_source_identity()
    run_result = asyncio.run(OptimizationPlanParsingService().generate(identity))
    write_optimization_plan_packages(tmp_path, run_result)
    with pytest.raises(V3PersistenceError, match="frozen optimization plan"):
        load_v31_artifact_dir(tmp_path / "report")


def test_written_packages_persist_through_shared_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = synthetic_source_identity()
    run_result = asyncio.run(OptimizationPlanParsingService().generate(identity))
    write_optimization_plan_packages(tmp_path, run_result)
    monkeypatch.setattr(
        package_mod,
        "APPROVED_SOURCE_FILE_SHA256",
        run_result.report.result.source.source_sha256,
    )
    database = FakeDatabase()
    service = _service(database)
    persisted = asyncio.run(persist_optimization_plan_output(tmp_path, service))
    assert persisted["report"]["consumable"] is True
    assert persisted["data"]["consumable"] is True
    assert persisted["report"]["ruleVersion"] == run_result.report.result.rule_version
    loaded = asyncio.run(
        service.get_complete_delivery(
            run_result.report.result.rule_version,
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        )
    )
    assert loaded.consumable is True
