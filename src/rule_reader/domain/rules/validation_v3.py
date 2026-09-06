"""Deterministic semantic validation and evaluation for V3 rule structures."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeVar

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.models import FactDataType, RuleOperator
from rule_reader.domain.rules.v2 import (
    ConditionKindV2,
    ConditionNodeV2,
    FactKind,
    FactParameterV2,
    RequiredFactV2,
)
from rule_reader.domain.rules.v3 import (
    STAGE_ORDER_V3,
    RuleNodeStatusV3,
    RuleOutcomeV3,
    RuleStructureCandidateV3,
)
from rule_reader.domain.rules.validation_v2 import (
    EvaluationResult,
    SemanticValidationErrorV2,
    condition_fact_refs,
    evaluate_condition,
    infer_expression_type,
    validate_safe_structured_payload,
)


class SemanticValidationErrorV3(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class RuleEvaluationV3:
    outcome: RuleOutcomeV3
    matched_rule_codes: tuple[str, ...]
    reason_code: str


NUMERIC_TYPES = {FactDataType.INTEGER, FactDataType.NUMBER, FactDataType.MONEY}
DuplicateValue = TypeVar("DuplicateValue", str, int)


def _duplicates(values: Sequence[DuplicateValue]) -> list[DuplicateValue]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _catalog_fact_map(
    catalog: BusinessConfirmedFactCatalogV3,
) -> dict[str, RequiredFactV2]:
    result: dict[str, RequiredFactV2] = {}
    for fact in catalog.facts:
        parameters = [
            FactParameterV2(
                name=parameter.name,
                data_type=parameter.data_type,
                description=parameter.description,
                required=parameter.required,
            )
            for parameter in fact.parameters
        ]
        result[fact.fact_code] = RequiredFactV2(
            fact_code=fact.fact_code,
            name=fact.name,
            fact_kind=FactKind.SOURCE,
            data_type=fact.data_type,
            description=fact.description,
            nullable=fact.nullable,
            null_policy=fact.null_policy,
            grain=fact.grain,
            parameters=parameters,
            unit=fact.unit,
            allowed_values=list(fact.allowed_values),
        )
    return result


def _walk_conditions(node: ConditionNodeV2) -> list[ConditionNodeV2]:
    result = [node]
    for child in node.children:
        result.extend(_walk_conditions(child))
    return result


def _compatible(left: FactDataType, right: FactDataType) -> bool:
    return (
        left == right
        or (left in NUMERIC_TYPES and right in NUMERIC_TYPES)
        or (
            left is FactDataType.ENUM
            and right in {FactDataType.STRING, FactDataType.INTEGER, FactDataType.NUMBER}
        )
    )


def _validate_condition_types(
    node: ConditionNodeV2,
    facts: dict[str, RequiredFactV2],
    issues: list[str],
) -> None:
    for condition in _walk_conditions(node):
        if condition.kind is not ConditionKindV2.COMPARE:
            continue
        assert condition.left is not None and condition.operator is not None
        left_type = infer_expression_type(condition.left, facts, issues)
        if condition.right is None:
            continue
        right_type = infer_expression_type(condition.right, facts, issues)
        if condition.operator in {RuleOperator.IN, RuleOperator.NOT_IN}:
            if right_type is not FactDataType.LIST:
                issues.append(f"rule condition {condition.id} requires a list right expression")
        elif condition.operator in {
            RuleOperator.GT,
            RuleOperator.GTE,
            RuleOperator.LT,
            RuleOperator.LTE,
        }:
            comparable = NUMERIC_TYPES | {FactDataType.DATE, FactDataType.DATETIME}
            if left_type not in comparable or right_type not in comparable:
                issues.append(f"rule condition {condition.id} uses non-orderable types")
            elif not _compatible(left_type, right_type):
                issues.append(f"rule condition {condition.id} compares incompatible types")
        elif condition.operator in {RuleOperator.EQ, RuleOperator.NE} and not _compatible(
            left_type, right_type
        ):
            issues.append(f"rule condition {condition.id} compares incompatible types")


def validate_rule_structure_candidate_v3(
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
) -> None:
    """Validate catalog identity, stage ordering, references, types, and blockers."""

    issues: list[str] = []
    try:
        validate_fact_catalog_v3(catalog)
        validate_safe_structured_payload(candidate.model_dump(mode="json", by_alias=True))
    except (ValueError, SemanticValidationErrorV2) as error:
        issues.extend(getattr(error, "issues", (str(error),)))

    if (
        candidate.catalog_id,
        candidate.catalog_version,
        candidate.catalog_digest,
    ) != (catalog.catalog_id, catalog.catalog_version, catalog.catalog_digest):
        issues.append("candidate catalog identity does not match confirmed catalog")

    actual_stages = tuple(stage.stage for stage in candidate.stages)
    if actual_stages != STAGE_ORDER_V3:
        issues.append("stages must appear exactly once in the frozen V3 order")

    rule_codes = [rule.rule_code for stage in candidate.stages for rule in stage.rules]
    if duplicates := _duplicates(rule_codes):
        issues.append(f"duplicate ruleCode values: {duplicates}")
    for stage in candidate.stages:
        priorities = [rule.priority for rule in stage.rules]
        if priority_duplicates := _duplicates(priorities):
            issues.append(
                f"stage {stage.stage.value} has duplicate priorities: {priority_duplicates}"
            )
        if priorities != sorted(priorities):
            issues.append(f"stage {stage.stage.value} rules must be sorted by priority")
        for rule in stage.rules:
            if rule.status is RuleNodeStatusV3.BLOCKED:
                continue
            if stage.stage.value == "eligibility" and rule.outcome is not RuleOutcomeV3.READY:
                issues.append(f"eligibility rule {rule.rule_code} must produce READY")
            if stage.stage.value == "stateGuards" and rule.outcome not in {
                RuleOutcomeV3.SKIPPED,
                RuleOutcomeV3.ALREADY_RELEASED,
                RuleOutcomeV3.NO_RELEASE_REQUIRED,
            }:
                issues.append(f"stateGuards rule {rule.rule_code} has an invalid terminal outcome")
            if stage.stage.value == "prerequisites" and rule.outcome not in {
                RuleOutcomeV3.WAITING_COMPLETION,
                RuleOutcomeV3.WAITING_CONDITIONS,
                RuleOutcomeV3.NO_RELEASE_REQUIRED,
                RuleOutcomeV3.ALREADY_RELEASED,
            }:
                issues.append(
                    f"prerequisites rule {rule.rule_code} has an invalid terminal outcome"
                )
            if stage.stage.value in {"postGates", "exclusions"} and rule.outcome not in {
                RuleOutcomeV3.WAITING_CONDITIONS,
                RuleOutcomeV3.NO_RELEASE_REQUIRED,
                RuleOutcomeV3.INDETERMINATE,
            }:
                issues.append(
                    f"{stage.stage.value} rule {rule.rule_code} has an invalid terminal outcome"
                )

    issue_ids = [issue.issue_id for issue in candidate.blocking_issues]
    if duplicates := _duplicates(issue_ids):
        issues.append(f"duplicate blocking issue ids: {duplicates}")
    known_issues = set(issue_ids)
    referenced_issues: set[str] = set()
    active_refs: set[str] = set()
    condition_ids: list[str] = []
    facts = _catalog_fact_map(catalog)
    for stage in candidate.stages:
        for rule in stage.rules:
            referenced_issues.update(rule.blocking_issue_ids)
            if rule.status is RuleNodeStatusV3.BLOCKED:
                continue
            assert rule.when is not None
            active_refs.update(condition_fact_refs(rule.when))
            condition_ids.extend(node.id for node in _walk_conditions(rule.when))
            _validate_condition_types(rule.when, facts, issues)
    if duplicates := _duplicates(condition_ids):
        issues.append(f"duplicate condition ids: {duplicates}")
    if unknown := sorted(referenced_issues - known_issues):
        issues.append(f"rules reference unknown blocking issues: {unknown}")
    if unreferenced := sorted(known_issues - referenced_issues):
        issues.append(f"blocking issues are not referenced by blocked rules: {unreferenced}")

    catalog_codes = set(facts)
    declared = set(candidate.required_fact_codes)
    if duplicates := _duplicates(candidate.required_fact_codes):
        issues.append(f"duplicate requiredFactCodes: {duplicates}")
    if unknown := sorted(active_refs - catalog_codes):
        issues.append(f"active rules reference unconfirmed facts: {unknown}")
    if declared != active_refs:
        issues.append(
            "requiredFactCodes must equal the active condition reference closure: "
            f"declared={sorted(declared)}, actual={sorted(active_refs)}"
        )
    if unknown := sorted(declared - catalog_codes):
        issues.append(f"requiredFactCodes contain unconfirmed facts: {unknown}")
    if candidate.default_outcome is not RuleOutcomeV3.WAITING_CONDITIONS:
        issues.append("defaultOutcome must be WAITING_CONDITIONS")
    if len(candidate.source_views) != len(set(candidate.source_views)):
        issues.append("sourceViews must be unique")

    proposed_codes = [fact.fact_code for fact in candidate.proposed_facts]
    if duplicates := _duplicates(proposed_codes):
        issues.append(f"duplicate proposed fact codes: {duplicates}")
    if collisions := sorted(set(proposed_codes) & catalog_codes):
        issues.append(f"proposed facts collide with confirmed facts: {collisions}")
    blocking_fact_codes = {code for issue in candidate.blocking_issues for code in issue.fact_codes}
    if unreferenced := sorted(set(proposed_codes) - blocking_fact_codes):
        issues.append(f"proposed facts are not referenced by blocking issues: {unreferenced}")
    if missing := sorted(blocking_fact_codes - set(proposed_codes) - catalog_codes):
        issues.append(f"blocking issues reference undeclared fact concepts: {missing}")
    if issues:
        raise SemanticValidationErrorV3(issues)


def _matches_data_type(value: Any, data_type: FactDataType) -> bool:
    if data_type is FactDataType.BOOLEAN:
        return isinstance(value, bool)
    if data_type is FactDataType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type in NUMERIC_TYPES:
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if data_type is FactDataType.STRING:
        return isinstance(value, str)
    if data_type is FactDataType.ENUM:
        return isinstance(value, (str, int, float, bool))
    if data_type is FactDataType.LIST:
        return isinstance(value, list)
    if data_type is FactDataType.UNKNOWN:
        return True
    if not isinstance(value, str):
        return False
    try:
        if data_type is FactDataType.DATE:
            return "T" not in value and date.fromisoformat(value) is not None
        if data_type is FactDataType.DATETIME:
            return "T" in value and datetime.fromisoformat(value.replace("Z", "+00:00")) is not None
    except ValueError:
        return False
    return False


def _safe_evaluate_condition(
    node: ConditionNodeV2,
    given: dict[str, Any],
    facts: dict[str, RequiredFactV2],
) -> EvaluationResult:
    try:
        return evaluate_condition(node, given, facts)
    except (ArithmeticError, TypeError, ValueError):
        return EvaluationResult.INDETERMINATE


def _given_issues_v3(catalog: BusinessConfirmedFactCatalogV3, given: dict[str, Any]) -> list[str]:
    catalog_by_code = {fact.fact_code: fact for fact in catalog.facts}
    issues: list[str] = []
    if unknown_inputs := sorted(set(given) - set(catalog_by_code)):
        issues.append(f"given contains unknown facts: {unknown_inputs}")
    for code, value in given.items():
        fact = catalog_by_code.get(code)
        if fact is None:
            continue
        if value is None and not fact.nullable:
            issues.append(f"given[{code}] is null but the fact is not nullable")
        elif value is not None and not _matches_data_type(value, fact.data_type):
            issues.append(f"given[{code}] does not match {fact.data_type.value}")
        elif value is not None and fact.allowed_values and value not in fact.allowed_values:
            issues.append(f"given[{code}] is outside allowedValues")
    return issues


def evaluate_rule_structure_v3(
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
    given: dict[str, Any],
) -> RuleEvaluationV3:
    """Evaluate an unblocked candidate in stage/priority order without side effects."""

    validate_rule_structure_candidate_v3(candidate, catalog)
    if candidate.blocking_issues:
        return RuleEvaluationV3(RuleOutcomeV3.INDETERMINATE, (), "BUSINESS_CONFIRMATION_REQUIRED")
    input_issues = _given_issues_v3(catalog, given)
    if input_issues:
        raise SemanticValidationErrorV3(input_issues)

    facts = _catalog_fact_map(catalog)
    outcome = candidate.default_outcome
    reason_code = candidate.default_reason_code
    matched: list[str] = []
    for stage in candidate.stages:
        indeterminate = False
        for rule in stage.rules:
            if rule.status is RuleNodeStatusV3.BLOCKED:
                continue
            assert rule.when is not None
            assert rule.outcome is not None
            assert rule.reason_code is not None
            result = _safe_evaluate_condition(rule.when, given, facts)
            if result is EvaluationResult.PASS:
                outcome = rule.outcome
                reason_code = rule.reason_code
                matched.append(rule.rule_code)
                if stage.stage.value != "eligibility":
                    return RuleEvaluationV3(outcome, tuple(matched), reason_code)
                break
            if result is EvaluationResult.INDETERMINATE:
                indeterminate = True
        else:
            if indeterminate:
                return RuleEvaluationV3(
                    RuleOutcomeV3.INDETERMINATE,
                    tuple(matched),
                    "FACT_VALUE_MISSING_OR_INVALID",
                )
    return RuleEvaluationV3(outcome, tuple(matched), reason_code)


def validate_rule_reachability_witnesses_v3(
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
    witnesses: dict[str, dict[str, Any]],
) -> None:
    """Prove every active rule can be first match within its stage using external witnesses."""

    validate_rule_structure_candidate_v3(candidate, catalog)
    facts = _catalog_fact_map(catalog)
    active_codes = {
        rule.rule_code
        for stage in candidate.stages
        for rule in stage.rules
        if rule.status is RuleNodeStatusV3.ACTIVE
    }
    issues: list[str] = []
    if missing := sorted(active_codes - set(witnesses)):
        issues.append(f"active rules without reachability witnesses: {missing}")
    if extra := sorted(set(witnesses) - active_codes):
        issues.append(f"reachability witnesses for unknown or blocked rules: {extra}")
    for stage in candidate.stages:
        earlier: list[Any] = []
        for rule in stage.rules:
            if rule.status is RuleNodeStatusV3.BLOCKED:
                continue
            given = witnesses.get(rule.rule_code)
            if given is None:
                earlier.append(rule)
                continue
            for issue in _given_issues_v3(catalog, given):
                issues.append(f"witness for {rule.rule_code}: {issue}")
            assert rule.when is not None
            target_result = _safe_evaluate_condition(rule.when, given, facts)
            if target_result is not EvaluationResult.PASS:
                issues.append(f"witness for {rule.rule_code} does not make the target rule pass")
            for prior in earlier:
                assert prior.when is not None
                if _safe_evaluate_condition(prior.when, given, facts) is EvaluationResult.PASS:
                    issues.append(
                        f"witness for {rule.rule_code} is captured by earlier rule "
                        f"{prior.rule_code}"
                    )
            earlier.append(rule)
    if issues:
        raise SemanticValidationErrorV3(issues)
