from __future__ import annotations

from copy import deepcopy

import pytest
from tests.support import valid_candidate_v2

from rule_reader.domain.rules.bindings import build_fact_binding_requests
from rule_reader.domain.rules.models import ParserMetadata, SourceMetadata
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import (
    SemanticValidationErrorV2,
    enrich_candidate_v2,
    validate_candidate_v2,
)


def test_v2_candidate_preserves_formula_and_executes_examples() -> None:
    candidate = RuleCandidateV2.model_validate(valid_candidate_v2())

    validate_candidate_v2(candidate)
    parsed = enrich_candidate_v2(candidate)

    formula = parsed.root_condition.children[1]
    assert formula.left is not None
    assert formula.left.kind.value == "add"
    assert formula.right is not None
    assert formula.right.fact_code == "task.required_fee"


def test_v2_rejects_unused_formula_dependencies() -> None:
    payload = valid_candidate_v2()
    payload["rootCondition"]["children"][1]["right"] = {
        "kind": "literal",
        "value": 0,
    }
    candidate = RuleCandidateV2.model_validate(payload)

    with pytest.raises(SemanticValidationErrorV2, match="not used"):
        validate_candidate_v2(candidate)


def test_v2_rejects_test_case_that_disagrees_with_tree() -> None:
    payload = valid_candidate_v2()
    payload["testCases"][0]["expected"] = "fail"
    candidate = RuleCandidateV2.model_validate(payload)

    with pytest.raises(SemanticValidationErrorV2, match="expected fail but evaluated pass"):
        validate_candidate_v2(candidate)


def test_v2_rejects_derived_fact_cycle() -> None:
    payload = valid_candidate_v2()
    required = next(
        fact for fact in payload["requiredFacts"] if fact["factCode"] == "task.required_fee"
    )
    required["derivation"] = {"kind": "fact", "factCode": "task.required_fee"}
    candidate = RuleCandidateV2.model_validate(payload)

    with pytest.raises(SemanticValidationErrorV2, match="cycle"):
        validate_candidate_v2(candidate)


def test_v2_rejects_mutually_exclusive_branch_through_expected_case() -> None:
    payload = valid_candidate_v2()
    payload["rootCondition"] = {
        "id": "product-759",
        "kind": "all",
        "description": "错误地同时要求两个互斥区间",
        "children": [
            {
                "id": "lower",
                "kind": "compare",
                "description": "费用不超过十万",
                "left": {"kind": "fact", "factCode": "task.settlement_fee"},
                "operator": "lte",
                "right": {"kind": "literal", "value": 100000},
                "nullPolicy": "fail",
            },
            {
                "id": "upper",
                "kind": "compare",
                "description": "费用超过十万",
                "left": {"kind": "fact", "factCode": "task.settlement_fee"},
                "operator": "gt",
                "right": {"kind": "literal", "value": 100000},
                "nullPolicy": "fail",
            },
        ],
    }
    payload["requiredFacts"] = [
        fact
        for fact in payload["requiredFacts"]
        if fact["factCode"] == "task.settlement_fee"
    ]
    payload["fieldMappings"] = [
        mapping
        for mapping in payload["fieldMappings"]
        if mapping["factCode"] == "task.settlement_fee"
    ]
    payload["testCases"] = [
        {
            "id": "boundary-pass",
            "description": "来源规则要求十万元边界通过",
            "given": {"task.settlement_fee": 100000},
            "expected": "pass",
            "rationale": "互斥分支错误必须被案例发现",
        },
        {
            "id": "fail-case",
            "description": "保留反例",
            "given": {"task.settlement_fee": 100001},
            "expected": "fail",
            "rationale": "错误树不能通过",
        },
    ]
    candidate = RuleCandidateV2.model_validate(payload)

    with pytest.raises(SemanticValidationErrorV2, match="boundary-pass"):
        validate_candidate_v2(candidate)


def test_v2_models_exists_fact_and_executes_flow_cases() -> None:
    payload = valid_candidate_v2()
    payload["rootCondition"] = {
        "id": "no-unfinished-flow",
        "kind": "compare",
        "description": "不存在未结束流程",
        "left": {"kind": "fact", "factCode": "task.has_unfinished_flow"},
        "operator": "eq",
        "right": {"kind": "literal", "value": False},
        "nullPolicy": "error",
    }
    payload["requiredFacts"] = [
        {
            "factCode": "task.has_unfinished_flow",
            "name": "是否存在未结束流程",
            "factKind": "exists",
            "dataType": "boolean",
            "description": "按任务查询是否存在未结束流程记录",
            "nullable": False,
            "nullPolicy": "error",
            "grain": "formal_test_task",
            "parameters": [
                {
                    "name": "taskId",
                    "dataType": "integer",
                    "description": "正式实验任务 ID",
                    "required": True,
                }
            ],
        }
    ]
    payload["fieldMappings"] = [
        {
            "factCode": "task.has_unfinished_flow",
            "mappingStatus": "unresolved",
            "note": "需要 Agent 2 绑定存在性查询。",
        }
    ]
    payload["testCases"] = [
        {
            "id": "no-flow-pass",
            "description": "没有未结束流程",
            "given": {"task.has_unfinished_flow": False},
            "expected": "pass",
            "rationale": "不存在阻塞流程时通过。",
        },
        {
            "id": "flow-fail",
            "description": "存在未结束流程",
            "given": {"task.has_unfinished_flow": True},
            "expected": "fail",
            "rationale": "存在阻塞流程时不通过。",
        },
    ]

    candidate = RuleCandidateV2.model_validate(payload)

    validate_candidate_v2(candidate)
    assert candidate.required_facts[0].fact_kind.value == "exists"


def test_v2_executes_date_add_boundary_with_iso_datetimes() -> None:
    payload = valid_candidate_v2()
    payload["rootCondition"] = {
        "id": "release-time-reached",
        "kind": "compare",
        "description": "当前时间达到定时释放时间",
        "left": {"kind": "fact", "factCode": "task.current_time"},
        "operator": "gte",
        "right": {"kind": "fact", "factCode": "task.release_due_at"},
        "nullPolicy": "error",
    }
    parameter = {
        "name": "taskId",
        "dataType": "integer",
        "description": "正式实验任务 ID",
        "required": True,
    }
    payload["requiredFacts"] = [
        {
            "factCode": "task.current_time",
            "name": "当前时间",
            "factKind": "source",
            "dataType": "datetime",
            "description": "规则求值时的当前时间",
            "nullable": False,
            "nullPolicy": "error",
            "grain": "formal_test_task",
            "parameters": [parameter],
        },
        {
            "factCode": "task.completed_at",
            "name": "任务完成时间",
            "factKind": "source",
            "dataType": "datetime",
            "description": "任务完成时间",
            "nullable": False,
            "nullPolicy": "error",
            "grain": "formal_test_task",
            "parameters": [parameter],
        },
        {
            "factCode": "task.release_due_at",
            "name": "定时释放时间",
            "factKind": "derived",
            "dataType": "datetime",
            "description": "任务完成两天后的释放时间",
            "nullable": False,
            "nullPolicy": "error",
            "grain": "formal_test_task",
            "parameters": [],
            "derivation": {
                "kind": "dateAdd",
                "unit": "day",
                "children": [
                    {"kind": "fact", "factCode": "task.completed_at"},
                    {"kind": "literal", "value": 2},
                ],
            },
        },
    ]
    payload["fieldMappings"] = [
        {
            "factCode": fact["factCode"],
            "mappingStatus": "unresolved",
            "note": "等待事实绑定。",
        }
        for fact in payload["requiredFacts"]
    ]
    payload["testCases"] = [
        {
            "id": "exact-boundary-pass",
            "description": "恰好达到两天边界",
            "given": {
                "task.current_time": "2026-08-21T10:00:00Z",
                "task.completed_at": "2026-08-19T10:00:00Z",
            },
            "expected": "pass",
            "rationale": "边界使用大于等于。",
        },
        {
            "id": "before-boundary-fail",
            "description": "比两天边界早一秒",
            "given": {
                "task.current_time": "2026-08-21T09:59:59Z",
                "task.completed_at": "2026-08-19T10:00:00Z",
            },
            "expected": "fail",
            "rationale": "未达到释放时间。",
        },
    ]

    candidate = RuleCandidateV2.model_validate(payload)

    validate_candidate_v2(candidate)


def test_fact_binding_requests_are_atomic_and_exclude_derived_fact() -> None:
    candidate = RuleCandidateV2.model_validate(deepcopy(valid_candidate_v2()))
    validate_candidate_v2(candidate)
    parsed = enrich_candidate_v2(candidate)
    result = RuleParseResultV2(
        rule_version="TEST_RELEASE_002@20260819T000000000000Z-000000000000",
        generated_at="2026-08-19T00:00:00Z",
        parser=ParserMetadata(
            parser_version="0.4.0",
            prompt_version="rule-parser-v2",
            model="fake-deepseek",
        ),
        source=SourceMetadata(
            source_name="test.md",
            sha256="0" * 64,
            character_count=10,
        ),
        rule=parsed,
    )

    requests = build_fact_binding_requests(result)

    codes = {request.fact.fact_code for request in requests}
    assert "task.required_fee" not in codes
    assert codes == {
        "task.status",
        "task.received_amount",
        "task.base_fee",
        "task.extra_fee",
        "task.settlement_fee",
    }
    base_fee = next(request for request in requests if request.fact.fact_code == "task.base_fee")
    assert base_fee.usages[0].expression_side == "rightDerivation"
    settlement = next(
        request for request in requests if request.fact.fact_code == "task.settlement_fee"
    )
    assert settlement.mapping_candidate.view_field == "zssyjsfy"
    assert "sourceExpression" not in settlement.mapping_candidate.model_dump(by_alias=True)
