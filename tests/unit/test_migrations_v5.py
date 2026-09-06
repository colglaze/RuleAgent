"""Offline Schema v5 migration tests over an in-memory async database fake."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import CollectionInvalid, DuplicateKeyError

from rule_reader.infrastructure.migrations import (
    APP_METADATA_COLLECTION,
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
    FACT_BINDING_HANDOFFS_COLLECTION,
    LATEST_SCHEMA_VERSION,
    RULE_VERSIONS_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
    RUNTIME_SCHEMA_VERSION,
    V3_PERSISTENCE_SCHEMA_VERSION,
    V3_RECOVERIES_COLLECTION,
    DatabaseSchemaTooNewError,
    apply_migrations,
)

EXPECTED_COLLECTIONS = {
    "schema_migrations",
    APP_METADATA_COLLECTION,
    RULE_VERSIONS_COLLECTION,
    FACT_BINDING_HANDOFFS_COLLECTION,
    V3_RECOVERIES_COLLECTION,
    RULE_VERSIONS_V3_COLLECTION,
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
}
RUNTIME_COLLECTIONS = EXPECTED_COLLECTIONS - {
    RULE_VERSIONS_V3_COLLECTION,
    FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION,
}


class FakeCollection:
    def __init__(self, store: FakeCollectionStore) -> None:
        self._store = store

    async def create_index(self, keys: Any, *, unique: bool = False, name: str) -> None:
        await asyncio.sleep(0)
        self._store.add_index(name, keys, unique)

    async def insert_one(self, document: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self._store.insert(document)

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> None:
        await asyncio.sleep(0)
        self._store.update(query, update, upsert=upsert)

    async def find_one(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return self._store.find_one(query, sort=sort)


class FakeMigrationsCollection(FakeCollection):
    """The schema_migrations collection uses the same fake surface."""


class FakeCollectionStore:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.indexes: dict[str, tuple[list[tuple[str, int]], bool]] = {}
        self._auto_id = 0

    def add_index(self, name: str, keys: Any, unique: bool) -> None:
        normalized = [(field, int(direction)) for field, direction in keys]
        existing = self.indexes.get(name)
        if existing is not None:
            assert existing == (normalized, unique), f"index {name} redefined differently"
            return
        self.indexes[name] = (normalized, unique)

    def _key_of(self, document: dict[str, Any], fields: list[tuple[str, int]]) -> Any:
        return tuple(document.get(field) for field, _ in fields)

    def insert(self, document: dict[str, Any]) -> None:
        for name, (fields, unique) in self.indexes.items():
            if not unique:
                continue
            key = self._key_of(document, fields)
            if any(self._key_of(item, fields) == key for item in self.documents):
                raise DuplicateKeyError(f"unique index {name} violated")
        stored = deepcopy(document)
        if "_id" not in stored:
            self._auto_id += 1
            stored["_id"] = f"auto-{self._auto_id}"
        self.documents.append(stored)

    def update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
    ) -> None:
        for item in self.documents:
            if all(item.get(key) == value for key, value in query.items()):
                item.update(deepcopy(update.get("$set", {})))
                return
        if upsert:
            merged = deepcopy(query)
            merged.update(deepcopy(update.get("$setOnInsert", {})))
            merged.update(deepcopy(update.get("$set", {})))
            self.insert(merged)

    def find_one(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.documents
            if all(item.get(key) == value for key, value in query.items())
        ]
        if sort:
            for field, direction in reversed(sort):
                matches.sort(key=lambda item: item.get(field), reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None


class FakeDatabase:
    def __init__(self) -> None:
        self.stores: dict[str, FakeCollectionStore] = {}
        self.created: list[str] = []

    async def list_collection_names(self, *, filter: dict[str, Any]) -> list[str]:
        await asyncio.sleep(0)
        name = filter["name"]
        return [name] if name in self.stores else []

    async def create_collection(self, name: str) -> None:
        await asyncio.sleep(0)
        if name in self.stores:
            raise CollectionInvalid(name)
        self.stores[name] = FakeCollectionStore()
        self.created.append(name)

    def get_collection(self, name: str) -> Any:
        store = self.stores.setdefault(name, FakeCollectionStore())
        if name == "schema_migrations":
            return FakeMigrationsCollection(store)
        return FakeCollection(store)

    def __getitem__(self, name: str) -> Any:
        return self.get_collection(name)


def _migration_records(database: FakeDatabase) -> list[dict[str, Any]]:
    return database.stores["schema_migrations"].documents


def _metadata() -> dict[str, Any]:
    return {"key": "database_schema", "schema_version": 1, "service": "rule-reader"}


def test_apply_migrations_defaults_to_runtime_schema_v4() -> None:
    database = FakeDatabase()

    result = asyncio.run(apply_migrations(database))  # type: ignore[arg-type]

    assert result == RUNTIME_SCHEMA_VERSION == 4
    assert set(database.stores) == RUNTIME_COLLECTIONS
    assert RULE_VERSIONS_V3_COLLECTION not in database.stores
    assert FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION not in database.stores
    assert [record["version"] for record in _migration_records(database)] == [1, 2, 3, 4]
    metadata = database.stores[APP_METADATA_COLLECTION].find_one({"key": "database_schema"})
    assert metadata is not None
    assert metadata["schema_version"] == 4


def test_schema_v5_first_run_creates_exactly_two_collections_and_indexes() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())

    result = asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )

    assert result == LATEST_SCHEMA_VERSION == 5
    assert set(database.stores) == EXPECTED_COLLECTIONS
    rule_indexes = database.stores[RULE_VERSIONS_V3_COLLECTION].indexes
    assert rule_indexes["uq_rule_versions_v3_rule_version"] == ([("rule_version", 1)], True)
    assert rule_indexes["uq_rule_versions_v3_source_catalog"] == (
        [("rule_set_id", 1), ("source_sha256", 1), ("catalog_digest", 1)],
        True,
    )
    batch_indexes = database.stores[FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION].indexes
    assert batch_indexes["uq_fact_binding_handoff_batches_v3_rule_version"] == (
        [("rule_version", 1)],
        True,
    )
    assert database.stores[APP_METADATA_COLLECTION].documents[0]["schema_version"] == 5
    assert [record["version"] for record in _migration_records(database)] == [1, 2, 3, 4, 5]


def test_schema_v5_repeat_run_is_idempotent() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())
    asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )
    records_before = deepcopy(_migration_records(database))
    metadata_before = deepcopy(database.stores[APP_METADATA_COLLECTION].documents)

    result = asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )

    assert result == 5
    assert _migration_records(database) == records_before
    assert database.stores[APP_METADATA_COLLECTION].documents == metadata_before
    assert database.created.count(RULE_VERSIONS_V3_COLLECTION) == 1
    assert database.created.count(FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION) == 1


def test_schema_v5_concurrent_initialization_stays_idempotent() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())

    async def run_concurrently() -> tuple[int, int]:
        return await asyncio.gather(
            apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION),  # type: ignore[arg-type]
            apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION),  # type: ignore[arg-type]
        )

    first, second = asyncio.run(run_concurrently())

    assert first == 5 and second == 5
    assert [record["version"] for record in _migration_records(database)] == [1, 2, 3, 4, 5]
    assert database.created.count(RULE_VERSIONS_V3_COLLECTION) == 1
    assert database.created.count(FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION) == 1


def test_schema_v5_does_not_touch_v1_v4_collections_or_existing_documents() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())
    asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )
    legacy_names = (
        RULE_VERSIONS_COLLECTION,
        FACT_BINDING_HANDOFFS_COLLECTION,
        V3_RECOVERIES_COLLECTION,
    )
    for name in legacy_names:
        database.stores[name].insert({"_id": f"{name}-seed", "seed": name})
    indexes_before = {name: deepcopy(database.stores[name].indexes) for name in legacy_names}
    documents_before = {name: deepcopy(database.stores[name].documents) for name in legacy_names}

    asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )

    for name in legacy_names:
        assert database.stores[name].indexes == indexes_before[name]
        assert database.stores[name].documents == documents_before[name]


def test_apply_migrations_rejects_unsupported_target_before_any_write() -> None:
    for bad_target in (0, 1, 3, 6, 99):
        database = FakeDatabase()
        with pytest.raises(ValueError, match="target"):
            asyncio.run(
                apply_migrations(database, target_version=bad_target)  # type: ignore[arg-type]
            )
        assert database.stores == {}
        assert database.created == []


def test_runtime_target_on_v5_database_starts_normally_without_rewrite() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())
    asyncio.run(
        apply_migrations(database, target_version=V3_PERSISTENCE_SCHEMA_VERSION)  # type: ignore[arg-type]
    )
    records_before = deepcopy(_migration_records(database))
    metadata_before = deepcopy(database.stores[APP_METADATA_COLLECTION].documents)

    result = asyncio.run(apply_migrations(database))  # type: ignore[arg-type]

    assert result == 5
    assert _migration_records(database) == records_before
    assert database.stores[APP_METADATA_COLLECTION].documents == metadata_before
    assert database.created.count(RULE_VERSIONS_V3_COLLECTION) == 1
    assert database.created.count(FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION) == 1


def test_apply_migrations_fails_fast_when_database_is_newer() -> None:
    database = FakeDatabase()
    database.stores[APP_METADATA_COLLECTION] = FakeCollectionStore()
    database.stores[APP_METADATA_COLLECTION].insert(_metadata())
    migrations_store = FakeCollectionStore()
    database.stores["schema_migrations"] = migrations_store
    migrations_store.insert({"version": 99, "name": "future"})

    with pytest.raises(DatabaseSchemaTooNewError):
        asyncio.run(apply_migrations(database))  # type: ignore[arg-type]


def test_mongo_manager_initialize_targets_runtime_schema_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rule_reader.core.config import Settings
    from rule_reader.infrastructure import mongodb

    calls: list[int] = []

    async def fake_apply_migrations(database: object, *, target_version: int) -> int:
        del database
        calls.append(target_version)
        return target_version

    monkeypatch.setattr(mongodb, "apply_migrations", fake_apply_migrations)
    manager = mongodb.MongoManager(Settings(_env_file=None))
    manager._database = object()  # type: ignore[assignment]

    assert asyncio.run(manager.initialize()) == RUNTIME_SCHEMA_VERSION
    assert (
        asyncio.run(manager.initialize(target_version=V3_PERSISTENCE_SCHEMA_VERSION))
        == V3_PERSISTENCE_SCHEMA_VERSION
    )
    assert calls == [RUNTIME_SCHEMA_VERSION, V3_PERSISTENCE_SCHEMA_VERSION]


def test_fake_collection_store_reports_first_write_time() -> None:
    store = FakeCollectionStore()
    store.add_index("uq", [("rule_version", 1)], True)
    now = datetime(2026, 9, 6, tzinfo=UTC)
    store.insert({"_id": "v1", "rule_version": "v1", "stored_at": now})
    with pytest.raises(DuplicateKeyError):
        store.insert({"_id": "v2", "rule_version": "v1", "stored_at": now})
    assert store.documents[0]["stored_at"] == now
