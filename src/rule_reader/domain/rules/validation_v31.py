"""Deterministic validation and evaluation for Rule Schema 3.1.0."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.models import FactDataType, RuleOperator
from rule_reader.domain.rules.v2 import (
    DateUnit,
    FactKind,
    FactParameterV2,
    NullPolicy,
    RequiredFactV2,
)
from rule_reader.domain.rules.v3 import RuleNodeStatusV3, RuleOutcomeV3, RuleStageNameV3
from rule_reader.domain.rules.v31 import (
    STAGE_ORDER_V31,
    ConditionKindV31,
    ConditionNodeV31,
    DuplicateMemberPolicyV31,
    EmptyCollectionPolicyV31,
    ExpressionKindV31,
    ExpressionNodeV31,
    MissingMemberPolicyV31,
    RuleStructureCandidateV31,
    RuntimeParameterV31,
)
from rule_reader.domain.rules.validation_v2 import (
    EvaluationResult,
    SemanticValidationErrorV2,
    validate_safe_structured_payload,
)
from rule_reader.domain.rules.validation_v3 import NUMERIC_TYPES, SemanticValidationErrorV3

# Asia/Shanghai has no DST; a fixed UTC+8 offset keeps tests independent of tzdata.
BUSINESS_TZ = timezone(timedelta(hours=8))
UNARY_OPERATORS = {
    RuleOperator.IS_NULL,
    RuleOperator.IS_NOT_NULL,
    RuleOperator.IS_BLANK,
    RuleOperator.IS_NOT_BLANK,
}


class _Missing:
    pass


MISSING = _Missing()
EvaluationValue = str | int | float | bool | Decimal | date | datetime | list[Any] | None | _Missing
DuplicateValue = TypeVar("DuplicateValue", str, int)


@dataclass(frozen=True, slots=True)
class RuleEvaluationV31:
    outcome: RuleOutcomeV3
    matched_rule_codes: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True, slots=True)
class EvaluationContextV31:
    facts: Mapping[str, Any]
    runtime: Mapping[str, Any]
    members: Mapping[str, Mapping[str, Any]]


def _duplicates(values: Sequence[DuplicateValue]) -> list[DuplicateValue]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _catalog_fact_map(catalog: BusinessConfirmedFactCatalogV3) -> dict[str, RequiredFactV2]:
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


def walk_conditions_v31(node: ConditionNodeV31) -> list[ConditionNodeV31]:
    result = [node]
    for child in node.children:
        result.extend(walk_conditions_v31(child))
    if node.already_satisfied is not None:
        result.extend(walk_conditions_v31(node.already_satisfied))
    if node.member_predicate is not None:
        result.extend(walk_conditions_v31(node.member_predicate))
    return result


def expression_fact_refs_v31(expression: ExpressionNodeV31 | None) -> set[str]:
    if expression is None:
        return set()
    codes = {expression.fact_code} if expression.fact_code else set()
    for child in expression.children:
        codes |= expression_fact_refs_v31(child)
    return codes


def condition_fact_refs_v31(node: ConditionNodeV31) -> set[str]:
    refs: set[str] = set()
    for condition in walk_conditions_v31(node):
        refs |= expression_fact_refs_v31(condition.left)
        refs |= expression_fact_refs_v31(condition.right)
        if condition.collection_fact_code:
            refs.add(condition.collection_fact_code)
    return refs


def expression_parameter_refs_v31(expression: ExpressionNodeV31 | None) -> set[str]:
    if expression is None:
        return set()
    names = {expression.parameter_name} if expression.parameter_name else set()
    for child in expression.children:
        names |= expression_parameter_refs_v31(child)
    return names


def condition_parameter_refs_v31(node: ConditionNodeV31) -> set[str]:
    names: set[str] = set()
    for condition in walk_conditions_v31(node):
        names |= expression_parameter_refs_v31(condition.left)
        names |= expression_parameter_refs_v31(condition.right)
    return names


def _compatible(left: FactDataType, right: FactDataType) -> bool:
    return (
        left == right
        or (left in NUMERIC_TYPES and right in NUMERIC_TYPES)
        or (
            left is FactDataType.ENUM
            and right in {FactDataType.STRING, FactDataType.INTEGER, FactDataType.NUMBER}
        )
        or (
            left in {FactDataType.DATE, FactDataType.DATETIME}
            and right in {FactDataType.DATE, FactDataType.DATETIME}
        )
    )


def _parameter_map(candidate: RuleStructureCandidateV31) -> dict[str, RuntimeParameterV31]:
    return {item.name: item for item in candidate.runtime_parameters}


def _infer_expression_type(
    expression: ExpressionNodeV31,
    facts: dict[str, RequiredFactV2],
    parameters: dict[str, RuntimeParameterV31],
    issues: list[str],
) -> FactDataType:
    if expression.kind is ExpressionKindV31.FACT:
        fact = facts.get(expression.fact_code or "")
        return FactDataType.UNKNOWN if fact is None else fact.data_type
    if expression.kind is ExpressionKindV31.LITERAL:
        value = expression.value
        if isinstance(value, bool):
            return FactDataType.BOOLEAN
        if isinstance(value, int):
            return FactDataType.INTEGER
        if isinstance(value, float):
            return FactDataType.NUMBER
        if isinstance(value, list):
            return FactDataType.LIST
        if isinstance(value, str) and len(value) == 10 and value[4] == "-":
            return FactDataType.DATE
        return FactDataType.STRING
    if expression.kind is ExpressionKindV31.PARAMETER:
        parameter = parameters.get(expression.parameter_name or "")
        if parameter is None:
            issues.append(f"unknown runtime parameter {expression.parameter_name}")
            return FactDataType.UNKNOWN
        return parameter.data_type
    child_types = [
        _infer_expression_type(child, facts, parameters, issues) for child in expression.children
    ]
    if expression.kind in {
        ExpressionKindV31.ADD,
        ExpressionKindV31.SUBTRACT,
        ExpressionKindV31.MULTIPLY,
        ExpressionKindV31.DIVIDE,
    }:
        if any(item not in NUMERIC_TYPES for item in child_types):
            issues.append(f"{expression.kind.value} expression requires numeric children")
            return FactDataType.UNKNOWN
        return FactDataType.MONEY if FactDataType.MONEY in child_types else FactDataType.NUMBER
    if expression.kind is ExpressionKindV31.COALESCE:
        return child_types[0] if child_types else FactDataType.UNKNOWN
    if expression.kind is ExpressionKindV31.DATE_ADD:
        return child_types[0] if child_types else FactDataType.DATE
    return FactDataType.UNKNOWN


def validate_rule_structure_candidate_v31(
    candidate: RuleStructureCandidateV31,
    catalog: BusinessConfirmedFactCatalogV3,
) -> None:
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
    if actual_stages != STAGE_ORDER_V31:
        issues.append("stages must appear exactly once in the frozen V3 order")

    rule_codes = [rule.rule_code for stage in candidate.stages for rule in stage.rules]
    if duplicates := _duplicates(rule_codes):
        issues.append(f"duplicate ruleCode values: {duplicates}")
    for stage in candidate.stages:
        if stage.stage is RuleStageNameV3.ELIGIBILITY and not stage.rules:
            issues.append("eligibility cannot be empty")
        priorities = [rule.priority for rule in stage.rules]
        if priority_duplicates := _duplicates(priorities):
            issues.append(
                f"stage {stage.stage.value} has duplicate priorities: {priority_duplicates}"
            )
        if priorities != sorted(priorities):
            issues.append(f"stage {stage.stage.value} rules must be sorted by priority")

    facts = _catalog_fact_map(catalog)
    parameters = _parameter_map(candidate)
    active_refs: set[str] = set()
    parameter_refs: set[str] = set()
    condition_ids: list[str] = []
    for stage in candidate.stages:
        for rule in stage.rules:
            if rule.status is RuleNodeStatusV3.BLOCKED:
                continue
            assert rule.when is not None
            active_refs.update(condition_fact_refs_v31(rule.when))
            parameter_refs.update(condition_parameter_refs_v31(rule.when))
            condition_ids.extend(node.id for node in walk_conditions_v31(rule.when))
            for condition in walk_conditions_v31(rule.when):
                if condition.kind is not ConditionKindV31.COMPARE:
                    continue
                assert condition.left is not None and condition.operator is not None
                left_type = _infer_expression_type(condition.left, facts, parameters, issues)
                if condition.right is None:
                    continue
                right_type = _infer_expression_type(condition.right, facts, parameters, issues)
                if condition.operator in {RuleOperator.IN, RuleOperator.NOT_IN}:
                    if right_type is not FactDataType.LIST:
                        issues.append(
                            f"rule condition {condition.id} requires a list right expression"
                        )
                elif condition.operator in {
                    RuleOperator.GT,
                    RuleOperator.GTE,
                    RuleOperator.LT,
                    RuleOperator.LTE,
                }:
                    comparable = NUMERIC_TYPES | {FactDataType.DATE, FactDataType.DATETIME}
                    if left_type not in comparable or right_type not in comparable:
                        issues.append(f"rule condition {condition.id} uses non-orderable types")
                elif condition.operator in {RuleOperator.EQ, RuleOperator.NE} and not _compatible(
                    left_type, right_type
                ):
                    issues.append(f"rule condition {condition.id} compares incompatible types")
    if duplicates := _duplicates(condition_ids):
        issues.append(f"duplicate condition ids: {duplicates}")
    declared = set(candidate.required_fact_codes)
    if duplicates := _duplicates(candidate.required_fact_codes):
        issues.append(f"duplicate requiredFactCodes: {duplicates}")
    catalog_codes = set(facts)
    if unknown := sorted(active_refs - catalog_codes):
        issues.append(f"active rules reference unconfirmed facts: {unknown}")
    if declared != active_refs:
        issues.append(
            "requiredFactCodes must equal the active condition reference closure: "
            f"declared={sorted(declared)}, actual={sorted(active_refs)}"
        )
    if unknown := sorted(parameter_refs - set(parameters)):
        issues.append(f"conditions reference unknown runtime parameters: {unknown}")
    if candidate.default_outcome is not RuleOutcomeV3.WAITING_CONDITIONS:
        issues.append("defaultOutcome must be WAITING_CONDITIONS")
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
    if data_type is FactDataType.DATE:
        if isinstance(value, datetime):
            return True
        if isinstance(value, date) and not isinstance(value, datetime):
            return True
        return isinstance(value, str)
    if data_type is FactDataType.DATETIME:
        return isinstance(value, datetime) or (isinstance(value, str) and "T" in value)
    return True


def _as_decimal(value: EvaluationValue) -> Decimal | _Missing:
    if isinstance(value, bool) or value is None or isinstance(value, _Missing):
        return MISSING
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return MISSING


def to_business_date(value: object) -> date | _Missing:
    if isinstance(value, _Missing) or value is None:
        return MISSING
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=BUSINESS_TZ)
        return moment.astimezone(BUSINESS_TZ).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return MISSING
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return to_business_date(parsed)
        return date.fromisoformat(value)
    except ValueError:
        return MISSING


def _as_temporal(value: EvaluationValue) -> date | datetime | _Missing:
    converted = to_business_date(value)
    return converted


def _null_result(policy: NullPolicy) -> EvaluationResult:
    if policy is NullPolicy.PASS:
        return EvaluationResult.PASS
    if policy is NullPolicy.FAIL:
        return EvaluationResult.FAIL
    return EvaluationResult.INDETERMINATE


def _evaluate_expression(
    expression: ExpressionNodeV31,
    context: EvaluationContextV31,
    facts: dict[str, RequiredFactV2],
    parameters: dict[str, RuntimeParameterV31],
) -> EvaluationValue:
    if expression.kind is ExpressionKindV31.LITERAL:
        return expression.value
    if expression.kind is ExpressionKindV31.PARAMETER:
        name = expression.parameter_name or ""
        if name in context.runtime:
            value: EvaluationValue = context.runtime[name]
            parameter = parameters.get(name)
            if parameter is not None and parameter.data_type in {
                FactDataType.DATE,
                FactDataType.DATETIME,
            }:
                return to_business_date(value)
            return value
        parameter = parameters.get(name)
        if parameter is not None and parameter.bound_value is not None:
            if parameter.data_type in {FactDataType.DATE, FactDataType.DATETIME}:
                return to_business_date(parameter.bound_value)
            return parameter.bound_value
        return MISSING
    if expression.kind is ExpressionKindV31.FACT:
        code = expression.fact_code or ""
        if code in context.facts:
            value = context.facts[code]
            fact = facts.get(code)
            if fact is not None and fact.data_type in {FactDataType.DATE, FactDataType.DATETIME}:
                return to_business_date(value)
            return value
        return MISSING

    values = [
        _evaluate_expression(child, context, facts, parameters) for child in expression.children
    ]
    if expression.kind is ExpressionKindV31.COALESCE:
        return next(
            (item for item in values if not isinstance(item, _Missing) and item is not None),
            MISSING,
        )
    if expression.kind is ExpressionKindV31.DATE_ADD:
        temporal = to_business_date(values[0])
        amount = _as_decimal(values[1])
        if isinstance(temporal, _Missing) or isinstance(amount, _Missing):
            return MISSING
        if expression.unit is DateUnit.DAY:
            return temporal + timedelta(days=int(amount))
        return MISSING
    numbers = [_as_decimal(item) for item in values]
    if any(isinstance(item, _Missing) for item in numbers):
        return MISSING
    decimals = [item for item in numbers if isinstance(item, Decimal)]
    if expression.kind is ExpressionKindV31.ADD:
        return sum(decimals, Decimal(0))
    if expression.kind is ExpressionKindV31.MULTIPLY:
        result = Decimal(1)
        for item in decimals:
            result *= item
        return result
    if expression.kind is ExpressionKindV31.SUBTRACT:
        return decimals[0] - decimals[1]
    if decimals[1] == 0:
        return MISSING
    return decimals[0] / decimals[1]


def _unique_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in values:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def evaluate_condition_v31(
    node: ConditionNodeV31,
    context: EvaluationContextV31,
    facts: dict[str, RequiredFactV2],
    parameters: dict[str, RuntimeParameterV31],
) -> EvaluationResult:
    if not node.enabled:
        return EvaluationResult.PASS
    if node.kind is ConditionKindV31.COMPARE:
        return _evaluate_compare(node, context, facts, parameters)
    if node.kind is ConditionKindV31.ALL_MEMBERS:
        return _evaluate_all_members(node, context, facts, parameters)
    results = [evaluate_condition_v31(child, context, facts, parameters) for child in node.children]
    if node.kind is ConditionKindV31.NOT:
        return {
            EvaluationResult.PASS: EvaluationResult.FAIL,
            EvaluationResult.FAIL: EvaluationResult.PASS,
        }.get(results[0], EvaluationResult.INDETERMINATE)
    if node.kind is ConditionKindV31.ALL:
        if EvaluationResult.FAIL in results:
            return EvaluationResult.FAIL
        if EvaluationResult.INDETERMINATE in results:
            return EvaluationResult.INDETERMINATE
        return EvaluationResult.PASS
    if EvaluationResult.PASS in results:
        return EvaluationResult.PASS
    if EvaluationResult.INDETERMINATE in results:
        return EvaluationResult.INDETERMINATE
    return EvaluationResult.FAIL


def _evaluate_compare(
    node: ConditionNodeV31,
    context: EvaluationContextV31,
    facts: dict[str, RequiredFactV2],
    parameters: dict[str, RuntimeParameterV31],
) -> EvaluationResult:
    assert node.left is not None and node.operator is not None
    left = _evaluate_expression(node.left, context, facts, parameters)
    operator = node.operator
    if operator is RuleOperator.IS_NULL:
        return EvaluationResult.PASS if left is None else EvaluationResult.FAIL
    if operator is RuleOperator.IS_NOT_NULL:
        return EvaluationResult.FAIL if left is None else EvaluationResult.PASS
    if operator is RuleOperator.IS_BLANK:
        return EvaluationResult.PASS if left is None or left == "" else EvaluationResult.FAIL
    if operator is RuleOperator.IS_NOT_BLANK:
        return EvaluationResult.FAIL if left is None or left == "" else EvaluationResult.PASS
    if isinstance(left, _Missing) or left is None or node.right is None:
        return _null_result(node.null_policy)
    right = _evaluate_expression(node.right, context, facts, parameters)
    if isinstance(right, _Missing) or right is None:
        return _null_result(node.null_policy)
    try:
        if operator is RuleOperator.EQ:
            matched = left == right
        elif operator is RuleOperator.NE:
            matched = left != right
        elif operator is RuleOperator.IN:
            matched = isinstance(right, list) and left in right
        elif operator is RuleOperator.NOT_IN:
            matched = isinstance(right, list) and left not in right
        else:
            left_value: Any = left
            right_value: Any = right
            left_decimal = _as_decimal(left)
            right_decimal = _as_decimal(right)
            if not isinstance(left_decimal, _Missing) and not isinstance(right_decimal, _Missing):
                left_value, right_value = left_decimal, right_decimal
            if operator is RuleOperator.GT:
                matched = left_value > right_value
            elif operator is RuleOperator.GTE:
                matched = left_value >= right_value
            elif operator is RuleOperator.LT:
                matched = left_value < right_value
            else:
                matched = left_value <= right_value
    except (TypeError, ValueError):
        return EvaluationResult.INDETERMINATE
    return EvaluationResult.PASS if matched else EvaluationResult.FAIL


def _evaluate_all_members(
    node: ConditionNodeV31,
    context: EvaluationContextV31,
    facts: dict[str, RequiredFactV2],
    parameters: dict[str, RuntimeParameterV31],
) -> EvaluationResult:
    assert node.collection_fact_code is not None
    assert node.empty_collection_policy is not None
    assert node.duplicate_member_policy is DuplicateMemberPolicyV31.UNIQUE_PRESERVE_ORDER
    assert node.missing_member_policy is not None
    assert node.member_predicate is not None
    raw = context.facts.get(node.collection_fact_code, MISSING)
    if isinstance(raw, _Missing) or raw is None:
        return EvaluationResult.INDETERMINATE
    if not isinstance(raw, list):
        return EvaluationResult.INDETERMINATE
    keys = _unique_preserve_order(raw)
    if not keys:
        if node.empty_collection_policy is EmptyCollectionPolicyV31.PASS:
            return EvaluationResult.PASS
        if node.empty_collection_policy is EmptyCollectionPolicyV31.FAIL:
            return EvaluationResult.FAIL
        return EvaluationResult.INDETERMINATE
    saw_indeterminate = False
    for key in keys:
        snapshot = context.members.get(str(key))
        if snapshot is None:
            if node.missing_member_policy is MissingMemberPolicyV31.FAIL:
                return EvaluationResult.FAIL
            saw_indeterminate = True
            continue
        member_context = EvaluationContextV31(
            facts=snapshot,
            runtime=context.runtime,
            members=context.members,
        )
        if node.already_satisfied is not None:
            already = evaluate_condition_v31(
                node.already_satisfied, member_context, facts, parameters
            )
            if already is EvaluationResult.PASS:
                continue
            if already is EvaluationResult.INDETERMINATE:
                saw_indeterminate = True
                continue
        predicate = evaluate_condition_v31(node.member_predicate, member_context, facts, parameters)
        if predicate is EvaluationResult.FAIL:
            return EvaluationResult.FAIL
        if predicate is EvaluationResult.INDETERMINATE:
            saw_indeterminate = True
    if saw_indeterminate:
        return EvaluationResult.INDETERMINATE
    return EvaluationResult.PASS


def _given_issues_v31(
    catalog: BusinessConfirmedFactCatalogV3,
    given: Mapping[str, Any],
) -> list[str]:
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


def evaluate_rule_structure_v31(
    candidate: RuleStructureCandidateV31,
    catalog: BusinessConfirmedFactCatalogV3,
    given: Mapping[str, Any],
    *,
    runtime: Mapping[str, Any] | None = None,
    members: Mapping[str, Mapping[str, Any]] | None = None,
) -> RuleEvaluationV31:
    validate_rule_structure_candidate_v31(candidate, catalog)
    if candidate.blocking_issues:
        return RuleEvaluationV31(RuleOutcomeV3.INDETERMINATE, (), "BUSINESS_CONFIRMATION_REQUIRED")
    input_issues = _given_issues_v31(catalog, given)
    if input_issues:
        raise SemanticValidationErrorV3(input_issues)
    resolved_runtime = dict(runtime or {})
    for parameter in candidate.runtime_parameters:
        if parameter.name not in resolved_runtime and parameter.bound_value is not None:
            resolved_runtime[parameter.name] = parameter.bound_value
    context = EvaluationContextV31(facts=given, runtime=resolved_runtime, members=members or {})
    facts = _catalog_fact_map(catalog)
    parameters = _parameter_map(candidate)
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
            try:
                result = evaluate_condition_v31(rule.when, context, facts, parameters)
            except (ArithmeticError, TypeError, ValueError):
                result = EvaluationResult.INDETERMINATE
            if result is EvaluationResult.PASS:
                outcome = rule.outcome
                reason_code = rule.reason_code
                matched.append(rule.rule_code)
                if stage.stage is not RuleStageNameV3.ELIGIBILITY:
                    return RuleEvaluationV31(outcome, tuple(matched), reason_code)
                break
            if result is EvaluationResult.INDETERMINATE:
                indeterminate = True
        else:
            if indeterminate:
                return RuleEvaluationV31(
                    RuleOutcomeV3.INDETERMINATE,
                    tuple(matched),
                    "FACT_VALUE_MISSING_OR_INVALID",
                )
    return RuleEvaluationV31(outcome, tuple(matched), reason_code)
