from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest
from pymongo import AsyncMongoClient
from tests.integration.mongodb_test_guard import resolve_isolated_test_uri
from tests.support import QueueModel, valid_candidate_v2
from tests.v3_delivery_fixtures import synthetic_ready_delivery_v3

from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.application.v3_persistence.ports import V3PersistenceConflictError
from rule_reader.application.v3_persistence.service import (
    V3PersistenceService,
    prepare_v3_delivery,
)
from rule_reader.infrastructure.migrations import (
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
    FACT_BINDING_HANDOFFS_COLLECTION,
    RULE_VERSIONS_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
    RUNTIME_SCHEMA_VERSION,
    V3_PERSISTENCE_SCHEMA_VERSION,
    V3_RECOVERIES_COLLECTION,
    apply_migrations,
)
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository
from rule_reader.infrastructure.v3_persistence import MongoV3PersistenceRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mongodb_initialization_is_idempotent() -> None:
    uri = resolve_isolated_test_uri()
    database_name = f"rule_reader_test_{uuid.uuid4().hex}"
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    cleanup_database = False

    try:
        await client.admin.command({"ping": 1})
        database = client.get_database(database_name)
        # ping 成功后、任何写入之前武装清理: 任何中途失败也会删除该随机测试库。
        assert database_name.startswith("rule_reader_test_")
        cleanup_database = True

        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 4
        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 4

        collections = set(await database.list_collection_names())
        assert {
            "schema_migrations",
            "app_metadata",
            RULE_VERSIONS_COLLECTION,
            FACT_BINDING_HANDOFFS_COLLECTION,
            V3_RECOVERIES_COLLECTION,
        }.issubset(collections)
        migration_indexes = await database["schema_migrations"].index_information()
        metadata_indexes = await database["app_metadata"].index_information()
        version_indexes = await database[RULE_VERSIONS_COLLECTION].index_information()
        handoff_indexes = await database[FACT_BINDING_HANDOFFS_COLLECTION].index_information()
        v3_indexes = await database[V3_RECOVERIES_COLLECTION].index_information()
        assert migration_indexes["uq_schema_migrations_version"]["unique"] is True
        assert metadata_indexes["uq_app_metadata_key"]["unique"] is True
        assert version_indexes["uq_rule_versions_rule_version"]["unique"] is True
        assert "ix_rule_versions_rule_id_generated_at" in version_indexes
        assert "ix_rule_versions_source_sha256" in version_indexes
        assert handoff_indexes["_id_"]["key"] == [("_id", 1)]
        assert handoff_indexes["uq_fact_binding_handoffs_request_id"]["unique"] is True
        assert handoff_indexes["uq_fact_binding_handoffs_rule_version_fact_code"]["unique"] is True
        assert v3_indexes["uq_rule_structure_candidates_v3_candidate_id"]["unique"] is True
        assert v3_indexes["uq_rule_structure_candidates_v3_source_catalog"]["unique"] is True
        assert await database["schema_migrations"].count_documents({"version": 1}) == 1
        assert await database["schema_migrations"].count_documents({"version": 2}) == 1
        assert await database["schema_migrations"].count_documents({"version": 3}) == 1
        assert await database["schema_migrations"].count_documents({"version": 4}) == 1
        metadata = await database["app_metadata"].find_one({"key": "database_schema"})
        assert metadata is not None
        assert metadata["schema_version"] == 4

        parser = RuleParsingService(
            QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)]),
            max_characters=10_000,
            max_retries=0,
        )
        await parser.start()
        try:
            result = await parser.parse_text("# 测试规则", source_name="integration.md")
        finally:
            await parser.close()

        repository = MongoRuleVersionRepository(lambda: database)
        first = await repository.save(result)
        duplicate = await repository.save(result)
        stored = await repository.get(result.rule_version)

        assert first.inserted is True
        assert duplicate.inserted is False
        assert duplicate.record.stored_at == first.record.stored_at
        assert stored is not None
        assert stored.document == result
        assert await database[RULE_VERSIONS_COLLECTION].count_documents({}) == 1
    finally:
        if cleanup_database:
            assert database_name.startswith("rule_reader_test_")
            await client.drop_database(database_name)
        await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_v5_migrates_only_on_explicit_target() -> None:
    uri = resolve_isolated_test_uri()
    database_name = f"rule_reader_test_{uuid.uuid4().hex}"
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    cleanup_database = False

    try:
        await client.admin.command({"ping": 1})
        database = client.get_database(database_name)
        # ping 成功后、任何写入之前武装清理: 任何中途失败也会删除该随机测试库。
        assert database_name.startswith("rule_reader_test_")
        cleanup_database = True

        # 普通目标只到 v4, 不创建 V3 持久化集合。
        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 4
        collections = set(await database.list_collection_names())
        assert RULE_VERSIONS_V3_COLLECTION not in collections
        assert FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION not in collections

        await database[RULE_VERSIONS_COLLECTION].insert_one(
            {"_id": "runtime-seed", "rule_version": "runtime-seed"}
        )
        rules_before = await _find_all(database[RULE_VERSIONS_COLLECTION])
        indexes_before = await database[RULE_VERSIONS_COLLECTION].index_information()

        # 显式 target v5 才创建两个新集合与三个唯一索引, 历史集合不变。
        assert await apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION) == 5
        collections = set(await database.list_collection_names())
        assert RULE_VERSIONS_V3_COLLECTION in collections
        assert FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION in collections
        rule_v3_indexes = await database[RULE_VERSIONS_V3_COLLECTION].index_information()
        assert rule_v3_indexes["uq_rule_versions_v3_rule_version"]["unique"] is True
        assert rule_v3_indexes["uq_rule_versions_v3_source_catalog"]["unique"] is True
        assert rule_v3_indexes["uq_rule_versions_v3_source_catalog"]["key"] == [
            ("rule_set_id", 1),
            ("source_sha256", 1),
            ("catalog_digest", 1),
        ]
        batch_v3_indexes = await database[
            FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION
        ].index_information()
        assert batch_v3_indexes["uq_fact_binding_handoff_batches_v3_rule_version"]["unique"] is True
        assert await database["schema_migrations"].count_documents({"version": 5}) == 1
        metadata = await database["app_metadata"].find_one({"key": "database_schema"})
        assert metadata is not None
        assert metadata["schema_version"] == 5
        assert await _find_all(database[RULE_VERSIONS_COLLECTION]) == rules_before
        assert await database[RULE_VERSIONS_COLLECTION].index_information() == indexes_before

        # v5 库上普通目标正常启动: 不降级、不重写 migration 记录。
        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 5
        assert await database["schema_migrations"].count_documents({"version": 5}) == 1
        assert await _find_all(database[RULE_VERSIONS_COLLECTION]) == rules_before
    finally:
        if cleanup_database:
            assert database_name.startswith("rule_reader_test_")
            await client.drop_database(database_name)
        await client.close()


async def _find_all(collection: object) -> list[dict[str, object]]:
    return [document async for document in collection.find({}, sort=[("_id", 1)])]  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_v3_persistence_repositories_are_immutable() -> None:
    uri = resolve_isolated_test_uri()
    database_name = f"rule_reader_test_{uuid.uuid4().hex}"
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    cleanup_database = False

    try:
        await client.admin.command({"ping": 1})
        database = client.get_database(database_name)
        # ping 成功后、任何写入之前武装清理: 任何中途失败也会删除该随机测试库。
        assert database_name.startswith("rule_reader_test_")
        cleanup_database = True
        assert await apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION) == 5

        repository = MongoV3PersistenceRepository(lambda: database)
        catalog, candidate, result, requests = synthetic_ready_delivery_v3()
        prepared_rule, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)

        first_rule = await repository.save_rule(prepared_rule)
        second_rule = await repository.save_rule(prepared_rule)
        assert first_rule.inserted is True
        assert second_rule.inserted is False
        assert second_rule.record.stored_at == first_rule.record.stored_at

        first_batch = await repository.save_batch(prepared_batch)
        replay_batch = await repository.save_batch(prepared_batch)
        assert first_batch.inserted is True
        assert replay_batch.inserted is False
        assert replay_batch.record.created_at == first_batch.record.created_at

        # wrappers 乱序是非法 prepared record, 由仓储拒绝; 输入顺序无关性属于应用服务语义。
        malformed_batch = replace(
            prepared_batch,
            wrappers=tuple(reversed(prepared_batch.wrappers)),
        )
        with pytest.raises(V3PersistenceConflictError):
            await repository.save_batch(malformed_batch)

        conflicting_rule = replace(prepared_rule, payload_sha256="f" * 64)
        with pytest.raises(V3PersistenceConflictError):
            await repository.save_rule(conflicting_rule)
        assert await database[RULE_VERSIONS_V3_COLLECTION].count_documents({}) == 1
        assert await database[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].count_documents({}) == 1
        stored_rule = await repository.get_rule(result.rule_version)
        stored_batch = await repository.get_batch(result.rule_version)
        assert stored_rule is not None and stored_batch is not None
        assert stored_rule.record.payload_sha256 == prepared_rule.payload_sha256
        assert stored_batch.record.batch_sha256 == prepared_batch.batch_sha256
        assert stored_rule.record.stored_at == first_rule.record.stored_at
        assert stored_batch.record.created_at == first_batch.record.created_at
    finally:
        if cleanup_database:
            assert database_name.startswith("rule_reader_test_")
            await client.drop_database(database_name)
        await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_v3_persistence_service_replay_is_input_order_independent() -> None:
    uri = resolve_isolated_test_uri()
    database_name = f"rule_reader_test_{uuid.uuid4().hex}"
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    cleanup_database = False

    try:
        await client.admin.command({"ping": 1})
        database = client.get_database(database_name)
        # ping 成功后、任何写入之前武装清理: 任何中途失败也会删除该随机测试库。
        assert database_name.startswith("rule_reader_test_")
        cleanup_database = True
        assert await apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION) == 5

        repository = MongoV3PersistenceRepository(lambda: database)
        service = V3PersistenceService(repository, repository, repository)
        catalog, candidate, result, requests = synthetic_ready_delivery_v3()

        first = await service.persist(catalog, candidate, result, requests)
        rule_after_first = await repository.get_rule(result.rule_version)
        batch_after_first = await repository.get_batch(result.rule_version)
        assert rule_after_first is not None and batch_after_first is not None

        # 应用服务输入顺序无关: 乱序 requests 由 prepare_v3_delivery 统一排序后幂等重放。
        second = await service.persist(catalog, candidate, result, tuple(reversed(requests)))

        assert first.rule_inserted is True and first.batch_inserted is True
        assert second.rule_inserted is False and second.batch_inserted is False
        assert second.rule_payload_sha256 == first.rule_payload_sha256
        assert second.batch_sha256 == first.batch_sha256
        rule_after_replay = await repository.get_rule(result.rule_version)
        batch_after_replay = await repository.get_batch(result.rule_version)
        assert rule_after_replay == rule_after_first
        assert batch_after_replay == batch_after_first
    finally:
        if cleanup_database:
            assert database_name.startswith("rule_reader_test_")
            await client.drop_database(database_name)
        await client.close()
