from __future__ import annotations

import json
import os
import uuid

import pytest
from pymongo import AsyncMongoClient
from tests.support import QueueModel, valid_candidate

from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.core.config import Settings
from rule_reader.infrastructure.migrations import RULE_VERSIONS_COLLECTION, apply_migrations
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mongodb_initialization_is_idempotent() -> None:
    uri = os.getenv("RULEREADER_TEST_MONGODB_URI") or Settings().mongodb_uri
    database_name = f"rule_reader_test_{uuid.uuid4().hex}"
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    database_created = False

    try:
        await client.admin.command({"ping": 1})
        database = client.get_database(database_name)

        assert await apply_migrations(database) == 2
        database_created = True
        assert await apply_migrations(database) == 2

        collections = set(await database.list_collection_names())
        assert {"schema_migrations", "app_metadata", RULE_VERSIONS_COLLECTION}.issubset(
            collections
        )
        migration_indexes = await database["schema_migrations"].index_information()
        metadata_indexes = await database["app_metadata"].index_information()
        version_indexes = await database[RULE_VERSIONS_COLLECTION].index_information()
        assert migration_indexes["uq_schema_migrations_version"]["unique"] is True
        assert metadata_indexes["uq_app_metadata_key"]["unique"] is True
        assert version_indexes["uq_rule_versions_rule_version"]["unique"] is True
        assert "ix_rule_versions_rule_id_generated_at" in version_indexes
        assert "ix_rule_versions_source_sha256" in version_indexes
        assert await database["schema_migrations"].count_documents({"version": 1}) == 1
        assert await database["schema_migrations"].count_documents({"version": 2}) == 1
        metadata = await database["app_metadata"].find_one({"key": "database_schema"})
        assert metadata is not None
        assert metadata["schema_version"] == 2

        parser = RuleParsingService(
            QueueModel([json.dumps(valid_candidate(), ensure_ascii=False)]),
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
        if database_created and database_name.startswith("rule_reader_test_"):
            await client.drop_database(database_name)
        await client.close()
