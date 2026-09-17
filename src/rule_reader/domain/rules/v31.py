"""Rule Schema 3.1.0: runtime parameters, member quantifiers, and dual source identity."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.models import FactDataType, RuleOperator
from rule_reader.domain.rules.v2 import DateUnit, NullPolicy
from rule_reader.domain.rules.v3 import (
    BlockingIssueV3,
    ProposedFactV3,
    RuleNodeStatusV3,
    RuleOutcomeV3,
    RuleStageNameV3,
)

RULE_STRUCTURE_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RULE_STRUCTURE_SCHEMA_ID_V31 = "urn:rulereader:rule-structure-candidate:3.1.0"
STAGE_ORDER_V31 = tuple(RuleStageNameV3)
EVALUATION_TIMEZONE_V31: Literal["Asia/Shanghai"] = "Asia/Shanghai"


class RuleModelV31(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ExpressionKindV31(StrEnum):
    FACT = "fact"
    LITERAL = "literal"
    PARAMETER = "parameter"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    COALESCE = "coalesce"
    DATE_ADD = "dateAdd"


class ConditionKindV31(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not"
    COMPARE = "compare"
    ALL_MEMBERS = "allMembers"


class EmptyCollectionPolicyV31(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class DuplicateMemberPolicyV31(StrEnum):
    UNIQUE_PRESERVE_ORDER = "uniquePreserveOrder"


class MissingMemberPolicyV31(StrEnum):
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class StageHitPolicyV31(StrEnum):
    TERMINATE = "terminate"
    FIRST_MATCH_THEN_CONTINUE = "firstMatchThenContinue"


class RuntimeParameterRoleV31(StrEnum):
    EVALUATION_CLOCK = "evaluationClock"
    CUTOFF = "cutoff"
    EFFECTIVE_FROM = "effectiveFrom"


class ExpressionNodeV31(RuleModelV31):
    kind: ExpressionKindV31
    fact_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    parameter_name: str | None = Field(
        default=None,
        pattern=r"^[a-z][A-Za-z0-9]*$",
        max_length=100,
    )
    value: str | int | float | bool | list[str | int | float | bool] | None = None
    children: list[ExpressionNodeV31] = Field(default_factory=list)
    unit: DateUnit | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ExpressionNodeV31:
        if self.kind is ExpressionKindV31.FACT:
            if (
                self.fact_code is None
                or self.parameter_name is not None
                or self.value is not None
                or self.children
                or self.unit
            ):
                raise ValueError("fact expressions require only factCode")
        elif self.kind is ExpressionKindV31.LITERAL:
            if (
                self.value is None
                or self.fact_code is not None
                or self.parameter_name is not None
                or self.children
                or self.unit
            ):
                raise ValueError("literal expressions require only a non-null value")
        elif self.kind is ExpressionKindV31.PARAMETER:
            if (
                self.parameter_name is None
                or self.fact_code is not None
                or self.value is not None
                or self.children
                or self.unit
            ):
                raise ValueError("parameter expressions require only parameterName")
        elif self.kind in {ExpressionKindV31.ADD, ExpressionKindV31.MULTIPLY}:
            if (
                len(self.children) < 2
                or self.fact_code is not None
                or self.parameter_name is not None
                or self.value is not None
                or self.unit is not None
            ):
                raise ValueError("add/multiply expressions require at least two children")
        elif self.kind in {ExpressionKindV31.SUBTRACT, ExpressionKindV31.DIVIDE}:
            if (
                len(self.children) != 2
                or self.fact_code is not None
                or self.parameter_name is not None
                or self.value is not None
                or self.unit is not None
            ):
                raise ValueError("subtract/divide expressions require exactly two children")
        elif self.kind is ExpressionKindV31.COALESCE:
            if (
                len(self.children) < 2
                or self.fact_code is not None
                or self.parameter_name is not None
                or self.value is not None
                or self.unit is not None
            ):
                raise ValueError("coalesce expressions require at least two children")
        elif self.kind is ExpressionKindV31.DATE_ADD:
            if (
                len(self.children) != 2
                or self.unit is None
                or self.fact_code is not None
                or self.parameter_name is not None
                or self.value is not None
            ):
                raise ValueError("dateAdd expressions require two children and unit")
        return self


class ConditionNodeV31(RuleModelV31):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=160)
    kind: ConditionKindV31
    description: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True
    children: list[ConditionNodeV31] = Field(default_factory=list)
    left: ExpressionNodeV31 | None = None
    operator: RuleOperator | None = None
    right: ExpressionNodeV31 | None = None
    null_policy: NullPolicy = NullPolicy.INDETERMINATE
    collection_fact_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    empty_collection_policy: EmptyCollectionPolicyV31 | None = None
    duplicate_member_policy: DuplicateMemberPolicyV31 | None = None
    missing_member_policy: MissingMemberPolicyV31 | None = None
    already_satisfied: ConditionNodeV31 | None = None
    member_predicate: ConditionNodeV31 | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ConditionNodeV31:
        comparison_present = any((self.left is not None, self.operator is not None, self.right))
        member_present = any(
            (
                self.collection_fact_code is not None,
                self.empty_collection_policy is not None,
                self.duplicate_member_policy is not None,
                self.missing_member_policy is not None,
                self.already_satisfied is not None,
                self.member_predicate is not None,
            )
        )
        if self.kind in {ConditionKindV31.ALL, ConditionKindV31.ANY}:
            if not self.children or comparison_present or member_present:
                raise ValueError("all/any nodes require children and no comparison/member fields")
        elif self.kind is ConditionKindV31.NOT:
            if len(self.children) != 1 or comparison_present or member_present:
                raise ValueError(
                    "not nodes require exactly one child and no comparison/member fields"
                )
        elif self.kind is ConditionKindV31.COMPARE:
            if self.children or member_present or self.left is None or self.operator is None:
                raise ValueError(
                    "compare nodes require left/operator and no children/member fields"
                )
            unary = {
                RuleOperator.IS_NULL,
                RuleOperator.IS_NOT_NULL,
                RuleOperator.IS_BLANK,
                RuleOperator.IS_NOT_BLANK,
            }
            if self.operator in unary and self.right is not None:
                raise ValueError("null/blank operators cannot contain right")
            if self.operator not in unary and self.right is None:
                raise ValueError("binary compare operators require right")
        else:
            if (
                self.children
                or comparison_present
                or self.collection_fact_code is None
                or self.empty_collection_policy is None
                or self.duplicate_member_policy is None
                or self.missing_member_policy is None
                or self.member_predicate is None
            ):
                raise ValueError(
                    "allMembers nodes require collection, policies, memberPredicate, and no children"
                )
        return self


class RuntimeParameterV31(RuleModelV31):
    name: str = Field(pattern=r"^[a-z][A-Za-z0-9]*$", max_length=100)
    data_type: FactDataType
    role: RuntimeParameterRoleV31
    required: bool = True
    bound_value: str | int | float | bool | None = None
    inclusive: bool = True
    description: str = Field(min_length=1, max_length=1_000)


class StageSemanticsV31(RuleModelV31):
    on_hit: StageHitPolicyV31
    unknown: Literal["indeterminate"] = "indeterminate"


class RuleNodeV31(RuleModelV31):
    rule_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    priority: int = Field(ge=1, le=10_000)
    title: str = Field(min_length=1, max_length=300)
    status: RuleNodeStatusV3
    when: ConditionNodeV31 | None = None
    outcome: RuleOutcomeV3 | None = None
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    failure_reason: str = Field(min_length=1, max_length=2_000)
    recommendations: list[str] = Field(min_length=1)
    blocking_issue_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> RuleNodeV31:
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


class RuleStageV31(RuleModelV31):
    stage: RuleStageNameV3
    rules: list[RuleNodeV31] = Field(default_factory=list)
    empty_stage_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_empty_stage(self) -> RuleStageV31:
        if self.rules:
            if self.empty_stage_reason is not None:
                raise ValueError("non-empty stages cannot declare emptyStageReason")
        elif self.empty_stage_reason is None:
            raise ValueError("empty stages require emptyStageReason")
        return self


class SourceIdentityV31(RuleModelV31):
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extractor_version: str = Field(min_length=1, max_length=80)
    extracted_sections: list[str] = Field(min_length=1)
    source_file_byte_length: int = Field(ge=1)
    parse_input_character_count: int = Field(ge=1)


class RuleStructureCandidateV31(RuleModelV31):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="RuleStructureCandidate 3.1.0",
        json_schema_extra={
            "$schema": RULE_STRUCTURE_SCHEMA_DIALECT,
            "$id": RULE_STRUCTURE_SCHEMA_ID_V31,
        },
    )

    contract_version: Literal["3.1.0"]
    rule_set_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    title: str = Field(min_length=1, max_length=300)
    scope: str = Field(min_length=1, max_length=4_000)
    catalog_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    catalog_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=120)
    catalog_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_views: list[str] = Field(min_length=1)
    source_identity: SourceIdentityV31
    runtime_parameters: list[RuntimeParameterV31] = Field(min_length=1)
    evaluation_timezone: Literal["Asia/Shanghai"] = EVALUATION_TIMEZONE_V31
    required_fact_codes: list[str] = Field(min_length=1)
    stages: list[RuleStageV31] = Field(min_length=5, max_length=5)
    stage_semantics: dict[str, StageSemanticsV31]
    default_outcome: RuleOutcomeV3
    default_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    blocking_issues: list[BlockingIssueV3] = Field(default_factory=list)
    proposed_facts: list[ProposedFactV3] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stage_semantics(self) -> RuleStructureCandidateV31:
        expected = {stage.value for stage in RuleStageNameV3}
        if set(self.stage_semantics) != expected:
            raise ValueError("stageSemantics must declare every frozen V3 stage exactly once")
        eligibility = self.stage_semantics[RuleStageNameV3.ELIGIBILITY.value]
        if eligibility.on_hit is not StageHitPolicyV31.FIRST_MATCH_THEN_CONTINUE:
            raise ValueError("eligibility onHit must be firstMatchThenContinue")
        for name, semantics in self.stage_semantics.items():
            if name != RuleStageNameV3.ELIGIBILITY.value and semantics.on_hit is not (
                StageHitPolicyV31.TERMINATE
            ):
                raise ValueError(f"{name} onHit must terminate")
        names = [parameter.name for parameter in self.runtime_parameters]
        if len(names) != len(set(names)):
            raise ValueError("runtime parameter names must be unique")
        return self


def default_stage_semantics_v31() -> dict[str, StageSemanticsV31]:
    terminate = StageSemanticsV31(on_hit=StageHitPolicyV31.TERMINATE)
    return {
        RuleStageNameV3.STATE_GUARDS.value: terminate,
        RuleStageNameV3.PREREQUISITES.value: terminate,
        RuleStageNameV3.ELIGIBILITY.value: StageSemanticsV31(
            on_hit=StageHitPolicyV31.FIRST_MATCH_THEN_CONTINUE
        ),
        RuleStageNameV3.POST_GATES.value: terminate,
        RuleStageNameV3.EXCLUSIONS.value: terminate,
    }


def rule_structure_candidate_schema_v31() -> dict[str, object]:
    return RuleStructureCandidateV31.model_json_schema(by_alias=True, mode="validation")
