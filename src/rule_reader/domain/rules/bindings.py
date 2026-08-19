"""Deterministic fact-level handoff from RuleReader to Agent 2."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field

from rule_reader.domain.rules.models import MappingStatus, RuleOperator
from rule_reader.domain.rules.v2 import (
    ConditionKindV2,
    ConditionNodeV2,
    ContractModelV2,
    FactKind,
    RequiredFactV2,
    RuleParseResultV2,
)
from rule_reader.domain.rules.validation_v2 import expression_fact_refs


class BindingRuleRef(ContractModelV2):
    rule_id: str
    rule_version: str
    schema_version: Literal["2.0.0"] = "2.0.0"
    source_sha256: str


class FactUsage(ContractModelV2):
    condition_id: str
    condition_path: str
    operator: RuleOperator
    expression_side: Literal["left", "right", "leftDerivation", "rightDerivation"]


class FactExample(ContractModelV2):
    test_case_id: str
    value: str | int | float | bool | list[str | int | float | bool] | None
    expected_rule_result: Literal["pass", "fail"]


class BindingMappingCandidate(ContractModelV2):
    fact_code: str
    mapping_status: MappingStatus
    view_name: str | None = None
    view_field: str | None = None
    view_active: bool | None = None
    review_status: Literal["candidate"] = "candidate"
    note: str


class FactBindingRequest(ContractModelV2):
    contract_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["candidate"] = "candidate"
    rule_ref: BindingRuleRef
    fact: RequiredFactV2
    usages: list[FactUsage] = Field(min_length=1)
    mapping_candidate: BindingMappingCandidate
    examples: list[FactExample] = Field(default_factory=list)
    target_dialect: Literal["sqlserver"] = "sqlserver"
    requires_metadata_snapshot: Literal[True] = True
    temp_table_allowed: Literal[False] = False


def _atomic_fact_codes(
    code: str,
    facts: dict[str, RequiredFactV2],
    visiting: set[str] | None = None,
) -> set[str]:
    fact = facts[code]
    if fact.fact_kind is not FactKind.DERIVED or fact.derivation is None:
        return {code}
    active = set() if visiting is None else visiting
    if code in active:
        return set()
    active.add(code)
    result: set[str] = set()
    for dependency in expression_fact_refs(fact.derivation):
        result.update(_atomic_fact_codes(dependency, facts, active))
    active.remove(code)
    return result


def _collect_usages(
    node: ConditionNodeV2,
    facts: dict[str, RequiredFactV2],
    path: tuple[str, ...],
    target: dict[str, list[FactUsage]],
) -> None:
    current_path = (*path, node.id)
    if node.kind is ConditionKindV2.COMPARE:
        assert node.operator is not None
        for side, expression in (("left", node.left), ("right", node.right)):
            if expression is None:
                continue
            for reference in expression_fact_refs(expression):
                fact = facts[reference]
                atomic_codes = _atomic_fact_codes(reference, facts)
                derived = fact.fact_kind is FactKind.DERIVED
                usage_side = cast(
                    Literal["left", "right", "leftDerivation", "rightDerivation"],
                    f"{side}Derivation" if derived else side,
                )
                for atomic_code in atomic_codes:
                    target.setdefault(atomic_code, []).append(
                        FactUsage(
                            condition_id=node.id,
                            condition_path="/".join(current_path),
                            operator=node.operator,
                            expression_side=usage_side,
                        )
                    )
    for child in node.children:
        _collect_usages(child, facts, current_path, target)


def build_fact_binding_requests(result: RuleParseResultV2) -> list[FactBindingRequest]:
    facts = {fact.fact_code: fact for fact in result.rule.required_facts}
    mappings = {mapping.fact_code: mapping for mapping in result.rule.field_mappings}
    usages: dict[str, list[FactUsage]] = {}
    _collect_usages(result.rule.root_condition, facts, (), usages)
    rule_ref = BindingRuleRef(
        rule_id=result.rule.rule_id,
        rule_version=result.rule_version,
        source_sha256=result.source.sha256,
    )
    requests: list[FactBindingRequest] = []
    for fact in result.rule.required_facts:
        if fact.fact_kind is FactKind.DERIVED:
            continue
        unique_usages = list(
            {
                (
                    usage.condition_id,
                    usage.condition_path,
                    usage.operator,
                    usage.expression_side,
                ): usage
                for usage in usages.get(fact.fact_code, [])
            }.values()
        )
        examples = [
            FactExample(
                test_case_id=test.id,
                value=test.given[fact.fact_code],
                expected_rule_result=test.expected.value,
            )
            for test in result.rule.test_cases
            if fact.fact_code in test.given
        ]
        requests.append(
            FactBindingRequest(
                rule_ref=rule_ref,
                fact=fact,
                usages=unique_usages,
                mapping_candidate=BindingMappingCandidate.model_validate(
                    mappings[fact.fact_code].model_dump(exclude={"source_expression"})
                ),
                examples=examples,
            )
        )
    return requests
