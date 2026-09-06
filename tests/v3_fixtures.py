"""Synthetic, non-business fixtures for Rule Schema 3.0."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rule_reader.domain.rules.catalog_v3 import catalog_digest_v3


def valid_fact_catalog_v3() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": "SYNTHETIC_RELEASE_FACTS",
        "catalogVersion": "2026-09-05.1",
        "catalogDigest": "0" * 64,
        "facts": [
            {
                "factCode": "task.status_code",
                "name": "合成任务状态",
                "description": "用于离线测试的任务状态代码。",
                "dataType": "enum",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "task",
                "parameters": [
                    {
                        "name": "taskId",
                        "role": "entityKey",
                        "dataType": "string",
                        "required": True,
                        "description": "合成任务标识。",
                    }
                ],
                "allowedValues": [19, 20],
                "unit": None,
                "evidenceRefs": ["confirmation.status"],
                "bindingProfileRef": None,
                "bindingIssues": ["测试夹具不提供物理绑定。"],
            },
            {
                "factCode": "order.received_amount",
                "name": "合成已收金额",
                "description": "用于离线测试的金额。",
                "dataType": "money",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "order",
                "parameters": [
                    {
                        "name": "orderId",
                        "role": "entityKey",
                        "dataType": "string",
                        "required": True,
                        "description": "合成订单标识。",
                    }
                ],
                "allowedValues": [],
                "unit": "CNY",
                "evidenceRefs": ["confirmation.amount"],
                "bindingProfileRef": None,
                "bindingIssues": ["测试夹具不提供物理绑定。"],
            },
        ],
        "evidence": [
            {
                "evidenceId": "confirmation.status",
                "sourceKind": "businessConfirmation",
                "sourceId": "synthetic-confirmation",
                "sourceSha256": "1" * 64,
                "locator": "row:1",
                "note": "脱敏合成证据。",
            },
            {
                "evidenceId": "confirmation.amount",
                "sourceKind": "businessConfirmation",
                "sourceId": "synthetic-confirmation",
                "sourceSha256": "1" * 64,
                "locator": "row:2",
                "note": "脱敏合成证据。",
            },
        ],
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    return payload


def _condition(
    condition_id: str, fact_code: str, operator: str, value: str | int | float
) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "compare",
        "description": f"合成条件 {condition_id}",
        "enabled": True,
        "children": [],
        "left": {"kind": "fact", "factCode": fact_code, "children": []},
        "operator": operator,
        "right": {"kind": "literal", "value": value, "children": []},
        "nullPolicy": "indeterminate",
    }


def _active_rule(
    code: str,
    priority: int,
    condition: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    return {
        "ruleCode": code,
        "priority": priority,
        "title": f"合成规则 {code}",
        "status": "active",
        "when": condition,
        "outcome": outcome,
        "reasonCode": f"{code}_RESULT",
        "failureReason": "合成规则未满足。",
        "recommendations": ["核对合成输入。"],
        "blockingIssueIds": [],
    }


def valid_rule_structure_candidate_v3() -> dict[str, Any]:
    catalog = valid_fact_catalog_v3()
    return {
        "contractVersion": "3.0.0",
        "ruleSetId": "SYNTHETIC_REPORT_RELEASE",
        "title": "合成报告释放规则",
        "scope": "只用于离线契约和解释器测试。",
        "catalogId": catalog["catalogId"],
        "catalogVersion": catalog["catalogVersion"],
        "catalogDigest": catalog["catalogDigest"],
        "sourceViews": ["synthetic_release_view"],
        "requiredFactCodes": ["order.received_amount", "task.status_code"],
        "stages": [
            {
                "stage": "stateGuards",
                "rules": [
                    _active_rule(
                        "STATE_INVALID",
                        10,
                        _condition("state-invalid", "task.status_code", "ne", 19),
                        "NO_RELEASE_REQUIRED",
                    )
                ],
            },
            {
                "stage": "prerequisites",
                "rules": [
                    _active_rule(
                        "AMOUNT_NEGATIVE",
                        10,
                        _condition("amount-negative", "order.received_amount", "lt", 0),
                        "WAITING_CONDITIONS",
                    )
                ],
            },
            {
                "stage": "eligibility",
                "rules": [
                    _active_rule(
                        "AMOUNT_THRESHOLD",
                        10,
                        _condition("amount-threshold", "order.received_amount", "gte", 80),
                        "READY",
                    )
                ],
            },
            {
                "stage": "postGates",
                "rules": [
                    _active_rule(
                        "LOW_AMOUNT_GATE",
                        10,
                        _condition("low-amount-gate", "order.received_amount", "lt", 10),
                        "WAITING_CONDITIONS",
                    )
                ],
            },
            {
                "stage": "exclusions",
                "rules": [
                    _active_rule(
                        "CLOSED_TASK_EXCLUSION",
                        10,
                        _condition("closed-task-exclusion", "task.status_code", "eq", 20),
                        "NO_RELEASE_REQUIRED",
                    )
                ],
            },
        ],
        "defaultOutcome": "WAITING_CONDITIONS",
        "defaultReasonCode": "NO_RELEASE_PATH_MATCHED",
        "blockingIssues": [],
        "proposedFacts": [],
    }


def blocked_rule_structure_candidate_v3() -> dict[str, Any]:
    payload = deepcopy(valid_rule_structure_candidate_v3())
    payload["stages"][2]["rules"][0] = {
        "ruleCode": "MISSING_BUSINESS_FACT",
        "priority": 10,
        "title": "缺少业务确认事实",
        "status": "blocked",
        "when": None,
        "outcome": None,
        "reasonCode": None,
        "failureReason": "缺少已确认事实，不能构造条件。",
        "recommendations": ["由业务审核者确认事实契约。"],
        "blockingIssueIds": ["business.fact.missing"],
    }
    payload["blockingIssues"] = [
        {
            "issueId": "business.fact.missing",
            "code": "BUSINESS_FACT_MISSING",
            "message": "合成业务事实尚未确认。",
            "factCodes": ["report.synthetic_flag"],
            "resolutionHint": "补充事实类型、粒度和空值语义。",
        }
    ]
    payload["proposedFacts"] = [
        {
            "factCode": "report.synthetic_flag",
            "name": "候选标志",
            "dataTypeHint": "boolean",
            "reason": "规则文本引用了目录外概念。",
            "sourceLocator": "synthetic:1",
        }
    ]
    return payload


def valid_fact_binding_request_v3() -> dict[str, Any]:
    rule_version = "SYNTHETIC_REPORT_RELEASE@20260905T000000000000Z-111111111111-222222222222"
    return {
        "contractVersion": "3.0.0",
        "status": "candidate",
        "executable": False,
        "requestId": f"{rule_version}#task.status_code",
        "ruleRef": {
            "ruleSetId": "SYNTHETIC_REPORT_RELEASE",
            "ruleVersion": rule_version,
            "schemaVersion": "3.0.0",
            "sourceSha256": "1" * 64,
            "catalogDigest": "2" * 64,
            "candidatePayloadSha256": "3" * 64,
        },
        "fact": {
            "factCode": "task.status_code",
            "name": "合成任务状态",
            "factKind": "source",
            "dataType": "string",
            "description": "按任务返回一个状态代码。",
            "nullable": False,
            "nullPolicy": "error",
            "grain": "task",
            "parameters": [
                {
                    "name": "taskId",
                    "role": "entityKey",
                    "dataType": "string",
                    "required": True,
                    "description": "任务标识。",
                }
            ],
            "unit": None,
            "allowedValues": ["READY", "CLOSED"],
        },
        "queryRequirements": {
            "entity": {
                "entityType": "task",
                "grain": "task",
                "keyParameters": ["taskId"],
                "evidenceIds": ["fact.declaration", "query.contract"],
            },
            "fields": [
                {
                    "fieldId": "factValue",
                    "role": "value",
                    "logicalName": "task.status_code",
                    "dataType": "string",
                    "required": True,
                    "evidenceIds": ["fact.declaration", "query.contract"],
                },
                {
                    "fieldId": "parameter.taskId",
                    "role": "entityKey",
                    "logicalName": "taskId",
                    "dataType": "string",
                    "required": True,
                    "evidenceIds": ["query.contract"],
                },
            ],
            "filters": {
                "items": [
                    {
                        "filterId": "task.key",
                        "fieldId": "parameter.taskId",
                        "operator": "eq",
                        "value": {"kind": "parameter", "parameterName": "taskId"},
                        "nullPolicy": "error",
                        "required": True,
                        "evidenceIds": ["query.contract"],
                    }
                ],
                "completeness": "complete",
                "evidenceIds": ["query.contract"],
            },
            "aggregation": {
                "mode": "none",
                "function": None,
                "inputFieldIds": [],
                "groupByFieldIds": [],
                "distinct": None,
                "evidenceIds": ["query.contract"],
            },
            "timeRange": {
                "mode": "none",
                "timeFieldId": None,
                "start": None,
                "end": None,
                "timezone": None,
                "evidenceIds": ["query.contract"],
            },
            "result": {
                "columnName": "fact_value",
                "dataType": "string",
                "cardinality": "scalar",
                "nullable": False,
                "nullPolicy": "error",
                "unit": None,
            },
        },
        "usages": [
            {
                "stage": "prerequisites",
                "ruleCode": "STATE_CHECK",
                "priority": 10,
                "conditionId": "state-check",
                "conditionPath": "/stages/1/rules/0/when",
                "outcome": "WAITING_CONDITIONS",
                "evidenceIds": ["condition.usage"],
            }
        ],
        "examples": [
            {
                "exampleId": "status-ready",
                "value": "READY",
                "expectedOutcome": "READY",
                "evidenceIds": ["example.ready"],
            }
        ],
        "mappingCandidate": {
            "factCode": "task.status_code",
            "mappingStatus": "unresolved",
            "viewName": None,
            "viewField": None,
            "viewActive": None,
            "reviewStatus": "candidate",
            "note": "物理来源由 metadataReview 解析。",
        },
        "provenance": {
            "sourceName": "synthetic-ordered-rule.md",
            "relativePath": "examples/synthetic-ordered-rule.md",
            "sourceSha256": "1" * 64,
            "sourceCharacterCount": 100,
            "parserVersion": "0.11.0",
            "promptVersion": "rule-structure-v3.1",
            "provider": "reviewed_import",
            "model": "synthetic-author",
        },
        "evidence": [
            {
                "evidenceId": "fact.declaration",
                "kind": "factDeclaration",
                "sourceDocument": "catalog",
                "sourcePath": "/facts/0",
            },
            {
                "evidenceId": "query.contract",
                "kind": "queryRequirement",
                "sourceDocument": "ruleResult",
                "sourcePath": "/factDeclarations/0/query",
            },
            {
                "evidenceId": "condition.usage",
                "kind": "conditionUsage",
                "sourceDocument": "candidate",
                "sourcePath": "/stages/1/rules/0/when",
            },
            {
                "evidenceId": "example.ready",
                "kind": "example",
                "sourceDocument": "ruleResult",
                "sourcePath": "/testCases/0",
            },
        ],
        "uncertainties": [],
        "targetDialect": "sqlserver",
        "requiresMetadataSnapshot": True,
        "tempTableAllowed": False,
    }


def valid_rule_parse_result_v3() -> dict[str, Any]:
    request = valid_fact_binding_request_v3()
    rule_ref = request["ruleRef"]
    return {
        "schemaVersion": "3.0.0",
        "ruleVersion": rule_ref["ruleVersion"],
        "ruleSetId": rule_ref["ruleSetId"],
        "generatedAt": "2026-09-05T00:00:00Z",
        "status": "draft",
        "executable": False,
        "source": request["provenance"],
        "parser": {
            "parserVersion": request["provenance"]["parserVersion"],
            "promptVersion": request["provenance"]["promptVersion"],
            "provider": request["provenance"]["provider"],
            "model": request["provenance"]["model"],
        },
        "catalogRef": {
            "catalogId": "SYNTHETIC_RELEASE_FACTS",
            "catalogVersion": "2026-09-05.1",
            "catalogDigest": rule_ref["catalogDigest"],
        },
        "candidateRef": {
            "payloadSha256": rule_ref["candidatePayloadSha256"],
            "ruleBlockSha256": rule_ref["sourceSha256"],
        },
        "factDeclarations": [
            {
                "fact": request["fact"],
                "query": request["queryRequirements"],
                "uncertainties": [],
            }
        ],
        "testCases": [
            {
                "caseId": "synthetic-waiting",
                "description": "合成状态等待案例。",
                "given": {"task.status_code": "READY"},
                "expectedOutcome": "WAITING_CONDITIONS",
                "expectedReasonCode": "STATE_CHECK_MATCHED",
                "expectedMatchedRuleCodes": ["STATE_CHECK"],
            }
        ],
        "agent2ReadinessReady": False,
    }
