"""Synthetic, non-business fixtures for Rule Schema 3.1.0."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tests.v3_fixtures import valid_fact_catalog_v3, valid_rule_structure_candidate_v3


def valid_rule_structure_candidate_v31() -> dict[str, Any]:
    catalog = valid_fact_catalog_v3()
    payload = deepcopy(valid_rule_structure_candidate_v3())
    payload["contractVersion"] = "3.1.0"
    payload["sourceIdentity"] = {
        "sourceFileSha256": "a" * 64,
        "parseInputSha256": "b" * 64,
        "extractorVersion": "synthetic-v1",
        "extractedSections": ["1.3"],
        "sourceFileByteLength": 32,
        "parseInputCharacterCount": 16,
    }
    payload["runtimeParameters"] = [
        {
            "name": "evaluationDate",
            "dataType": "date",
            "role": "evaluationClock",
            "required": True,
            "boundValue": "2026-09-17",
            "inclusive": True,
            "description": "Synthetic evaluation date.",
        }
    ]
    payload["evaluationTimezone"] = "Asia/Shanghai"
    payload["stageSemantics"] = {
        "stateGuards": {"onHit": "terminate", "unknown": "indeterminate"},
        "prerequisites": {"onHit": "terminate", "unknown": "indeterminate"},
        "eligibility": {"onHit": "firstMatchThenContinue", "unknown": "indeterminate"},
        "postGates": {"onHit": "terminate", "unknown": "indeterminate"},
        "exclusions": {"onHit": "terminate", "unknown": "indeterminate"},
    }
    payload["catalogId"] = catalog["catalogId"]
    payload["catalogVersion"] = catalog["catalogVersion"]
    payload["catalogDigest"] = catalog["catalogDigest"]
    return payload


def valid_fact_binding_request_v31() -> dict[str, Any]:
    rule_version = (
        "SYNTHETIC_REPORT_RELEASE@20260917T140000000000Z-" + ("a" * 12) + "-" + ("c" * 12)
    )
    return {
        "contractVersion": "3.1.0",
        "status": "candidate",
        "executable": False,
        "requestId": f"{rule_version}#task.status_code",
        "ruleRef": {
            "ruleSetId": "SYNTHETIC_REPORT_RELEASE",
            "ruleVersion": rule_version,
            "schemaVersion": "3.1.0",
            "sourceSha256": "a" * 64,
            "parseInputSha256": "b" * 64,
            "catalogDigest": "c" * 64,
            "candidatePayloadSha256": "d" * 64,
        },
        "fact": {
            "factCode": "task.status_code",
            "name": "Synthetic task status",
            "factKind": "source",
            "dataType": "integer",
            "description": "Returns one status code for a task.",
            "nullable": True,
            "nullPolicy": "indeterminate",
            "grain": "task",
            "parameters": [
                {
                    "name": "taskId",
                    "role": "entityKey",
                    "dataType": "string",
                    "required": True,
                    "description": "Task key.",
                }
            ],
            "unit": None,
            "allowedValues": [],
        },
        "queryRequirements": {
            "entity": {
                "entityType": "task",
                "grain": "task",
                "keyParameters": ["taskId"],
                "evidenceIds": ["query.task.status_code"],
            },
            "fields": [
                {
                    "fieldId": "factValue",
                    "role": "value",
                    "logicalName": "Task status",
                    "dataType": "integer",
                    "required": False,
                    "evidenceIds": ["query.task.status_code"],
                }
            ],
            "filters": {
                "items": [],
                "completeness": "complete",
                "evidenceIds": ["query.task.status_code"],
            },
            "aggregation": {
                "mode": "none",
                "function": None,
                "inputFieldIds": [],
                "groupByFieldIds": [],
                "distinct": None,
                "evidenceIds": ["query.task.status_code"],
            },
            "timeRange": {
                "mode": "none",
                "timeFieldId": None,
                "start": None,
                "end": None,
                "timezone": None,
                "evidenceIds": ["query.task.status_code"],
            },
            "result": {
                "columnName": "fact_value",
                "dataType": "integer",
                "cardinality": "scalar",
                "nullable": True,
                "nullPolicy": "indeterminate",
                "unit": None,
            },
        },
        "usages": [
            {
                "stage": "prerequisites",
                "ruleCode": "TASK_NOT_COMPLETED",
                "priority": 10,
                "conditionId": "status-ne-19",
                "conditionPath": "/stages/1/rules/0/when",
                "outcome": "WAITING_COMPLETION",
                "evidenceIds": ["condition.status-ne-19"],
            }
        ],
        "examples": [
            {
                "exampleId": "case-not-completed",
                "value": 10,
                "expectedOutcome": "WAITING_COMPLETION",
                "evidenceIds": ["case-not-completed"],
            }
        ],
        "mappingCandidate": {
            "factCode": "task.status_code",
            "mappingStatus": "unresolved",
            "viewName": None,
            "viewField": None,
            "viewActive": None,
            "reviewStatus": "candidate",
            "note": "Physical source is resolved by metadataReview.",
        },
        "provenance": {
            "sourceName": "synthetic-optimization-plan.md",
            "relativePath": "synthetic.md",
            "sourceSha256": "a" * 64,
            "parseInputSha256": "b" * 64,
            "sourceFileByteLength": 32,
            "parseInputCharacterCount": 16,
            "extractorVersion": "synthetic-v1",
            "extractedSections": ["1.3"],
            "parserVersion": "0.13.0",
            "promptVersion": "optimization-plan-v31",
            "provider": "reviewed_import",
            "model": "optimization-plan-translator-v1",
        },
        "evidence": [
            {
                "evidenceId": "fact.task.status_code",
                "kind": "factDeclaration",
                "sourceDocument": "ruleResult",
                "sourcePath": "/factDeclarations/0",
            }
        ],
        "uncertainties": [],
        "targetDialect": "sqlserver",
        "requiresMetadataSnapshot": True,
        "tempTableAllowed": False,
    }


def valid_rule_parse_result_v31() -> dict[str, Any]:
    catalog = valid_fact_catalog_v3()
    rule_version = (
        "SYNTHETIC_REPORT_RELEASE@20260917T140000000000Z-"
        + ("a" * 12)
        + "-"
        + catalog["catalogDigest"][:12]
    )
    request = valid_fact_binding_request_v31()
    request["requestId"] = f"{rule_version}#task.status_code"
    request["ruleRef"]["ruleVersion"] = rule_version
    request["ruleRef"]["catalogDigest"] = catalog["catalogDigest"]
    return {
        "schemaVersion": "3.1.0",
        "ruleVersion": rule_version,
        "ruleSetId": "SYNTHETIC_REPORT_RELEASE",
        "generatedAt": "2026-09-17T14:00:00+00:00",
        "status": "draft",
        "executable": False,
        "source": request["provenance"],
        "parser": {
            "parserVersion": "0.13.0",
            "promptVersion": "optimization-plan-v31",
            "provider": "reviewed_import",
            "model": "optimization-plan-translator-v1",
        },
        "catalogRef": {
            "catalogId": catalog["catalogId"],
            "catalogVersion": catalog["catalogVersion"],
            "catalogDigest": catalog["catalogDigest"],
            "payloadSha256": "e" * 64,
        },
        "candidateRef": {
            "payloadSha256": "d" * 64,
            "parseInputSha256": "b" * 64,
        },
        "deliveryRef": {
            "catalogPayloadSha256": "e" * 64,
            "candidatePayloadSha256": "d" * 64,
            "resultPayloadSha256": None,
            "purpose": "optimization-plan-generation",
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
                "caseId": "not-completed",
                "description": "Uncompleted synthetic task waits.",
                "given": {"task.status_code": 10, "order.received_amount": 1},
                "runtime": {"evaluationDate": "2026-09-17"},
                "members": [],
                "expectedOutcome": "WAITING_COMPLETION",
                "expectedReasonCode": "STATE_INVALID_RESULT",
                "expectedMatchedRuleCodes": ["STATE_INVALID"],
            }
        ],
        "agent2ReadinessReady": True,
    }
