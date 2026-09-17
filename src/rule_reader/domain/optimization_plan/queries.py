"""Logical query requirements for optimization-plan 3.1.0 facts."""

from __future__ import annotations

from typing import Any

from rule_reader.domain.optimization_plan import (
    COMPLETED_APPROVAL_NODE_TYPES,
    DATA_SPECIAL_APPLICATION_TYPE,
    REPORT_SPECIAL_APPLICATION_TYPE,
)
from rule_reader.domain.optimization_plan.catalogs import DATA_FACT_KINDS, REPORT_FACT_KINDS
from rule_reader.domain.rules.catalog_v3 import ConfirmedFactV3
from rule_reader.domain.rules.v2 import FactKind

_AS_OF_FACTS = {"report.release_status", "data.release_status"}
_SET_FACTS = {"report.merge_group_member_ids", "order.seal_scope_contract_ids"}


def _evidence(fact_code: str) -> list[str]:
    return [f"query.{fact_code}"]


def _entity_key(grain: str) -> str:
    if grain == "contract":
        return "contractId"
    if grain == "order":
        return "orderId"
    return "taskId"


def _base_fields(fact: ConfirmedFactV3, extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = _evidence(fact.fact_code)
    grain = fact.grain
    fields: list[dict[str, Any]] = [
        {
            "fieldId": "factValue",
            "role": "value",
            "logicalName": fact.name,
            "dataType": fact.data_type.value,
            "required": not fact.nullable,
            "evidenceIds": evidence,
        },
        {
            "fieldId": f"{grain}.id",
            "role": "entityKey",
            "logicalName": f"{grain} key",
            "dataType": "string",
            "required": True,
            "evidenceIds": evidence,
        },
    ]
    result: list[dict[str, Any]] = list(fields)
    result.extend(extra)
    return result


def _literal_filter(
    filter_id: str,
    field_id: str,
    operator: str,
    literal: Any,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "filterId": filter_id,
        "fieldId": field_id,
        "operator": operator,
        "value": {"kind": "literal", "literal": literal},
        "nullPolicy": "fail",
        "required": True,
        "evidenceIds": evidence,
    }


def _parameter_filter(
    filter_id: str,
    field_id: str,
    operator: str,
    parameter_name: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "filterId": filter_id,
        "fieldId": field_id,
        "operator": operator,
        "value": {"kind": "parameter", "parameterName": parameter_name},
        "nullPolicy": "fail",
        "required": True,
        "evidenceIds": evidence,
    }


def _aggregation(kind: FactKind, evidence: list[str]) -> dict[str, Any]:
    if kind is FactKind.AGGREGATE:
        return {
            "mode": "compute",
            "function": "count",
            "inputFieldIds": ["factValue"],
            "groupByFieldIds": [],
            "distinct": False,
            "evidenceIds": evidence,
        }
    if kind is FactKind.EXISTS:
        return {
            "mode": "exists",
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence,
        }
    return {
        "mode": "none",
        "function": None,
        "inputFieldIds": [],
        "groupByFieldIds": [],
        "distinct": None,
        "evidenceIds": evidence,
    }


def _time_range_none(evidence: list[str]) -> dict[str, Any]:
    return {
        "mode": "none",
        "timeFieldId": None,
        "start": None,
        "end": None,
        "timezone": None,
        "evidenceIds": evidence,
    }


def _time_range_as_of(evidence: list[str]) -> dict[str, Any]:
    return {
        "mode": "asOf",
        "timeFieldId": "status.asOfDate",
        "start": None,
        "end": {
            "kind": "parameter",
            "parameterName": "evaluationDate",
            "inclusive": True,
        },
        "timezone": "Asia/Shanghai",
        "evidenceIds": evidence,
    }


def _special_application_query(fact: ConfirmedFactV3, application_type: int) -> dict[str, Any]:
    evidence = _evidence(fact.fact_code)
    extra = [
        {
            "fieldId": "application.type",
            "role": "filter",
            "logicalName": "Special application type",
            "dataType": "integer",
            "required": True,
            "evidenceIds": evidence,
        },
        {
            "fieldId": "approval.nodeType",
            "role": "filter",
            "logicalName": "Approval node type",
            "dataType": "integer",
            "required": True,
            "evidenceIds": evidence,
        },
        {
            "fieldId": "application.rowId",
            "role": "filter",
            "logicalName": "Join row identity counted without de-duplication",
            "dataType": "string",
            "required": True,
            "evidenceIds": evidence,
        },
    ]
    payload = {
        "entity": {
            "entityType": "task",
            "grain": "task",
            "keyParameters": ["taskId"],
            "evidenceIds": evidence,
        },
        "fields": _base_fields(fact, extra),
        "filters": {
            "items": [
                _literal_filter(
                    "application-type",
                    "application.type",
                    "eq",
                    application_type,
                    evidence,
                ),
                _literal_filter(
                    "completed-approval-node",
                    "approval.nodeType",
                    "in",
                    list(COMPLETED_APPROVAL_NODE_TYPES),
                    evidence,
                ),
            ],
            "completeness": "complete",
            "evidenceIds": evidence,
        },
        "aggregation": {
            "mode": "compute",
            "function": "count",
            "inputFieldIds": ["application.rowId"],
            "groupByFieldIds": [],
            "distinct": False,
            "evidenceIds": evidence,
        },
        "timeRange": _time_range_none(evidence),
        "result": {
            "columnName": "fact_value",
            "dataType": fact.data_type.value,
            "cardinality": "scalar",
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "unit": fact.unit,
        },
    }
    return payload


def _set_query(
    fact: ConfirmedFactV3, extra_fields: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> dict[str, Any]:
    evidence = _evidence(fact.fact_code)
    return {
        "entity": {
            "entityType": fact.grain,
            "grain": fact.grain,
            "keyParameters": [_entity_key(fact.grain)],
            "evidenceIds": evidence,
        },
        "fields": _base_fields(fact, extra_fields),
        "filters": {
            "items": filters,
            "completeness": "complete",
            "evidenceIds": evidence,
        },
        "aggregation": {
            "mode": "none",
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence,
        },
        "timeRange": _time_range_none(evidence),
        "result": {
            "columnName": "fact_value",
            "dataType": "list",
            "cardinality": "set",
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "unit": fact.unit,
        },
    }


def _default_query(
    fact: ConfirmedFactV3, kind: FactKind, extra_fields: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    evidence = _evidence(fact.fact_code)
    extra = extra_fields or []
    if fact.fact_code in _AS_OF_FACTS:
        extra.append(
            {
                "fieldId": "status.asOfDate",
                "role": "time",
                "logicalName": "Status as-of calendar date",
                "dataType": "date",
                "required": True,
                "evidenceIds": evidence,
            }
        )
    return {
        "entity": {
            "entityType": fact.grain,
            "grain": fact.grain,
            "keyParameters": [_entity_key(fact.grain)],
            "evidenceIds": evidence,
        },
        "fields": _base_fields(fact, extra),
        "filters": {
            "items": [],
            "completeness": "complete",
            "evidenceIds": evidence,
        },
        "aggregation": _aggregation(kind, evidence),
        "timeRange": _time_range_as_of(evidence)
        if fact.fact_code in _AS_OF_FACTS
        else _time_range_none(evidence),
        "result": {
            "columnName": "fact_value",
            "dataType": fact.data_type.value,
            "cardinality": "set" if fact.fact_code in _SET_FACTS else "scalar",
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "unit": fact.unit,
        },
    }


def _oa_query(fact: ConfirmedFactV3, process_kind: str) -> dict[str, Any]:
    evidence = _evidence(fact.fact_code)
    extra = [
        {
            "fieldId": "oa.processKind",
            "role": "filter",
            "logicalName": "OA process kind",
            "dataType": "string",
            "required": True,
            "evidenceIds": evidence,
        }
    ]
    payload = _default_query(fact, FactKind.EXISTS, extra)
    payload["filters"]["items"] = [
        _literal_filter("oa-process-kind", "oa.processKind", "eq", process_kind, evidence)
    ]
    return payload


def _sequencing_query(fact: ConfirmedFactV3) -> dict[str, Any]:
    evidence = _evidence(fact.fact_code)
    extra = [
        {
            "fieldId": "service.isSequencing",
            "role": "filter",
            "logicalName": "Sequencing service flag",
            "dataType": "boolean",
            "required": True,
            "evidenceIds": evidence,
        },
        {
            "fieldId": "service.completedQuantity",
            "role": "filter",
            "logicalName": "Completed quantity",
            "dataType": "number",
            "required": True,
            "evidenceIds": evidence,
        },
        {
            "fieldId": "service.requestedQuantity",
            "role": "filter",
            "logicalName": "Requested quantity",
            "dataType": "number",
            "required": True,
            "evidenceIds": evidence,
        },
    ]
    payload = _default_query(fact, FactKind.EXISTS, extra)
    payload["filters"]["items"] = [
        _literal_filter("sequencing-service", "service.isSequencing", "eq", True, evidence)
    ]
    return payload


def build_query_for_fact(fact: ConfirmedFactV3, *, rule_set: str) -> dict[str, Any]:
    kinds = REPORT_FACT_KINDS if rule_set == "report" else DATA_FACT_KINDS
    kind = kinds.get(fact.fact_code, FactKind.SOURCE)
    if fact.fact_code == "release.special_application_count":
        application_type = (
            REPORT_SPECIAL_APPLICATION_TYPE
            if rule_set == "report"
            else DATA_SPECIAL_APPLICATION_TYPE
        )
        return _special_application_query(fact, application_type)
    if fact.fact_code == "report.merge_group_member_ids":
        evidence = _evidence(fact.fact_code)
        return _set_query(
            fact,
            [
                {
                    "fieldId": "relationship.kind",
                    "role": "filter",
                    "logicalName": "Related merge-report membership",
                    "dataType": "string",
                    "required": True,
                    "evidenceIds": evidence,
                },
                {
                    "fieldId": "member.taskId",
                    "role": "filter",
                    "logicalName": "Related member task key",
                    "dataType": "string",
                    "required": True,
                    "evidenceIds": evidence,
                },
            ],
            [
                _literal_filter(
                    "merge-related",
                    "relationship.kind",
                    "eq",
                    "mergeReportRelated",
                    evidence,
                ),
                _parameter_filter("exclude-self", "member.taskId", "ne", "taskId", evidence),
            ],
        )
    if fact.fact_code == "order.seal_scope_contract_ids":
        evidence = _evidence(fact.fact_code)
        return _set_query(
            fact,
            [
                {
                    "fieldId": "contract.inSealScope",
                    "role": "filter",
                    "logicalName": "Execution contract or remaining amount greater than 0",
                    "dataType": "boolean",
                    "required": True,
                    "evidenceIds": evidence,
                },
                {
                    "fieldId": "contract.remainingAmount",
                    "role": "filter",
                    "logicalName": "Remaining contract amount",
                    "dataType": "money",
                    "required": False,
                    "evidenceIds": evidence,
                },
                {
                    "fieldId": "contract.isExecutionContract",
                    "role": "filter",
                    "logicalName": "Execution contract flag",
                    "dataType": "boolean",
                    "required": False,
                    "evidenceIds": evidence,
                },
            ],
            [
                _literal_filter("in-seal-scope", "contract.inSealScope", "eq", True, evidence),
            ],
        )
    if fact.fact_code == "task.in_project_report_release_oa":
        return _oa_query(fact, "projectReportRelease")
    if fact.fact_code == "task.in_raw_data_release_oa":
        return _oa_query(fact, "rawDataRelease")
    if fact.fact_code == "order.sequencing_services_complete":
        return _sequencing_query(fact)
    return _default_query(fact, kind)
