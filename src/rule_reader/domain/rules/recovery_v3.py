"""Immutable MongoDB payload for a source-bound V3 rule-structure recovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import validate_rule_structure_candidate_v3


class RecoveryModelV3(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


class RecoverySourceV3(RecoveryModelV3):
    bundle_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=160)
    bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    workbook_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_block_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_block_characters: int = Field(ge=1)


def recovery_candidate_id_v3(rule_set_id: str, source_sha256: str, catalog_digest: str) -> str:
    return f"{rule_set_id}@{source_sha256[:12]}-{catalog_digest[:12]}"


class V3RecoveryPayload(RecoveryModelV3):
    contract_version: Literal["3.0.0"]
    candidate_id: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]*@[a-f0-9]{12}-[a-f0-9]{12}$", max_length=160
    )
    status: Literal["validatedBlockedCandidate"]
    executable: Literal[False]
    source: RecoverySourceV3
    catalog: BusinessConfirmedFactCatalogV3
    candidate: RuleStructureCandidateV3

    @model_validator(mode="after")
    def validate_identity_and_contracts(self) -> V3RecoveryPayload:
        validate_fact_catalog_v3(self.catalog)
        validate_rule_structure_candidate_v3(self.candidate, self.catalog)
        expected_id = recovery_candidate_id_v3(
            self.candidate.rule_set_id,
            self.source.rule_block_sha256,
            self.catalog.catalog_digest,
        )
        if self.candidate_id != expected_id:
            raise ValueError("candidateId does not match source and catalog identity")
        if not self.candidate.blocking_issues:
            raise ValueError("V3 recovery payload must preserve blocking issues")
        return self


def recovery_payload_dict_v3(payload: V3RecoveryPayload) -> dict[str, Any]:
    return payload.model_dump(mode="json", by_alias=True)


def recovery_payload_sha256_v3(payload: V3RecoveryPayload | dict[str, Any]) -> str:
    value = recovery_payload_dict_v3(payload) if isinstance(payload, V3RecoveryPayload) else payload
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
