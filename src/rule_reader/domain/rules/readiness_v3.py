"""Deterministic V2 compatibility and Agent 2 readiness reports for V3 candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.bindings_v3 import (
    AggregationModeV3,
    FactBindingRequestV3,
    TimeRangeModeV3,
)
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3, FactParameterRoleV3
from rule_reader.domain.rules.models import RuleOperator
from rule_reader.domain.rules.result_v3 import RuleParseResultV3
from rule_reader.domain.rules.v2 import ConditionNodeV2, FactKind
from rule_reader.domain.rules.v3 import RuleNodeStatusV3, RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v2 import condition_fact_refs

_UNARY_OPERATORS = {
    RuleOperator.IS_NULL,
    RuleOperator.IS_NOT_NULL,
    RuleOperator.IS_BLANK,
    RuleOperator.IS_NOT_BLANK,
}

_AGGREGATION_KIND_MODES: dict[FactKind, set[AggregationModeV3]] = {
    FactKind.SOURCE: {AggregationModeV3.NONE, AggregationModeV3.PRECOMPUTED},
    FactKind.AGGREGATE: {AggregationModeV3.COMPUTE},
    FactKind.EXISTS: {AggregationModeV3.EXISTS},
}

_TIME_RANGE_MODES = set(TimeRangeModeV3)

_EXPORTABLE_FACT_KINDS = {FactKind.SOURCE, FactKind.AGGREGATE, FactKind.EXISTS}


class ReportModelV3(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class ReviewOwnerV3(StrEnum):
    BUSINESS_RULE_REVIEW = "businessRuleReview"
    RULE_CONTRACT_DESIGN = "ruleContractDesign"


class GateResultV3(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class CompatibilityGateV3(ReportModelV3):
    gate_id: str
    result: GateResultV3
    reason: str


class V2V3CompatibilityDecision(ReportModelV3):
    selected_path: str = "B"
    semantically_equivalent: bool = False
    v2_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    v3_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    gates: list[CompatibilityGateV3]
    conclusion: str


class GapDimensionsV3(ReportModelV3):
    missing_fact: bool
    source_conflict: bool
    enum_conflict: bool
    type_conflict: bool
    entity_grain: bool
    parameter_roles: bool
    null_policy: bool
    filter_semantics: bool
    aggregation_semantics: bool
    time_semantics: bool


class BlockingGapV3(ReportModelV3):
    issue_id: str
    issue_code: str
    stages: list[str]
    rule_codes: list[str]
    owner: ReviewOwnerV3
    fact_codes: list[str]
    missing_fact_codes: list[str]
    dimensions: GapDimensionsV3
    blocks_agent2_handoff: bool = True
    business_confirmation: str
    deterministic_fix_available: bool = False


class ReadinessGateV3(ReportModelV3):
    gate: int = Field(ge=1, le=16)
    name: str
    result: GateResultV3
    evidence: str


class Agent2ReadinessReportV3(ReportModelV3):
    rule_set_id: str
    ready: bool
    selected_path: str
    blocking_count: int
    counts_by_code: dict[str, int]
    gaps: list[BlockingGapV3]
    gates: list[ReadinessGateV3]
    planned_rule_versions: int
    planned_handoffs: int
    requires_sqlbot_contract_upgrade: bool


def assess_v2_compatibility_v3(
    *,
    v2_source_sha256: str,
    v3_source_sha256: str,
) -> V2V3CompatibilityDecision:
    gates = [
        CompatibilityGateV3(
            gate_id="sourceIdentity",
            result=GateResultV3.FAIL,
            reason="V2 remediation and ordered V3 bind different normalized source SHA-256 values.",
        ),
        CompatibilityGateV3(
            gate_id="stageOrder",
            result=GateResultV3.FAIL,
            reason="RuleParseResultV2 has one root condition and no five-stage ordering contract.",
        ),
        CompatibilityGateV3(
            gate_id="priority",
            result=GateResultV3.FAIL,
            reason="RuleParseResultV2 cannot preserve first-match rule priority across stages.",
        ),
        CompatibilityGateV3(
            gate_id="multiOutcome",
            result=GateResultV3.FAIL,
            reason="V2 test/evaluation outcomes are pass/fail and lose V3 terminal outcomes.",
        ),
        CompatibilityGateV3(
            gate_id="postGateAndExclusion",
            result=GateResultV3.FAIL,
            reason="V2 has no native postGates or exclusions that can downgrade an earlier result.",
        ),
    ]
    return V2V3CompatibilityDecision(
        v2_source_sha256=v2_source_sha256,
        v3_source_sha256=v3_source_sha256,
        gates=gates,
        conclusion=(
            "Path A is rejected. Restoring the V2 remediation would change source identity "
            "and lose "
            "ordered V3 semantics; use Path B and keep the current candidate blocked."
        ),
    )


def _gap_dimensions(issue_id: str, issue_code: str) -> GapDimensionsV3:
    missing = issue_code == "BUSINESS_FACT_MISSING"
    conflict = issue_code in {
        "SOURCE_VALUE_CONFLICT",
        "SOURCE_BRANCH_UNREACHABLE_WITH_CONFIRMED_ENUM",
    }
    aggregation = issue_id in {"rule.r0", "rule.r5", "rule.r6", "rule.r7", "report.merge"}
    time_semantics = issue_id in {"rule.r4", "rule.r8"}
    return GapDimensionsV3(
        missing_fact=missing,
        source_conflict=conflict,
        enum_conflict=conflict,
        type_conflict=issue_code == "SOURCE_VALUE_CONFLICT",
        entity_grain=missing,
        parameter_roles=missing,
        null_policy=missing or conflict,
        filter_semantics=True,
        aggregation_semantics=aggregation,
        time_semantics=time_semantics,
    )


def _condition_fact_codes(node: ConditionNodeV2) -> set[str]:
    return condition_fact_refs(node)


def build_agent2_readiness_report_v3(
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
    result: RuleParseResultV3 | None = None,
    requests: Sequence[FactBindingRequestV3] | None = None,
) -> Agent2ReadinessReportV3:
    locations: dict[str, tuple[list[str], list[str]]] = {}
    for stage in candidate.stages:
        for rule in stage.rules:
            for issue_id in rule.blocking_issue_ids:
                stages, rules = locations.setdefault(issue_id, ([], []))
                stages.append(stage.stage.value)
                rules.append(rule.rule_code)
    catalog_codes = {fact.fact_code for fact in catalog.facts}
    gaps = [
        BlockingGapV3(
            issue_id=issue.issue_id,
            issue_code=issue.code,
            stages=locations.get(issue.issue_id, ([], []))[0],
            rule_codes=locations.get(issue.issue_id, ([], []))[1],
            owner=ReviewOwnerV3.BUSINESS_RULE_REVIEW,
            fact_codes=issue.fact_codes,
            missing_fact_codes=sorted(set(issue.fact_codes) - catalog_codes),
            dimensions=_gap_dimensions(issue.issue_id, issue.code),
            business_confirmation=(
                "Confirm the logical fact contract and reconcile all valid source representations "
                f"for issue {issue.issue_id}; do not select a source implicitly."
            ),
        )
        for issue in candidate.blocking_issues
    ]
    counts = dict(sorted(Counter(gap.issue_code for gap in gaps).items()))

    facts_by_code = {fact.fact_code: fact for fact in catalog.facts}
    evidence_ids = {evidence.evidence_id for evidence in catalog.evidence}
    rule_nodes = [rule for stage in candidate.stages for rule in stage.rules]
    blocked_nodes = [rule for rule in rule_nodes if rule.status is RuleNodeStatusV3.BLOCKED]
    referenced: set[str] = set(candidate.required_fact_codes)
    for issue in candidate.blocking_issues:
        referenced.update(issue.fact_codes)
    for rule in rule_nodes:
        if rule.when is not None:
            referenced |= _condition_fact_codes(rule.when)
    missing_contracts = sorted(referenced - catalog_codes)
    has_blockers = bool(candidate.blocking_issues)
    contracts_pending = has_blockers or bool(missing_contracts)
    entity_ok = not missing_contracts and all(
        facts_by_code[code].grain
        and any(
            parameter.role is FactParameterRoleV3.ENTITY_KEY
            for parameter in facts_by_code[code].parameters
        )
        for code in referenced
        if code in facts_by_code
    )
    evidence_ok = not missing_contracts and all(
        bool(fact.evidence_refs) and set(fact.evidence_refs) <= evidence_ids
        for code in referenced
        if (fact := facts_by_code.get(code)) is not None
    )
    identity_ok = (
        candidate.catalog_id == catalog.catalog_id
        and candidate.catalog_version == catalog.catalog_version
        and candidate.catalog_digest == catalog.catalog_digest
    )
    query_pending_evidence = "Query requirements await RuleParseResultV3 (Slice 3-6)."

    gate_values: list[tuple[int, str, GateResultV3, str]] = [
        (1, "immutableRuleVersion", GateResultV3.FAIL, "No RuleParseResultV3 exists."),
        (
            2,
            "noBusinessBlocking",
            GateResultV3.FAIL if has_blockers else GateResultV3.PASS,
            f"{len(gaps)} blockers." if has_blockers else "No blocking issues remain.",
        ),
        (
            3,
            "requiredFactsComplete",
            GateResultV3.FAIL if contracts_pending else GateResultV3.PASS,
            "Missing facts remain."
            if contracts_pending
            else "All required facts have confirmed contracts.",
        ),
        (
            4,
            "oneRequestPerAtomicFact",
            GateResultV3.BLOCKED,
            "No export allowed."
            if contracts_pending
            else "Export awaits RuleParseResultV3 (Slice 3-6).",
        ),
        (
            5,
            "derivedFactsExcluded",
            GateResultV3.BLOCKED,
            "Fact kinds unresolved."
            if contracts_pending
            else "Fact kinds are assigned with RuleParseResultV3 (Slice 3-6).",
        ),
        (
            6,
            "entityGrainKeys",
            GateResultV3.PASS if entity_ok else GateResultV3.FAIL,
            "Every referenced fact declares grain and entity key."
            if entity_ok
            else "Missing fact contracts.",
        ),
    ]
    for gate_number, gate_name, blocked_evidence in [
        (7, "stableFields", "No complete field requirements."),
        (8, "filtersComplete", "Filter sets are incomplete."),
        (9, "filterSemantics", "Filter values/nulls unresolved."),
        (10, "aggregationComplete", "Aggregations unresolved."),
        (11, "timeRangeComplete", "Time boundaries unresolved."),
        (12, "scalarResult", "Result contracts unresolved."),
    ]:
        gate_values.append(
            (
                gate_number,
                gate_name,
                GateResultV3.FAIL,
                blocked_evidence if contracts_pending else query_pending_evidence,
            )
        )
    gate_values.extend(
        [
            (
                13,
                "stableConditionUsage",
                GateResultV3.FAIL if blocked_nodes else GateResultV3.PASS,
                "Blocked rules lack conditions."
                if blocked_nodes
                else "Every rule carries an active condition.",
            ),
            (
                14,
                "evidenceClosure",
                GateResultV3.PASS if evidence_ok else GateResultV3.FAIL,
                "Every referenced fact closes to catalog evidence."
                if evidence_ok
                else "Missing facts lack evidence.",
            ),
            (
                15,
                "provenanceComplete",
                GateResultV3.PASS if identity_ok else GateResultV3.FAIL,
                "Source/catalog hashes close."
                if identity_ok
                else "Candidate catalog identity does not match the confirmed catalog.",
            ),
            (16, "candidateNonExecutable", GateResultV3.PASS, "Executable is false."),
        ]
    )

    result_overrides: dict[int, tuple[GateResultV3, str]] = {}
    if result is not None:
        version_identity_ok = (
            result.rule_version.endswith(
                f"{result.candidate_ref.rule_block_sha256[:12]}"
                f"-{result.catalog_ref.catalog_digest[:12]}"
            )
            and result.candidate_ref.rule_block_sha256 == result.source.source_sha256
            and result.catalog_ref.catalog_id == catalog.catalog_id
            and result.catalog_ref.catalog_version == catalog.catalog_version
            and result.catalog_ref.catalog_digest == catalog.catalog_digest
        )
        result_overrides[1] = (
            (GateResultV3.PASS, "Immutable rule version closes to source and catalog identity.")
            if version_identity_ok
            else (
                GateResultV3.FAIL,
                "Rule version identity does not close to source and catalog.",
            )
        )
        result_overrides[5] = (
            (GateResultV3.FAIL, "Derived facts cannot be declared or exported.")
            if any(
                declaration.fact.fact_kind not in _EXPORTABLE_FACT_KINDS
                for declaration in result.fact_declarations
            )
            else (
                GateResultV3.PASS,
                "Fact kinds are assigned and no derived fact is declared.",
            )
        )
        if requests is None:
            result_overrides[4] = (
                GateResultV3.BLOCKED,
                "Export awaits RuleParseResultV3 requests.",
            )
        else:
            expected_codes = {
                declaration.fact.fact_code for declaration in result.fact_declarations
            }
            exported_codes = {request.fact.fact_code for request in requests}
            identity_closed = all(
                request.request_id == f"{result.rule_version}#{request.fact.fact_code}"
                for request in requests
            )
            result_overrides[4] = (
                (
                    GateResultV3.PASS,
                    "One request per non-derived fact with closed identity.",
                )
                if expected_codes == exported_codes
                and len(requests) == len(expected_codes)
                and identity_closed
                else (
                    GateResultV3.FAIL,
                    "Request export does not close to fact declarations.",
                )
            )
        result_overrides[7] = (
            (GateResultV3.PASS, "Every fact declaration carries stable field requirements.")
            if all(
                any(
                    field.field_id == "factValue" and field.required
                    for field in declaration.query.fields
                )
                for declaration in result.fact_declarations
            )
            else (GateResultV3.FAIL, "Fact declarations lack stable field requirements.")
        )
        result_overrides[8] = (
            (GateResultV3.PASS, "Filter sets are complete on every fact declaration.")
            if all(
                declaration.query.filters.completeness == "complete"
                for declaration in result.fact_declarations
            )
            else (GateResultV3.FAIL, "Fact declaration filter sets are incomplete.")
        )
        result_overrides[9] = (
            (GateResultV3.PASS, "Filter values and null policies are resolved on every fact.")
            if all(
                item.value is not None or item.operator in _UNARY_OPERATORS
                for declaration in result.fact_declarations
                for item in declaration.query.filters.items
            )
            else (GateResultV3.FAIL, "Fact declaration filter semantics are unresolved.")
        )
        result_overrides[10] = (
            (GateResultV3.PASS, "Aggregation semantics are explicit on every fact declaration.")
            if all(
                declaration.query.aggregation.mode
                in _AGGREGATION_KIND_MODES[declaration.fact.fact_kind]
                for declaration in result.fact_declarations
            )
            else (GateResultV3.FAIL, "Fact declaration aggregations are unresolved.")
        )
        result_overrides[11] = (
            (GateResultV3.PASS, "Time range semantics are explicit on every fact declaration.")
            if all(
                declaration.query.time_range.mode in _TIME_RANGE_MODES
                for declaration in result.fact_declarations
            )
            else (GateResultV3.FAIL, "Fact declaration time boundaries are unresolved.")
        )
        result_overrides[12] = (
            (GateResultV3.PASS, "Scalar fact_value results are declared on every fact.")
            if all(
                declaration.query.result.column_name == "fact_value"
                and declaration.query.result.cardinality == "scalar"
                and declaration.query.result.data_type is declaration.fact.data_type
                for declaration in result.fact_declarations
            )
            else (GateResultV3.FAIL, "Fact declaration result contracts are unresolved.")
        )
    gate_values = [
        (gate, name, *result_overrides[gate]) if gate in result_overrides else (gate, name, res, ev)
        for gate, name, res, ev in gate_values
    ]
    gates = [
        ReadinessGateV3(gate=gate, name=name, result=gate_result, evidence=evidence)
        for gate, name, gate_result, evidence in gate_values
    ]
    return Agent2ReadinessReportV3(
        rule_set_id=candidate.rule_set_id,
        ready=all(gate.result is GateResultV3.PASS for gate in gates),
        selected_path="B",
        blocking_count=len(gaps),
        counts_by_code=counts,
        gaps=gaps,
        gates=gates,
        planned_rule_versions=0,
        planned_handoffs=0,
        requires_sqlbot_contract_upgrade=True,
    )
