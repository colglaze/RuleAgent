"""FastAPI state accessors."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from rule_reader.application.rule_parsing.ports import RuleParserLifecycle
from rule_reader.application.rule_versions.ports import RuleVersionRepository
from rule_reader.core.config import Settings
from rule_reader.infrastructure.mongodb import DatabaseLifecycle


def settings_from(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def database_from(request: Request) -> DatabaseLifecycle:
    return cast(DatabaseLifecycle, request.app.state.database)


def rule_parser_from(request: Request) -> RuleParserLifecycle:
    return cast(RuleParserLifecycle, request.app.state.rule_parser)


def rule_versions_from(request: Request) -> RuleVersionRepository | None:
    return cast(RuleVersionRepository | None, request.app.state.rule_versions)
