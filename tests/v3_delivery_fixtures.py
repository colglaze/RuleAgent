"""Synthetic, fully-closing V3 delivery fixture for persistence tests.

Builds a catalog, an unblocked candidate, a ready ``RuleParseResultV3``, and its exported
``FactBindingRequestV3`` list from the offline synthetic fixtures only — no private
business data. The fixture fails fast when any closure does not hold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rule_reader.domain.rules.bindings_v3 import FactKind
from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    ConfirmedFactV3,
)
from rule_reader.domain.rules.readiness_v3 import build_agent2_readiness_report_v3
from rule_reader.domain.rules.result_v3 import (
    FactDeclarationV3,
    RuleParseResultV3,
    TestCaseV3,
    build_rule_version_v3,
    export_fact_binding_requests_v3,
)
from rule_reader.domain.rules.validation_v3 import evaluate_rule_structure_v3
from tests.v3_fixtures import (
    valid_fact_catalog_v3,
    valid_rule_structure_candidate_v3,
)

FIXED_GENERATED_AT = datetime(2026, 9, 5, 0, 0, 0, tzinfo=UTC)
SYNTHETIC_SOURCE_SHA256 = "1" * 64

_FACT_KINDS: dict[str, FactKind] = {
    "task.status_code": FactKind.SOURCE,
    "order.received_amount": FactKind.SOURCE,
}

_KEY_PARAMETER_BY_GRAIN = {"task": "taskId", "order": "orderId"}


def _bindable_fact(fact: ConfirmedFactV3) -> dict[str, Any]:
    return {
        "factCode": fact.fact_code,
        "name": fact.name,
        "factKind": _FACT_KINDS[fact.fact_code].value,
        "dataType": fact.data_type.value,
        "description": fact.description,
        "nullable": fact.nullable,
        "nullPolicy": fact.null_policy.value,
        "grain": fact.grain,
        "parameters": [
            parameter.model_dump(mode="json", by_alias=True) for parameter in fact.parameters
        ],
        "unit": fact.unit,
        "allowedValues": fact.allowed_values,
    }


def _query_requirements(fact: ConfirmedFactV3) -> dict[str, Any]:
    key_parameter = _KEY_PARAMETER_BY_GRAIN[fact.grain]
    key_field_id = f"parameter.{key_parameter}"
    evidence_ids = [f"fact.{fact.fact_code}", f"query.{fact.fact_code}"]
    return {
        "entity": {
            "entityType": fact.grain,
            "grain": fact.grain,
            "keyParameters": [key_parameter],
            "evidenceIds": evidence_ids,
        },
        "fields": [
            {
                "fieldId": "factValue",
                "role": "value",
                "logicalName": fact.fact_code,
                "dataType": fact.data_type.value,
                "required": True,
                "evidenceIds": evidence_ids,
            },
            {
                "fieldId": key_field_id,
                "role": "entityKey",
                "logicalName": key_parameter,
                "dataType": "string",
                "required": True,
                "evidenceIds": evidence_ids,
            },
        ],
        "filters": {
            "items": [
                {
                    "filterId": f"{fact.grain}.key",
                    "fieldId": key_field_id,
                    "operator": "eq",
                    "value": {"kind": "parameter", "parameterName": key_parameter},
                    "nullPolicy": "error",
                    "required": True,
                    "evidenceIds": evidence_ids,
                }
            ],
            "completeness": "complete",
            "evidenceIds": evidence_ids,
        },
        "aggregation": {
            "mode": "none",
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence_ids,
        },
        "timeRange": {
            "mode": "none",
            "timeFieldId": None,
            "start": None,
            "end": None,
            "timezone": None,
            "evidenceIds": evidence_ids,
        },
        "result": {
            "columnName": "fact_value",
            "dataType": fact.data_type.value,
            "cardinality": "scalar",
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "unit": fact.unit,
        },
    }


def _declarations(
    catalog: BusinessConfirmedFactCatalogV3,
    required_codes: set[str],
) -> list[FactDeclarationV3]:
    declarations: list[FactDeclarationV3] = []
    for fact in catalog.facts:
        if fact.fact_code not in required_codes:
            continue
        declarations.append(
            FactDeclarationV3.model_validate(
                {
                    "fact": _bindable_fact(fact),
                    "query": _query_requirements(fact),
                    "uncertainties": [],
                }
            )
        )
    return declarations


def _test_cases() -> list[TestCaseV3]:
    specs: list[dict[str, Any]] = [
        {
            "caseId": "synthetic-ready",
            "description": "合成金额达到阈值时直接就绪。",
            "given": {"task.status_code": 19, "order.received_amount": 100.0},
            "expectedOutcome": "READY",
            "expectedReasonCode": "AMOUNT_THRESHOLD_RESULT",
            "expectedMatchedRuleCodes": ["AMOUNT_THRESHOLD"],
        },
        {
            "caseId": "synthetic-state-invalid",
            "description": "合成状态不在值域时无需释放。",
            "given": {"task.status_code": 20, "order.received_amount": 100.0},
            "expectedOutcome": "NO_RELEASE_REQUIRED",
            "expectedReasonCode": "STATE_INVALID_RESULT",
            "expectedMatchedRuleCodes": ["STATE_INVALID"],
        },
        {
            "caseId": "synthetic-low-amount",
            "description": "合成金额低于门槛时等待满足条件。",
            "given": {"task.status_code": 19, "order.received_amount": 5.0},
            "expectedOutcome": "WAITING_CONDITIONS",
            "expectedReasonCode": "LOW_AMOUNT_GATE_RESULT",
            "expectedMatchedRuleCodes": ["LOW_AMOUNT_GATE"],
        },
    ]
    return [TestCaseV3.model_validate(spec) for spec in specs]


def synthetic_ready_delivery_v3() -> tuple[
    BusinessConfirmedFactCatalogV3,
    Any,
    RuleParseResultV3,
    tuple[Any, ...],
]:
    """Return a fully closing synthetic (catalog, candidate, ready result, requests)."""

    from rule_reader.domain.rules.v3 import RuleStructureCandidateV3

    catalog = BusinessConfirmedFactCatalogV3.model_validate(valid_fact_catalog_v3())
    candidate = RuleStructureCandidateV3.model_validate(valid_rule_structure_candidate_v3())
    declarations = _declarations(catalog, set(candidate.required_fact_codes))
    test_cases = _test_cases()
    for case in test_cases:
        evaluation = evaluate_rule_structure_v3(candidate, catalog, dict(case.given))
        assert evaluation.outcome is case.expected_outcome
        assert evaluation.reason_code == case.expected_reason_code
        assert list(evaluation.matched_rule_codes) == case.expected_matched_rule_codes

    rule_version = build_rule_version_v3(
        candidate.rule_set_id,
        FIXED_GENERATED_AT,
        SYNTHETIC_SOURCE_SHA256,
        catalog.catalog_digest,
    )
    provenance = {
        "sourceName": "synthetic-ordered-rule.md",
        "relativePath": "examples/synthetic-ordered-rule.md",
        "sourceSha256": SYNTHETIC_SOURCE_SHA256,
        "sourceCharacterCount": 100,
        "parserVersion": "0.11.0",
        "promptVersion": "rule-structure-v3.1",
        "provider": "reviewed_import",
        "model": "synthetic-author",
    }
    result = RuleParseResultV3.model_validate(
        {
            "schemaVersion": "3.0.0",
            "ruleVersion": rule_version,
            "ruleSetId": candidate.rule_set_id,
            "generatedAt": FIXED_GENERATED_AT.isoformat(),
            "status": "draft",
            "executable": False,
            "source": provenance,
            "parser": {
                "parserVersion": provenance["parserVersion"],
                "promptVersion": provenance["promptVersion"],
                "provider": provenance["provider"],
                "model": provenance["model"],
            },
            "catalogRef": {
                "catalogId": catalog.catalog_id,
                "catalogVersion": catalog.catalog_version,
                "catalogDigest": catalog.catalog_digest,
            },
            "candidateRef": {
                "payloadSha256": "0" * 64,
                "ruleBlockSha256": SYNTHETIC_SOURCE_SHA256,
            },
            "factDeclarations": [
                declaration.model_dump(mode="json", by_alias=True) for declaration in declarations
            ],
            "testCases": [case.model_dump(mode="json", by_alias=True) for case in test_cases],
            "agent2ReadinessReady": False,
        }
    )
    pre = build_agent2_readiness_report_v3(catalog=catalog, candidate=candidate, result=result)
    non_export_gates = [gate for gate in pre.gates if gate.gate != 4]
    assert all(gate.result.value == "pass" for gate in non_export_gates), [
        (gate.gate, gate.result.value, gate.evidence) for gate in non_export_gates
    ]
    from rule_reader.domain.rules.result_v3 import candidate_payload_sha256_v3

    ready_result = result.model_copy(update={"agent2_readiness_ready": True})
    closed_result = ready_result.model_copy(
        update={
            "candidate_ref": ready_result.candidate_ref.model_copy(
                update={"payload_sha256": candidate_payload_sha256_v3(candidate)}
            )
        }
    )
    requests = export_fact_binding_requests_v3(closed_result, candidate, catalog)
    final = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=closed_result,
        requests=requests,
    )
    assert final.ready is True, [
        (gate.gate, gate.result.value, gate.evidence) for gate in final.gates
    ]
    return catalog, candidate, closed_result, tuple(requests)
