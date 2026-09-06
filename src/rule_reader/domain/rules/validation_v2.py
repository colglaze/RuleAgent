"""Deterministic validation and evaluation for Schema 2.0 rules."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, cast

from rule_reader.domain.rules.catalog import resolve_catalog_field
from rule_reader.domain.rules.models import FactDataType, MappingStatus, RuleOperator
from rule_reader.domain.rules.v2 import (
    ConditionKindV2,
    ConditionNodeV2,
    DateUnit,
    ExpressionKind,
    ExpressionNodeV2,
    FactKind,
    FieldMappingV2,
    NullPolicy,
    ParsedRuleV2,
    RequiredFactV2,
    RuleCandidateV2,
    TestExpectationV2,
)


class SemanticValidationErrorV2(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)


class EvaluationResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class _Missing:
    pass


MISSING = _Missing()
EvaluationValue = str | int | float | bool | Decimal | date | datetime | list[Any] | None | _Missing

_EXECUTABLE_SQL_PATTERN = re.compile(
    r"(?i)(?:^|[;\s])(?:select|insert|update|delete|drop|alter|create|merge|exec|execute)\s+"
)
_CONNECTION_OR_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|sqlserver)://|"
    r"\b(?:password|passwd|pwd|user\s*id|uid|account)\s*[:=]"
)


def _duplicates(values: list[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def _sensitive_text_issues(value: object, path: str = "$") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            issues.extend(_sensitive_text_issues(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(_sensitive_text_issues(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if _EXECUTABLE_SQL_PATTERN.search(value):
            issues.append(f"{path} contains executable SQL text")
        if _CONNECTION_OR_CREDENTIAL_PATTERN.search(value):
            issues.append(f"{path} contains a database connection or credential pattern")
    return issues


def validate_safe_structured_payload(value: object) -> None:
    """Reject executable query text and connection or credential material."""

    if issues := _sensitive_text_issues(value):
        raise SemanticValidationErrorV2(issues)


def _walk_conditions(node: ConditionNodeV2) -> list[ConditionNodeV2]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk_conditions(child))
    return nodes


def _walk_expressions(node: ExpressionNodeV2) -> list[ExpressionNodeV2]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk_expressions(child))
    return nodes


def expression_fact_refs(node: ExpressionNodeV2) -> set[str]:
    return {
        item.fact_code
        for item in _walk_expressions(node)
        if item.kind is ExpressionKind.FACT and item.fact_code is not None
    }


def condition_fact_refs(node: ConditionNodeV2) -> set[str]:
    references: set[str] = set()
    for condition in _walk_conditions(node):
        if condition.left is not None:
            references.update(expression_fact_refs(condition.left))
        if condition.right is not None:
            references.update(expression_fact_refs(condition.right))
    return references


def _fact_reference_closure(
    direct_references: set[str],
    facts: dict[str, RequiredFactV2],
    issues: list[str],
) -> set[str]:
    closure: set[str] = set()
    visiting: set[str] = set()

    def visit(code: str) -> None:
        if code in visiting:
            issues.append(f"derived fact cycle detected at {code}")
            return
        if code in closure:
            return
        fact = facts.get(code)
        if fact is None:
            issues.append(f"unknown fact reference: {code}")
            return
        closure.add(code)
        if fact.fact_kind is not FactKind.DERIVED or fact.derivation is None:
            return
        visiting.add(code)
        for dependency in expression_fact_refs(fact.derivation):
            visit(dependency)
        visiting.remove(code)

    for reference in direct_references:
        visit(reference)
    return closure


NUMERIC_TYPES = {
    FactDataType.INTEGER,
    FactDataType.NUMBER,
    FactDataType.MONEY,
}


def _literal_type(value: Any) -> FactDataType:
    if isinstance(value, bool):
        return FactDataType.BOOLEAN
    if isinstance(value, int):
        return FactDataType.INTEGER
    if isinstance(value, float):
        return FactDataType.NUMBER
    if isinstance(value, list):
        return FactDataType.LIST
    return FactDataType.STRING


def _compatible(left: FactDataType, right: FactDataType) -> bool:
    return (
        left == right
        or (left in NUMERIC_TYPES and right in NUMERIC_TYPES)
        or (left is FactDataType.ENUM and right is FactDataType.STRING)
    )


def _matches_fact_data_type(value: Any, data_type: FactDataType) -> bool:
    if data_type is FactDataType.UNKNOWN:
        return True
    if data_type is FactDataType.BOOLEAN:
        return isinstance(value, bool)
    if data_type is FactDataType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type in {FactDataType.NUMBER, FactDataType.MONEY}:
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if data_type is FactDataType.STRING:
        return isinstance(value, str)
    if data_type is FactDataType.LIST:
        return isinstance(value, list)
    if data_type is FactDataType.ENUM:
        return isinstance(value, (str, int, float, bool))
    if not isinstance(value, str):
        return False
    try:
        if data_type is FactDataType.DATE:
            if "T" in value:
                return False
            date.fromisoformat(value)
            return True
        if data_type is FactDataType.DATETIME:
            if "T" not in value:
                return False
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
    except ValueError:
        return False
    return False


def _validate_test_value(
    *,
    test_id: str,
    fact: RequiredFactV2,
    value: Any,
    issues: list[str],
) -> None:
    path = f"test case {test_id} given[{fact.fact_code}]"
    if value is None:
        if not fact.nullable:
            issues.append(f"{path} is null but the fact is not nullable")
        return
    if not _matches_fact_data_type(value, fact.data_type):
        issues.append(f"{path} does not match dataType {fact.data_type.value}")
        return
    if fact.allowed_values and value not in fact.allowed_values:
        issues.append(f"{path} is not in allowedValues")


def infer_expression_type(
    expression: ExpressionNodeV2,
    facts: dict[str, RequiredFactV2],
    issues: list[str],
) -> FactDataType:
    if expression.kind is ExpressionKind.FACT:
        fact = facts.get(expression.fact_code or "")
        if fact is None:
            return FactDataType.UNKNOWN
        return fact.data_type
    if expression.kind is ExpressionKind.LITERAL:
        return _literal_type(expression.value)

    child_types = [infer_expression_type(child, facts, issues) for child in expression.children]
    if expression.kind in {
        ExpressionKind.ADD,
        ExpressionKind.SUBTRACT,
        ExpressionKind.MULTIPLY,
        ExpressionKind.DIVIDE,
    }:
        if any(item not in NUMERIC_TYPES for item in child_types):
            issues.append(f"{expression.kind.value} expression requires numeric children")
            return FactDataType.UNKNOWN
        return FactDataType.MONEY if FactDataType.MONEY in child_types else FactDataType.NUMBER
    if expression.kind is ExpressionKind.COALESCE:
        first = child_types[0]
        if any(not _compatible(first, item) for item in child_types[1:]):
            issues.append("coalesce expression children have incompatible types")
            return FactDataType.UNKNOWN
        return first
    if expression.kind is ExpressionKind.DATE_ADD:
        if child_types[0] not in {FactDataType.DATE, FactDataType.DATETIME}:
            issues.append("dateAdd first child must be date or datetime")
        if child_types[0] is FactDataType.DATE and expression.unit is not DateUnit.DAY:
            issues.append("dateAdd on a date only supports day units")
        if child_types[1] is not FactDataType.INTEGER:
            issues.append("dateAdd second child must be integer")
        return child_types[0]
    return FactDataType.UNKNOWN


def _validate_condition_types(
    node: ConditionNodeV2,
    facts: dict[str, RequiredFactV2],
    issues: list[str],
) -> None:
    for child in node.children:
        _validate_condition_types(child, facts, issues)
    if node.kind is not ConditionKindV2.COMPARE or node.left is None or node.operator is None:
        return
    left_type = infer_expression_type(node.left, facts, issues)
    if node.right is None:
        return
    right_type = infer_expression_type(node.right, facts, issues)
    if node.operator in {RuleOperator.IN, RuleOperator.NOT_IN}:
        if right_type is not FactDataType.LIST:
            issues.append(f"condition {node.id} requires a list right expression")
        return
    if node.operator in {RuleOperator.GT, RuleOperator.GTE, RuleOperator.LT, RuleOperator.LTE}:
        comparable = NUMERIC_TYPES | {FactDataType.DATE, FactDataType.DATETIME}
        if left_type not in comparable or right_type not in comparable:
            issues.append(f"condition {node.id} uses non-orderable comparison types")
        elif not _compatible(left_type, right_type):
            issues.append(f"condition {node.id} compares incompatible types")
        return
    if node.operator in {RuleOperator.EQ, RuleOperator.NE} and not _compatible(
        left_type, right_type
    ):
        issues.append(f"condition {node.id} compares incompatible types")


def _as_decimal(value: EvaluationValue) -> Decimal | _Missing:
    if isinstance(value, bool) or value is None or isinstance(value, _Missing):
        return MISSING
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return MISSING


def _as_temporal(value: EvaluationValue) -> date | datetime | _Missing:
    if isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str):
        return MISSING
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value)
    except ValueError:
        return MISSING


def _evaluate_expression(
    expression: ExpressionNodeV2,
    given: dict[str, Any],
    facts: dict[str, RequiredFactV2],
    resolving: set[str],
) -> EvaluationValue:
    if expression.kind is ExpressionKind.LITERAL:
        return expression.value
    if expression.kind is ExpressionKind.FACT:
        code = expression.fact_code or ""
        if code in given:
            value = cast(EvaluationValue, given[code])
            fact = facts.get(code)
            if fact is not None and fact.data_type in {
                FactDataType.DATE,
                FactDataType.DATETIME,
            }:
                return _as_temporal(value)
            return value
        fact = facts.get(code)
        if fact is None or fact.derivation is None or code in resolving:
            return MISSING
        resolving.add(code)
        try:
            return _evaluate_expression(fact.derivation, given, facts, resolving)
        finally:
            resolving.remove(code)

    values = [_evaluate_expression(child, given, facts, resolving) for child in expression.children]
    if expression.kind is ExpressionKind.COALESCE:
        return next(
            (item for item in values if not isinstance(item, _Missing) and item is not None),
            MISSING,
        )
    if expression.kind is ExpressionKind.DATE_ADD:
        temporal = _as_temporal(values[0])
        amount = _as_decimal(values[1])
        if isinstance(temporal, _Missing) or isinstance(amount, _Missing):
            return MISSING
        seconds = int(amount)
        if expression.unit is DateUnit.DAY:
            return temporal + timedelta(days=seconds)
        if expression.unit is DateUnit.HOUR:
            return temporal + timedelta(hours=seconds)
        return temporal + timedelta(minutes=seconds)

    numbers = [_as_decimal(item) for item in values]
    if any(isinstance(item, _Missing) for item in numbers):
        return MISSING
    decimals = [item for item in numbers if isinstance(item, Decimal)]
    if expression.kind is ExpressionKind.ADD:
        return sum(decimals, Decimal(0))
    if expression.kind is ExpressionKind.MULTIPLY:
        result = Decimal(1)
        for item in decimals:
            result *= item
        return result
    if expression.kind is ExpressionKind.SUBTRACT:
        return decimals[0] - decimals[1]
    if decimals[1] == 0:
        return MISSING
    return decimals[0] / decimals[1]


def _null_result(policy: NullPolicy) -> EvaluationResult:
    if policy is NullPolicy.PASS:
        return EvaluationResult.PASS
    if policy is NullPolicy.FAIL:
        return EvaluationResult.FAIL
    return EvaluationResult.INDETERMINATE


def _evaluate_compare(
    node: ConditionNodeV2,
    given: dict[str, Any],
    facts: dict[str, RequiredFactV2],
) -> EvaluationResult:
    assert node.left is not None
    assert node.operator is not None
    left = _evaluate_expression(node.left, given, facts, set())
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
    right = _evaluate_expression(node.right, given, facts, set())
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
        elif operator is RuleOperator.CONTAINS:
            matched = right in left  # type: ignore[operator]
        elif operator is RuleOperator.NOT_CONTAINS:
            matched = right not in left  # type: ignore[operator]
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


def evaluate_condition(
    node: ConditionNodeV2,
    given: dict[str, Any],
    facts: dict[str, RequiredFactV2],
) -> EvaluationResult:
    if not node.enabled:
        return EvaluationResult.PASS
    if node.kind is ConditionKindV2.COMPARE:
        return _evaluate_compare(node, given, facts)
    results = [evaluate_condition(child, given, facts) for child in node.children]
    if node.kind is ConditionKindV2.NOT:
        return {
            EvaluationResult.PASS: EvaluationResult.FAIL,
            EvaluationResult.FAIL: EvaluationResult.PASS,
        }.get(results[0], EvaluationResult.INDETERMINATE)
    if node.kind is ConditionKindV2.ALL:
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


def validate_candidate_v2(candidate: RuleCandidateV2) -> None:
    issues: list[str] = []
    issues.extend(_sensitive_text_issues(candidate.model_dump(mode="json")))
    fact_codes = [fact.fact_code for fact in candidate.required_facts]
    facts = {fact.fact_code: fact for fact in candidate.required_facts}
    duplicate_facts = _duplicates(fact_codes)
    if duplicate_facts:
        issues.append(f"duplicate requiredFacts codes: {sorted(duplicate_facts)}")

    conditions = _walk_conditions(candidate.root_condition)
    duplicate_conditions = _duplicates([node.id for node in conditions])
    if duplicate_conditions:
        issues.append(f"duplicate condition ids: {sorted(duplicate_conditions)}")

    direct_refs = condition_fact_refs(candidate.root_condition)
    closure = _fact_reference_closure(direct_refs, facts, issues)
    unused = sorted(set(fact_codes) - closure)
    if unused:
        issues.append(f"requiredFacts not used by condition/derivation closure: {unused}")
    missing = sorted(closure - set(fact_codes))
    if missing:
        issues.append(f"missing requiredFacts: {missing}")

    for fact in candidate.required_facts:
        if fact.derivation is not None:
            derived_type = infer_expression_type(fact.derivation, facts, issues)
            if not _compatible(fact.data_type, derived_type):
                issues.append(
                    f"derived fact {fact.fact_code} declares {fact.data_type.value} "
                    f"but expression returns {derived_type.value}"
                )
    _validate_condition_types(candidate.root_condition, facts, issues)

    test_ids = [test.id for test in candidate.test_cases]
    duplicate_tests = _duplicates(test_ids)
    if duplicate_tests:
        issues.append(f"duplicate test case ids: {sorted(duplicate_tests)}")
    expectations = {test.expected for test in candidate.test_cases}
    if TestExpectationV2.PASS not in expectations or TestExpectationV2.FAIL not in expectations:
        issues.append("testCases must contain at least one pass and one fail case")
    for test in candidate.test_cases:
        unknown = sorted(set(test.given) - set(fact_codes))
        if unknown:
            issues.append(f"test case {test.id} uses unknown facts: {unknown}")
            continue
        issue_count = len(issues)
        for code, value in test.given.items():
            _validate_test_value(
                test_id=test.id,
                fact=facts[code],
                value=value,
                issues=issues,
            )
        if len(issues) != issue_count:
            continue
        actual = evaluate_condition(candidate.root_condition, test.given, facts)
        if actual.value != test.expected.value:
            pointers: list[str] = []
            if actual is EvaluationResult.INDETERMINATE:
                closure = _fact_reference_closure(
                    condition_fact_refs(candidate.root_condition), facts, []
                )
                missing = sorted(
                    code
                    for code in closure
                    if code not in test.given and facts[code].derivation is None
                )
                unresolved = sorted(
                    code
                    for code, value in test.given.items()
                    if value is None and facts[code].null_policy is NullPolicy.INDETERMINATE
                )
                if missing:
                    pointers.append(f"missing given values: {missing}")
                if unresolved:
                    pointers.append(
                        f"null given values under indeterminate nullPolicy: {unresolved}"
                    )
            detail = ("; " + "; ".join(pointers)) if pointers else ""
            issues.append(
                f"test case {test.id} expected {test.expected.value} "
                f"but evaluated {actual.value}{detail}"
            )

    mapping_codes = [mapping.fact_code for mapping in candidate.field_mappings]
    duplicate_mappings = _duplicates(mapping_codes)
    if duplicate_mappings:
        issues.append(f"duplicate field mappings: {sorted(duplicate_mappings)}")
    if missing_mappings := sorted(set(fact_codes) - set(mapping_codes)):
        issues.append(f"facts without field mappings: {missing_mappings}")
    if extra_mappings := sorted(set(mapping_codes) - set(fact_codes)):
        issues.append(f"field mappings for unknown facts: {extra_mappings}")
    for mapping in candidate.field_mappings:
        if mapping.mapping_status is not MappingStatus.MAPPED:
            continue
        assert mapping.view_name is not None
        assert mapping.view_field is not None
        if resolve_catalog_field(mapping.view_name, mapping.view_field) is None:
            issues.append(
                f"mapping {mapping.fact_code} references unknown catalogue field "
                f"{mapping.view_name}.{mapping.view_field}"
            )
    if duplicate_views := _duplicates(candidate.source_views):
        issues.append(f"duplicate sourceViews: {sorted(duplicate_views)}")
    if issues:
        raise SemanticValidationErrorV2(issues)


def enrich_candidate_v2(candidate: RuleCandidateV2) -> ParsedRuleV2:
    mappings: list[FieldMappingV2] = []
    for candidate_mapping in candidate.field_mappings:
        if candidate_mapping.mapping_status is MappingStatus.UNRESOLVED:
            mappings.append(
                FieldMappingV2(
                    fact_code=candidate_mapping.fact_code,
                    mapping_status=MappingStatus.UNRESOLVED,
                    note=candidate_mapping.note,
                )
            )
            continue
        assert candidate_mapping.view_name is not None
        assert candidate_mapping.view_field is not None
        resolved = resolve_catalog_field(
            candidate_mapping.view_name,
            candidate_mapping.view_field,
        )
        if resolved is None:
            raise SemanticValidationErrorV2(
                [
                    "field mapping was not validated before enrichment: "
                    f"{candidate_mapping.view_name}.{candidate_mapping.view_field}"
                ]
            )
        view, _ = resolved
        mappings.append(
            FieldMappingV2(
                fact_code=candidate_mapping.fact_code,
                mapping_status=MappingStatus.MAPPED,
                view_name=candidate_mapping.view_name,
                view_field=candidate_mapping.view_field,
                view_active=view.active,
                note=candidate_mapping.note,
            )
        )
    body = candidate.model_dump(exclude={"field_mappings"})
    return ParsedRuleV2.model_validate({**body, "field_mappings": mappings})
