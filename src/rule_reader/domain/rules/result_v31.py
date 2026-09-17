"""Immutable RuleParseResult 3.1.0 with dual source identity and complete delivery refs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.bindings_v2 import BindingMappingCandidateV2
from rule_reader.domain.rules.bindings_v3 import (
    BindableFactV3,
    BindingScalarV3,
    EvidenceKindV3,
    EvidenceV3,
    FactExampleV3,
    FactUsageV3,
    UncertaintyV3,
)
from rule_reader.domain.rules.bindings_v31 import (
    FactBindingRequestV31,
    ProvenanceV31,
    QueryRequirementsV31,
    ResultRequirementV31,
)
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.v3 import RuleOutcomeV3
from rule_reader.domain.rules.v31 import (
    ConditionNodeV31,
    ExpressionNodeV31,
    RuleStructureCandidateV31,
)
from rule_reader.domain.rules.validation_v31 import (
    evaluate_rule_structure_v31,
    validate_rule_structure_candidate_v31,
)

RULE_PARSE_RESULT_SCHEMA_VERSION = "3.1.0"
RULE_PARSE_RESULT_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RULE_PARSE_RESULT_SCHEMA_ID_V31 = "urn:rulereader:rule-parse-result:3.1.0"
_RULE_VERSION_PATTERN = re.compile(
    r"^(?P<ruleSetId>[A-Z][A-Z0-9_]*)@"
    r"(?P<timestamp>\d{8}T\d{6}(?:\d{6})?Z)-"
    r"(?P<sourceSha12>[0-9a-f]{12})-"
    r"(?P<catalogDigest12>[0-9a-f]{12})$"
)


class ResultModelV31(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ParserProvenanceV31(ResultModelV31):
    parser_version: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=120)
    provider: Literal["reviewed_import"]
    model: str = Field(min_length=1, max_length=160)


class CatalogRefV31(ResultModelV31):
    catalog_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    catalog_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=120)
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateRefV31(ResultModelV31):
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FactDeclarationV31(ResultModelV31):
    fact: BindableFactV3
    query: QueryRequirementsV31
    uncertainties: list[UncertaintyV3] = Field(default_factory=list)


class MemberSnapshotV31(ResultModelV31):
    member_key: str = Field(min_length=1, max_length=160)
    facts: dict[str, BindingScalarV3 | list[BindingScalarV3] | None]


class TestCaseV31(ResultModelV31):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    description: str = Field(min_length=1, max_length=500)
    given: dict[str, BindingScalarV3 | list[BindingScalarV3] | None]
    runtime: dict[str, BindingScalarV3] = Field(default_factory=dict)
    members: list[MemberSnapshotV31] = Field(default_factory=list)
    expected_outcome: RuleOutcomeV3
    expected_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    expected_matched_rule_codes: list[str]


class CompleteDeliveryRefV31(ResultModelV31):
    catalog_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    purpose: Literal["optimization-plan-generation"]


class RuleParseResultV31(ResultModelV31):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="RuleParseResult 3.1.0",
        json_schema_extra={
            "$schema": RULE_PARSE_RESULT_SCHEMA_DIALECT,
            "$id": RULE_PARSE_RESULT_SCHEMA_ID_V31,
        },
    )

    schema_version: Literal["3.1.0"]
    rule_version: str = Field(min_length=1, max_length=260)
    rule_set_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    generated_at: datetime
    status: Literal["draft"]
    executable: Literal[False]
    source: ProvenanceV31
    parser: ParserProvenanceV31
    catalog_ref: CatalogRefV31
    candidate_ref: CandidateRefV31
    delivery_ref: CompleteDeliveryRefV31
    fact_declarations: list[FactDeclarationV31] = Field(min_length=1)
    test_cases: list[TestCaseV31] = Field(min_length=1)
    agent2_readiness_ready: bool

    @model_validator(mode="after")
    def validate_shape(self) -> RuleParseResultV31:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generatedAt requires a timezone")
        match = _RULE_VERSION_PATTERN.fullmatch(self.rule_version)
        if match is None:
            raise ValueError("ruleVersion must be <ruleSetId>@<UTC>-<sourceSha12>-<catalog12>")
        if match.group("ruleSetId") != self.rule_set_id:
            raise ValueError("ruleVersion ruleSetId must match ruleSetId")
        expected_timestamp = self.generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        if match.group("timestamp") != expected_timestamp:
            raise ValueError("ruleVersion timestamp must match generatedAt")
        if match.group("sourceSha12") != self.source.source_sha256[:12]:
            raise ValueError("ruleVersion sourceSha12 must close to the source file SHA-256")
        if match.group("catalogDigest12") != self.catalog_ref.catalog_digest[:12]:
            raise ValueError("ruleVersion catalogDigest12 must close to the catalog digest")
        if self.source.source_sha256 == self.source.parse_input_sha256:
            raise ValueError("source file hash must not equal parse input hash")
        if self.candidate_ref.parse_input_sha256 != self.source.parse_input_sha256:
            raise ValueError("candidateRef parse input hash must match provenance")
        if (
            self.source.parser_version != self.parser.parser_version
            or self.source.prompt_version != self.parser.prompt_version
            or self.source.provider != self.parser.provider
            or self.source.model != self.parser.model
        ):
            raise ValueError("source and parser provenance must match")
        if self.delivery_ref.catalog_payload_sha256 != self.catalog_ref.payload_sha256:
            raise ValueError("deliveryRef catalog hash must match catalogRef")
        if self.delivery_ref.candidate_payload_sha256 != self.candidate_ref.payload_sha256:
            raise ValueError("deliveryRef candidate hash must match candidateRef")
        declarations = [item.fact.fact_code for item in self.fact_declarations]
        if len(declarations) != len(set(declarations)):
            raise ValueError("fact declarations must be unique")
        case_ids = [item.case_id for item in self.test_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("test case IDs must be unique")
        return self


def canonical_payload_sha256_v31(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def candidate_payload_sha256_v31(candidate: RuleStructureCandidateV31) -> str:
    return canonical_payload_sha256_v31(candidate.model_dump(mode="json", by_alias=True))


def catalog_payload_sha256_v31(catalog: BusinessConfirmedFactCatalogV3) -> str:
    return canonical_payload_sha256_v31(catalog.model_dump(mode="json", by_alias=True))


def utc_compact_timestamp_v31(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def build_rule_version_v31(
    rule_set_id: str,
    generated_at: datetime,
    source_file_sha256: str,
    catalog_digest: str,
) -> str:
    timestamp = utc_compact_timestamp_v31(generated_at)
    return f"{rule_set_id}@{timestamp}-{source_file_sha256[:12]}-{catalog_digest[:12]}"


def rule_parse_result_schema_v31() -> dict[str, object]:
    return RuleParseResultV31.model_json_schema(by_alias=True, mode="validation")


def export_fact_binding_requests_v31(
    result: RuleParseResultV31,
    candidate: RuleStructureCandidateV31,
    catalog: BusinessConfirmedFactCatalogV3,
) -> list[FactBindingRequestV31]:
    if candidate.blocking_issues:
        raise ValueError("candidate still carries blocking issues; export is not allowed")
    if not result.agent2_readiness_ready:
        raise ValueError("agent2 readiness is not ready; export is not allowed")
    validate_rule_structure_candidate_v31(candidate, catalog)
    if result.rule_set_id != candidate.rule_set_id:
        raise ValueError("result ruleSetId does not match candidate")
    if result.catalog_ref.catalog_digest != catalog.catalog_digest:
        raise ValueError("result catalogRef does not match catalog")
    if result.candidate_ref.payload_sha256 != candidate_payload_sha256_v31(candidate):
        raise ValueError("result candidateRef payload hash does not match candidate")
    if result.candidate_ref.parse_input_sha256 != candidate.source_identity.parse_input_sha256:
        raise ValueError("result parse input hash does not match candidate identity")
    if result.source.source_sha256 != candidate.source_identity.source_file_sha256:
        raise ValueError("result source file hash does not match candidate identity")
    _assert_test_cases_pass_v31(result, candidate, catalog)
    usages_by_fact = _usages_by_fact(candidate)
    requests: list[FactBindingRequestV31] = []
    for index, declaration in enumerate(result.fact_declarations):
        fact = declaration.fact
        usages = usages_by_fact.get(fact.fact_code)
        if not usages:
            raise ValueError(f"fact {fact.fact_code} has no active condition usages")
        examples = _examples_for_fact(result, fact.fact_code)
        if not examples:
            raise ValueError(f"fact {fact.fact_code} has no test case examples")
        evidence = _evidence_for_request(index, declaration, usages, examples, result.test_cases)
        cardinality = "set" if fact.data_type.value == "list" else "scalar"
        query_payload = declaration.query.model_dump(mode="json", by_alias=True)
        query_payload["result"] = ResultRequirementV31.model_validate(
            {
                "columnName": "fact_value",
                "dataType": fact.data_type.value,
                "cardinality": cardinality,
                "nullable": fact.nullable,
                "nullPolicy": fact.null_policy.value,
                "unit": fact.unit,
            }
        ).model_dump(mode="json", by_alias=True)
        requests.append(
            FactBindingRequestV31.model_validate(
                {
                    "contractVersion": "3.1.0",
                    "status": "candidate",
                    "executable": False,
                    "requestId": f"{result.rule_version}#{fact.fact_code}",
                    "ruleRef": {
                        "ruleSetId": result.rule_set_id,
                        "ruleVersion": result.rule_version,
                        "schemaVersion": "3.1.0",
                        "sourceSha256": result.source.source_sha256,
                        "parseInputSha256": result.source.parse_input_sha256,
                        "catalogDigest": result.catalog_ref.catalog_digest,
                        "candidatePayloadSha256": result.candidate_ref.payload_sha256,
                    },
                    "fact": fact.model_dump(mode="json", by_alias=True),
                    "queryRequirements": query_payload,
                    "usages": [usage.model_dump(mode="json", by_alias=True) for usage in usages],
                    "examples": examples,
                    "mappingCandidate": BindingMappingCandidateV2.model_validate(
                        {
                            "factCode": fact.fact_code,
                            "mappingStatus": "unresolved",
                            "viewName": None,
                            "viewField": None,
                            "viewActive": None,
                            "reviewStatus": "candidate",
                            "note": "Physical source is resolved by metadataReview.",
                        }
                    ).model_dump(mode="json", by_alias=True),
                    "provenance": result.source.model_dump(mode="json", by_alias=True),
                    "evidence": evidence,
                    "uncertainties": [
                        item.model_dump(mode="json", by_alias=True)
                        for item in declaration.uncertainties
                    ],
                    "targetDialect": "sqlserver",
                    "requiresMetadataSnapshot": True,
                    "tempTableAllowed": False,
                }
            )
        )
    return requests


def _assert_test_cases_pass_v31(
    result: RuleParseResultV31,
    candidate: RuleStructureCandidateV31,
    catalog: BusinessConfirmedFactCatalogV3,
) -> None:
    for case in result.test_cases:
        member_map = {item.member_key: dict(item.facts) for item in case.members}
        evaluation = evaluate_rule_structure_v31(
            candidate,
            catalog,
            dict(case.given),
            runtime=dict(case.runtime),
            members=member_map,
        )
        if (
            evaluation.outcome is not case.expected_outcome
            or evaluation.reason_code != case.expected_reason_code
            or list(evaluation.matched_rule_codes) != case.expected_matched_rule_codes
        ):
            raise ValueError(
                f"test case {case.case_id} does not reproduce the recorded expectation"
            )


def _usages_by_fact(candidate: RuleStructureCandidateV31) -> dict[str, list[FactUsageV3]]:
    usages: dict[str, list[FactUsageV3]] = {}
    for stage_index, stage in enumerate(candidate.stages):
        for rule_index, rule in enumerate(stage.rules):
            if rule.status.value != "active" or rule.when is None or rule.outcome is None:
                continue
            root_path = f"/stages/{stage_index}/rules/{rule_index}/when"
            for condition_id, fact_code, condition_path in _condition_fact_refs(
                rule.when, root_path
            ):
                usages.setdefault(fact_code, []).append(
                    FactUsageV3.model_validate(
                        {
                            "stage": stage.stage.value,
                            "ruleCode": rule.rule_code,
                            "priority": rule.priority,
                            "conditionId": condition_id,
                            "conditionPath": condition_path,
                            "outcome": rule.outcome.value,
                            "evidenceIds": [f"condition.{condition_id}"],
                        }
                    )
                )
    if not usages:
        raise ValueError("candidate has no active condition usages")
    return usages


def _condition_fact_refs(node: ConditionNodeV31, path: str) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    if node.collection_fact_code:
        refs.append((node.id, node.collection_fact_code, path))
    for expression in (node.left, node.right):
        for fact_code in _expression_fact_codes(expression):
            refs.append((node.id, fact_code, path))
    for index, child in enumerate(node.children):
        refs.extend(_condition_fact_refs(child, f"{path}/children/{index}"))
    if node.already_satisfied is not None:
        refs.extend(_condition_fact_refs(node.already_satisfied, f"{path}/alreadySatisfied"))
    if node.member_predicate is not None:
        refs.extend(_condition_fact_refs(node.member_predicate, f"{path}/memberPredicate"))
    return refs


def _expression_fact_codes(expression: ExpressionNodeV31 | None) -> set[str]:
    if expression is None:
        return set()
    codes = {expression.fact_code} if expression.fact_code else set()
    for child in expression.children:
        codes |= _expression_fact_codes(child)
    return {code for code in codes if code}


def _examples_for_fact(result: RuleParseResultV31, fact_code: str) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    seen: set[tuple[object, str]] = set()
    for case in result.test_cases:
        values: list[object] = []
        if fact_code in case.given:
            values.append(case.given[fact_code])
        for member in case.members:
            if fact_code in member.facts:
                values.append(member.facts[fact_code])
        if not values:
            continue
        value = values[0]
        key = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            case.expected_outcome.value,
        )
        if key in seen:
            continue
        seen.add(key)
        examples.append(
            FactExampleV3.model_validate(
                {
                    "exampleId": f"case-{case.case_id}",
                    "value": value,
                    "expectedOutcome": case.expected_outcome.value,
                    "evidenceIds": [f"case-{case.case_id}"],
                }
            ).model_dump(mode="json", by_alias=True)
        )
    return examples


def _evidence_for_request(
    declaration_index: int,
    declaration: FactDeclarationV31,
    usages: list[FactUsageV3],
    examples: list[dict[str, object]],
    test_cases: list[TestCaseV31],
) -> list[dict[str, object]]:
    fact_code = declaration.fact.fact_code
    items: list[dict[str, object]] = [
        {
            "evidenceId": f"fact.{fact_code}",
            "kind": EvidenceKindV3.FACT.value,
            "sourceDocument": "ruleResult",
            "sourcePath": f"/factDeclarations/{declaration_index}",
        },
        {
            "evidenceId": f"query.{fact_code}",
            "kind": EvidenceKindV3.QUERY.value,
            "sourceDocument": "ruleResult",
            "sourcePath": f"/factDeclarations/{declaration_index}/query",
        },
    ]
    for usage in usages:
        items.append(
            {
                "evidenceId": f"condition.{usage.condition_id}",
                "kind": EvidenceKindV3.CONDITION.value,
                "sourceDocument": "candidate",
                "sourcePath": usage.condition_path,
            }
        )
    for example in examples:
        case_id = str(example["exampleId"]).removeprefix("case-")
        case_index = next(index for index, case in enumerate(test_cases) if case.case_id == case_id)
        items.append(
            {
                "evidenceId": f"case-{case_id}",
                "kind": EvidenceKindV3.EXAMPLE.value,
                "sourceDocument": "ruleResult",
                "sourcePath": f"/testCases/{case_index}",
            }
        )
    unique: dict[str, dict[str, object]] = {}
    for item in items:
        unique[str(item["evidenceId"])] = item
    return [
        EvidenceV3.model_validate(item).model_dump(mode="json", by_alias=True)
        for item in unique.values()
    ]
