"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rule_reader.api.routes import router
from rule_reader.application.rule_parsing.ports import RuleParserLifecycle
from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.application.rule_versions.ports import RuleVersionRepository
from rule_reader.core.config import Settings, get_settings
from rule_reader.core.logging import configure_logging
from rule_reader.core.version import __version__, ensure_supported_python
from rule_reader.infrastructure.deepseek import DeepSeekChatModel
from rule_reader.infrastructure.mongodb import DatabaseLifecycle, MongoManager
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: DatabaseLifecycle | None = None,
    rule_parser: RuleParserLifecycle | None = None,
    rule_version_repository: RuleVersionRepository | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_database = database or MongoManager(resolved_settings)
    resolved_rule_parser = rule_parser or RuleParsingService(
        DeepSeekChatModel(resolved_settings),
        max_characters=resolved_settings.rule_max_characters,
        max_retries=resolved_settings.deepseek_max_retries,
        retry_base_delay_seconds=(resolved_settings.deepseek_retry_base_delay_seconds),
        retry_max_delay_seconds=resolved_settings.deepseek_retry_max_delay_seconds,
        idempotency_cache_max_entries=(resolved_settings.deepseek_idempotency_cache_max_entries),
    )
    resolved_rule_versions = rule_version_repository
    if resolved_rule_versions is None and isinstance(resolved_database, MongoManager):
        resolved_rule_versions = MongoRuleVersionRepository(lambda: resolved_database.database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_supported_python()
        configure_logging(resolved_settings.log_level)
        app.state.settings = resolved_settings
        app.state.database = resolved_database
        app.state.rule_parser = resolved_rule_parser
        app.state.rule_versions = resolved_rule_versions
        app.state.schema_version = None
        try:
            await resolved_database.start()
            app.state.schema_version = await resolved_database.initialize()
            await resolved_rule_parser.start()
            logger.info(
                "RuleReader started database=%s schema_version=%s",
                resolved_settings.mongodb_database,
                app.state.schema_version,
            )
            yield
        except Exception:
            logger.exception("RuleReader startup failed")
            raise
        finally:
            await resolved_rule_parser.close()
            await resolved_database.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
