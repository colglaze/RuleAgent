"""MongoDB connection lifecycle."""

from __future__ import annotations

from typing import Any, Protocol

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from rule_reader.core.config import Settings
from rule_reader.infrastructure.migrations import (
    RUNTIME_SCHEMA_VERSION,
    apply_migrations,
)

Document = dict[str, Any]


class DatabaseLifecycle(Protocol):
    async def start(self) -> None: ...

    async def initialize(self) -> int: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class MongoStartupError(RuntimeError):
    """A sanitized MongoDB startup failure."""


class MongoManager:
    """Own one async client for one FastAPI event loop."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncMongoClient[Document] | None = None
        self._database: AsyncDatabase[Document] | None = None

    @property
    def database(self) -> AsyncDatabase[Document]:
        if self._database is None:
            raise RuntimeError("MongoDB manager has not started")
        return self._database

    async def start(self) -> None:
        if self._client is not None:
            return

        client: AsyncMongoClient[Document] = AsyncMongoClient(
            self._settings.mongodb_uri,
            appname=self._settings.app_name,
            tz_aware=True,
            serverSelectionTimeoutMS=self._settings.mongodb_server_selection_timeout_ms,
            connectTimeoutMS=self._settings.mongodb_connect_timeout_ms,
        )
        self._client = client
        self._database = client.get_database(self._settings.mongodb_database)
        try:
            await self.ping()
        except Exception as error:
            await self.close()
            raise MongoStartupError(
                "MongoDB is unavailable; check RULEREADER_MONGODB_URI and the container"
            ) from error

    async def initialize(self, target_version: int = RUNTIME_SCHEMA_VERSION) -> int:
        try:
            return await apply_migrations(self.database, target_version=target_version)
        except Exception as error:
            raise MongoStartupError("MongoDB schema initialization failed") from error

    async def ping(self) -> None:
        if self._client is None:
            raise RuntimeError("MongoDB manager has not started")
        await self._client.admin.command({"ping": 1})

    async def close(self) -> None:
        client = self._client
        self._client = None
        self._database = None
        if client is not None:
            await client.close()
