"""Offline rule-structure candidate contract for Rule Schema 3.0."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.v2 import ConditionNodeV2

RULE_STRUCTURE_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RULE_STRUCTURE_SCHEMA_ID_V3 = "urn:rulereader:rule-structure-candidate:3.0.0"


class RuleModelV3(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class RuleOutcomeV3(StrEnum):
    READY = "READY"
    WAITING_COMPLETION = "WAITING_COMPLETION"
    WAITING_CONDITIONS = "WAITING_CONDITIONS"
    NO_RELEASE_REQUIRED = "NO_RELEASE_REQUIRED"
    ALREADY_RELEASED = "ALREADY_RELEASED"
    SKIPPED = "SKIPPED"
    INDETERMINATE = "INDETERMINATE"


class RuleStageNameV3(StrEnum):
    STATE_GUARDS = "stateGuards"
    PREREQUISITES = "prerequisites"
    ELIGIBILITY = "eligibility"
    POST_GATES = "postGates"
    EXCLUSIONS = "exclusions"


STAGE_ORDER_V3 = tuple(RuleStageNameV3)


class RuleNodeStatusV3(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class BlockingIssueV3(RuleModelV3):
    issue_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=160)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    message: str = Field(min_length=1, max_length=2_000)
    fact_codes: list[str] = Field(default_factory=list)
    resolution_hint: str = Field(min_length=1, max_length=2_000)


class ProposedFactV3(RuleModelV3):
    fact_code: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=160)
    name: str = Field(min_length=1, max_length=200)
    data_type_hint: str | None = Field(default=None, max_length=80)
    reason: str = Field(min_length=1, max_length=2_000)
    source_locator: str = Field(min_length=1, max_length=300)


class RuleNodeV3(RuleModelV3):
    rule_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    priority: int = Field(ge=1, le=10_000)
    title: str = Field(min_length=1, max_length=300)
    status: RuleNodeStatusV3
    when: ConditionNodeV2 | None = None
    outcome: RuleOutcomeV3 | None = None
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    failure_reason: str = Field(min_length=1, max_length=2_000)
    recommendations: list[str] = Field(min_length=1)
    blocking_issue_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> RuleNodeV3:
        if self.status is RuleNodeStatusV3.ACTIVE:
            if self.when is None or self.outcome is None or self.reason_code is None:
                raise ValueError("active rules require when, outcome, and reasonCode")
            if self.blocking_issue_ids:
                raise ValueError("active rules cannot reference blocking issues")
        else:
            if self.when is not None or self.outcome is not None or self.reason_code is not None:
                raise ValueError("blocked rules cannot contain executable decision fields")
            if not self.blocking_issue_ids:
                raise ValueError("blocked rules require blockingIssueIds")
        return self


class RuleStageV3(RuleModelV3):
    stage: RuleStageNameV3
    rules: list[RuleNodeV3] = Field(min_length=1)


class RuleStructureCandidateV3(RuleModelV3):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="RuleStructureCandidate 3.0.0",
        json_schema_extra={
            "$schema": RULE_STRUCTURE_SCHEMA_DIALECT,
            "$id": RULE_STRUCTURE_SCHEMA_ID_V3,
        },
    )

    contract_version: Literal["3.0.0"]
    rule_set_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    title: str = Field(min_length=1, max_length=300)
    scope: str = Field(min_length=1, max_length=4_000)
    catalog_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    catalog_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=120)
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_views: list[str] = Field(min_length=1)
    required_fact_codes: list[str] = Field(min_length=1)
    stages: list[RuleStageV3] = Field(min_length=5, max_length=5)
    default_outcome: RuleOutcomeV3
    default_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    blocking_issues: list[BlockingIssueV3] = Field(default_factory=list)
    proposed_facts: list[ProposedFactV3] = Field(default_factory=list)


def rule_structure_candidate_schema_v3() -> dict[str, object]:
    return RuleStructureCandidateV3.model_json_schema(by_alias=True, mode="validation")
