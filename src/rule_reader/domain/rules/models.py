"""Pydantic contracts for untrusted model candidates and final rule drafts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class FactDataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"
    MONEY = "money"
    LIST = "list"
    UNKNOWN = "unknown"


class ConditionKind(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not"
    PREDICATE = "predicate"
    FORMULA = "formula"
    EXISTS = "exists"


class RuleOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    IS_BLANK = "is_blank"
    IS_NOT_BLANK = "is_not_blank"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"


class MappingStatus(StrEnum):
    MAPPED = "mapped"
    UNRESOLVED = "unresolved"


class TestExpectation(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"


ScalarValue: TypeAlias = str | int | float | bool | None
ConditionValue: TypeAlias = ScalarValue | list[str | int | float | bool]


class RequiredFact(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    name: str = Field(min_length=1, max_length=200)
    data_type: FactDataType
    description: str = Field(min_length=1, max_length=2_000)
    nullable: bool


class ConditionNode(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    kind: ConditionKind
    description: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True
    children: list[ConditionNode] = Field(default_factory=list)
    fact_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    operator: RuleOperator | None = None
    value: ConditionValue = None
    expression: str | None = Field(default=None, max_length=4_000)
    fact_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> ConditionNode:
        leaf_fields_present = any(
            (
                self.fact_key is not None,
                self.operator is not None,
                self.value is not None,
                self.expression is not None,
                bool(self.fact_refs),
            )
        )

        if self.kind in {ConditionKind.ALL, ConditionKind.ANY}:
            if not self.children or leaf_fields_present:
                raise ValueError("all/any nodes require children and no leaf fields")
        elif self.kind is ConditionKind.NOT:
            if len(self.children) != 1 or leaf_fields_present:
                raise ValueError("not nodes require exactly one child and no leaf fields")
        elif self.kind is ConditionKind.PREDICATE:
            if self.children or self.fact_key is None or self.operator is None:
                raise ValueError("predicate nodes require factKey/operator and no children")
        elif self.kind is ConditionKind.FORMULA:
            if self.children or not self.expression or not self.fact_refs:
                raise ValueError("formula nodes require expression/factRefs and no children")
            if self.fact_key is not None or self.operator is not None or self.value is not None:
                raise ValueError("formula nodes cannot contain predicate fields")
        elif self.kind is ConditionKind.EXISTS:
            if not self.expression and not self.children:
                raise ValueError("exists nodes require expression or child conditions")
            if self.fact_key is not None or self.operator is not None or self.value is not None:
                raise ValueError("exists nodes cannot contain predicate fields")

        return self


class RuleTestCase(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=120)
    description: str = Field(min_length=1, max_length=1_000)
    given: dict[str, ConditionValue] = Field(min_length=1)
    expected: TestExpectation
    rationale: str = Field(min_length=1, max_length=2_000)


class FieldMappingCandidate(ContractModel):
    fact_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    mapping_status: MappingStatus
    view_name: str | None = Field(default=None, max_length=150)
    view_field: str | None = Field(default=None, max_length=150)
    note: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_mapping_shape(self) -> FieldMappingCandidate:
        if self.mapping_status is MappingStatus.MAPPED:
            if not self.view_name or not self.view_field:
                raise ValueError("mapped entries require viewName and viewField")
        elif self.view_name is not None or self.view_field is not None:
            raise ValueError("unresolved entries cannot contain viewName or viewField")
        return self


class RuleBody(ContractModel):
    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    title: str = Field(min_length=1, max_length=300)
    scope: str = Field(min_length=1, max_length=4_000)
    source_views: list[str] = Field(min_length=1)
    required_facts: list[RequiredFact] = Field(min_length=1)
    root_condition: ConditionNode
    exception_notes: list[str] = Field(min_length=1)
    failure_reasons: list[str] = Field(min_length=1)
    recommendations: list[str] = Field(min_length=1)
    responsible_roles: list[str] = Field(min_length=1)
    test_cases: list[RuleTestCase] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class RuleCandidate(RuleBody):
    field_mappings: list[FieldMappingCandidate] = Field(min_length=1)


class FieldMapping(ContractModel):
    fact_key: str
    mapping_status: MappingStatus
    view_name: str | None = None
    view_field: str | None = None
    source_expression: str | None = None
    view_active: bool | None = None
    review_status: Literal["candidate"] = "candidate"
    note: str


class ParsedRule(RuleBody):
    field_mappings: list[FieldMapping] = Field(min_length=1)


class ParserMetadata(ContractModel):
    parser_version: str
    prompt_version: str
    provider: Literal["deepseek"] = "deepseek"
    model: str


class SourceMetadata(ContractModel):
    source_name: str
    relative_path: str | None = None
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    character_count: int = Field(ge=1)


class RuleParseResult(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    rule_version: str
    generated_at: datetime
    status: Literal["draft"] = "draft"
    executable: Literal[False] = False
    parser: ParserMetadata
    source: SourceMetadata
    rule: ParsedRule

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.model_dump_json(by_alias=True, indent=indent)
