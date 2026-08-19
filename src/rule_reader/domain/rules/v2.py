"""Schema 2.0 rule contracts with structured expressions and fact semantics."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.models import (
    FactDataType,
    MappingStatus,
    ParserMetadata,
    RuleOperator,
    SourceMetadata,
)


class ContractModelV2(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class FactKind(StrEnum):
    SOURCE = "source"
    AGGREGATE = "aggregate"
    EXISTS = "exists"
    DERIVED = "derived"


class NullPolicy(StrEnum):
    FAIL = "fail"
    PASS = "pass"
    INDETERMINATE = "indeterminate"
    ERROR = "error"


class ExpressionKind(StrEnum):
    FACT = "fact"
    LITERAL = "literal"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    COALESCE = "coalesce"
    DATE_ADD = "dateAdd"


class DateUnit(StrEnum):
    DAY = "day"
    HOUR = "hour"
    MINUTE = "minute"


class ConditionKindV2(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not"
    COMPARE = "compare"


class TestExpectationV2(StrEnum):
    PASS = "pass"
    FAIL = "fail"


ScalarValue: TypeAlias = str | int | float | bool | None
ExpressionValue: TypeAlias = str | int | float | bool | list[str | int | float | bool]


class ExpressionNodeV2(ContractModelV2):
    kind: ExpressionKind
    fact_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    value: ExpressionValue | None = None
    children: list[ExpressionNodeV2] = Field(default_factory=list)
    unit: DateUnit | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ExpressionNodeV2:
        if self.kind is ExpressionKind.FACT:
            if self.fact_code is None or self.value is not None or self.children or self.unit:
                raise ValueError("fact expressions require only factCode")
        elif self.kind is ExpressionKind.LITERAL:
            if self.value is None or self.fact_code is not None or self.children or self.unit:
                raise ValueError("literal expressions require only a non-null value")
        elif self.kind in {ExpressionKind.ADD, ExpressionKind.MULTIPLY}:
            if len(self.children) < 2 or self.fact_code is not None or self.value is not None:
                raise ValueError("add/multiply expressions require at least two children")
            if self.unit is not None:
                raise ValueError("add/multiply expressions cannot contain unit")
        elif self.kind in {ExpressionKind.SUBTRACT, ExpressionKind.DIVIDE}:
            if len(self.children) != 2 or self.fact_code is not None or self.value is not None:
                raise ValueError("subtract/divide expressions require exactly two children")
            if self.unit is not None:
                raise ValueError("subtract/divide expressions cannot contain unit")
        elif self.kind is ExpressionKind.COALESCE:
            if len(self.children) < 2 or self.fact_code is not None or self.value is not None:
                raise ValueError("coalesce expressions require at least two children")
            if self.unit is not None:
                raise ValueError("coalesce expressions cannot contain unit")
        elif self.kind is ExpressionKind.DATE_ADD:
            if (
                len(self.children) != 2
                or self.unit is None
                or self.fact_code is not None
                or self.value is not None
            ):
                raise ValueError("dateAdd expressions require two children and unit")
        return self


class FactParameterV2(ContractModelV2):
    name: str = Field(pattern=r"^[a-z][A-Za-z0-9]*$", max_length=100)
    data_type: FactDataType
    description: str = Field(min_length=1, max_length=1_000)
    required: bool = True


class RequiredFactV2(ContractModelV2):
    fact_code: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    name: str = Field(min_length=1, max_length=200)
    fact_kind: FactKind
    data_type: FactDataType
    description: str = Field(min_length=1, max_length=2_000)
    nullable: bool
    null_policy: NullPolicy
    grain: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    parameters: list[FactParameterV2] = Field(default_factory=list)
    unit: str | None = Field(default=None, max_length=80)
    allowed_values: list[ExpressionValue] = Field(default_factory=list)
    default_value: ScalarValue = None
    derivation: ExpressionNodeV2 | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> RequiredFactV2:
        if self.fact_kind is FactKind.DERIVED:
            if self.derivation is None:
                raise ValueError("derived facts require derivation")
        elif self.derivation is not None:
            raise ValueError("only derived facts can contain derivation")
        if self.fact_kind is not FactKind.DERIVED and not self.parameters:
            raise ValueError("source/aggregate/exists facts require parameters")
        return self


class ConditionNodeV2(ContractModelV2):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    kind: ConditionKindV2
    description: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True
    children: list[ConditionNodeV2] = Field(default_factory=list)
    left: ExpressionNodeV2 | None = None
    operator: RuleOperator | None = None
    right: ExpressionNodeV2 | None = None
    null_policy: NullPolicy = NullPolicy.INDETERMINATE

    @model_validator(mode="after")
    def validate_shape(self) -> ConditionNodeV2:
        comparison_present = any((self.left is not None, self.operator is not None, self.right))
        if self.kind in {ConditionKindV2.ALL, ConditionKindV2.ANY}:
            if not self.children or comparison_present:
                raise ValueError("all/any nodes require children and no comparison fields")
        elif self.kind is ConditionKindV2.NOT:
            if len(self.children) != 1 or comparison_present:
                raise ValueError("not nodes require exactly one child and no comparison fields")
        else:
            if self.children or self.left is None or self.operator is None:
                raise ValueError("compare nodes require left/operator and no children")
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
        return self


class RuleTestCaseV2(ContractModelV2):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    description: str = Field(min_length=1, max_length=1_000)
    given: dict[str, ExpressionValue | None] = Field(min_length=1)
    expected: TestExpectationV2
    rationale: str = Field(min_length=1, max_length=2_000)


class FieldMappingCandidateV2(ContractModelV2):
    fact_code: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    mapping_status: MappingStatus
    view_name: str | None = Field(default=None, max_length=150)
    view_field: str | None = Field(default=None, max_length=150)
    note: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_mapping_shape(self) -> FieldMappingCandidateV2:
        if self.mapping_status is MappingStatus.MAPPED:
            if not self.view_name or not self.view_field:
                raise ValueError("mapped entries require viewName and viewField")
        elif self.view_name is not None or self.view_field is not None:
            raise ValueError("unresolved entries cannot contain viewName or viewField")
        return self


class RuleBodyV2(ContractModelV2):
    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    title: str = Field(min_length=1, max_length=300)
    scope: str = Field(min_length=1, max_length=4_000)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    source_views: list[str] = Field(min_length=1)
    required_facts: list[RequiredFactV2] = Field(min_length=1)
    root_condition: ConditionNodeV2
    exception_notes: list[str] = Field(min_length=1)
    failure_reasons: list[str] = Field(min_length=1)
    recommendations: list[str] = Field(min_length=1)
    responsible_roles: list[str] = Field(min_length=1)
    test_cases: list[RuleTestCaseV2] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class RuleCandidateV2(RuleBodyV2):
    field_mappings: list[FieldMappingCandidateV2] = Field(min_length=1)


class FieldMappingV2(ContractModelV2):
    fact_code: str
    mapping_status: MappingStatus
    view_name: str | None = None
    view_field: str | None = None
    source_expression: str | None = None
    view_active: bool | None = None
    review_status: Literal["candidate"] = "candidate"
    note: str


class ParsedRuleV2(RuleBodyV2):
    field_mappings: list[FieldMappingV2] = Field(min_length=1)


class RuleParseResultV2(ContractModelV2):
    schema_version: Literal["2.0.0"] = "2.0.0"
    rule_version: str
    generated_at: datetime
    status: Literal["draft"] = "draft"
    executable: Literal[False] = False
    parser: ParserMetadata
    source: SourceMetadata
    rule: ParsedRuleV2

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.model_dump_json(by_alias=True, indent=indent)
