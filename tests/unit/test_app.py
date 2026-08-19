from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from tests.support import QueueModel, valid_candidate, valid_candidate_v2

from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.application.rule_versions.ports import (
    RuleVersionPersistenceError,
    SavedRuleVersion,
    StoredRuleVersion,
)
from rule_reader.core.config import Settings
from rule_reader.domain.rules.models import (
    ParserMetadata,
    RuleCandidate,
    RuleParseResult,
    SourceMetadata,
)
from rule_reader.domain.rules.validation import enrich_candidate, validate_candidate
from rule_reader.main import create_app


@dataclass
class FakeDatabase:
    fail_ping: bool = False
    start_calls: int = 0
    initialize_calls: int = 0
    ping_calls: int = 0
    close_calls: int = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def initialize(self) -> int:
        self.initialize_calls += 1
        return 2

    async def ping(self) -> None:
        self.ping_calls += 1
        if self.fail_ping:
            raise RuntimeError("unavailable")

    async def close(self) -> None:
        self.close_calls += 1


@dataclass
class FakeRuleVersionRepository:
    fail_save: bool = False
    save_calls: int = 0

    def __post_init__(self) -> None:
        self.records: dict[str, StoredRuleVersion] = {}

    async def save(self, result: object) -> SavedRuleVersion:
        assert hasattr(result, "rule_version")
        self.save_calls += 1
        if self.fail_save:
            raise RuleVersionPersistenceError("unavailable")
        existing = self.records.get(result.rule_version)
        if existing is not None:
            return SavedRuleVersion(record=existing, inserted=False)
        record = StoredRuleVersion(
            document=result,
            stored_at=datetime(2026, 8, 18, 9, 30, tzinfo=UTC),
        )
        self.records[result.rule_version] = record
        return SavedRuleVersion(record=record, inserted=True)

    async def get(self, rule_version: str) -> StoredRuleVersion | None:
        return self.records.get(rule_version)


async def request(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=payload)


@pytest.mark.asyncio
async def test_service_lifecycle_and_health_endpoints() -> None:
    database = FakeDatabase()
    app = create_app(settings=Settings(_env_file=None), database=database)

    async with app.router.lifespan_context(app):
        live = await request(app, "GET", "/health/live")
        ready = await request(app, "GET", "/health/ready")
        assert live.json()["status"] == "ok"
        assert ready.status_code == 200
        assert ready.json()["schema_version"] == 2
        assert database.start_calls == 1
        assert database.initialize_calls == 1

    assert database.close_calls == 1


@pytest.mark.asyncio
async def test_readiness_returns_503_without_leaking_error() -> None:
    database = FakeDatabase(fail_ping=True)
    app = create_app(settings=Settings(_env_file=None), database=database)

    async with app.router.lifespan_context(app):
        response = await request(app, "GET", "/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "service": "RuleReader",
        "version": "0.4.0",
        "schema_version": 2,
    }


@pytest.mark.asyncio
async def test_config_endpoint_is_sanitized() -> None:
    database = FakeDatabase()
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://user:password@localhost:27017/",
        deepseek_api_key="secret-key",
    )
    app = create_app(settings=settings, database=database)

    async with app.router.lifespan_context(app):
        response = await request(app, "GET", "/api/v1/config")

    assert response.status_code == 200
    assert response.json()["mongodb"]["database"] == "rule_reader"
    assert response.json()["rule_parser"]["max_characters"] == 100000
    assert "password" not in response.text
    assert "secret-key" not in response.text


@pytest.mark.asyncio
async def test_parse_rule_endpoint_returns_valid_json_document() -> None:
    database = FakeDatabase()
    repository = FakeRuleVersionRepository()
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    parser = RuleParsingService(model, max_characters=10_000, max_retries=0)
    app = create_app(
        settings=Settings(_env_file=None),
        database=database,
        rule_parser=parser,
        rule_version_repository=repository,
    )

    async with app.router.lifespan_context(app):
        response = await request(
            app,
            "POST",
            "/api/v1/rules/parse",
            {"text": "# 测试规则\n完成后释放。", "sourceName": "inline.md"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["schemaVersion"] == "2.0.0"
    assert response.json()["rule"]["ruleId"] == "TEST_RELEASE_002"
    assert response.json()["status"] == "draft"
    assert response.json()["executable"] is False
    assert repository.save_calls == 0


@pytest.mark.asyncio
async def test_parse_rule_endpoint_can_persist_and_read_exact_version() -> None:
    database = FakeDatabase()
    repository = FakeRuleVersionRepository()
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    parser = RuleParsingService(model, max_characters=10_000, max_retries=0)
    app = create_app(
        settings=Settings(_env_file=None),
        database=database,
        rule_parser=parser,
        rule_version_repository=repository,
    )

    async with app.router.lifespan_context(app):
        parsed = await request(
            app,
            "POST",
            "/api/v1/rules/parse",
            {
                "text": "# 测试规则\n完成后释放。",
                "sourceName": "inline.md",
                "persist": True,
            },
        )
        rule_version = parsed.json()["ruleVersion"]
        stored = await request(
            app,
            "GET",
            f"/api/v1/rules/versions/{rule_version}",
        )
        bindings = await request(
            app,
            "GET",
            f"/api/v1/rules/versions/{rule_version}/fact-binding-requests",
        )

    assert parsed.status_code == 200
    assert repository.save_calls == 1
    assert stored.status_code == 200
    assert stored.json()["ruleVersion"] == rule_version
    assert stored.json()["document"] == parsed.json()
    assert stored.json()["storedAt"] == "2026-08-18T09:30:00Z"
    assert bindings.status_code == 200
    binding_payload = bindings.json()
    assert binding_payload["ruleVersion"] == rule_version
    assert {
        item["fact"]["factCode"] for item in binding_payload["requests"]
    } == {
        "task.status",
        "task.received_amount",
        "task.base_fee",
        "task.extra_fee",
        "task.settlement_fee",
    }


@pytest.mark.asyncio
async def test_schema_v1_rule_can_be_read_but_not_exported_to_agent2() -> None:
    database = FakeDatabase()
    repository = FakeRuleVersionRepository()
    candidate = RuleCandidate.model_validate(valid_candidate(rule_id="LEGACY_RELEASE_001"))
    validate_candidate(candidate)
    legacy = RuleParseResult(
        rule_version="LEGACY_RELEASE_001@20260818T000000000000Z-000000000000",
        generated_at="2026-08-18T00:00:00Z",
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
    await repository.save(legacy)
    app = create_app(
        settings=Settings(_env_file=None),
        database=database,
        rule_version_repository=repository,
    )

    async with app.router.lifespan_context(app):
        stored = await request(
            app,
            "GET",
            f"/api/v1/rules/versions/{legacy.rule_version}",
        )
        binding = await request(
            app,
            "GET",
            f"/api/v1/rules/versions/{legacy.rule_version}/fact-binding-requests",
        )

    assert stored.status_code == 200
    assert stored.json()["document"]["schemaVersion"] == "1.0.0"
    assert binding.status_code == 409
    assert binding.json()["error"]["code"] == "RULE_SCHEMA_UNSUPPORTED_FOR_BINDING"


@pytest.mark.asyncio
async def test_get_rule_version_returns_404_when_missing() -> None:
    database = FakeDatabase()
    repository = FakeRuleVersionRepository()
    app = create_app(
        settings=Settings(_env_file=None),
        database=database,
        rule_version_repository=repository,
    )

    async with app.router.lifespan_context(app):
        response = await request(
            app,
            "GET",
            "/api/v1/rules/versions/MISSING@20260818T000000000000Z-000000000000",
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RULE_VERSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_parse_rule_endpoint_reports_persistence_failure() -> None:
    database = FakeDatabase()
    repository = FakeRuleVersionRepository(fail_save=True)
    model = QueueModel([json.dumps(valid_candidate_v2(), ensure_ascii=False)])
    parser = RuleParsingService(model, max_characters=10_000, max_retries=0)
    app = create_app(
        settings=Settings(_env_file=None),
        database=database,
        rule_parser=parser,
        rule_version_repository=repository,
    )

    async with app.router.lifespan_context(app):
        response = await request(
            app,
            "POST",
            "/api/v1/rules/parse",
            {"text": "# 测试规则", "persist": True},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RULE_PERSISTENCE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_parse_rule_endpoint_reports_missing_provider_configuration() -> None:
    database = FakeDatabase()
    app = create_app(settings=Settings(_env_file=None), database=database)

    async with app.router.lifespan_context(app):
        response = await request(
            app,
            "POST",
            "/api/v1/rules/parse",
            {"text": "# 测试规则\n完成后释放。", "sourceName": "inline.md"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert "api_key" not in response.text.lower()
