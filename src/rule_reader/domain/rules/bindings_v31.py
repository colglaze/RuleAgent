"""Fact-binding request 3.1.0: set cardinality and dual source hashes."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.bindings_v2 import BindingMappingCandidateV2
from rule_reader.domain.rules.bindings_v3 import (
    BindableFactV3,
    EvidenceV3,
    FactExampleV3,
    FactUsageV3,
    QueryRequirementsV3,
    UncertaintyV3,
)
from rule_reader.domain.rules.models import FactDataType
from rule_reader.domain.rules.v2 import ContractModelV2, NullPolicy

FACT_BINDING_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
FACT_BINDING_SCHEMA_ID_V31 = "urn:rulereader:fact-binding-request:3.1.0"


class ResultRequirementV31(ContractModelV2):
    column_name: Literal["fact_value"]
    data_type: FactDataType
    cardinality: Literal["scalar", "set"]
    nullable: bool
    null_policy: NullPolicy
    unit: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_cardinality(self) -> ResultRequirementV31:
        if self.cardinality == "set" and self.data_type is not FactDataType.LIST:
            raise ValueError("set cardinality requires list dataType")
        if self.cardinality == "scalar" and self.data_type is FactDataType.LIST:
            raise ValueError("scalar cardinality cannot use list dataType")
        return self


class QueryRequirementsV31(QueryRequirementsV3):
    result: ResultRequirementV31  # type: ignore[assignment]


class RuleRefV31(ContractModelV2):
    rule_set_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    rule_version: str = Field(min_length=1, max_length=260)
    schema_version: Literal["3.1.0"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProvenanceV31(ContractModelV2):
    source_name: str = Field(min_length=1, max_length=255)
    relative_path: str | None = Field(default=None, max_length=1_000)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_file_byte_length: int = Field(ge=1)
    parse_input_character_count: int = Field(ge=1)
    extractor_version: str = Field(min_length=1, max_length=80)
    extracted_sections: list[str] = Field(min_length=1)
    parser_version: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=120)
    provider: Literal["reviewed_import"]
    model: str = Field(min_length=1, max_length=160)


class FactBindingRequestV31(ContractModelV2):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="FactBindingRequest 3.1.0",
        json_schema_extra={
            "$schema": FACT_BINDING_SCHEMA_DIALECT,
            "$id": FACT_BINDING_SCHEMA_ID_V31,
        },
    )

    contract_version: Literal["3.1.0"]
    status: Literal["candidate"]
    executable: Literal[False]
    request_id: str = Field(min_length=3, max_length=420)
    rule_ref: RuleRefV31
    fact: BindableFactV3
    query_requirements: QueryRequirementsV31
    usages: list[FactUsageV3] = Field(min_length=1)
    examples: list[FactExampleV3] = Field(min_length=1)
    mapping_candidate: BindingMappingCandidateV2
    provenance: ProvenanceV31
    evidence: list[EvidenceV3] = Field(min_length=1)
    uncertainties: list[UncertaintyV3]
    target_dialect: Literal["sqlserver"]
    requires_metadata_snapshot: Literal[True]
    temp_table_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_closure(self) -> FactBindingRequestV31:
        if self.request_id != f"{self.rule_ref.rule_version}#{self.fact.fact_code}":
            raise ValueError("requestId must equal ruleVersion#factCode")
        if self.mapping_candidate.fact_code != self.fact.fact_code:
            raise ValueError("mappingCandidate factCode must match fact")
        if self.query_requirements.result.data_type is not self.fact.data_type:
            raise ValueError("result dataType must match fact")
        if self.provenance.source_sha256 != self.rule_ref.source_sha256:
            raise ValueError("provenance sourceSha256 must match ruleRef")
        if self.provenance.parse_input_sha256 != self.rule_ref.parse_input_sha256:
            raise ValueError("provenance parseInputSha256 must match ruleRef")
        if not self.rule_ref.rule_version.startswith(f"{self.rule_ref.rule_set_id}@"):
            raise ValueError("ruleVersion must belong to ruleSetId")
        if self.query_requirements.entity.grain != self.fact.grain:
            raise ValueError("query entity grain must match fact grain")
        if (
            self.query_requirements.result.nullable != self.fact.nullable
            or self.query_requirements.result.null_policy is not self.fact.null_policy
            or self.query_requirements.result.unit != self.fact.unit
        ):
            raise ValueError("result null and unit contract must match fact")
        return self


def fact_binding_request_schema_v31() -> dict[str, object]:
    return FactBindingRequestV31.model_json_schema(by_alias=True, mode="validation")
