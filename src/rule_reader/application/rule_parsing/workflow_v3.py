"""Explicit, bounded LangGraph branch for offline V3 ruleStructure generation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from rule_reader.application.rule_parsing.ports import RuleStructureModelV3
from rule_reader.application.rule_parsing.prompt_v3 import (
    SYSTEM_PROMPT_V3,
    build_rule_structure_payload_v3,
)
from rule_reader.application.rule_parsing.source_normalization import normalize_rule_source
from rule_reader.domain.rules.audit import ParseAttemptAudit, ParseAudit, ProviderTokenUsage
from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import (
    SemanticValidationErrorV3,
    validate_rule_structure_candidate_v3,
)


class V3State(TypedDict, total=False):
    text: str
    attempts: int
    raw_candidate: str
    candidate: dict[str, Any]
    feedback: list[str]
    error: ParseIssue | None
    audits: list[ParseAttemptAudit]


@dataclass(frozen=True, slots=True)
class RuleStructureRunV3:
    candidate: RuleStructureCandidateV3
    audit: ParseAudit


def _validation_details(error: ValidationError) -> list[str]:
    details: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location or '$'}: {item['msg']}")
    return details[:100]


def _total_usage(audits: list[ParseAttemptAudit]) -> ProviderTokenUsage | None:
    usages = [item.token_usage for item in audits if item.token_usage is not None]
    if not usages:
        return None

    def optional_sum(name: str) -> int | None:
        values = [getattr(item, name) for item in usages]
        return (
            sum(value for value in values if value is not None)
            if any(value is not None for value in values)
            else None
        )

    return ProviderTokenUsage(
        prompt_tokens=sum(item.prompt_tokens for item in usages),
        completion_tokens=sum(item.completion_tokens for item in usages),
        total_tokens=sum(item.total_tokens for item in usages),
        prompt_cache_hit_tokens=optional_sum("prompt_cache_hit_tokens"),
        prompt_cache_miss_tokens=optional_sum("prompt_cache_miss_tokens"),
        reasoning_tokens=optional_sum("reasoning_tokens"),
    )


class RuleStructureParsingServiceV3:
    """Generate, validate, and correct one in-memory V3 structure within a hard budget."""

    def __init__(
        self,
        model: RuleStructureModelV3,
        catalog: BusinessConfirmedFactCatalogV3,
        *,
        max_attempts: int = 1,
        max_characters: int = 100_000,
        retry_delay_seconds: float = 0,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        validate_fact_catalog_v3(catalog)
        self._model = model
        self._catalog = catalog
        self._max_attempts = max_attempts
        self._max_characters = max_characters
        self._retry_delay_seconds = retry_delay_seconds
        self._sleeper = sleeper or asyncio.sleep
        self._graph = self._build_graph()

    async def start(self) -> None:
        await self._model.start()

    async def close(self) -> None:
        await self._model.close()

    async def parse_rule_structure(self, text: str) -> RuleStructureRunV3:
        normalized = normalize_rule_source(text, max_characters=self._max_characters)
        request_id = uuid4()
        initial: V3State = {
            "text": normalized.text,
            "attempts": 0,
            "feedback": [],
            "audits": [],
            "error": None,
        }
        final = cast(V3State, await self._graph.ainvoke(initial))
        audit = self._audit(request_id, final.get("audits", []))
        if error := final.get("error"):
            raise RuleParsingError(replace(error, audit=audit))
        if payload := final.get("candidate"):
            return RuleStructureRunV3(
                candidate=RuleStructureCandidateV3.model_validate(payload), audit=audit
            )
        raise RuleParsingError(
            ParseIssue(
                ParseErrorCode.PROVIDER_RESPONSE_INVALID,
                "V3 ruleStructure generation ended without a candidate",
                audit=audit,
            )
        )

    def _build_graph(self) -> Any:
        builder = StateGraph(V3State)
        builder.add_node("invoke", self._invoke)
        builder.add_node("validate", self._validate)
        builder.add_edge(START, "invoke")
        builder.add_conditional_edges(
            "invoke",
            self._route_after_invoke,
            {"invoke": "invoke", "validate": "validate", "end": END},
        )
        builder.add_conditional_edges(
            "validate",
            self._route_after_validate,
            {"invoke": "invoke", "end": END},
        )
        return builder.compile()

    async def _invoke(self, state: V3State) -> V3State:
        attempt = state.get("attempts", 0) + 1
        if attempt > 1 and self._retry_delay_seconds:
            await self._sleeper(self._retry_delay_seconds)
        previous = state.get("raw_candidate") if state.get("feedback") else None
        try:
            generation = await self._model.generate_rule_structure_v3(
                system_prompt=SYSTEM_PROMPT_V3,
                user_payload=build_rule_structure_payload_v3(
                    rule_text=state["text"],
                    catalog=self._catalog,
                    feedback=tuple(state.get("feedback", [])),
                    previous_candidate=previous,
                ),
            )
        except RuleParsingError as error:
            audit = ParseAttemptAudit(
                attempt=attempt,
                backoff_seconds=self._retry_delay_seconds if attempt > 1 else 0,
                outcome_code=error.issue.code.value,
                retryable=error.issue.retryable,
            )
            return {
                "attempts": attempt,
                "audits": [*state.get("audits", []), audit],
                "feedback": list(error.issue.details),
                "error": error.issue,
            }
        audit = ParseAttemptAudit(
            attempt=attempt,
            backoff_seconds=self._retry_delay_seconds if attempt > 1 else 0,
            outcome_code="PROVIDER_RESPONSE_RECEIVED",
            retryable=False,
            provider_request_id=generation.provider_request_id,
            token_usage=generation.token_usage,
        )
        return {
            "attempts": attempt,
            "raw_candidate": generation.content,
            "audits": [*state.get("audits", []), audit],
            "feedback": [],
            "error": None,
        }

    def _validate(self, state: V3State) -> V3State:
        try:
            decoded = json.loads(state["raw_candidate"])
        except json.JSONDecodeError:
            return self._validation_failure(
                state,
                ParseIssue(
                    ParseErrorCode.CANDIDATE_JSON_INVALID,
                    "DeepSeek returned invalid V3 JSON",
                    retryable=True,
                    details=("Return one complete JSON object without Markdown fences",),
                ),
            )
        try:
            candidate = RuleStructureCandidateV3.model_validate(decoded)
        except ValidationError as error:
            return self._validation_failure(
                state,
                ParseIssue(
                    ParseErrorCode.CANDIDATE_SCHEMA_INVALID,
                    "DeepSeek output does not match the V3 ruleStructure schema",
                    retryable=True,
                    details=tuple(_validation_details(error)),
                ),
            )
        try:
            validate_rule_structure_candidate_v3(candidate, self._catalog)
        except SemanticValidationErrorV3 as error:
            return self._validation_failure(
                state,
                ParseIssue(
                    ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                    "DeepSeek V3 output failed deterministic semantic validation",
                    retryable=True,
                    details=error.issues[:100],
                ),
            )
        if candidate.blocking_issues or candidate.proposed_facts:
            return self._validation_failure(
                state,
                ParseIssue(
                    ParseErrorCode.BUSINESS_CONFIRMATION_REQUIRED,
                    "V3 ruleStructure requires business-confirmed facts before "
                    "correction can continue",
                    retryable=False,
                    details=tuple(issue.issue_id for issue in candidate.blocking_issues)[:100],
                ),
            )
        return {
            "candidate": candidate.model_dump(mode="json"),
            "audits": self._finish_latest_audit(state, "SUCCESS", False),
            "error": None,
        }

    def _validation_failure(self, state: V3State, issue: ParseIssue) -> V3State:
        return {
            "audits": self._finish_latest_audit(state, issue.code.value, issue.retryable),
            "feedback": list(issue.details),
            "error": issue,
        }

    @staticmethod
    def _finish_latest_audit(
        state: V3State, outcome_code: str, retryable: bool
    ) -> list[ParseAttemptAudit]:
        audits = list(state.get("audits", []))
        latest = audits[-1]
        audits[-1] = latest.model_copy(
            update={"outcome_code": outcome_code, "retryable": retryable}
        )
        return audits

    def _route_after_invoke(self, state: V3State) -> str:
        if state.get("raw_candidate") and state.get("error") is None:
            return "validate"
        return "invoke" if self._can_retry(state) else "end"

    def _route_after_validate(self, state: V3State) -> str:
        if state.get("candidate") is not None:
            return "end"
        return "invoke" if self._can_retry(state) else "end"

    def _can_retry(self, state: V3State) -> bool:
        error = state.get("error")
        return bool(error and error.retryable and state.get("attempts", 0) < self._max_attempts)

    def _audit(self, request_id: UUID, attempts: list[ParseAttemptAudit]) -> ParseAudit:
        return ParseAudit(
            request_id=request_id,
            idempotency_key_sha256=None,
            max_attempts=self._max_attempts,
            attempt_count=len(attempts),
            total_backoff_seconds=sum(item.backoff_seconds for item in attempts),
            attempts=attempts,
            total_token_usage=_total_usage(attempts),
        )
