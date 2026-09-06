"""Immutable RuleParseResult 3.0 contract and the Agent 2 fact-request exporter."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.bindings_v3 import (
    BindableFactV3,
    BindingScalarV3,
    FactBindingRequestV3,
    ProvenanceV3,
    QueryRequirementsV3,
    UncertaintyV3,
)
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.v3 import RuleOutcomeV3, RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import validate_rule_structure_candidate_v3

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from rule_reader.domain.rules.bindings_v3 import FactUsageV3

RULE_PARSE_RESULT_SCHEMA_VERSION = "3.0.0"
RULE_PARSE_RESULT_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RULE_PARSE_RESULT_SCHEMA_ID_V3 = "urn:rulereader:rule-parse-result:3.0.0"
_RULE_VERSION_PATTERN = re.compile(
    r"^(?P<ruleSetId>[A-Z][A-Z0-9_]*)@"
    r"(?P<timestamp>\d{8}T\d{6}(?:\d{6})?Z)-"
    r"(?P<sourceSha12>[0-9a-f]{12})-"
    r"(?P<catalogDigest12>[0-9a-f]{12})$"
)


class ResultModelV3(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ParserProvenanceV3(ResultModelV3):
    parser_version: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=120)
    provider: Literal["deepseek", "reviewed_import"]
    model: str = Field(min_length=1, max_length=160)


class CatalogRefV3(ResultModelV3):
    catalog_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    catalog_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=120)
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateRefV3(ResultModelV3):
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_block_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FactDeclarationV3(ResultModelV3):
    fact: BindableFactV3
    query: QueryRequirementsV3
    uncertainties: list[UncertaintyV3] = Field(default_factory=list)


class TestCaseV3(ResultModelV3):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    description: str = Field(min_length=1, max_length=500)
    given: dict[str, BindingScalarV3 | list[BindingScalarV3] | None]
    expected_outcome: RuleOutcomeV3
    expected_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    expected_matched_rule_codes: list[str]


class RuleParseResultV3(ResultModelV3):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="RuleParseResult 3.0.0",
        json_schema_extra={
            "$schema": RULE_PARSE_RESULT_SCHEMA_DIALECT,
            "$id": RULE_PARSE_RESULT_SCHEMA_ID_V3,
        },
    )

    schema_version: Literal["3.0.0"]
    rule_version: str = Field(min_length=1, max_length=260)
    rule_set_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    generated_at: datetime
    status: Literal["draft"]
    executable: Literal[False]
    source: ProvenanceV3
    parser: ParserProvenanceV3
    catalog_ref: CatalogRefV3
    candidate_ref: CandidateRefV3
    fact_declarations: list[FactDeclarationV3] = Field(min_length=1)
    test_cases: list[TestCaseV3] = Field(min_length=1)
    agent2_readiness_ready: bool

    @model_validator(mode="after")
    def validate_shape(self) -> RuleParseResultV3:
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
        if match.group("sourceSha12") != self.candidate_ref.rule_block_sha256[:12]:
            raise ValueError("ruleVersion sourceSha12 must close to the rule block SHA-256")
        if match.group("catalogDigest12") != self.catalog_ref.catalog_digest[:12]:
            raise ValueError("ruleVersion catalogDigest12 must close to the catalog digest")
        if (
            self.source.parser_version != self.parser.parser_version
            or self.source.prompt_version != self.parser.prompt_version
            or self.source.provider != self.parser.provider
            or self.source.model != self.parser.model
        ):
            raise ValueError("source and parser provenance must match")
        if self.source.source_sha256 != self.candidate_ref.rule_block_sha256:
            raise ValueError("source SHA-256 must match candidateRef rule block SHA-256")
        declarations = [item.fact.fact_code for item in self.fact_declarations]
        if len(declarations) != len(set(declarations)):
            raise ValueError("fact declarations must be unique")
        case_ids = [item.case_id for item in self.test_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("test case IDs must be unique")
        return self


def rule_parse_result_schema_v3() -> dict[str, object]:
    return RuleParseResultV3.model_json_schema(by_alias=True, mode="validation")


def canonical_result_payload_sha256_v3(payload: dict[str, object]) -> str:
    """Hash a payload with the same canonical JSON rules as the persistence plan."""

    import hashlib
    import json

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def candidate_payload_sha256_v3(candidate: RuleStructureCandidateV3) -> str:
    return canonical_result_payload_sha256_v3(candidate.model_dump(mode="json", by_alias=True))


def export_fact_binding_requests_v3(
    result: RuleParseResultV3,
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
) -> list[FactBindingRequestV3]:
    """Export one immutable Agent 2 request per non-derived declared fact.

    Raises when the candidate still carries blockers, the readiness conclusion is not
    ready, or the executed test cases do not reproduce their expectations.
    """

    if candidate.blocking_issues:
        raise ValueError("candidate still carries blocking issues; export is not allowed")
    if not result.agent2_readiness_ready:
        raise ValueError("agent2 readiness is not ready; export is not allowed")
    validate_rule_structure_candidate_v3(candidate, catalog)
    if result.rule_set_id != candidate.rule_set_id:
        raise ValueError("result ruleSetId does not match candidate")
    if (
        result.catalog_ref.catalog_id != catalog.catalog_id
        or result.catalog_ref.catalog_version != catalog.catalog_version
        or result.catalog_ref.catalog_digest != catalog.catalog_digest
    ):
        raise ValueError("result catalogRef does not match catalog")
    if result.candidate_ref.payload_sha256 != candidate_payload_sha256_v3(candidate):
        raise ValueError("result candidateRef payload hash does not match candidate")
    if result.candidate_ref.rule_block_sha256 != result.source.source_sha256:
        raise ValueError("result candidateRef source hash does not match provenance")
    declared_codes = {item.fact.fact_code for item in result.fact_declarations}
    if declared_codes != set(candidate.required_fact_codes):
        raise ValueError("fact declarations do not close to candidate requiredFactCodes")
    catalog_by_code = {fact.fact_code: fact for fact in catalog.facts}
    for declaration in result.fact_declarations:
        confirmed = catalog_by_code.get(declaration.fact.fact_code)
        if confirmed is None or (
            declaration.fact.name != confirmed.name
            or declaration.fact.description != confirmed.description
            or declaration.fact.data_type is not confirmed.data_type
            or declaration.fact.nullable != confirmed.nullable
            or declaration.fact.null_policy is not confirmed.null_policy
            or declaration.fact.grain != confirmed.grain
            or declaration.fact.allowed_values != confirmed.allowed_values
            or declaration.fact.unit != confirmed.unit
            or [
                (
                    item.name,
                    item.role,
                    item.data_type,
                    item.required,
                    item.description,
                )
                for item in declaration.fact.parameters
            ]
            != [
                (
                    item.name,
                    item.role,
                    item.data_type,
                    item.required,
                    item.description,
                )
                for item in confirmed.parameters
            ]
        ):
            raise ValueError(
                f"fact declaration {declaration.fact.fact_code} does not match catalog semantics"
            )
    _assert_test_cases_pass_v3(result, candidate, catalog)

    catalog_codes = {fact.fact_code for fact in catalog.facts}
    usages_by_fact = _usages_by_fact(candidate)
    requests: list[FactBindingRequestV3] = []
    for index, declaration in enumerate(result.fact_declarations):
        fact = declaration.fact
        if fact.fact_code not in catalog_codes:
            raise ValueError(f"declared fact {fact.fact_code} is missing from the catalog")
        usages = usages_by_fact.get(fact.fact_code)
        if not usages:
            raise ValueError(f"fact {fact.fact_code} has no active condition usages")
        examples = _examples_for_fact(result, fact.fact_code)
        if not examples:
            raise ValueError(f"fact {fact.fact_code} has no test case examples")
        evidence = _evidence_for_request(
            index,
            declaration,
            usages,
            examples,
            result.test_cases,
        )
        requests.append(
            FactBindingRequestV3.model_validate(
                {
                    "contractVersion": "3.0.0",
                    "status": "candidate",
                    "executable": False,
                    "requestId": f"{result.rule_version}#{fact.fact_code}",
                    "ruleRef": {
                        "ruleSetId": result.rule_set_id,
                        "ruleVersion": result.rule_version,
                        "schemaVersion": "3.0.0",
                        "sourceSha256": result.source.source_sha256,
                        "catalogDigest": result.catalog_ref.catalog_digest,
                        "candidatePayloadSha256": result.candidate_ref.payload_sha256,
                    },
                    "fact": fact.model_dump(mode="json", by_alias=True),
                    "queryRequirements": declaration.query.model_dump(mode="json", by_alias=True),
                    "usages": [
                        usage.model_dump(mode="json", by_alias=True)
                        for usage in usages_by_fact[fact.fact_code]
                    ],
                    "examples": examples,
                    "mappingCandidate": {
                        "factCode": fact.fact_code,
                        "mappingStatus": "unresolved",
                        "viewName": None,
                        "viewField": None,
                        "viewActive": None,
                        "reviewStatus": "candidate",
                        "note": "物理来源由 metadataReview 解析。",
                    },
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


def _usages_by_fact(candidate: RuleStructureCandidateV3) -> dict[str, list[FactUsageV3]]:
    from rule_reader.domain.rules.bindings_v3 import FactUsageV3

    usages: dict[str, list[FactUsageV3]] = {}
    for stage_index, stage in enumerate(candidate.stages):
        for rule_index, rule in enumerate(stage.rules):
            if rule.status.value != "active" or rule.when is None or rule.outcome is None:
                continue
            root_path = f"/stages/{stage_index}/rules/{rule_index}/when"
            for condition_id, fact_code, condition_path in _condition_fact_refs(
                rule.when,
                root_path,
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


def _condition_fact_refs(node: object, path: str) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    children = getattr(node, "children", []) or []
    operator = getattr(node, "operator", None)
    condition_id = getattr(node, "id", None)
    if operator is not None and condition_id:
        for expression in (getattr(node, "left", None), getattr(node, "right", None)):
            for fact_code in _expression_fact_codes(expression):
                refs.append((condition_id, fact_code, path))
    for index, child in enumerate(children):
        refs.extend(_condition_fact_refs(child, f"{path}/children/{index}"))
    return refs


def _expression_fact_codes(expression: object) -> set[str]:
    if expression is None:
        return set()
    codes = {str(code)} if (code := getattr(expression, "fact_code", None)) else set()
    for child in getattr(expression, "children", []) or []:
        codes |= _expression_fact_codes(child)
    return codes


def _examples_for_fact(
    result: RuleParseResultV3,
    fact_code: str,
) -> list[dict[str, object]]:
    from rule_reader.domain.rules.bindings_v3 import FactExampleV3

    examples: list[dict[str, object]] = []
    seen: set[tuple[object, str]] = set()
    for case in result.test_cases:
        if fact_code not in case.given:
            continue
        value = case.given[fact_code]
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
    declaration: FactDeclarationV3,
    usages: list[FactUsageV3],
    examples: list[dict[str, object]],
    test_cases: list[TestCaseV3],
) -> list[dict[str, object]]:
    from rule_reader.domain.rules.bindings_v3 import EvidenceKindV3, EvidenceV3

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
        usage_id = f"condition.{usage.condition_id}"
        items.append(
            {
                "evidenceId": usage_id,
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
    return [
        EvidenceV3.model_validate(item).model_dump(mode="json", by_alias=True) for item in items
    ]


def _assert_test_cases_pass_v3(
    result: RuleParseResultV3,
    candidate: RuleStructureCandidateV3,
    catalog: BusinessConfirmedFactCatalogV3,
) -> None:
    from rule_reader.domain.rules.validation_v3 import evaluate_rule_structure_v3

    for case in result.test_cases:
        evaluation = evaluate_rule_structure_v3(candidate, catalog, dict(case.given))
        if (
            evaluation.outcome is not case.expected_outcome
            or evaluation.reason_code != case.expected_reason_code
            or list(evaluation.matched_rule_codes) != case.expected_matched_rule_codes
        ):
            raise ValueError(
                f"test case {case.case_id} does not reproduce the recorded expectation"
            )


def utc_compact_timestamp_v3(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def build_rule_version_v3(
    rule_set_id: str,
    generated_at: datetime,
    source_sha256: str,
    catalog_digest: str,
) -> str:
    timestamp = utc_compact_timestamp_v3(generated_at)
    return f"{rule_set_id}@{timestamp}-{source_sha256[:12]}-{catalog_digest[:12]}"
