"""Offline tests for the Schema v5 V3 persistence service and MongoDB adapter."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import ConnectionFailure, DuplicateKeyError
from tests.v3_delivery_fixtures import (
    SYNTHETIC_SOURCE_SHA256,
    synthetic_ready_delivery_v3,
)

from rule_reader.application.v3_persistence.canonical import (
    batch_sha256_v3,
    canonical_payload_sha256,
)
from rule_reader.application.v3_persistence.ports import (
    V3PersistenceConflictError,
    V3PersistenceContractError,
    V3PersistenceUnavailableError,
    V3PersistenceVerificationError,
)
from rule_reader.application.v3_persistence.service import (
    V3PersistenceService,
    prepare_v3_delivery,
)
from rule_reader.domain.rules.v3 import BlockingIssueV3
from rule_reader.infrastructure.migrations import (
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
    RULE_VERSIONS_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
    V3_RECOVERIES_COLLECTION,
)
from rule_reader.infrastructure.v3_persistence import MongoV3PersistenceRepository

FIXED_TIME = datetime(2026, 9, 6, 12, 0, 0, 123456, tzinfo=UTC)

NEW_COLLECTIONS = (RULE_VERSIONS_V3_COLLECTION, FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION)
LEGACY_COLLECTIONS = (
    RULE_VERSIONS_COLLECTION,
    "fact_binding_handoffs",
    V3_RECOVERIES_COLLECTION,
)


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.insert_error: Exception | None = None
        self.find_error: Exception | None = None
        self.count_error: Exception | None = None

    async def insert_one(self, document: dict[str, Any]) -> None:
        if self.insert_error is not None:
            raise self.insert_error
        identity = document["_id"]
        if identity in self.documents:
            raise DuplicateKeyError("duplicate key")
        self.documents[identity] = deepcopy(document)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        if self.find_error is not None:
            raise self.find_error
        document = self.documents.get(query["_id"])
        return None if document is None else deepcopy(document)

    async def count_documents(self, query: dict[str, Any]) -> int:
        del query
        if self.count_error is not None:
            raise self.count_error
        return len(self.documents)


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            name: FakeCollection() for name in (*LEGACY_COLLECTIONS, *NEW_COLLECTIONS)
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def _repository(database: FakeDatabase) -> MongoV3PersistenceRepository:
    return MongoV3PersistenceRepository(
        lambda: database,  # type: ignore[arg-type]
        clock=lambda: FIXED_TIME,
    )


def _service(database: FakeDatabase) -> V3PersistenceService:
    repository = _repository(database)
    return V3PersistenceService(repository, repository, repository)


def _rule_document_count(database: FakeDatabase) -> int:
    return len(database.collections[RULE_VERSIONS_V3_COLLECTION].documents)


def _batch_document_count(database: FakeDatabase) -> int:
    return len(database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents)


def test_first_persist_saves_rule_and_batch_and_verifies_read_back() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    persisted = asyncio.run(service.persist(catalog, candidate, result, requests))

    assert persisted.rule_inserted is True
    assert persisted.batch_inserted is True
    assert persisted.request_count == len(requests) == 2
    assert persisted.request_ids == tuple(sorted(request.request_id for request in requests))
    assert persisted.legacy_counts_before == dict.fromkeys(LEGACY_COLLECTIONS, 0)
    assert persisted.legacy_counts_after == dict.fromkeys(LEGACY_COLLECTIONS, 0)

    rule_document = database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
    assert rule_document["_id"] == result.rule_version
    assert rule_document["rule_version"] == result.rule_version
    assert rule_document["rule_set_id"] == result.rule_set_id
    assert rule_document["schema_version"] == "3.0.0"
    assert rule_document["source_sha256"] == SYNTHETIC_SOURCE_SHA256
    assert rule_document["status"] == "draft"
    assert rule_document["executable"] is False
    assert rule_document["payload"]["ruleVersion"] == result.rule_version
    assert rule_document["stored_at"] == FIXED_TIME.replace(microsecond=123000)
    assert rule_document["payload_sha256"] == canonical_payload_sha256(rule_document["payload"])

    batch_document = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
        result.rule_version
    ]
    assert batch_document["_id"] == result.rule_version
    assert batch_document["contract_version"] == "3.0.0"
    assert batch_document["request_count"] == 2
    assert batch_document["request_ids"] == sorted(batch_document["request_ids"])
    assert [wrapper["request_id"] for wrapper in batch_document["requests"]] == (
        batch_document["request_ids"]
    )
    for wrapper in batch_document["requests"]:
        assert wrapper["contract_version"] == "3.0.0"
        assert wrapper["rule_version"] == result.rule_version
        assert wrapper["payload"]["requestId"] == wrapper["request_id"]
        assert wrapper["payload_sha256"] == canonical_payload_sha256(wrapper["payload"])
    assert batch_document["batch_sha256"] == batch_sha256_v3(
        (wrapper["request_id"], wrapper["payload_sha256"]) for wrapper in batch_document["requests"]
    )
    assert persisted.rule_payload_sha256 == rule_document["payload_sha256"]
    assert persisted.batch_sha256 == batch_document["batch_sha256"]


async def test_same_delivery_replay_is_idempotent_and_preserves_first_times() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    first = await service.persist(catalog, candidate, result, requests)
    rule_before = deepcopy(
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
    )
    batch_before = deepcopy(
        database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
            result.rule_version
        ]
    )
    second = await service.persist(catalog, candidate, result, requests)

    assert first.rule_inserted is True and first.batch_inserted is True
    assert second.rule_inserted is False and second.batch_inserted is False
    assert second.rule_payload_sha256 == first.rule_payload_sha256
    assert second.batch_sha256 == first.batch_sha256
    assert (
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
        == rule_before
    )
    assert (
        database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
            result.rule_version
        ]
        == batch_before
    )


async def test_changed_request_input_order_stays_idempotent() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    first = await service.persist(catalog, candidate, result, requests)
    second = await service.persist(catalog, candidate, result, tuple(reversed(requests)))

    assert second.rule_inserted is False
    assert second.batch_inserted is False
    assert second.batch_sha256 == first.batch_sha256
    batch_document = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
        result.rule_version
    ]
    assert batch_document["request_ids"] == sorted(batch_document["request_ids"])


async def test_same_rule_version_with_changed_rule_payload_conflicts() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    await service.persist(catalog, candidate, result, requests)
    rule_before = deepcopy(
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
    )
    batch_before = deepcopy(
        database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
            result.rule_version
        ]
    )
    tampered = result.model_copy(
        update={
            "test_cases": [
                case.model_copy(update={"description": "Changed description"})
                if index == 0
                else case
                for index, case in enumerate(result.test_cases)
            ]
        }
    )

    with pytest.raises(V3PersistenceConflictError):
        await service.persist(catalog, candidate, tampered, requests)

    assert (
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
        == rule_before
    )
    assert (
        database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
            result.rule_version
        ]
        == batch_before
    )


def test_repository_rule_conflict_on_different_payload_hash() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    async def scenario() -> None:
        prepared_rule, _ = prepare_v3_delivery(catalog, candidate, result, requests)
        await repository.save_rule(prepared_rule)
        changed = replace(prepared_rule, payload_sha256="f" * 64)
        with pytest.raises(V3PersistenceConflictError):
            await repository.save_rule(changed)

    asyncio.run(scenario())


def test_repository_batch_conflict_on_different_content() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    async def scenario() -> None:
        _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
        await repository.save_batch(prepared_batch)
        changed = replace(prepared_batch, batch_sha256="f" * 64)
        with pytest.raises(V3PersistenceConflictError):
            await repository.save_batch(changed)

    asyncio.run(scenario())


async def test_write_ahead_gate_rejections_leave_zero_writes() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    not_ready = result.model_copy(update={"agent2_readiness_ready": False})
    executable = result.model_copy(update={"executable": True})
    missing_declaration = result.model_copy(
        update={"fact_declarations": result.fact_declarations[:-1]}
    )
    wrong_request_id = requests[0].model_copy(update={"request_id": "WRONG#id"})
    wrong_rule_ref = requests[0].model_copy(
        update={
            "rule_ref": requests[0].rule_ref.model_copy(
                update={"rule_version": "OTHER@20260905T000000000000Z-111111111111-222222222222"}
            )
        }
    )
    blocked_candidate = candidate.model_copy(
        update={
            "blocking_issues": [
                BlockingIssueV3.model_validate(
                    {
                        "issueId": "synthetic.block",
                        "code": "BUSINESS_FACT_MISSING",
                        "message": "合成阻断。",
                        "factCodes": ["task.status_code"],
                        "resolutionHint": "补充确认。",
                    }
                )
            ]
        }
    )

    illegal_deliveries = [
        (catalog, blocked_candidate, result, requests),
        (catalog, candidate, not_ready, requests),
        (catalog, candidate, executable, requests),
        (catalog, candidate, missing_declaration, requests[:-1]),
        (catalog, candidate, result, (wrong_request_id, *requests[1:])),
        (catalog, candidate, result, (wrong_rule_ref, *requests[1:])),
        (catalog, candidate, result, (requests[0], requests[0])),
        (catalog, candidate, result, requests[:-1]),
    ]
    for index, delivery in enumerate(illegal_deliveries):
        with pytest.raises(V3PersistenceContractError):
            await service.persist(*delivery)
        assert _rule_document_count(database) == 0, f"rule written for case {index}"
        assert _batch_document_count(database) == 0, f"batch written for case {index}"


async def test_read_back_detects_corrupted_stored_batch() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    await service.persist(catalog, candidate, result, requests)
    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    batch_collection.documents[result.rule_version]["requests"][0].pop("request_id")

    with pytest.raises(V3PersistenceVerificationError):
        await service.persist(catalog, candidate, result, requests)


async def test_read_back_detects_naive_timezone_in_stored_rule_payload() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    await _service(database).persist(catalog, candidate, result, requests)
    rule_collection = database.collections[RULE_VERSIONS_V3_COLLECTION]
    rule_collection.documents[result.rule_version]["payload"]["generatedAt"] = "2026-09-05T00:00:00"

    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_rule(result.rule_version)


async def test_read_back_detects_wrong_batch_count_hash_and_order() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_batch(prepared_batch)

    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    batch_collection.documents[result.rule_version]["request_count"] = 99
    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_batch(result.rule_version)

    batch_collection.documents[result.rule_version]["request_count"] = 2
    batch_collection.documents[result.rule_version]["batch_sha256"] = "f" * 64
    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_batch(result.rule_version)

    batch_collection.documents[result.rule_version]["batch_sha256"] = prepared_batch.batch_sha256
    batch_collection.documents[result.rule_version]["request_ids"] = list(
        reversed(batch_collection.documents[result.rule_version]["request_ids"])
    )
    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_batch(result.rule_version)


async def test_read_back_detects_wrong_rule_wrapper_hash() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    prepared_rule, _ = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_rule(prepared_rule)

    rule_collection = database.collections[RULE_VERSIONS_V3_COLLECTION]
    rule_collection.documents[result.rule_version]["payload_sha256"] = "f" * 64
    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_rule(result.rule_version)


async def test_pymongo_failures_become_sanitized_unavailable_errors() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    prepared_rule, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)

    database.collections[RULE_VERSIONS_V3_COLLECTION].insert_error = ConnectionFailure(
        "mongodb://user:secret@localhost:27017/admin"
    )
    with pytest.raises(V3PersistenceUnavailableError) as rule_error:
        await repository.save_rule(prepared_rule)
    assert rule_error.value.code == "V3_PERSISTENCE_UNAVAILABLE"
    assert "mongodb://" not in str(rule_error.value)
    assert "secret" not in str(rule_error.value)
    assert isinstance(rule_error.value.__cause__, ConnectionFailure)

    database.collections[RULE_VERSIONS_V3_COLLECTION].insert_error = None
    database.collections[
        FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION
    ].insert_error = ConnectionFailure("boom")
    await repository.save_rule(prepared_rule)
    with pytest.raises(V3PersistenceUnavailableError):
        await repository.save_batch(prepared_batch)

    database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].insert_error = None
    database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].find_error = ConnectionFailure(
        "boom"
    )
    with pytest.raises(V3PersistenceUnavailableError):
        await repository.get_batch(result.rule_version)

    database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].find_error = None
    database.collections[RULE_VERSIONS_COLLECTION].count_error = ConnectionFailure("boom")
    with pytest.raises(V3PersistenceUnavailableError):
        await repository.count(RULE_VERSIONS_COLLECTION)


async def test_legacy_count_change_during_persist_fails_verification() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _prepared_rule, _prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)

    class MutatingCounter:
        def __init__(self) -> None:
            self.calls = 0

        async def count(self, collection_name: str) -> int:
            self.calls += 1
            if self.calls == 2:
                # 第二次快照(写后)之前模拟并发写入历史集合。
                await database.collections[RULE_VERSIONS_COLLECTION].insert_one(
                    {"_id": "concurrent", "rule_version": "concurrent"}
                )
            return await repository.count(collection_name)

    service = V3PersistenceService(repository, repository, MutatingCounter())
    with pytest.raises(V3PersistenceVerificationError, match="Legacy collection counts"):
        await service.persist(catalog, candidate, result, requests)


async def test_idempotent_replay_repeats_exact_read_back() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()

    first = await service.persist(catalog, candidate, result, requests)
    second = await service.persist(catalog, candidate, result, requests)

    assert first.rule_inserted and first.batch_inserted
    assert not second.rule_inserted and not second.batch_inserted
    assert second.legacy_counts_after == second.legacy_counts_before
    assert second.request_ids == first.request_ids


async def test_read_back_rejects_reversed_stored_wrappers() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_batch(prepared_batch)
    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    # 只反转 wrapper 数组, 顶层 request_ids 保持升序: 排序比较不得掩盖存储顺序损坏。
    batch_collection.documents[result.rule_version]["requests"] = list(
        reversed(batch_collection.documents[result.rule_version]["requests"])
    )

    with pytest.raises(V3PersistenceVerificationError, match="order"):
        await repository.get_batch(result.rule_version)


async def test_read_back_rejects_duplicate_request_ids_with_recomputed_hash() -> None:
    from rule_reader.application.v3_persistence.canonical import batch_sha256_v3

    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_batch(prepared_batch)
    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    document = batch_collection.documents[result.rule_version]
    duplicated = [document["requests"][0], deepcopy(document["requests"][0])]
    duplicated.append(document["requests"][1])
    document["requests"] = duplicated
    document["request_ids"] = [wrapper["request_id"] for wrapper in duplicated]
    document["request_count"] = len(duplicated)
    document["batch_sha256"] = batch_sha256_v3(
        (wrapper["request_id"], wrapper["payload_sha256"]) for wrapper in duplicated
    )

    with pytest.raises(V3PersistenceVerificationError, match="duplicate"):
        await repository.get_batch(result.rule_version)


async def test_read_back_rejects_duplicate_fact_codes() -> None:
    from rule_reader.application.v3_persistence.canonical import batch_sha256_v3

    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_batch(prepared_batch)
    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    document = batch_collection.documents[result.rule_version]
    wrapper = deepcopy(document["requests"][0])
    # 两个不同 request_id 携带同一 factCode 的 wrapper 在身份闭包下不可构造,
    # 因此直接复制同一 wrapper 并同步顶层身份字段, 任何重复路径都必须被拒绝。
    duplicated = document["requests"] + [wrapper]
    document["requests"] = duplicated
    document["request_ids"] = [entry["request_id"] for entry in duplicated]
    document["request_count"] = len(duplicated)
    document["batch_sha256"] = batch_sha256_v3(
        (entry["request_id"], entry["payload_sha256"]) for entry in duplicated
    )

    with pytest.raises(V3PersistenceVerificationError):
        await repository.get_batch(result.rule_version)


async def test_read_back_rejects_wrapper_created_at_mismatch() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    _, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_batch(prepared_batch)
    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    document = batch_collection.documents[result.rule_version]
    shifted = document["created_at"].replace(year=document["created_at"].year - 1)
    document["requests"][0]["created_at"] = shifted

    with pytest.raises(V3PersistenceVerificationError, match="created_at"):
        await repository.get_batch(result.rule_version)


async def test_read_back_rejects_naive_stored_times() -> None:
    database = FakeDatabase()
    repository = _repository(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    prepared_rule, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)
    await repository.save_rule(prepared_rule)
    await repository.save_batch(prepared_batch)

    rule_collection = database.collections[RULE_VERSIONS_V3_COLLECTION]
    rule_collection.documents[result.rule_version]["stored_at"] = rule_collection.documents[
        result.rule_version
    ]["stored_at"].replace(tzinfo=None)
    with pytest.raises(V3PersistenceVerificationError, match="timezone"):
        await repository.get_rule(result.rule_version)

    batch_collection = database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION]
    batch_document = batch_collection.documents[result.rule_version]
    batch_document["created_at"] = batch_document["created_at"].replace(tzinfo=None)
    with pytest.raises(V3PersistenceVerificationError, match="timezone"):
        await repository.get_batch(result.rule_version)

    batch_document["created_at"] = FIXED_TIME.replace(microsecond=123000)
    batch_document["requests"][0]["created_at"] = FIXED_TIME.replace(
        microsecond=123000, tzinfo=None
    )
    with pytest.raises(V3PersistenceVerificationError, match="timezone"):
        await repository.get_batch(result.rule_version)


async def test_batch_recovery_after_rule_exists_inserts_only_batch() -> None:
    database = FakeDatabase()
    service = _service(database)
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    first = await service.persist(catalog, candidate, result, requests)
    rule_before = deepcopy(
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
    )

    # 模拟规则已写入而 batch 丢失的恢复路径: 删除 batch 后依靠规则写入幂等补写。
    del database.collections[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].documents[
        result.rule_version
    ]
    recovered = await service.persist(catalog, candidate, result, requests)

    assert first.rule_inserted is True and first.batch_inserted is True
    assert recovered.rule_inserted is False
    assert recovered.batch_inserted is True
    assert (
        database.collections[RULE_VERSIONS_V3_COLLECTION].documents[result.rule_version]
        == rule_before
    )
    stored_batch = await _repository(database).get_batch(result.rule_version)
    assert stored_batch is not None
    assert stored_batch.record.request_count == len(requests)
