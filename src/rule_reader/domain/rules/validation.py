"""Deterministic semantic validation and field mapping enrichment."""

from __future__ import annotations

from collections import Counter

from rule_reader.domain.rules.catalog import resolve_catalog_field
from rule_reader.domain.rules.models import (
    ConditionKind,
    ConditionNode,
    FieldMapping,
    MappingStatus,
    ParsedRule,
    RuleCandidate,
    TestExpectation,
)


class SemanticValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)


def _duplicates(values: list[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def _walk_conditions(node: ConditionNode) -> list[ConditionNode]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk_conditions(child))
    return nodes


def validate_candidate(candidate: RuleCandidate) -> None:
    issues: list[str] = []
    fact_keys = [fact.key for fact in candidate.required_facts]
    fact_key_set = set(fact_keys)

    duplicate_facts = _duplicates(fact_keys)
    if duplicate_facts:
        issues.append(f"duplicate requiredFacts keys: {sorted(duplicate_facts)}")

    condition_nodes = _walk_conditions(candidate.root_condition)
    condition_ids = [node.id for node in condition_nodes]
    duplicate_conditions = _duplicates(condition_ids)
    if duplicate_conditions:
        issues.append(f"duplicate condition ids: {sorted(duplicate_conditions)}")

    for node in condition_nodes:
        references: list[str] = []
        if node.kind is ConditionKind.PREDICATE and node.fact_key is not None:
            references.append(node.fact_key)
        references.extend(node.fact_refs)
        unknown = sorted(set(references) - fact_key_set)
        if unknown:
            issues.append(f"condition {node.id} references unknown facts: {unknown}")

    test_ids = [test.id for test in candidate.test_cases]
    duplicate_tests = _duplicates(test_ids)
    if duplicate_tests:
        issues.append(f"duplicate test case ids: {sorted(duplicate_tests)}")

    expectations = {test.expected for test in candidate.test_cases}
    if TestExpectation.PASS not in expectations or TestExpectation.FAIL not in expectations:
        issues.append("testCases must contain at least one pass and one fail case")

    for test in candidate.test_cases:
        unknown = sorted(set(test.given) - fact_key_set)
        if unknown:
            issues.append(f"test case {test.id} uses unknown facts: {unknown}")

    mapping_keys = [mapping.fact_key for mapping in candidate.field_mappings]
    duplicate_mappings = _duplicates(mapping_keys)
    if duplicate_mappings:
        issues.append(f"duplicate field mappings: {sorted(duplicate_mappings)}")

    missing_mappings = sorted(fact_key_set - set(mapping_keys))
    extra_mappings = sorted(set(mapping_keys) - fact_key_set)
    if missing_mappings:
        issues.append(f"facts without field mappings: {missing_mappings}")
    if extra_mappings:
        issues.append(f"field mappings for unknown facts: {extra_mappings}")

    for mapping in candidate.field_mappings:
        if mapping.mapping_status is not MappingStatus.MAPPED:
            continue
        assert mapping.view_name is not None
        assert mapping.view_field is not None
        if resolve_catalog_field(mapping.view_name, mapping.view_field) is None:
            issues.append(
                f"mapping {mapping.fact_key} references unknown catalogue field "
                f"{mapping.view_name}.{mapping.view_field}"
            )

    duplicate_views = _duplicates(candidate.source_views)
    if duplicate_views:
        issues.append(f"duplicate sourceViews: {sorted(duplicate_views)}")

    if issues:
        raise SemanticValidationError(issues)


def enrich_candidate(candidate: RuleCandidate) -> ParsedRule:
    mappings: list[FieldMapping] = []
    for candidate_mapping in candidate.field_mappings:
        if candidate_mapping.mapping_status is MappingStatus.UNRESOLVED:
            mappings.append(
                FieldMapping(
                    fact_key=candidate_mapping.fact_key,
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
            raise SemanticValidationError(
                [
                    "field mapping was not validated before enrichment: "
                    f"{candidate_mapping.view_name}.{candidate_mapping.view_field}"
                ]
            )
        view, field = resolved
        mappings.append(
            FieldMapping(
                fact_key=candidate_mapping.fact_key,
                mapping_status=MappingStatus.MAPPED,
                view_name=candidate_mapping.view_name,
                view_field=candidate_mapping.view_field,
                source_expression=field.expression,
                view_active=view.active,
                note=candidate_mapping.note,
            )
        )

    body = candidate.model_dump(exclude={"field_mappings"})
    return ParsedRule.model_validate({**body, "field_mappings": mappings})
