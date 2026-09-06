"""LangGraph workflow for safe, auditable rule parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from rule_reader.application.rule_parsing.ports import RuleCandidateModel
from rule_reader.application.rule_parsing.source_normalization import normalize_rule_source
from rule_reader.core.version import __version__
from rule_reader.domain.rules.audit import (
    ParseAttemptAudit,
    ParseAudit,
    ProviderTokenUsage,
)
from rule_reader.domain.rules.catalog import catalog_for_prompt
from rule_reader.domain.rules.errors import (
    ParseErrorCode,
    ParseIssue,
    RuleParsingError,
)
from rule_reader.domain.rules.models import ParserMetadata, SourceMetadata
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import (
    SemanticValidationErrorV2,
    enrich_candidate_v2,
    validate_candidate_v2,
)

PROMPT_VERSION = "rule-parser-v8"
SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_SUCCESS_OUTCOME = "SUCCESS"
_PROVIDER_RESPONSE_RECEIVED = "PROVIDER_RESPONSE_RECEIVED"


class IssueState(TypedDict):
    code: str
    message: str
    retryable: bool
    details: list[str]


class TokenUsageState(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int | None
    prompt_cache_miss_tokens: int | None
    reasoning_tokens: int | None


class AttemptAuditState(TypedDict):
    attempt: int
    backoff_seconds: float
    outcome_code: str
    retryable: bool
    provider_request_id: str | None
    token_usage: TokenUsageState | None


class ParserState(TypedDict, total=False):
    text: str
    source_name: str
    relative_path: str | None
    source_hash: str
    request_id: str
    idempotency_key_sha256: str | None
    attempts: int
    attempt_audits: list[AttemptAuditState]
    raw_candidate: str
    candidate: dict[str, Any]
    result: dict[str, Any]
    error: IssueState | None


@dataclass(frozen=True, slots=True)
class _CompletedIdempotencyEntry:
    fingerprint: str
    result: RuleParseResultV2


@dataclass(frozen=True, slots=True)
class _InFlightIdempotencyEntry:
    fingerprint: str
    task: asyncio.Task[RuleParseResultV2]


def _issue_state(issue: ParseIssue) -> IssueState:
    return {
        "code": issue.code.value,
        "message": issue.message,
        "retryable": issue.retryable,
        "details": list(issue.details),
    }


def _parse_issue(state: IssueState) -> ParseIssue:
    return ParseIssue(
        code=ParseErrorCode(state["code"]),
        message=state["message"],
        retryable=state["retryable"],
        details=tuple(state["details"]),
    )


def _validation_details(error: ValidationError) -> tuple[str, ...]:
    details: list[str] = []
    for item in error.errors(include_input=False, include_url=False)[:100]:
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return tuple(details)


def _consume_task_exception(task: asyncio.Task[RuleParseResultV2]) -> None:
    if not task.cancelled():
        task.exception()


class RuleParsingService:
    """Validate every untrusted model response before producing a draft."""

    def __init__(
        self,
        model: RuleCandidateModel,
        *,
        max_characters: int,
        max_retries: int,
        retry_base_delay_seconds: float = 1.0,
        retry_max_delay_seconds: float = 8.0,
        idempotency_cache_max_entries: int = 64,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        request_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        if retry_base_delay_seconds < 0 or retry_max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if retry_max_delay_seconds < retry_base_delay_seconds:
            raise ValueError("maximum retry delay cannot be less than base delay")
        if idempotency_cache_max_entries < 1:
            raise ValueError("idempotency cache must contain at least one entry")

        self._model = model
        self._max_characters = max_characters
        self._max_attempts = max_retries + 1
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds
        self._idempotency_cache_max_entries = idempotency_cache_max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or asyncio.sleep
        self._request_id_factory = request_id_factory or uuid4
        self._idempotency_lock = asyncio.Lock()
        self._completed_idempotency: OrderedDict[str, _CompletedIdempotencyEntry] = OrderedDict()
        self._inflight_idempotency: dict[str, _InFlightIdempotencyEntry] = {}
        self._graph: Any = self._build_graph()

    async def start(self) -> None:
        await self._model.start()

    async def close(self) -> None:
        await self._model.close()
        async with self._idempotency_lock:
            self._completed_idempotency.clear()
            self._inflight_idempotency.clear()

    async def parse_text(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        idempotency_key: str | None = None,
    ) -> RuleParseResultV2:
        if idempotency_key is None:
            return await self._parse_once(
                text,
                source_name=source_name,
                relative_path=relative_path,
                request_id=str(self._request_id_factory()),
                idempotency_key_sha256=None,
            )

        if _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
            request_id = str(self._request_id_factory())
            issue = ParseIssue(
                code=ParseErrorCode.IDEMPOTENCY_KEY_INVALID,
                message="Idempotency key must contain 8-128 safe ASCII characters",
                audit=self._empty_audit(request_id, None),
            )
            raise RuleParsingError(issue)

        key_digest = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
        fingerprint = self._request_fingerprint(
            text,
            source_name=source_name,
            relative_path=relative_path,
        )
        async with self._idempotency_lock:
            completed = self._completed_idempotency.get(key_digest)
            if completed is not None:
                if completed.fingerprint != fingerprint:
                    raise self._idempotency_conflict(key_digest)
                self._completed_idempotency.move_to_end(key_digest)
                return completed.result

            inflight = self._inflight_idempotency.get(key_digest)
            if inflight is not None:
                if inflight.fingerprint != fingerprint:
                    raise self._idempotency_conflict(key_digest)
                task = inflight.task
            else:
                request_id = str(self._request_id_factory())
                task = asyncio.create_task(
                    self._run_idempotent(
                        key_digest,
                        fingerprint,
                        text,
                        source_name=source_name,
                        relative_path=relative_path,
                        request_id=request_id,
                    )
                )
                task.add_done_callback(_consume_task_exception)
                self._inflight_idempotency[key_digest] = _InFlightIdempotencyEntry(
                    fingerprint=fingerprint, task=task
                )

        return await asyncio.shield(task)

    async def parse_to_json(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        idempotency_key: str | None = None,
        indent: int | None = 2,
    ) -> str:
        result = await self.parse_text(
            text,
            source_name=source_name,
            relative_path=relative_path,
            idempotency_key=idempotency_key,
        )
        return result.to_json(indent=indent)

    async def _run_idempotent(
        self,
        key_digest: str,
        fingerprint: str,
        text: str,
        *,
        source_name: str,
        relative_path: str | None,
        request_id: str,
    ) -> RuleParseResultV2:
        try:
            result = await self._parse_once(
                text,
                source_name=source_name,
                relative_path=relative_path,
                request_id=request_id,
                idempotency_key_sha256=key_digest,
            )
        except BaseException:
            async with self._idempotency_lock:
                current = self._inflight_idempotency.get(key_digest)
                if current is not None and current.task is asyncio.current_task():
                    self._inflight_idempotency.pop(key_digest, None)
            raise

        async with self._idempotency_lock:
            current = self._inflight_idempotency.get(key_digest)
            if current is not None and current.task is asyncio.current_task():
                self._inflight_idempotency.pop(key_digest, None)
                self._completed_idempotency[key_digest] = _CompletedIdempotencyEntry(
                    fingerprint=fingerprint,
                    result=result,
                )
                self._completed_idempotency.move_to_end(key_digest)
                while len(self._completed_idempotency) > self._idempotency_cache_max_entries:
                    self._completed_idempotency.popitem(last=False)
        return result

    async def _parse_once(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None,
        request_id: str,
        idempotency_key_sha256: str | None,
    ) -> RuleParseResultV2:
        initial: ParserState = {
            "text": text,
            "source_name": source_name,
            "relative_path": relative_path,
            "request_id": request_id,
            "idempotency_key_sha256": idempotency_key_sha256,
            "attempts": 0,
            "attempt_audits": [],
            "error": None,
        }
        final_state = cast(ParserState, await self._graph.ainvoke(initial))
        audit = self._audit_from_state(final_state)
        error = final_state.get("error")
        if error is not None:
            raise RuleParsingError(replace(_parse_issue(error), audit=audit))
        result = final_state.get("result")
        if result is None:
            raise RuleParsingError(
                ParseIssue(
                    code=ParseErrorCode.PROVIDER_RESPONSE_INVALID,
                    message="Rule parsing ended without a result",
                    audit=audit,
                )
            )
        return RuleParseResultV2.model_validate(result)

    def _build_graph(self) -> Any:
        builder = StateGraph(ParserState)
        builder.add_node("prepare_input", self._prepare_input)
        builder.add_node("invoke_model", self._invoke_model)
        builder.add_node("validate_candidate", self._validate_candidate)
        builder.add_node("build_result", self._build_result)
        builder.add_node("error", self._error_terminal)

        builder.add_edge(START, "prepare_input")
        builder.add_conditional_edges(
            "prepare_input",
            self._route_after_prepare,
            {"invoke_model": "invoke_model", "error": "error"},
        )
        builder.add_conditional_edges(
            "invoke_model",
            self._route_after_model,
            {
                "invoke_model": "invoke_model",
                "validate_candidate": "validate_candidate",
                "error": "error",
            },
        )
        builder.add_conditional_edges(
            "validate_candidate",
            self._route_after_validation,
            {
                "invoke_model": "invoke_model",
                "build_result": "build_result",
                "error": "error",
            },
        )
        builder.add_edge("build_result", END)
        builder.add_edge("error", END)
        return builder.compile()

    def _prepare_input(self, state: ParserState) -> ParserState:
        try:
            normalized = normalize_rule_source(
                state["text"],
                max_characters=self._max_characters,
            )
        except RuleParsingError as error:
            return {"error": _issue_state(error.issue)}
        return {
            "text": normalized.text,
            "source_hash": normalized.sha256,
            "error": None,
        }

    async def _invoke_model(self, state: ParserState) -> ParserState:
        previous_error = state.get("error")
        feedback = tuple(previous_error["details"]) if previous_error else ()
        attempt = state.get("attempts", 0) + 1
        backoff_seconds = self._retry_delay(attempt)
        if backoff_seconds > 0:
            await self._sleeper(backoff_seconds)

        prior_audits = state.get("attempt_audits", [])
        try:
            generation = await self._model.generate_candidate(
                text=state["text"],
                candidate_schema=RuleCandidateV2.model_json_schema(
                    by_alias=True,
                    mode="validation",
                ),
                field_catalog=catalog_for_prompt(),
                feedback=feedback,
                previous_candidate=(state.get("raw_candidate") if feedback else None),
            )
        except RuleParsingError as error:
            attempt_audit: AttemptAuditState = {
                "attempt": attempt,
                "backoff_seconds": backoff_seconds,
                "outcome_code": error.issue.code.value,
                "retryable": error.issue.retryable,
                "provider_request_id": None,
                "token_usage": None,
            }
            return {
                "attempts": attempt,
                "attempt_audits": [*prior_audits, attempt_audit],
                "error": _issue_state(error.issue),
            }

        token_usage: TokenUsageState | None = None
        if generation.token_usage is not None:
            token_usage = cast(
                TokenUsageState,
                generation.token_usage.model_dump(mode="python"),
            )
        attempt_audit = {
            "attempt": attempt,
            "backoff_seconds": backoff_seconds,
            "outcome_code": _PROVIDER_RESPONSE_RECEIVED,
            "retryable": False,
            "provider_request_id": generation.provider_request_id,
            "token_usage": token_usage,
        }
        return {
            "attempts": attempt,
            "attempt_audits": [*prior_audits, attempt_audit],
            "raw_candidate": generation.content,
            "error": None,
        }

    def _validate_candidate(self, state: ParserState) -> ParserState:
        try:
            decoded = json.loads(state["raw_candidate"])
        except json.JSONDecodeError:
            issue = ParseIssue(
                ParseErrorCode.CANDIDATE_JSON_INVALID,
                "DeepSeek returned invalid JSON",
                retryable=True,
                details=("Return one complete JSON object without Markdown fences",),
            )
            return {
                "attempt_audits": self._finish_attempt(state, issue),
                "error": _issue_state(issue),
            }

        try:
            candidate = RuleCandidateV2.model_validate(decoded)
        except ValidationError as error:
            issue = ParseIssue(
                ParseErrorCode.CANDIDATE_SCHEMA_INVALID,
                "DeepSeek output does not match the rule candidate schema",
                retryable=True,
                details=_validation_details(error),
            )
            return {
                "attempt_audits": self._finish_attempt(state, issue),
                "error": _issue_state(issue),
            }

        try:
            validate_candidate_v2(candidate)
        except SemanticValidationErrorV2 as error:
            issue = ParseIssue(
                ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                "DeepSeek output failed deterministic semantic validation",
                retryable=True,
                details=error.issues[:100],
            )
            return {
                "attempt_audits": self._finish_attempt(state, issue),
                "error": _issue_state(issue),
            }

        return {
            "attempt_audits": self._finish_attempt(state, None),
            "candidate": candidate.model_dump(mode="json"),
            "error": None,
        }

    def _build_result(self, state: ParserState) -> ParserState:
        candidate = RuleCandidateV2.model_validate(state["candidate"])
        parsed_rule = enrich_candidate_v2(candidate)
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        source_hash = state["source_hash"]
        result = RuleParseResultV2(
            schema_version=SCHEMA_VERSION,
            rule_version=f"{candidate.rule_id}@{timestamp}-{source_hash[:12]}",
            generated_at=now,
            parser=ParserMetadata(
                parser_version=__version__,
                prompt_version=PROMPT_VERSION,
                model=self._model.model_name,
                audit=self._audit_from_state(state),
            ),
            source=SourceMetadata(
                source_name=state["source_name"],
                relative_path=state.get("relative_path"),
                sha256=source_hash,
                character_count=len(state["text"]),
            ),
            rule=parsed_rule,
        )
        return {"result": result.model_dump(mode="json"), "error": None}

    def _route_after_prepare(self, state: ParserState) -> Literal["invoke_model", "error"]:
        return "error" if state.get("error") is not None else "invoke_model"

    def _route_after_model(
        self,
        state: ParserState,
    ) -> Literal["invoke_model", "validate_candidate", "error"]:
        error = state.get("error")
        if error is None:
            return "validate_candidate"
        if error["retryable"] and state.get("attempts", 0) < self._max_attempts:
            return "invoke_model"
        return "error"

    def _route_after_validation(
        self,
        state: ParserState,
    ) -> Literal["invoke_model", "build_result", "error"]:
        error = state.get("error")
        if error is None:
            return "build_result"
        if error["retryable"] and state.get("attempts", 0) < self._max_attempts:
            return "invoke_model"
        return "error"

    @staticmethod
    def _error_terminal(state: ParserState) -> ParserState:
        return {"error": state.get("error")}

    def _retry_delay(self, attempt: int) -> float:
        if attempt <= 1:
            return 0.0
        return float(
            min(
                self._retry_base_delay_seconds * (2 ** (attempt - 2)),
                self._retry_max_delay_seconds,
            )
        )

    @staticmethod
    def _finish_attempt(
        state: ParserState,
        issue: ParseIssue | None,
    ) -> list[AttemptAuditState]:
        attempts = [*state.get("attempt_audits", [])]
        if not attempts:
            return attempts
        current = {**attempts[-1]}
        current["outcome_code"] = issue.code.value if issue is not None else _SUCCESS_OUTCOME
        current["retryable"] = issue.retryable if issue is not None else False
        attempts[-1] = cast(AttemptAuditState, current)
        return attempts

    def _audit_from_state(self, state: ParserState) -> ParseAudit:
        attempts = [
            ParseAttemptAudit.model_validate(item) for item in state.get("attempt_audits", [])
        ]
        return ParseAudit(
            request_id=UUID(state["request_id"]),
            idempotency_key_sha256=state.get("idempotency_key_sha256"),
            max_attempts=self._max_attempts,
            attempt_count=len(attempts),
            total_backoff_seconds=sum(item.backoff_seconds for item in attempts),
            attempts=attempts,
            total_token_usage=self._aggregate_token_usage(attempts),
        )

    def _empty_audit(
        self,
        request_id: str,
        idempotency_key_sha256: str | None,
    ) -> ParseAudit:
        return ParseAudit(
            request_id=UUID(request_id),
            idempotency_key_sha256=idempotency_key_sha256,
            max_attempts=self._max_attempts,
            attempt_count=0,
            total_backoff_seconds=0,
            attempts=[],
            total_token_usage=None,
        )

    @staticmethod
    def _aggregate_token_usage(
        attempts: list[ParseAttemptAudit],
    ) -> ProviderTokenUsage | None:
        usages = [item.token_usage for item in attempts if item.token_usage is not None]
        if not usages:
            return None

        def optional_sum(attribute: str) -> int | None:
            values = [
                cast(int, value)
                for usage in usages
                if (value := getattr(usage, attribute)) is not None
            ]
            return sum(values) if values else None

        return ProviderTokenUsage(
            prompt_tokens=sum(item.prompt_tokens for item in usages),
            completion_tokens=sum(item.completion_tokens for item in usages),
            total_tokens=sum(item.total_tokens for item in usages),
            prompt_cache_hit_tokens=optional_sum("prompt_cache_hit_tokens"),
            prompt_cache_miss_tokens=optional_sum("prompt_cache_miss_tokens"),
            reasoning_tokens=optional_sum("reasoning_tokens"),
        )

    def _request_fingerprint(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None,
    ) -> str:
        identity = {
            "text": text,
            "sourceName": source_name,
            "relativePath": relative_path,
            "schemaVersion": SCHEMA_VERSION,
            "parserVersion": __version__,
            "promptVersion": PROMPT_VERSION,
            "provider": "deepseek",
            "model": self._model.model_name,
        }
        canonical = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _idempotency_conflict(self, key_digest: str) -> RuleParsingError:
        request_id = str(self._request_id_factory())
        return RuleParsingError(
            ParseIssue(
                code=ParseErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                message="Idempotency key is already bound to a different parse request",
                audit=self._empty_audit(request_id, key_digest),
            )
        )
