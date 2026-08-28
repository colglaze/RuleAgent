"""Backend skeleton HTTP routes."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from rule_reader.api.dependencies import (
    database_from,
    rule_parser_from,
    rule_versions_from,
    settings_from,
)
from rule_reader.api.models import (
    ConfigResponse,
    FactBindingRequestsResponse,
    HealthResponse,
    ParseErrorResponse,
    ParseRuleRequest,
    RootResponse,
    StoredRuleVersionResponse,
)
from rule_reader.application.rule_versions.ports import RuleVersionPersistenceError
from rule_reader.core.version import __version__
from rule_reader.domain.rules.bindings_v2 import (
    FactBindingRequestV2,
    build_fact_binding_requests_v2,
)
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError
from rule_reader.domain.rules.v2 import RuleParseResultV2

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
        ParseErrorCode.IDEMPOTENCY_KEY_INVALID,
    }:
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    if code is ParseErrorCode.IDEMPOTENCY_KEY_CONFLICT:
        return status.HTTP_409_CONFLICT
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
    response_model=RuleParseResultV2,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ParseErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ParseErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ParseErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ParseErrorResponse},
    },
)
async def parse_rule(
    request: Request,
    payload: ParseRuleRequest,
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> RuleParseResultV2 | JSONResponse:
    parser = rule_parser_from(request)
    try:
        result = await parser.parse_text(
            payload.text,
            source_name=payload.source_name,
            idempotency_key=idempotency_key,
        )
    except RuleParsingError as error:
        request_id = str(error.issue.audit.request_id) if error.issue.audit is not None else None
        logger.warning(
            "Rule parsing failed code=%s request_id=%s",
            error.issue.code.value,
            request_id,
        )
        return JSONResponse(
            status_code=_parse_error_status(error.issue.code),
            content={"error": error.issue.to_dict()},
            headers=_request_id_headers(request_id),
        )
    request_id = str(result.parser.audit.request_id) if result.parser.audit else None
    if request_id is not None:
        response.headers["X-RuleReader-Request-ID"] = request_id
    if payload.persist:
        repository = rule_versions_from(request)
        if repository is None:
            return _persistence_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                RuleVersionPersistenceError.code,
                "Rule version persistence is unavailable",
                request_id=request_id,
            )
        try:
            await repository.save(result)
        except RuleVersionPersistenceError:
            logger.warning("Rule version persistence failed")
            return _persistence_error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                RuleVersionPersistenceError.code,
                "Rule version could not be saved",
                request_id=request_id,
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


@router.get(
    "/api/v1/rules/versions/{rule_version}/fact-binding-requests",
    response_model=FactBindingRequestsResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ParseErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ParseErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ParseErrorResponse},
    },
)
async def get_fact_binding_requests(
    request: Request,
    rule_version: str = Path(min_length=1, max_length=220),
    contract_version: Literal["2.0.0"] = Query(
        default="2.0.0",
        alias="contractVersion",
    ),
) -> FactBindingRequestsResponse | JSONResponse:
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
        logger.warning("Rule version read failed for fact binding export")
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
    if not isinstance(stored.document, RuleParseResultV2):
        return _persistence_error_response(
            status.HTTP_409_CONFLICT,
            "RULE_SCHEMA_UNSUPPORTED_FOR_BINDING",
            "Only rule schema 2.0.0 can be exported for Agent 2 binding",
        )
    binding_requests: list[FactBindingRequestV2] = [
        *build_fact_binding_requests_v2(stored.document)
    ]
    return FactBindingRequestsResponse(
        rule_version=stored.document.rule_version,
        requests=binding_requests,
    )


def _persistence_error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: str | None = None,
) -> JSONResponse:
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
        headers=_request_id_headers(request_id),
    )


def _request_id_headers(request_id: str | None) -> dict[str, str]:
    if request_id is None:
        return {}
    return {"X-RuleReader-Request-ID": request_id}
