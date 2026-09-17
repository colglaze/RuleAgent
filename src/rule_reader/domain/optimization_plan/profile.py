"""Assemble complete 3.1.0 optimization-plan deliveries from frozen trees and catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from rule_reader.domain.optimization_plan import (
    DATA_RULE_SET_ID,
    EXTRACTED_SECTIONS,
    EXTRACTOR_VERSION,
    GENERATED_AT_ISO,
    OPTIMIZATION_PLAN_RELATIVE_PATH,
    PARSER_MODEL,
    PARSER_VERSION,
    PROMPT_VERSION,
    REPORT_RULE_SET_ID,
)
from rule_reader.domain.optimization_plan.cases import data_test_cases, report_test_cases
from rule_reader.domain.optimization_plan.catalogs import (
    DATA_FACT_KINDS,
    REPORT_FACT_KINDS,
    build_data_catalog,
    build_report_catalog,
)
from rule_reader.domain.optimization_plan.data_tree import build_data_candidate_payload
from rule_reader.domain.optimization_plan.queries import build_query_for_fact
from rule_reader.domain.optimization_plan.report_tree import build_report_candidate_payload
from rule_reader.domain.rules.bindings_v31 import FactBindingRequestV31, QueryRequirementsV31
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.result_v31 import (
    RuleParseResultV31,
    build_rule_version_v31,
    candidate_payload_sha256_v31,
    catalog_payload_sha256_v31,
    export_fact_binding_requests_v31,
)
from rule_reader.domain.rules.v2 import FactKind
from rule_reader.domain.rules.v31 import RuleStructureCandidateV31, SourceIdentityV31
from rule_reader.domain.rules.validation_v31 import validate_rule_structure_candidate_v31

RuleSetKind = Literal["report", "data"]


@dataclass(frozen=True, slots=True)
class OptimizationPlanDelivery:
    kind: RuleSetKind
    catalog: BusinessConfirmedFactCatalogV3
    candidate: RuleStructureCandidateV31
    result: RuleParseResultV31
    requests: tuple[FactBindingRequestV31, ...]


def _generated_at() -> datetime:
    return datetime.fromisoformat(GENERATED_AT_ISO)


def _identity_payload(identity: SourceIdentityV31) -> dict[str, Any]:
    return identity.model_dump(mode="json", by_alias=True)


def _bindable_fact(fact: Any, kind: FactKind) -> dict[str, Any]:
    return {
        "factCode": fact.fact_code,
        "name": fact.name,
        "factKind": kind.value,
        "dataType": fact.data_type.value,
        "description": fact.description,
        "nullable": fact.nullable,
        "nullPolicy": fact.null_policy.value,
        "grain": fact.grain,
        "parameters": [
            {
                "name": parameter.name,
                "role": parameter.role.value,
                "dataType": parameter.data_type.value,
                "required": parameter.required,
                "description": parameter.description,
            }
            for parameter in fact.parameters
        ],
        "unit": fact.unit,
        "allowedValues": list(fact.allowed_values),
    }


def _declarations(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV31,
    kinds: dict[str, FactKind],
    rule_set: RuleSetKind,
) -> list[dict[str, Any]]:
    by_code = {fact.fact_code: fact for fact in catalog.facts}
    declarations: list[dict[str, Any]] = []
    for code in candidate.required_fact_codes:
        fact = by_code[code]
        declarations.append(
            {
                "fact": _bindable_fact(fact, kinds.get(code, FactKind.SOURCE)),
                "query": QueryRequirementsV31.model_validate(
                    build_query_for_fact(fact, rule_set=rule_set)
                ).model_dump(mode="json", by_alias=True),
                "uncertainties": [],
            }
        )
    return declarations


def _source_payload(identity: SourceIdentityV31) -> dict[str, Any]:
    return {
        "sourceName": "optimization-plan-v2.0",
        "relativePath": OPTIMIZATION_PLAN_RELATIVE_PATH,
        "sourceSha256": identity.source_file_sha256,
        "parseInputSha256": identity.parse_input_sha256,
        "sourceFileByteLength": identity.source_file_byte_length,
        "parseInputCharacterCount": identity.parse_input_character_count,
        "extractorVersion": identity.extractor_version,
        "extractedSections": list(identity.extracted_sections),
        "parserVersion": PARSER_VERSION,
        "promptVersion": PROMPT_VERSION,
        "provider": "reviewed_import",
        "model": PARSER_MODEL,
    }


def _build_result(
    *,
    kind: RuleSetKind,
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV31,
    identity: SourceIdentityV31,
    test_cases: list[dict[str, Any]],
) -> RuleParseResultV31:
    generated_at = _generated_at()
    catalog_sha = catalog_payload_sha256_v31(catalog)
    candidate_sha = candidate_payload_sha256_v31(candidate)
    rule_set_id = REPORT_RULE_SET_ID if kind == "report" else DATA_RULE_SET_ID
    kinds = REPORT_FACT_KINDS if kind == "report" else DATA_FACT_KINDS
    payload = {
        "schemaVersion": "3.1.0",
        "ruleVersion": build_rule_version_v31(
            rule_set_id,
            generated_at,
            identity.source_file_sha256,
            catalog.catalog_digest,
        ),
        "ruleSetId": rule_set_id,
        "generatedAt": generated_at.isoformat(),
        "status": "draft",
        "executable": False,
        "source": _source_payload(identity),
        "parser": {
            "parserVersion": PARSER_VERSION,
            "promptVersion": PROMPT_VERSION,
            "provider": "reviewed_import",
            "model": PARSER_MODEL,
        },
        "catalogRef": {
            "catalogId": catalog.catalog_id,
            "catalogVersion": catalog.catalog_version,
            "catalogDigest": catalog.catalog_digest,
            "payloadSha256": catalog_sha,
        },
        "candidateRef": {
            "payloadSha256": candidate_sha,
            "parseInputSha256": identity.parse_input_sha256,
        },
        "deliveryRef": {
            "catalogPayloadSha256": catalog_sha,
            "candidatePayloadSha256": candidate_sha,
            "resultPayloadSha256": None,
            "purpose": "optimization-plan-generation",
        },
        "factDeclarations": _declarations(catalog, candidate, kinds, kind),
        "testCases": test_cases,
        "agent2ReadinessReady": True,
    }
    return RuleParseResultV31.model_validate(payload)


def build_delivery(kind: RuleSetKind, identity: SourceIdentityV31) -> OptimizationPlanDelivery:
    if identity.extractor_version != EXTRACTOR_VERSION:
        raise ValueError("extractor version does not match the frozen optimization-plan extractor")
    if tuple(identity.extracted_sections) != EXTRACTED_SECTIONS:
        raise ValueError("extracted sections do not match the frozen optimization-plan sections")
    identity_payload = _identity_payload(identity)
    if kind == "report":
        catalog = build_report_catalog(source_file_sha256=identity.source_file_sha256)
        candidate = RuleStructureCandidateV31.model_validate(
            build_report_candidate_payload(catalog.catalog_digest, identity_payload)
        )
        cases = report_test_cases()
    else:
        catalog = build_data_catalog(source_file_sha256=identity.source_file_sha256)
        candidate = RuleStructureCandidateV31.model_validate(
            build_data_candidate_payload(catalog.catalog_digest, identity_payload)
        )
        cases = data_test_cases()
    validate_rule_structure_candidate_v31(candidate, catalog)
    result = _build_result(
        kind=kind,
        catalog=catalog,
        candidate=candidate,
        identity=identity,
        test_cases=cases,
    )
    requests = tuple(export_fact_binding_requests_v31(result, candidate, catalog))
    return OptimizationPlanDelivery(
        kind=kind,
        catalog=catalog,
        candidate=candidate,
        result=result,
        requests=requests,
    )


def build_report_delivery(identity: SourceIdentityV31) -> OptimizationPlanDelivery:
    return build_delivery("report", identity)


def build_data_delivery(identity: SourceIdentityV31) -> OptimizationPlanDelivery:
    return build_delivery("data", identity)


def build_both_deliveries(
    identity: SourceIdentityV31,
) -> tuple[OptimizationPlanDelivery, OptimizationPlanDelivery]:
    return build_report_delivery(identity), build_data_delivery(identity)
