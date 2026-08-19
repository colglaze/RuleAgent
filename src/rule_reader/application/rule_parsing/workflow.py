"""LangGraph workflow for safe rule parsing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from rule_reader.application.rule_parsing.ports import RuleCandidateModel
from rule_reader.core.version import __version__
from rule_reader.domain.rules.catalog import catalog_for_prompt
from rule_reader.domain.rules.errors import (
    ParseErrorCode,
    ParseIssue,
    RuleParsingError,
)
from rule_reader.domain.rules.models import (
    ParserMetadata,
    RuleCandidate,
    RuleParseResult,
    SourceMetadata,
)
from rule_reader.domain.rules.validation import (
    SemanticValidationError,
    enrich_candidate,
    validate_candidate,
)

PROMPT_VERSION = "rule-parser-v1"
SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


class IssueState(TypedDict):
    code: str
    message: str
    retryable: bool
    details: list[str]


class ParserState(TypedDict, total=False):
    text: str
    source_name: str
    relative_path: str | None
    source_hash: str
    attempts: int
    raw_candidate: str
    candidate: dict[str, Any]
    result: dict[str, Any]
    error: IssueState | None


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
    for item in error.errors(include_input=False, include_url=False)[:12]:
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return tuple(details)


class RuleParsingService:
    """Validate every untrusted model response before producing a draft."""

    def __init__(
        self,
        model: RuleCandidateModel,
        *,
        max_characters: int,
        max_retries: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._model = model
        self._max_characters = max_characters
        self._max_attempts = max_retries + 1
        self._clock = clock or (lambda: datetime.now(UTC))
        self._graph: Any = self._build_graph()

    async def start(self) -> None:
        await self._model.start()

    async def close(self) -> None:
        await self._model.close()

    async def parse_text(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
    ) -> RuleParseResult:
        initial: ParserState = {
            "text": text,
            "source_name": source_name,
            "relative_path": relative_path,
            "attempts": 0,
            "error": None,
        }
        final_state = cast(ParserState, await self._graph.ainvoke(initial))
        error = final_state.get("error")
        if error is not None:
            raise RuleParsingError(_parse_issue(error))
        result = final_state.get("result")
        if result is None:
            raise RuleParsingError(
                ParseIssue(
                    code=ParseErrorCode.PROVIDER_RESPONSE_INVALID,
                    message="Rule parsing ended without a result",
                )
            )
        return RuleParseResult.model_validate(result)

    async def parse_to_json(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        indent: int | None = 2,
    ) -> str:
        result = await self.parse_text(
            text,
            source_name=source_name,
            relative_path=relative_path,
        )
        return result.to_json(indent=indent)

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
        normalized = state["text"].lstrip("\ufeff").replace("\r\n", "\n").strip()
        if not normalized:
            return {
                "error": _issue_state(
                    ParseIssue(ParseErrorCode.INPUT_EMPTY, "Rule text cannot be empty")
                )
            }
        if len(normalized) > self._max_characters:
            return {
                "error": _issue_state(
                    ParseIssue(
                        ParseErrorCode.INPUT_TOO_LARGE,
                        f"Rule text exceeds the {self._max_characters} character limit",
                    )
                )
            }
        return {
            "text": normalized,
            "source_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "error": None,
        }

    async def _invoke_model(self, state: ParserState) -> ParserState:
        previous_error = state.get("error")
        feedback = tuple(previous_error["details"]) if previous_error else ()
        attempts = state.get("attempts", 0) + 1
        try:
            raw_candidate = await self._model.generate_candidate(
                text=state["text"],
                candidate_schema=RuleCandidate.model_json_schema(
                    by_alias=True,
                    mode="validation",
                ),
                field_catalog=catalog_for_prompt(),
                feedback=feedback,
            )
        except RuleParsingError as error:
            return {"attempts": attempts, "error": _issue_state(error.issue)}
        return {
            "attempts": attempts,
            "raw_candidate": raw_candidate,
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
            return {"error": _issue_state(issue)}

        try:
            candidate = RuleCandidate.model_validate(decoded)
        except ValidationError as error:
            issue = ParseIssue(
                ParseErrorCode.CANDIDATE_SCHEMA_INVALID,
                "DeepSeek output does not match the rule candidate schema",
                retryable=True,
                details=_validation_details(error),
            )
            return {"error": _issue_state(issue)}

        try:
            validate_candidate(candidate)
        except SemanticValidationError as error:
            issue = ParseIssue(
                ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                "DeepSeek output failed deterministic semantic validation",
                retryable=True,
                details=error.issues[:12],
            )
            return {"error": _issue_state(issue)}

        return {"candidate": candidate.model_dump(mode="json"), "error": None}

    def _build_result(self, state: ParserState) -> ParserState:
        candidate = RuleCandidate.model_validate(state["candidate"])
        parsed_rule = enrich_candidate(candidate)
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        source_hash = state["source_hash"]
        result = RuleParseResult(
            schema_version=SCHEMA_VERSION,
            rule_version=f"{candidate.rule_id}@{timestamp}-{source_hash[:12]}",
            generated_at=now,
            parser=ParserMetadata(
                parser_version=__version__,
                prompt_version=PROMPT_VERSION,
                model=self._model.model_name,
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
