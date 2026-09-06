"""Business-confirmed logical fact catalog for Rule Schema 3.0."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.models import FactDataType
from rule_reader.domain.rules.v2 import NullPolicy

FACT_CATALOG_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
FACT_CATALOG_SCHEMA_ID_V3 = "urn:rulereader:business-confirmed-fact-catalog:3.0.0"


class CatalogModelV3(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class FactParameterRoleV3(StrEnum):
    ENTITY_KEY = "entityKey"
    FILTER = "filter"
    TIME_ANCHOR = "timeAnchor"


class FactEvidenceV3(CatalogModelV3):
    evidence_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=160)
    source_kind: Literal["businessConfirmation", "ruleText", "viewDefinition"]
    source_id: str = Field(min_length=1, max_length=240)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=300)
    note: str = Field(min_length=1, max_length=1_000)


class FactParameterV3(CatalogModelV3):
    name: str = Field(pattern=r"^[a-z][A-Za-z0-9]*$", max_length=100)
    role: FactParameterRoleV3
    data_type: FactDataType
    required: bool = True
    description: str = Field(min_length=1, max_length=1_000)


class ConfirmedFactV3(CatalogModelV3):
    fact_code: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=160)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    data_type: FactDataType
    nullable: bool
    null_policy: NullPolicy
    grain: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    parameters: list[FactParameterV3] = Field(min_length=1)
    allowed_values: list[str | int | float | bool] = Field(default_factory=list)
    unit: str | None = Field(default=None, max_length=80)
    evidence_refs: list[str] = Field(min_length=1)
    binding_profile_ref: str | None = Field(default=None, max_length=240)
    binding_issues: list[str] = Field(default_factory=list)


class BusinessConfirmedFactCatalogV3(CatalogModelV3):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="BusinessConfirmedFactCatalog 3.0.0",
        json_schema_extra={
            "$schema": FACT_CATALOG_SCHEMA_DIALECT,
            "$id": FACT_CATALOG_SCHEMA_ID_V3,
        },
    )

    contract_version: Literal["3.0.0"]
    catalog_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    catalog_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=120)
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    facts: list[ConfirmedFactV3] = Field(min_length=1)
    evidence: list[FactEvidenceV3] = Field(min_length=1)


class FactCatalogValidationErrorV3(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)


def catalog_digest_v3(value: BusinessConfirmedFactCatalogV3 | dict[str, Any]) -> str:
    """Return the canonical digest, excluding the self-referential digest field."""

    if isinstance(value, BusinessConfirmedFactCatalogV3):
        payload = value.model_dump(mode="json", by_alias=True)
    else:
        payload = dict(value)
    payload.pop("catalogDigest", None)
    payload.pop("catalog_digest", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_fact_catalog_v3(catalog: BusinessConfirmedFactCatalogV3) -> None:
    issues: list[str] = []
    fact_codes = [fact.fact_code for fact in catalog.facts]
    duplicate_facts = sorted(code for code, count in Counter(fact_codes).items() if count > 1)
    if duplicate_facts:
        issues.append(f"duplicate fact codes: {duplicate_facts}")
    evidence_ids = [item.evidence_id for item in catalog.evidence]
    duplicate_evidence = sorted(code for code, count in Counter(evidence_ids).items() if count > 1)
    if duplicate_evidence:
        issues.append(f"duplicate evidence ids: {duplicate_evidence}")
    known_evidence = set(evidence_ids)
    for fact in catalog.facts:
        parameter_names = [parameter.name for parameter in fact.parameters]
        duplicate_parameters = sorted(
            name for name, count in Counter(parameter_names).items() if count > 1
        )
        if duplicate_parameters:
            issues.append(f"fact {fact.fact_code} has duplicate parameters: {duplicate_parameters}")
        if len(fact.evidence_refs) != len(set(fact.evidence_refs)):
            issues.append(f"fact {fact.fact_code} has duplicate evidenceRefs")
        unknown = sorted(set(fact.evidence_refs) - known_evidence)
        if unknown:
            issues.append(f"fact {fact.fact_code} references unknown evidence: {unknown}")
        if fact.binding_profile_ref is None and not fact.binding_issues:
            issues.append(f"fact {fact.fact_code} without bindingProfileRef requires bindingIssues")
        if fact.data_type is FactDataType.ENUM and not fact.allowed_values:
            issues.append(f"enum fact {fact.fact_code} requires allowedValues")
        if fact.data_type is FactDataType.UNKNOWN:
            issues.append(f"confirmed fact {fact.fact_code} cannot use unknown dataType")
    expected = catalog_digest_v3(catalog)
    if catalog.catalog_digest != expected:
        issues.append("catalogDigest does not match canonical catalog content")
    if issues:
        raise FactCatalogValidationErrorV3(issues)


def fact_catalog_schema_v3() -> dict[str, object]:
    return BusinessConfirmedFactCatalogV3.model_json_schema(by_alias=True, mode="validation")
