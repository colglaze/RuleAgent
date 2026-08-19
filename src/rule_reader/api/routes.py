"""Backend skeleton HTTP routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Path, Request, status
from fastapi.responses import JSONResponse

from rule_reader.api.dependencies import (
    database_from,
    rule_parser_from,
    rule_versions_from,
    settings_from,
)
from rule_reader.api.models import (
    ConfigResponse,
    HealthResponse,
    ParseErrorResponse,
    ParseRuleRequest,
    RootResponse,
    StoredRuleVersionResponse,
)
from rule_reader.application.rule_versions.ports import RuleVersionPersistenceError
from rule_reader.core.version import __version__
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError
from rule_reader.domain.rules.models import RuleParseResult

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=RootResponse)
async def root(request: Request) -> RootResponse:
    settings = settings_from(request)
    return RootResponse(service=settings.app_name, version=__version__, docs="/docs")


@router.get("/health/live", response_model=HealthResponse)
async def liveness(request: Request) -> HealthResponse:
    settings = settings_from(request)
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def readiness(request: Request) -> JSONResponse:
    settings = settings_from(request)
    database = database_from(request)
    schema_version = getattr(request.app.state, "schema_version", None)
    try:
        await database.ping()
    except Exception:
        logger.exception("MongoDB readiness check failed")
        payload = HealthResponse(
            status="unavailable",
            service=settings.app_name,
            version=__version__,
            schema_version=schema_version,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )

    payload = HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        schema_version=schema_version,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get("/api/v1/config", response_model=ConfigResponse)
async def public_config(request: Request) -> ConfigResponse:
    return ConfigResponse.model_validate(settings_from(request).public_summary())


def _parse_error_status(code: ParseErrorCode) -> int:
    if code in {
        ParseErrorCode.INPUT_EMPTY,
        ParseErrorCode.INPUT_TOO_LARGE,
        ParseErrorCode.DOCUMENT_NOT_FOUND,
        ParseErrorCode.DOCUMENT_OUTSIDE_ROOT,
        ParseErrorCode.DOCUMENT_TYPE_UNSUPPORTED,
        ParseErrorCode.DOCUMENT_ENCODING_INVALID,
    }:
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    if code in {
        ParseErrorCode.PROVIDER_NOT_CONFIGURED,
        ParseErrorCode.PROVIDER_TIMEOUT,
        ParseErrorCode.PROVIDER_RATE_LIMITED,
        ParseErrorCode.PROVIDER_UNAVAILABLE,
    }:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_502_BAD_GATEWAY


@router.post(
    "/api/v1/rules/parse",
    response_model=RuleParseResult,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ParseErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ParseErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ParseErrorResponse},
    },
)
async def parse_rule(
    request: Request,
    payload: ParseRuleRequest,
) -> RuleParseResult | JSONResponse:
    parser = rule_parser_from(request)
    try:
        result = await parser.parse_text(
            payload.text,
            source_name=payload.source_name,
        )
    except RuleParsingError as error:
        logger.warning("Rule parsing failed code=%s", error.issue.code.value)
        return JSONResponse(
            status_code=_parse_error_status(error.issue.code),
            content={"error": error.issue.to_dict()},
        )
    if payload.persist:
        repository = rule_versions_from(request)
        if repository is None:
            return _persistence_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                RuleVersionPersistenceError.code,
                "Rule version persistence is unavailable",
            )
        try:
            await repository.save(result)
        except RuleVersionPersistenceError:
            logger.warning("Rule version persistence failed")
            return _persistence_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                RuleVersionPersistenceError.code,
                "Rule version could not be saved",
            )
    return result


@router.get(
    "/api/v1/rules/versions/{rule_version}",
    response_model=StoredRuleVersionResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ParseErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ParseErrorResponse},
    },
)
async def get_rule_version(
    request: Request,
    rule_version: str = Path(min_length=1, max_length=220),
) -> StoredRuleVersionResponse | JSONResponse:
    repository = rule_versions_from(request)
    if repository is None:
        return _persistence_error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            RuleVersionPersistenceError.code,
            "Rule version persistence is unavailable",
        )
    try:
        stored = await repository.get(rule_version)
    except RuleVersionPersistenceError:
        logger.warning("Rule version read failed")
        return _persistence_error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            RuleVersionPersistenceError.code,
            "Rule version could not be read",
        )
    if stored is None:
        return _persistence_error_response(
            status.HTTP_404_NOT_FOUND,
            "RULE_VERSION_NOT_FOUND",
            "Rule version was not found",
        )
    return StoredRuleVersionResponse(
        rule_version=stored.document.rule_version,
        stored_at=stored.stored_at,
        document=stored.document,
    )


def _persistence_error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": status_code == status.HTTP_503_SERVICE_UNAVAILABLE,
                "details": [],
            }
        },
    )
