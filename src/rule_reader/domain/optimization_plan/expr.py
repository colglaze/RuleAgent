"""Small builders for 3.1.0 expressions and conditions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rule_reader.domain.rules.models import RuleOperator


def fact(code: str) -> dict[str, Any]:
    return {"kind": "fact", "factCode": code}


def lit(value: str | int | float | bool | Sequence[str | int | float | bool]) -> dict[str, Any]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return {"kind": "literal", "value": list(value)}
    return {"kind": "literal", "value": value}


def param(name: str) -> dict[str, Any]:
    return {"kind": "parameter", "parameterName": name}


def add(*children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "add", "children": list(children)}


def sub(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "subtract", "children": [left, right]}


def mul(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "multiply", "children": [left, right]}


def coalesce(*children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "coalesce", "children": list(children)}


def date_add(base: dict[str, Any], days: int) -> dict[str, Any]:
    return {
        "kind": "dateAdd",
        "unit": "day",
        "children": [base, lit(days)],
    }


def compare(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    operator: RuleOperator,
    right: dict[str, Any] | None = None,
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": condition_id,
        "kind": "compare",
        "description": description,
        "left": left,
        "operator": operator.value,
        "nullPolicy": null_policy,
    }
    if right is not None:
        payload["right"] = right
    return payload


def all_of(condition_id: str, description: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "all",
        "description": description,
        "children": list(children),
    }


def any_of(condition_id: str, description: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "any",
        "description": description,
        "children": list(children),
    }


def not_of(condition_id: str, description: str, child: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "not",
        "description": description,
        "children": [child],
    }


def eq(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    value: str | int | float | bool,
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id, description, left, RuleOperator.EQ, lit(value), null_policy=null_policy
    )


def ne(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    value: str | int | float | bool,
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id, description, left, RuleOperator.NE, lit(value), null_policy=null_policy
    )


def gt(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    value: str | int | float,
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id, description, left, RuleOperator.GT, lit(value), null_policy=null_policy
    )


def gte(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id, description, left, RuleOperator.GTE, right, null_policy=null_policy
    )


def lt(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    value: str | int | float,
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id, description, left, RuleOperator.LT, lit(value), null_policy=null_policy
    )


def is_null(condition_id: str, description: str, left: dict[str, Any]) -> dict[str, Any]:
    return compare(condition_id, description, left, RuleOperator.IS_NULL, null_policy="pass")


def in_list(
    condition_id: str,
    description: str,
    left: dict[str, Any],
    values: Sequence[str | int | float | bool],
    *,
    null_policy: str = "fail",
) -> dict[str, Any]:
    return compare(
        condition_id,
        description,
        left,
        RuleOperator.IN,
        lit(values),
        null_policy=null_policy,
    )


def expression_fact_codes(expression: dict[str, Any] | None) -> set[str]:
    if not expression:
        return set()
    codes = {expression["factCode"]} if expression.get("factCode") else set()
    for child in expression.get("children") or []:
        codes |= expression_fact_codes(child)
    return codes


def condition_fact_codes(node: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    if node.get("collectionFactCode"):
        codes.add(str(node["collectionFactCode"]))
    codes |= expression_fact_codes(node.get("left"))
    codes |= expression_fact_codes(node.get("right"))
    for child in node.get("children") or []:
        codes |= condition_fact_codes(child)
    if node.get("alreadySatisfied"):
        codes |= condition_fact_codes(node["alreadySatisfied"])
    if node.get("memberPredicate"):
        codes |= condition_fact_codes(node["memberPredicate"])
    return codes


def required_fact_codes_from_stages(stages: list[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()
    for stage in stages:
        for rule in stage.get("rules") or []:
            when = rule.get("when")
            if when:
                codes |= condition_fact_codes(when)
    return sorted(codes)
