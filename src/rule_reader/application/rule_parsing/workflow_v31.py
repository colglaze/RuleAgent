"""LangGraph workflow for Agent1 offline Schema 3.1.0 optimization-plan generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from rule_reader.domain.optimization_plan import (
    EXTRACTED_SECTIONS,
    EXTRACTOR_VERSION,
    OPTIMIZATION_PLAN_FILE_SHA256,
    PARSER_MODEL,
    PROMPT_VERSION,
)
from rule_reader.domain.optimization_plan.extractor import (
    SourceIdentityError,
    build_source_identity,
)
from rule_reader.domain.optimization_plan.profile import (
    OptimizationPlanDelivery,
    build_data_delivery,
    build_report_delivery,
)
from rule_reader.domain.rules.audit import ParseAttemptAudit, ParseAudit
from rule_reader.domain.rules.errors import ParseErrorCode, ParseIssue, RuleParsingError
from rule_reader.domain.rules.purpose_v31 import (
    HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
    DeliveryPurposeDeniedError,
    DeliveryPurposeV31,
    assert_delivery_purpose_allowed,
)
from rule_reader.domain.rules.v31 import SourceIdentityV31

_MAX_ATTEMPTS = 1


class V31State(TypedDict, total=False):
    source_file_sha256: str
    parse_input_sha256: str
    extractor_version: str
    extracted_sections: list[str]
    source_file_byte_length: int
    parse_input_character_count: int
    report_delivery: OptimizationPlanDelivery
    data_delivery: OptimizationPlanDelivery
    error: ParseIssue | None


@dataclass(frozen=True, slots=True)
class OptimizationPlanAgentRun:
    report: OptimizationPlanDelivery
    data: OptimizationPlanDelivery
    audit: ParseAudit


def _identity_from_state(state: V31State) -> SourceIdentityV31:
    return SourceIdentityV31(
        source_file_sha256=state["source_file_sha256"],
        parse_input_sha256=state["parse_input_sha256"],
        extractor_version=state["extractor_version"],
        extracted_sections=list(state["extracted_sections"]),
        source_file_byte_length=state["source_file_byte_length"],
        parse_input_character_count=state["parse_input_character_count"],
    )


def _semantic_issue(message: str, details: tuple[str, ...] = ()) -> ParseIssue:
    return ParseIssue(
        ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
        message,
        details=details,
    )


class OptimizationPlanParsingService:
    """Agent1 entry that emits both 3.1.0 complete deliveries without a model."""

    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def generate(self, identity: SourceIdentityV31) -> OptimizationPlanAgentRun:
        request_id = uuid4()
        initial: V31State = {
            "source_file_sha256": identity.source_file_sha256,
            "parse_input_sha256": identity.parse_input_sha256,
            "extractor_version": identity.extractor_version,
            "extracted_sections": list(identity.extracted_sections),
            "source_file_byte_length": identity.source_file_byte_length,
            "parse_input_character_count": identity.parse_input_character_count,
            "error": None,
        }
        final = cast(V31State, await self._graph.ainvoke(initial))
        error = final.get("error")
        if error is not None:
            raise RuleParsingError(replace(error, audit=self._audit(request_id, error.code.value)))
        report = final.get("report_delivery")
        data = final.get("data_delivery")
        if report is None or data is None:
            raise RuleParsingError(
                ParseIssue(
                    ParseErrorCode.PROVIDER_RESPONSE_INVALID,
                    "Optimization-plan generation ended without both deliveries",
                    audit=self._audit(request_id, ParseErrorCode.PROVIDER_RESPONSE_INVALID.value),
                )
            )
        return OptimizationPlanAgentRun(
            report=report,
            data=data,
            audit=self._audit(request_id, "SUCCESS"),
        )

    async def generate_from_source_bytes(
        self,
        file_bytes: bytes,
        source_text: str,
        *,
        expected_file_sha256: str = OPTIMIZATION_PLAN_FILE_SHA256,
    ) -> OptimizationPlanAgentRun:
        try:
            _extracted, identity = build_source_identity(
                file_bytes,
                source_text,
                expected_file_sha256=expected_file_sha256,
            )
        except SourceIdentityError as error:
            issue = _semantic_issue(str(error))
            raise RuleParsingError(
                replace(issue, audit=self._audit(uuid4(), issue.code.value))
            ) from error
        return await self.generate(identity)

    def _build_graph(self) -> Any:
        builder = StateGraph(V31State)
        builder.add_node("check_identity", self._check_identity)
        builder.add_node("generate_report", self._generate_report)
        builder.add_node("generate_data", self._generate_data)
        builder.add_node("gate_delivery", self._gate_delivery)
        builder.add_edge(START, "check_identity")
        builder.add_conditional_edges(
            "check_identity",
            self._route_after_identity,
            {"generate_report": "generate_report", "end": END},
        )
        builder.add_conditional_edges(
            "generate_report",
            self._route_after_report,
            {"generate_data": "generate_data", "end": END},
        )
        builder.add_conditional_edges(
            "generate_data",
            self._route_after_data,
            {"gate_delivery": "gate_delivery", "end": END},
        )
        builder.add_edge("gate_delivery", END)
        return builder.compile()

    def _check_identity(self, state: V31State) -> V31State:
        try:
            identity = _identity_from_state(state)
        except (KeyError, ValidationError):
            return {"error": _semantic_issue("Optimization-plan source identity is invalid")}
        if identity.extractor_version != EXTRACTOR_VERSION:
            return {"error": _semantic_issue("extractor version does not match the frozen extractor")}
        if tuple(identity.extracted_sections) != EXTRACTED_SECTIONS:
            return {"error": _semantic_issue("extracted sections do not match the frozen sections")}
        if identity.source_file_sha256 == identity.parse_input_sha256:
            return {"error": _semantic_issue("source file hash must not equal parse input hash")}
        return {"error": None}

    def _generate_report(self, state: V31State) -> V31State:
        try:
            delivery = build_report_delivery(_identity_from_state(state))
        except (ValueError, ValidationError) as error:
            return {
                "error": ParseIssue(
                    ParseErrorCode.CANDIDATE_SCHEMA_INVALID
                    if isinstance(error, ValidationError)
                    else ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                    "Report 3.1.0 delivery could not be generated",
                    details=(str(error),)[:1],
                )
            }
        return {"report_delivery": delivery, "error": None}

    def _generate_data(self, state: V31State) -> V31State:
        try:
            delivery = build_data_delivery(_identity_from_state(state))
        except (ValueError, ValidationError) as error:
            return {
                "error": ParseIssue(
                    ParseErrorCode.CANDIDATE_SCHEMA_INVALID
                    if isinstance(error, ValidationError)
                    else ParseErrorCode.CANDIDATE_SEMANTIC_INVALID,
                    "Raw-data 3.1.0 delivery could not be generated",
                    details=(str(error),)[:1],
                )
            }
        return {"data_delivery": delivery, "error": None}

    def _gate_delivery(self, state: V31State) -> V31State:
        report = state.get("report_delivery")
        data = state.get("data_delivery")
        if report is None or data is None:
            return {
                "error": _semantic_issue("Optimization-plan generation is missing a delivery"),
            }
        try:
            assert_delivery_purpose_allowed(
                report.result.rule_version, DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION
            )
            assert_delivery_purpose_allowed(
                data.result.rule_version, DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION
            )
        except DeliveryPurposeDeniedError:
            return {"error": _semantic_issue("Delivery purpose is not allowed")}
        if report.result.rule_version == HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION:
            return {"error": _semantic_issue("Historical 2026-09-05 delivery cannot be generated")}
        if report.result.rule_set_id == data.result.rule_set_id:
            return {"error": _semantic_issue("Report and raw-data rule sets must be independent")}
        if report.catalog.catalog_digest == data.catalog.catalog_digest:
            return {"error": _semantic_issue("Report and raw-data catalogs must not share a digest")}
        for delivery in (report, data):
            result = delivery.result
            if (
                result.status != "draft"
                or result.executable is not False
                or result.delivery_ref.purpose != "optimization-plan-generation"
                or result.parser.provider != "reviewed_import"
                or result.parser.model != PARSER_MODEL
                or result.parser.prompt_version != PROMPT_VERSION
            ):
                return {"error": _semantic_issue("Generated delivery is not a 3.1.0 reviewed import")}
            if not delivery.requests:
                return {"error": _semantic_issue("Generated delivery has no fact binding requests")}
        return {"error": None}

    @staticmethod
    def _route_after_identity(state: V31State) -> str:
        return "end" if state.get("error") is not None else "generate_report"

    @staticmethod
    def _route_after_report(state: V31State) -> str:
        return "end" if state.get("error") is not None else "generate_data"

    @staticmethod
    def _route_after_data(state: V31State) -> str:
        return "end" if state.get("error") is not None else "gate_delivery"

    @staticmethod
    def _audit(request_id: UUID, outcome_code: str) -> ParseAudit:
        return ParseAudit(
            request_id=request_id,
            idempotency_key_sha256=None,
            max_attempts=_MAX_ATTEMPTS,
            attempt_count=1,
            total_backoff_seconds=0,
            attempts=[
                ParseAttemptAudit(
                    attempt=1,
                    backoff_seconds=0,
                    outcome_code=outcome_code,
                    retryable=False,
                )
            ],
            total_token_usage=None,
        )
