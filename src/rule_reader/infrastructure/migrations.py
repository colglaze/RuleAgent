"""Versioned, idempotent MongoDB schema initialization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, DuplicateKeyError

from rule_reader.core.version import __version__

Document = dict[str, Any]
Database = AsyncDatabase[Document]
MigrationFunction = Callable[[Database], Awaitable[None]]
LATEST_SCHEMA_VERSION = 2
MIGRATIONS_COLLECTION = "schema_migrations"
APP_METADATA_COLLECTION = "app_metadata"
RULE_VERSIONS_COLLECTION = "rule_versions"


class DatabaseSchemaTooNewError(RuntimeError):
    """Raised when the database schema is newer than this service."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction


async def _ensure_collection(database: Database, name: str) -> None:
    existing = await database.list_collection_names(filter={"name": name})
    if existing:
        return
    try:
        await database.create_collection(name)
    except CollectionInvalid:
        # Another process may have created the collection after the list operation.
        return


async def _apply_v1(database: Database) -> None:
    await _ensure_collection(database, APP_METADATA_COLLECTION)
    metadata = database.get_collection(APP_METADATA_COLLECTION)
    await metadata.create_index(
        [("key", ASCENDING)],
        unique=True,
        name="uq_app_metadata_key",
    )
    now = datetime.now(UTC)
    await metadata.update_one(
        {"key": "database_schema"},
        {
            "$set": {
                "schema_version": 1,
                "service": "rule-reader",
                "service_version": __version__,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def _apply_v2(database: Database) -> None:
    await _ensure_collection(database, RULE_VERSIONS_COLLECTION)
    rule_versions = database.get_collection(RULE_VERSIONS_COLLECTION)
    await rule_versions.create_index(
        [("rule_version", ASCENDING)],
        unique=True,
        name="uq_rule_versions_rule_version",
    )
    await rule_versions.create_index(
        [("rule_id", ASCENDING), ("generated_at", DESCENDING)],
        name="ix_rule_versions_rule_id_generated_at",
    )
    await rule_versions.create_index(
        [("source_sha256", ASCENDING)],
        name="ix_rule_versions_source_sha256",
    )
    now = datetime.now(UTC)
    await database.get_collection(APP_METADATA_COLLECTION).update_one(
        {"key": "database_schema"},
        {
            "$set": {
                "schema_version": 2,
                "service": "rule-reader",
                "service_version": __version__,
                "updated_at": now,
            }
        },
        upsert=False,
    )


MIGRATIONS = (
    Migration(version=1, name="bootstrap_metadata", apply=_apply_v1),
    Migration(version=2, name="create_rule_versions", apply=_apply_v2),
)


async def apply_migrations(database: Database) -> int:
    """Apply every missing migration and return the resulting schema version."""

    migrations = database.get_collection(MIGRATIONS_COLLECTION)
    await migrations.create_index(
        [("version", ASCENDING)],
        unique=True,
        name="uq_schema_migrations_version",
    )

    latest_record = await migrations.find_one({}, sort=[("version", DESCENDING)])
    if latest_record is not None and latest_record.get("version", 0) > LATEST_SCHEMA_VERSION:
        raise DatabaseSchemaTooNewError(
            "MongoDB schema is newer than this RuleReader service version"
        )

    for migration in MIGRATIONS:
        if await migrations.find_one({"version": migration.version}) is not None:
            continue

        await migration.apply(database)
        try:
            await migrations.insert_one(
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(UTC),
                    "service_version": __version__,
                }
            )
        except DuplicateKeyError:
            # A concurrent service instance completed the same idempotent migration.
            continue

    return LATEST_SCHEMA_VERSION
