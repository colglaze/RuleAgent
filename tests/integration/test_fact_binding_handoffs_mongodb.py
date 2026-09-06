from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pymongo import ASCENDING, AsyncMongoClient
from tests.integration.mongodb_test_guard import resolve_isolated_test_uri
from tests.report_release_fixtures import historical_persisted_report_release_rule
from tests.support import valid_candidate

from rule_reader.application.fact_binding_handoffs.canonical import (
    canonical_payload_sha256,
    fact_binding_payload,
)
from rule_reader.application.fact_binding_handoffs.ports import (
    FactBindingHandoffConflictError,
    FactBindingHandoffSchemaUnsupportedError,
    PreparedFactBindingHandoff,
)
from rule_reader.application.fact_binding_handoffs.service import (
    FactBindingHandoffService,
    load_checked_in_fact_binding_schema,
)
from rule_reader.domain.rules.bindings_v2 import (
    FactBindingRequestV2,
    build_fact_binding_requests_v2,
)
from rule_reader.domain.rules.models import (
    ParserMetadata,
    RuleCandidate,
    RuleParseResult,
    SourceMetadata,
)
from rule_reader.domain.rules.v2 import RuleParseResultV2
from rule_reader.domain.rules.validation import enrich_candidate, validate_candidate
from rule_reader.infrastructure.fact_binding_handoffs import (
    MongoFactBindingHandoffRepository,
)
from rule_reader.infrastructure.migrations import (
    APP_METADATA_COLLECTION,
    FACT_BINDING_HANDOFFS_COLLECTION,
    MIGRATIONS,
    MIGRATIONS_COLLECTION,
    RULE_VERSIONS_COLLECTION,
    RUNTIME_SCHEMA_VERSION,
    apply_migrations,
)
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository

FIXED_TIME = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)


async def _initialize_schema_v2(database: object) -> None:
    migrations = database[MIGRATIONS_COLLECTION]
    await migrations.create_index(
        [("version", ASCENDING)],
        unique=True,
        name="uq_schema_migrations_version",
    )
    for migration in MIGRATIONS:
        if migration.version > 2:
            break
        await migration.apply(database)
        await migrations.insert_one(
            {
                "version": migration.version,
                "name": migration.name,
                "applied_at": FIXED_TIME,
                "service_version": "0.7.0",
            }
        )


async def _all_documents(collection: object) -> list[dict[str, object]]:
    return [document async for document in collection.find({}, sort=[("_id", 1)])]


def _reviewed_rule() -> RuleParseResultV2:
    return historical_persisted_report_release_rule()


def _legacy_rule() -> RuleParseResult:
    candidate = RuleCandidate.model_validate(valid_candidate(rule_id="LEGACY_HANDOFF_001"))
    validate_candidate(candidate)
    return RuleParseResult(
        rule_version="LEGACY_HANDOFF_001@20260818T000000000000Z-000000000000",
        generated_at=datetime(2026, 8, 18, tzinfo=UTC),
        parser=ParserMetadata(
            parser_version="0.3.0",
            prompt_version="rule-parser-v1",
            model="legacy",
        ),
        source=SourceMetadata(
            source_name="legacy.md",
            sha256="0" * 64,
            character_count=10,
        ),
        rule=enrich_candidate(candidate),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_v3_persists_immutable_33_request_handoff() -> None:
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
        await _initialize_schema_v2(database)
        metadata_v2 = await database[APP_METADATA_COLLECTION].find_one({"key": "database_schema"})
        assert metadata_v2 is not None
        assert metadata_v2["schema_version"] == 2
        assert FACT_BINDING_HANDOFFS_COLLECTION not in await database.list_collection_names()

        rule_repository = MongoRuleVersionRepository(lambda: database)
        reviewed = _reviewed_rule()
        legacy = _legacy_rule()
        await rule_repository.save(reviewed)
        await rule_repository.save(legacy)
        rules_before_migration = deepcopy(await _all_documents(database[RULE_VERSIONS_COLLECTION]))

        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 4
        assert await apply_migrations(database, target_version=RUNTIME_SCHEMA_VERSION) == 4
        assert await database[MIGRATIONS_COLLECTION].count_documents({"version": 3}) == 1
        metadata_v3 = await database[APP_METADATA_COLLECTION].find_one({"key": "database_schema"})
        assert metadata_v3 is not None
        assert metadata_v3["schema_version"] == 4
        assert await _all_documents(database[RULE_VERSIONS_COLLECTION]) == (rules_before_migration)

        handoff_collection = database[FACT_BINDING_HANDOFFS_COLLECTION]
        indexes = await handoff_collection.index_information()
        assert indexes["_id_"]["key"] == [("_id", 1)]
        assert indexes["uq_fact_binding_handoffs_request_id"]["unique"] is True
        assert indexes["uq_fact_binding_handoffs_rule_version_fact_code"]["key"] == [
            ("rule_version", 1),
            ("fact_code", 1),
        ]
        assert indexes["uq_fact_binding_handoffs_rule_version_fact_code"]["unique"] is True

        handoff_repository = MongoFactBindingHandoffRepository(
            lambda: database,
            clock=lambda: FIXED_TIME,
        )
        schema = load_checked_in_fact_binding_schema()
        service = FactBindingHandoffService(
            rule_repository,
            handoff_repository,
            schema,
        )
        expected_requests = {
            request.request_id: request for request in build_fact_binding_requests_v2(reviewed)
        }

        first = await service.persist(reviewed.rule_version)
        assert len(first.records) == 33
        assert first.inserted_count == 33
        assert first.existing_count == 0
        assert first.blocking_request_count == 33
        assert first.source_rule_unchanged is True
        assert (
            await handoff_collection.count_documents({"rule_version": reviewed.rule_version}) == 33
        )

        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        raw_after_first = deepcopy(await _all_documents(handoff_collection))
        assert len(raw_after_first) == 33
        for document in raw_after_first:
            payload = document["payload"]
            request = FactBindingRequestV2.model_validate(payload)
            validator.validate(payload)
            expected = expected_requests[request.request_id]
            assert document["_id"] == request.request_id
            assert document["request_id"] == request.request_id
            assert document["rule_version"] == reviewed.rule_version
            assert document["fact_code"] == request.fact.fact_code
            assert document["contract_version"] == "2.0.0"
            assert document["payload_sha256"] == canonical_payload_sha256(payload)
            assert request.uncertainties == expected.uncertainties
            assert any(item.impact.value == "blocking" for item in request.uncertainties)

        second = await service.persist(reviewed.rule_version)
        assert second.inserted_count == 0
        assert second.existing_count == 33
        assert await _all_documents(handoff_collection) == raw_after_first

        original_record = first.records[0]
        changed_payload = fact_binding_payload(original_record.payload)
        changed_payload["fact"]["description"] += " conflict variant"
        changed_request = FactBindingRequestV2.model_validate(changed_payload)
        conflicting = PreparedFactBindingHandoff(
            request_id=changed_request.request_id,
            rule_version=changed_request.rule_ref.rule_version,
            fact_code=changed_request.fact.fact_code,
            contract_version=changed_request.contract_version,
            payload_sha256=canonical_payload_sha256(changed_payload),
            payload=changed_request,
        )
        with pytest.raises(FactBindingHandoffConflictError):
            await handoff_repository.save_many((conflicting,))
        assert await _all_documents(handoff_collection) == raw_after_first

        with pytest.raises(FactBindingHandoffSchemaUnsupportedError):
            await service.persist(legacy.rule_version)
        assert await handoff_collection.count_documents({"rule_version": legacy.rule_version}) == 0
        assert await _all_documents(database[RULE_VERSIONS_COLLECTION]) == (rules_before_migration)
        assert await database[RULE_VERSIONS_COLLECTION].count_documents({}) == 2
    finally:
        if cleanup_database:
            assert database_name.startswith("rule_reader_test_")
            await client.drop_database(database_name)
        await client.close()
