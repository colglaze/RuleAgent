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
# Ordinary application use cases (serve, init-db, V1/V2 persistence, V2 handoffs, V3
# recovery) only migrate up to the runtime schema; Schema v5 is reserved for the
# explicitly authorized V3 delivery persistence script (BUG-20260906-03).
RUNTIME_SCHEMA_VERSION = 4
V3_PERSISTENCE_SCHEMA_VERSION = 5
LATEST_SCHEMA_VERSION = 5
MIGRATIONS_COLLECTION = "schema_migrations"
APP_METADATA_COLLECTION = "app_metadata"
RULE_VERSIONS_COLLECTION = "rule_versions"
FACT_BINDING_HANDOFFS_COLLECTION = "fact_binding_handoffs"
V3_RECOVERIES_COLLECTION = "rule_structure_candidates_v3"
RULE_VERSIONS_V3_COLLECTION = "rule_versions_v3"
FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION = "fact_binding_handoff_batches_v3"


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


async def _apply_v3(database: Database) -> None:
    await _ensure_collection(database, FACT_BINDING_HANDOFFS_COLLECTION)
    handoffs = database.get_collection(FACT_BINDING_HANDOFFS_COLLECTION)
    await handoffs.create_index(
        [("request_id", ASCENDING)],
        unique=True,
        name="uq_fact_binding_handoffs_request_id",
    )
    await handoffs.create_index(
        [("rule_version", ASCENDING), ("fact_code", ASCENDING)],
        unique=True,
        name="uq_fact_binding_handoffs_rule_version_fact_code",
    )
    now = datetime.now(UTC)
    await database.get_collection(APP_METADATA_COLLECTION).update_one(
        {"key": "database_schema"},
        {
            "$set": {
                "schema_version": 3,
                "service": "rule-reader",
                "service_version": __version__,
                "updated_at": now,
            }
        },
        upsert=False,
    )


async def _apply_v4(database: Database) -> None:
    await _ensure_collection(database, V3_RECOVERIES_COLLECTION)
    recoveries = database.get_collection(V3_RECOVERIES_COLLECTION)
    await recoveries.create_index(
        [("candidate_id", ASCENDING)],
        unique=True,
        name="uq_rule_structure_candidates_v3_candidate_id",
    )
    await recoveries.create_index(
        [
            ("rule_set_id", ASCENDING),
            ("rule_block_sha256", ASCENDING),
            ("catalog_digest", ASCENDING),
        ],
        unique=True,
        name="uq_rule_structure_candidates_v3_source_catalog",
    )
    now = datetime.now(UTC)
    await database.get_collection(APP_METADATA_COLLECTION).update_one(
        {"key": "database_schema"},
        {
            "$set": {
                "schema_version": 4,
                "service": "rule-reader",
                "service_version": __version__,
                "updated_at": now,
            }
        },
        upsert=False,
    )


async def _apply_v5(database: Database) -> None:
    await _ensure_collection(database, RULE_VERSIONS_V3_COLLECTION)
    rule_versions_v3 = database.get_collection(RULE_VERSIONS_V3_COLLECTION)
    await rule_versions_v3.create_index(
        [("rule_version", ASCENDING)],
        unique=True,
        name="uq_rule_versions_v3_rule_version",
    )
    await rule_versions_v3.create_index(
        [
            ("rule_set_id", ASCENDING),
            ("source_sha256", ASCENDING),
            ("catalog_digest", ASCENDING),
        ],
        unique=True,
        name="uq_rule_versions_v3_source_catalog",
    )
    await _ensure_collection(database, FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION)
    batches_v3 = database.get_collection(FACT_BINDING_HANDOFF_BATCHES_V3_COLLECTION)
    await batches_v3.create_index(
        [("rule_version", ASCENDING)],
        unique=True,
        name="uq_fact_binding_handoff_batches_v3_rule_version",
    )
    now = datetime.now(UTC)
    await database.get_collection(APP_METADATA_COLLECTION).update_one(
        {"key": "database_schema"},
        {
            "$set": {
                "schema_version": 5,
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
    Migration(version=3, name="create_fact_binding_handoffs", apply=_apply_v3),
    Migration(version=4, name="create_rule_structure_candidates_v3", apply=_apply_v4),
    Migration(version=5, name="create_rule_versions_v3_and_handoff_batches_v3", apply=_apply_v5),
)


async def apply_migrations(
    database: Database,
    *,
    target_version: int = RUNTIME_SCHEMA_VERSION,
) -> int:
    """Apply missing migrations up to ``target_version`` and return the effective version.

    Only :data:`RUNTIME_SCHEMA_VERSION` and :data:`V3_PERSISTENCE_SCHEMA_VERSION` are
    accepted targets; anything else fails before touching the database. The database is
    never downgraded: when it is already at a higher recorded version, that version is
    returned and no migration is rewritten.
    """

    if target_version not in (RUNTIME_SCHEMA_VERSION, V3_PERSISTENCE_SCHEMA_VERSION):
        raise ValueError(
            f"Unsupported migration target version: {target_version}; "
            f"expected {RUNTIME_SCHEMA_VERSION} or {V3_PERSISTENCE_SCHEMA_VERSION}"
        )

    migrations = database.get_collection(MIGRATIONS_COLLECTION)
    await migrations.create_index(
        [("version", ASCENDING)],
        unique=True,
        name="uq_schema_migrations_version",
    )

    latest_record = await migrations.find_one({}, sort=[("version", DESCENDING)])
    recorded_version = 0
    if latest_record is not None:
        raw_version = latest_record.get("version", 0)
        recorded_version = raw_version if isinstance(raw_version, int) else 0
    if recorded_version > LATEST_SCHEMA_VERSION:
        raise DatabaseSchemaTooNewError(
            "MongoDB schema is newer than this RuleReader service version"
        )

    for migration in MIGRATIONS:
        if migration.version > target_version:
            break
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

    return max(target_version, recorded_version)
