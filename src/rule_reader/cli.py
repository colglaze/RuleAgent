"""RuleReader command-line entry points."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from rule_reader.application.fact_binding_handoffs.ports import (
    FactBindingHandoffError,
    FactBindingHandoffPersistenceError,
)
from rule_reader.application.fact_binding_handoffs.service import (
    FactBindingHandoffService,
    load_checked_in_fact_binding_schema,
)
from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.application.rule_versions.ports import RuleVersionPersistenceError
from rule_reader.core.config import Settings
from rule_reader.core.logging import configure_logging
from rule_reader.core.version import ensure_supported_python
from rule_reader.domain.rules.errors import RuleParsingError
from rule_reader.infrastructure.deepseek import DeepSeekChatModel
from rule_reader.infrastructure.documents import LocalDocumentReader
from rule_reader.infrastructure.fact_binding_handoffs import (
    MongoFactBindingHandoffRepository,
)
from rule_reader.infrastructure.migrations import FACT_BINDING_HANDOFFS_COLLECTION
from rule_reader.infrastructure.mongodb import MongoManager, MongoStartupError
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rule-reader")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="start the FastAPI service")
    subparsers.add_parser("check-config", help="print sanitized configuration")
    subparsers.add_parser("init-db", help="initialize the MongoDB schema")
    parse_parser = subparsers.add_parser("parse", help="parse one local Markdown rule")
    parse_parser.add_argument(
        "--file",
        type=Path,
        required=True,
        help="Markdown path under RULEREADER_DOCUMENT_ROOT",
    )
    parse_parser.add_argument(
        "--persist",
        action="store_true",
        help="persist the validated draft as an immutable MongoDB version",
    )
    parse_parser.add_argument(
        "--idempotency-key",
        help="process-local idempotency key for this parsing operation",
    )
    handoff_parser = subparsers.add_parser(
        "persist-handoffs",
        help="persist immutable FactBindingRequest 2.0 handoffs for one stored rule",
    )
    handoff_parser.add_argument(
        "--rule-version",
        required=True,
        help="exact immutable Schema 2.0.0 rule version",
    )
    parser.set_defaults(command="serve")
    return parser


async def _initialize_database(settings: Settings) -> int:
    manager = MongoManager(settings)
    try:
        await manager.start()
        return await manager.initialize()
    finally:
        await manager.close()


async def _parse_document(
    settings: Settings,
    path: Path,
    *,
    persist: bool,
    idempotency_key: str | None,
) -> str:
    reader = LocalDocumentReader(
        settings.document_root,
        max_characters=settings.rule_max_characters,
    )
    document = reader.read(path)
    parser = RuleParsingService(
        DeepSeekChatModel(settings),
        max_characters=settings.rule_max_characters,
        max_retries=settings.deepseek_max_retries,
        retry_base_delay_seconds=settings.deepseek_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.deepseek_retry_max_delay_seconds,
        idempotency_cache_max_entries=(settings.deepseek_idempotency_cache_max_entries),
    )
    manager = MongoManager(settings) if persist else None
    try:
        if manager is not None:
            try:
                await manager.start()
                await manager.initialize()
            except MongoStartupError as error:
                raise RuleVersionPersistenceError(
                    "Rule version persistence is unavailable"
                ) from error
        await parser.start()
        result = await parser.parse_text(
            document.text,
            source_name=document.source_name,
            relative_path=document.relative_path,
            idempotency_key=idempotency_key,
        )
        if manager is not None:
            repository = MongoRuleVersionRepository(lambda: manager.database)
            await repository.save(result)
        return result.to_json()
    finally:
        await parser.close()
        if manager is not None:
            await manager.close()


async def _persist_fact_binding_handoffs(
    settings: Settings,
    rule_version: str,
) -> dict[str, object]:
    manager = MongoManager(settings)
    try:
        try:
            await manager.start()
            schema_version = await manager.initialize()
        except MongoStartupError as error:
            raise FactBindingHandoffPersistenceError(
                "Fact binding handoff persistence is unavailable"
            ) from error
        rule_versions = MongoRuleVersionRepository(lambda: manager.database)
        handoffs = MongoFactBindingHandoffRepository(lambda: manager.database)
        service = FactBindingHandoffService(
            rule_versions,
            handoffs,
            load_checked_in_fact_binding_schema(),
        )
        result = await service.persist(rule_version)
        return {
            "status": "persisted_and_verified",
            "databaseSchemaVersion": schema_version,
            "collection": FACT_BINDING_HANDOFFS_COLLECTION,
            "ruleVersion": result.rule_version,
            "contractVersion": "2.0.0",
            "records": len(result.records),
            "inserted": result.inserted_count,
            "existing": result.existing_count,
            "blockingRequests": result.blocking_request_count,
            "sourceRuleUnchanged": result.source_rule_unchanged,
        }
    finally:
        await manager.close()


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ensure_supported_python()
        settings = Settings()
    except (RuntimeError, ValidationError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)

    if args.command == "check-config":
        print(json.dumps(settings.public_summary(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "init-db":
        try:
            schema_version = asyncio.run(_initialize_database(settings))
        except Exception as error:
            print(f"database initialization failed: {type(error).__name__}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "status": "ok",
                    "database": settings.mongodb_database,
                    "schema_version": schema_version,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "parse":
        try:
            parsed_json = asyncio.run(
                _parse_document(
                    settings,
                    args.file,
                    persist=args.persist,
                    idempotency_key=args.idempotency_key,
                )
            )
        except RuleParsingError as error:
            print(
                json.dumps(
                    {"error": error.issue.to_dict()},
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        except RuleVersionPersistenceError as error:
            print(
                json.dumps(
                    {
                        "error": {
                            "code": error.code,
                            "message": str(error),
                            "retryable": True,
                            "details": [],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        print(parsed_json)
        return 0

    if args.command == "persist-handoffs":
        try:
            result = asyncio.run(_persist_fact_binding_handoffs(settings, args.rule_version))
        except FactBindingHandoffError as error:
            print(
                json.dumps(
                    {
                        "error": {
                            "code": error.code,
                            "message": str(error),
                            "retryable": error.retryable,
                            "details": [],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    uvicorn.run(
        "rule_reader.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.reload,
    )
    return 0


def main() -> None:
    raise SystemExit(run())
