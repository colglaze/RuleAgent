"""FactBindingRequest 2.0 contracts and deterministic export.

The contract describes logical query requirements only. It never derives SQL, physical
joins, credentials, or unreviewed metadata from free text.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.models import (
    FactDataType,
    MappingStatus,
    ParserProvider,
    RuleOperator,
)
from rule_reader.domain.rules.v2 import (
    ConditionKindV2,
    ConditionNodeV2,
    ContractModelV2,
    FactKind,
    NullPolicy,
    RequiredFactV2,
    RuleParseResultV2,
)
from rule_reader.domain.rules.validation_v2 import expression_fact_refs

FACT_BINDING_CONTRACT_VERSION_V2: Literal["2.0.0"] = "2.0.0"
FACT_BINDING_SCHEMA_ID_V2 = "urn:rulereader:fact-binding-request:2.0.0"
FACT_BINDING_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

BindingScalar: TypeAlias = str | int | float | bool
BindingExampleValue: TypeAlias = BindingScalar | list[BindingScalar] | None


class ResolutionStatus(StrEnum):
    """How strongly RuleReader can support a query requirement."""

    DECLARED = "declared"
    CANDIDATE = "candidate"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "notApplicable"


class FieldRole(StrEnum):
    VALUE = "value"
    ENTITY_KEY = "entityKey"
    FILTER = "filter"
    GROUP_BY = "groupBy"
    TIME = "time"


class FilterValueKind(StrEnum):
    PARAMETER = "parameter"
    LITERAL = "literal"


class FilterCompleteness(StrEnum):
    COMPLETE = "complete"
    UNRESOLVED = "unresolved"


class AggregationMode(StrEnum):
    NONE = "none"
    PRECOMPUTED = "precomputed"
    COMPUTE = "compute"
    EXISTS = "exists"
    UNRESOLVED = "unresolved"


class AggregationFunction(StrEnum):
    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "countDistinct"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class TimeRangeMode(StrEnum):
    NONE = "none"
    AS_OF = "asOf"
    BETWEEN = "between"
    UNRESOLVED = "unresolved"


class EvidenceKind(StrEnum):
    FACT_DECLARATION = "factDeclaration"
    CONDITION_USAGE = "conditionUsage"
    MAPPING_CANDIDATE = "mappingCandidate"
    TEST_CASE = "testCase"


class UncertaintyCategory(StrEnum):
    ENTITY = "entity"
    FIELD = "field"
    FILTER = "filter"
    AGGREGATION = "aggregation"
    TIME_RANGE = "timeRange"
    SOURCE = "source"


class UncertaintyImpact(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class BindingFactParameterV2(ContractModelV2):
    name: str = Field(
        pattern=r"^[a-z][A-Za-z0-9]*$",
        max_length=100,
        description="Stable camelCase runtime parameter name used by the fact query.",
    )
    data_type: FactDataType = Field(description="Logical parameter value type.")
    description: str = Field(
        min_length=1,
        max_length=1_000,
        description="Business meaning of the parameter; never a SQL expression.",
    )
    required: bool = Field(description="Whether every fact lookup must receive this parameter.")


class BindableFactV2(ContractModelV2):
    fact_code: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
        description="Stable dotted business fact identifier.",
    )
    name: str = Field(min_length=1, max_length=200, description="Human-readable fact name.")
    fact_kind: Literal[FactKind.SOURCE, FactKind.AGGREGATE, FactKind.EXISTS] = Field(
        description="Bindable fact kind; derived facts are intentionally excluded."
    )
    data_type: FactDataType = Field(description="Logical scalar result type.")
    description: str = Field(
        min_length=1,
        max_length=2_000,
        description="Business definition of the fact; never executable SQL.",
    )
    nullable: bool = Field(description="Whether the fact result may be null.")
    null_policy: NullPolicy = Field(description="Rule behavior when the fact is null or missing.")
    grain: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=100,
        description="Business grain represented by one fact value.",
    )
    parameters: list[BindingFactParameterV2] = Field(
        min_length=1,
        description="Runtime business parameters required to retrieve the fact.",
    )
    unit: str | None = Field(
        max_length=80,
        description="Business unit such as CNY, or null when no unit applies.",
    )
    allowed_values: list[BindingScalar | list[BindingScalar]] = Field(
        description="Closed business values when declared; empty means no closed list."
    )
    default_value: BindingScalar | None = Field(
        description="Declared default value, or null when no default is authorized."
    )
    derivation: Literal[None] = Field(
        description="Always null because derived facts never enter SQL binding."
    )

    @model_validator(mode="after")
    def reject_duplicate_parameters(self) -> BindableFactV2:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("fact parameters cannot contain duplicate names")
        return self


class BindingRuleRefV2(ContractModelV2):
    rule_id: str = Field(min_length=1, max_length=120, description="Stable rule identifier.")
    rule_version: str = Field(
        min_length=1,
        max_length=220,
        description="Exact immutable RuleReader draft version.",
    )
    schema_version: Literal["2.0.0"] = Field(
        description="Rule document schema version, independent of contractVersion."
    )
    source_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 of the normalized source document.",
    )


class SourceFieldCandidateV2(ContractModelV2):
    relation_name: str = Field(
        min_length=1,
        max_length=150,
        description="Unqualified candidate relation or view name from the RuleReader catalog.",
    )
    field_name: str = Field(
        min_length=1,
        max_length=150,
        description="Candidate output field name; never an arbitrary SQL expression.",
    )
    relation_active: bool | None = Field(
        description="Catalog activity hint, or null when the catalog has no state."
    )
    review_status: Literal["candidate"] = Field(
        description="The physical source hint is not approved."
    )


class EntityRequirementV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"keyResolutionStatus": {"const": "candidate"}}},
                    "then": {"properties": {"keyParameters": {"minItems": 1}}},
                },
                {
                    "if": {"properties": {"keyResolutionStatus": {"const": "unresolved"}}},
                    "then": {"properties": {"keyParameters": {"maxItems": 0}}},
                },
            ]
        }
    )

    entity_type: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=100,
        description="Logical business entity to which this fact belongs.",
    )
    grain: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=100,
        description="Logical grain at which one scalar fact value is returned.",
    )
    key_parameters: list[str] = Field(
        description="Fact parameters confirmed as entity identity keys; empty when unresolved.",
    )
    resolution_status: Literal[ResolutionStatus.DECLARED] = Field(
        description="Entity semantics come directly from the validated rule draft."
    )
    key_resolution_status: Literal[
        ResolutionStatus.CANDIDATE,
        ResolutionStatus.UNRESOLVED,
    ] = Field(description="Whether entity identity parameters are known or unresolved.")
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Evidence registry IDs supporting the entity requirement.",
    )

    @model_validator(mode="after")
    def validate_key_resolution(self) -> EntityRequirementV2:
        if self.key_resolution_status is ResolutionStatus.CANDIDATE:
            if not self.key_parameters:
                raise ValueError("candidate entity keys require keyParameters")
        elif self.key_parameters:
            raise ValueError("unresolved entity keys cannot assert keyParameters")
        return self


class FieldRequirementV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"resolutionStatus": {"const": "candidate"}}},
                    "then": {"properties": {"sourceCandidate": {"type": "object"}}},
                },
                {
                    "if": {"properties": {"resolutionStatus": {"const": "unresolved"}}},
                    "then": {"properties": {"sourceCandidate": {"type": "null"}}},
                },
            ]
        }
    )

    field_id: str = Field(
        pattern=r"^[a-z][A-Za-z0-9_.-]*$",
        max_length=160,
        description="Request-local identifier referenced by filters, aggregation, and time range.",
    )
    role: FieldRole = Field(description="Logical role played by this field in a SQL template.")
    logical_name: str = Field(
        min_length=1,
        max_length=200,
        description="Business name or fact/parameter code, not a physical SQL identifier.",
    )
    data_type: FactDataType = Field(description="Logical value type expected from the field.")
    required: bool = Field(description="Whether the SQL template must resolve this field.")
    source_candidate: SourceFieldCandidateV2 | None = Field(
        description="Unapproved physical source hint, or null when unresolved."
    )
    resolution_status: Literal[
        ResolutionStatus.CANDIDATE,
        ResolutionStatus.UNRESOLVED,
    ] = Field(description="Whether a source hint exists or remains unresolved.")
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Evidence registry IDs supporting this field requirement.",
    )

    @model_validator(mode="after")
    def validate_resolution(self) -> FieldRequirementV2:
        if self.resolution_status is ResolutionStatus.CANDIDATE:
            if self.source_candidate is None:
                raise ValueError("candidate fields require sourceCandidate")
        elif self.source_candidate is not None:
            raise ValueError("unresolved fields cannot contain sourceCandidate")
        return self


class ParameterFilterValueV2(ContractModelV2):
    kind: Literal[FilterValueKind.PARAMETER] = Field(
        description="Filter value is supplied by a named runtime parameter."
    )
    parameter_name: str = Field(
        pattern=r"^[a-z][A-Za-z0-9]*$",
        max_length=100,
        description="Name of a declared fact parameter.",
    )


class LiteralFilterValueV2(ContractModelV2):
    kind: Literal[FilterValueKind.LITERAL] = Field(
        description="Filter value is a declared scalar or scalar list literal."
    )
    value: BindingScalar | list[BindingScalar] = Field(
        description="Literal comparison value; null is represented with an is-null operator."
    )


FilterValueV2: TypeAlias = Annotated[
    ParameterFilterValueV2 | LiteralFilterValueV2,
    Field(discriminator="kind"),
]


class FilterRequirementV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "operator": {
                                "enum": [
                                    "is_null",
                                    "is_not_null",
                                    "is_blank",
                                    "is_not_blank",
                                ]
                            }
                        }
                    },
                    "then": {"properties": {"value": {"type": "null"}}},
                    "else": {"properties": {"value": {"not": {"type": "null"}}}},
                }
            ]
        }
    )

    filter_id: str = Field(
        pattern=r"^[a-z][A-Za-z0-9_.-]*$",
        max_length=160,
        description="Stable request-local filter identifier.",
    )
    field_id: str = Field(
        min_length=1,
        max_length=160,
        description="Field requirement to which this predicate applies.",
    )
    operator: RuleOperator = Field(description="Controlled comparison operator.")
    value: FilterValueV2 | None = Field(
        description="Structured parameter/literal value, or null for unary null operators."
    )
    required: bool = Field(description="Whether the predicate is mandatory for every lookup.")
    resolution_status: Literal[
        ResolutionStatus.CANDIDATE,
        ResolutionStatus.UNRESOLVED,
    ] = Field(description="Whether the predicate has sufficient field/source information.")
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Evidence registry IDs supporting this filter.",
    )

    @model_validator(mode="after")
    def validate_operator_value(self) -> FilterRequirementV2:
        unary = {
            RuleOperator.IS_NULL,
            RuleOperator.IS_NOT_NULL,
            RuleOperator.IS_BLANK,
            RuleOperator.IS_NOT_BLANK,
        }
        if self.operator in unary and self.value is not None:
            raise ValueError("null filter operators cannot contain value")
        if self.operator not in unary and self.value is None:
            raise ValueError("binary filter operators require value")
        return self


class FilterSetV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"completeness": {"const": "complete"}}},
                    "then": {
                        "properties": {
                            "items": {
                                "items": {
                                    "properties": {"resolutionStatus": {"const": "candidate"}}
                                }
                            }
                        }
                    },
                }
            ]
        }
    )

    items: list[FilterRequirementV2] = Field(
        description="Structured predicates required to retrieve the fact."
    )
    completeness: FilterCompleteness = Field(
        description="Whether the predicates fully express the fact's retrieval criteria."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs supporting filter completeness."
    )

    @model_validator(mode="after")
    def validate_completeness(self) -> FilterSetV2:
        ids = [item.filter_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("filters cannot contain duplicate filterId values")
        if self.completeness is FilterCompleteness.COMPLETE and any(
            item.resolution_status is ResolutionStatus.UNRESOLVED for item in self.items
        ):
            raise ValueError("complete filters cannot contain unresolved items")
        return self


class AggregationRequirementV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"mode": {"const": "compute"}}},
                    "then": {
                        "properties": {
                            "function": {"type": "string"},
                            "inputFieldIds": {"minItems": 1},
                            "distinct": {"type": "boolean"},
                            "resolutionStatus": {"enum": ["declared", "candidate"]},
                        }
                    },
                    "else": {
                        "properties": {
                            "function": {"type": "null"},
                            "inputFieldIds": {"maxItems": 0},
                            "groupByFieldIds": {"maxItems": 0},
                            "distinct": {"type": "null"},
                        }
                    },
                },
                {
                    "if": {"properties": {"mode": {"const": "none"}}},
                    "then": {"properties": {"resolutionStatus": {"const": "declared"}}},
                },
                {
                    "if": {"properties": {"mode": {"const": "precomputed"}}},
                    "then": {"properties": {"resolutionStatus": {"const": "candidate"}}},
                },
                {
                    "if": {"properties": {"mode": {"const": "exists"}}},
                    "then": {"properties": {"resolutionStatus": {"const": "declared"}}},
                },
                {
                    "if": {"properties": {"mode": {"const": "unresolved"}}},
                    "then": {"properties": {"resolutionStatus": {"const": "unresolved"}}},
                },
            ]
        }
    )

    mode: AggregationMode = Field(
        description="Whether the fact is direct, precomputed, computed, existential, or unresolved."
    )
    function: AggregationFunction | None = Field(
        description="Controlled aggregate function, only for mode=compute."
    )
    input_field_ids: list[str] = Field(
        description="Input field references, only for a computed aggregate."
    )
    group_by_field_ids: list[str] = Field(
        description="Field references defining the computed aggregate grain."
    )
    distinct: bool | None = Field(
        description="Distinct behavior for a computed aggregate, otherwise null."
    )
    resolution_status: ResolutionStatus = Field(
        description="Strength of the declared aggregation semantics."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs supporting aggregation semantics."
    )

    @model_validator(mode="after")
    def validate_shape(self) -> AggregationRequirementV2:
        if self.mode is AggregationMode.COMPUTE:
            if self.function is None or not self.input_field_ids or self.distinct is None:
                raise ValueError("computed aggregation requires function, inputs, and distinct")
            if self.resolution_status not in {
                ResolutionStatus.DECLARED,
                ResolutionStatus.CANDIDATE,
            }:
                raise ValueError("computed aggregation must be declared or candidate")
        else:
            if self.function is not None or self.input_field_ids or self.group_by_field_ids:
                raise ValueError("non-computed aggregation cannot contain compute fields")
            if self.distinct is not None:
                raise ValueError("non-computed aggregation requires distinct=null")
        expected_resolution = {
            AggregationMode.NONE: ResolutionStatus.DECLARED,
            AggregationMode.PRECOMPUTED: ResolutionStatus.CANDIDATE,
            AggregationMode.EXISTS: ResolutionStatus.DECLARED,
            AggregationMode.UNRESOLVED: ResolutionStatus.UNRESOLVED,
        }.get(self.mode)
        if expected_resolution is not None and self.resolution_status is not expected_resolution:
            raise ValueError(f"{self.mode.value} aggregation has invalid resolutionStatus")
        return self


class TimeBoundaryV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"kind": {"const": "parameter"}}},
                    "then": {
                        "properties": {
                            "parameterName": {"type": "string"},
                            "value": {"type": "null"},
                        }
                    },
                    "else": {
                        "properties": {
                            "parameterName": {"type": "null"},
                            "value": {"type": "string"},
                        }
                    },
                }
            ]
        }
    )

    kind: FilterValueKind = Field(
        description="Boundary source: a runtime parameter or an ISO-8601 literal."
    )
    parameter_name: str | None = Field(
        max_length=100, description="Declared parameter name when kind=parameter, otherwise null."
    )
    value: str | None = Field(
        max_length=80,
        description="ISO-8601 date/datetime literal when kind=literal, otherwise null.",
    )
    inclusive: bool = Field(description="Whether the boundary is inclusive.")

    @model_validator(mode="after")
    def validate_kind(self) -> TimeBoundaryV2:
        if self.kind is FilterValueKind.PARAMETER:
            if self.parameter_name is None or self.value is not None:
                raise ValueError("parameter boundary requires only parameterName")
        elif self.value is None or self.parameter_name is not None:
            raise ValueError("literal boundary requires only value")
        return self


class TimeRangeRequirementV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"mode": {"const": "none"}}},
                    "then": {
                        "properties": {
                            "timeFieldId": {"type": "null"},
                            "start": {"type": "null"},
                            "end": {"type": "null"},
                            "timezone": {"type": "null"},
                            "resolutionStatus": {"const": "notApplicable"},
                        }
                    },
                },
                {
                    "if": {"properties": {"mode": {"const": "unresolved"}}},
                    "then": {
                        "properties": {
                            "timeFieldId": {"type": "null"},
                            "start": {"type": "null"},
                            "end": {"type": "null"},
                            "timezone": {"type": "null"},
                            "resolutionStatus": {"const": "unresolved"},
                        }
                    },
                },
                {
                    "if": {"properties": {"mode": {"const": "asOf"}}},
                    "then": {
                        "properties": {
                            "timeFieldId": {"type": "string"},
                            "start": {"type": "null"},
                            "end": {"type": "object"},
                            "resolutionStatus": {"enum": ["declared", "candidate"]},
                        }
                    },
                },
                {
                    "if": {"properties": {"mode": {"const": "between"}}},
                    "then": {
                        "properties": {
                            "timeFieldId": {"type": "string"},
                            "start": {"type": "object"},
                            "end": {"type": "object"},
                            "resolutionStatus": {"enum": ["declared", "candidate"]},
                        }
                    },
                },
            ]
        }
    )

    mode: TimeRangeMode = Field(description="Declared temporal constraint shape.")
    time_field_id: str | None = Field(
        max_length=160, description="Field requirement used for temporal filtering, or null."
    )
    start: TimeBoundaryV2 | None = Field(description="Lower boundary, or null.")
    end: TimeBoundaryV2 | None = Field(description="Upper/as-of boundary, or null.")
    timezone: str | None = Field(
        max_length=80, description="Business timezone used to interpret boundaries, or null."
    )
    resolution_status: ResolutionStatus = Field(
        description="Whether time semantics are declared, not applicable, or unresolved."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs supporting time-range semantics."
    )

    @model_validator(mode="after")
    def validate_shape(self) -> TimeRangeRequirementV2:
        if self.mode is TimeRangeMode.NONE:
            if any((self.time_field_id, self.start, self.end, self.timezone)):
                raise ValueError("none time range cannot contain field, boundaries, or timezone")
            if self.resolution_status is not ResolutionStatus.NOT_APPLICABLE:
                raise ValueError("none time range requires notApplicable resolution")
        elif self.mode is TimeRangeMode.UNRESOLVED:
            if any((self.time_field_id, self.start, self.end, self.timezone)):
                raise ValueError("unresolved time range cannot assert temporal details")
            if self.resolution_status is not ResolutionStatus.UNRESOLVED:
                raise ValueError("unresolved time range requires unresolved resolution")
        elif self.mode is TimeRangeMode.AS_OF:
            if self.time_field_id is None or self.start is not None or self.end is None:
                raise ValueError("asOf time range requires timeFieldId and only end")
            if self.resolution_status not in {
                ResolutionStatus.DECLARED,
                ResolutionStatus.CANDIDATE,
            }:
                raise ValueError("asOf time range must be declared or candidate")
        elif (
            self.time_field_id is None
            or self.start is None
            or self.end is None
            or self.resolution_status not in {ResolutionStatus.DECLARED, ResolutionStatus.CANDIDATE}
        ):
            raise ValueError("between time range requires field, both bounds, and resolution")
        return self


class FactResultRequirementV2(ContractModelV2):
    column_name: Literal["fact_value"] = Field(description="Required SQL candidate output alias.")
    data_type: FactDataType = Field(description="Expected logical result type.")
    cardinality: Literal["scalar"] = Field(
        description="Exactly one value is expected per entity/parameter tuple."
    )
    nullable: bool = Field(description="Whether the scalar result may be null.")
    null_policy: NullPolicy = Field(description="Rule behavior for a null or missing result.")
    unit: str | None = Field(max_length=80, description="Expected result unit, or null.")


class QueryRequirementsV2(ContractModelV2):
    entity: EntityRequirementV2 = Field(description="Logical entity and grain contract.")
    fields: list[FieldRequirementV2] = Field(
        min_length=1, description="All logical and candidate physical fields needed by the query."
    )
    filters: FilterSetV2 = Field(description="Structured retrieval predicates.")
    aggregation: AggregationRequirementV2 = Field(description="Structured aggregation requirement.")
    time_range: TimeRangeRequirementV2 = Field(
        description="Explicit time-range requirement, including unresolved or not-applicable."
    )
    result: FactResultRequirementV2 = Field(description="Required scalar SQL result contract.")

    @model_validator(mode="after")
    def validate_references(self) -> QueryRequirementsV2:
        field_ids = [field.field_id for field in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("query fields cannot contain duplicate fieldId values")
        if field_ids.count("factValue") != 1:
            raise ValueError("query fields require exactly one factValue")
        value_field = next(field for field in self.fields if field.field_id == "factValue")
        if value_field.role is not FieldRole.VALUE:
            raise ValueError("factValue must have role=value")
        known_fields = set(field_ids)
        for item in self.filters.items:
            if item.field_id not in known_fields:
                raise ValueError(f"filter references unknown fieldId: {item.field_id}")
        aggregate_refs = {
            *self.aggregation.input_field_ids,
            *self.aggregation.group_by_field_ids,
        }
        if unknown := sorted(aggregate_refs - known_fields):
            raise ValueError(f"aggregation references unknown fieldIds: {unknown}")
        if self.time_range.time_field_id is not None:
            if self.time_range.time_field_id not in known_fields:
                raise ValueError("timeRange references unknown timeFieldId")
            time_field = next(
                field for field in self.fields if field.field_id == self.time_range.time_field_id
            )
            if time_field.role is not FieldRole.TIME:
                raise ValueError("timeRange timeFieldId must reference role=time")
        return self


class FactUsageV2(ContractModelV2):
    condition_id: str = Field(min_length=1, max_length=120, description="Rule condition ID.")
    condition_path: str = Field(
        min_length=1,
        max_length=1_000,
        description="Slash-separated logical condition ID path.",
    )
    operator: RuleOperator = Field(description="Rule comparison operator using this fact.")
    expression_side: Literal["left", "right", "leftDerivation", "rightDerivation"] = Field(
        description="Expression side on which the atomic fact contributes."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs for the condition usage."
    )


class FactExampleV2(ContractModelV2):
    test_case_id: str = Field(min_length=1, max_length=120, description="Rule test-case ID.")
    value: BindingExampleValue = Field(description="Fact value supplied by the test case.")
    expected_rule_result: Literal["pass", "fail"] = Field(
        description="Expected result of the full rule, not merely this fact."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs for the source test case."
    )


class BindingMappingCandidateV2(ContractModelV2):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"mappingStatus": {"const": "mapped"}}},
                    "then": {
                        "properties": {
                            "viewName": {"type": "string"},
                            "viewField": {"type": "string"},
                        }
                    },
                    "else": {
                        "properties": {
                            "viewName": {"type": "null"},
                            "viewField": {"type": "null"},
                            "viewActive": {"type": "null"},
                        }
                    },
                }
            ]
        }
    )

    fact_code: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=160,
        description="Fact code to which this mapping hint belongs.",
    )
    mapping_status: MappingStatus = Field(description="Whether a catalog field was matched.")
    view_name: str | None = Field(
        max_length=150, description="Candidate view/relation name, or null when unresolved."
    )
    view_field: str | None = Field(
        max_length=150, description="Candidate output field, or null when unresolved."
    )
    view_active: bool | None = Field(description="Catalog activity hint, or null.")
    review_status: Literal["candidate"] = Field(
        description="Mapping is never promoted to approved by RuleReader."
    )
    note: str = Field(
        min_length=1, max_length=1_000, description="Human-review note without executable SQL."
    )

    @model_validator(mode="after")
    def validate_shape(self) -> BindingMappingCandidateV2:
        if self.mapping_status is MappingStatus.MAPPED:
            if self.view_name is None or self.view_field is None:
                raise ValueError("mapped candidate requires viewName and viewField")
        elif any((self.view_name, self.view_field, self.view_active is not None)):
            raise ValueError("unresolved candidate cannot contain view details")
        return self


class BindingSourceProvenanceV2(ContractModelV2):
    source_name: str = Field(
        min_length=1, max_length=255, description="Original local or inline source file name."
    )
    relative_path: str | None = Field(
        max_length=1_000,
        description="Path relative to the configured document root, or null for inline input.",
    )
    sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$", description="SHA-256 of normalized source content."
    )
    character_count: int = Field(ge=1, description="Normalized source character count.")


class BindingParserProvenanceV2(ContractModelV2):
    parser_version: str = Field(
        min_length=1, max_length=80, description="RuleReader parser application version."
    )
    prompt_version: str = Field(
        min_length=1,
        max_length=120,
        description="Prompt contract version used to produce the rule draft.",
    )
    provider: ParserProvider = Field(
        description="DeepSeek generation or explicitly reviewed offline import provenance."
    )
    model: str = Field(min_length=1, max_length=160, description="Configured model ID.")


class BindingEvidenceV2(ContractModelV2):
    evidence_id: str = Field(
        pattern=r"^[a-z][A-Za-z0-9_.:-]*$",
        max_length=200,
        description="Request-local evidence identifier.",
    )
    kind: EvidenceKind = Field(description="Type of structured rule evidence.")
    source_path: str = Field(
        pattern=r"^/",
        max_length=1_000,
        description="RFC 6901 JSON Pointer into the immutable RuleParseResultV2 document.",
    )


class BindingProvenanceV2(ContractModelV2):
    source: BindingSourceProvenanceV2 = Field(description="Original rule source identity.")
    parser: BindingParserProvenanceV2 = Field(description="Parser and model identity.")
    generated_at: datetime = Field(description="UTC timestamp of the source rule draft.")
    evidence: list[BindingEvidenceV2] = Field(
        min_length=2, description="Evidence registry referenced throughout this request."
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence(self) -> BindingProvenanceV2:
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("provenance evidence cannot contain duplicate evidenceId values")
        return self


class BindingUncertaintyV2(ContractModelV2):
    uncertainty_id: str = Field(
        pattern=r"^[a-z][A-Za-z0-9_.:-]*$",
        max_length=200,
        description="Stable request-local uncertainty identifier.",
    )
    code: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]*$",
        max_length=120,
        description="Stable machine-readable uncertainty code.",
    )
    category: UncertaintyCategory = Field(description="Affected query requirement category.")
    field_path: str = Field(
        pattern=r"^/",
        max_length=1_000,
        description="JSON Pointer to the affected field in this binding request.",
    )
    impact: UncertaintyImpact = Field(
        description="blocking prevents safe SQL generation; warning requires review."
    )
    reason: str = Field(
        min_length=1,
        max_length=2_000,
        description="Why RuleReader cannot make a stronger assertion.",
    )
    resolution_hint: str | None = Field(
        max_length=2_000, description="Non-executable guidance for resolving the uncertainty."
    )
    evidence_ids: list[str] = Field(
        min_length=1, description="Evidence registry IDs that establish the uncertainty."
    )


class FactBindingRequestV2(ContractModelV2):
    """Strict fact-level input contract for future Agent 2 SQL candidate generation."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        title="FactBindingRequest 2.0.0",
        json_schema_extra={
            "$schema": FACT_BINDING_SCHEMA_DIALECT,
            "$id": FACT_BINDING_SCHEMA_ID_V2,
        },
    )

    contract_version: Literal["2.0.0"] = Field(description="Fact handoff contract version.")
    status: Literal["candidate"] = Field(
        description="Request remains unapproved and non-executable."
    )
    request_id: str = Field(
        min_length=3, max_length=384, description="Deterministic ruleVersion#factCode identifier."
    )
    rule_ref: BindingRuleRefV2 = Field(description="Immutable source rule reference.")
    fact: BindableFactV2 = Field(description="Complete non-derived business fact contract.")
    query_requirements: QueryRequirementsV2 = Field(
        description="Structured logical requirements for a future SQL template."
    )
    usages: list[FactUsageV2] = Field(
        min_length=1, description="Every rule condition in which the atomic fact participates."
    )
    mapping_candidate: BindingMappingCandidateV2 = Field(
        description="Unapproved catalog mapping hint without SQL expressions."
    )
    examples: list[FactExampleV2] = Field(
        description="Fact-level values extracted from deterministic rule test cases."
    )
    provenance: BindingProvenanceV2 = Field(
        description="Source, parser, timestamp, and structured evidence registry."
    )
    uncertainties: list[BindingUncertaintyV2] = Field(
        description="Explicit unresolved or review-required query semantics."
    )
    target_dialect: Literal["sqlserver"] = Field(
        description="Only the initial SQL Server handoff dialect is allowed."
    )
    requires_metadata_snapshot: Literal[True] = Field(
        description="Agent 2 must combine this request with a governed metadata snapshot."
    )
    temp_table_allowed: Literal[False] = Field(
        description="Session temporary tables are forbidden for this contract."
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> FactBindingRequestV2:
        expected_request_id = f"{self.rule_ref.rule_version}#{self.fact.fact_code}"
        if self.request_id != expected_request_id:
            raise ValueError("requestId must equal ruleVersion#factCode")
        if self.mapping_candidate.fact_code != self.fact.fact_code:
            raise ValueError("mappingCandidate factCode must match fact.factCode")
        if self.provenance.source.sha256 != self.rule_ref.source_sha256:
            raise ValueError("provenance source hash must match ruleRef.sourceSha256")

        parameter_names = [parameter.name for parameter in self.fact.parameters]
        parameter_name_set = set(parameter_names)
        if self.query_requirements.entity.grain != self.fact.grain:
            raise ValueError("query entity grain must match fact grain")
        key_parameters = self.query_requirements.entity.key_parameters
        if unknown_keys := sorted(set(key_parameters) - parameter_name_set):
            raise ValueError(f"entity keyParameters are not fact parameters: {unknown_keys}")

        fields = {field.field_id: field for field in self.query_requirements.fields}
        value_field = fields["factValue"]
        if value_field.logical_name != self.fact.fact_code:
            raise ValueError("factValue logicalName must match factCode")
        actual_entity_keys = {
            field.logical_name for field in fields.values() if field.role is FieldRole.ENTITY_KEY
        }
        if actual_entity_keys != set(key_parameters):
            raise ValueError("entityKey fields must match entity.keyParameters")
        for item in self.query_requirements.filters.items:
            if isinstance(item.value, ParameterFilterValueV2):
                if item.value.parameter_name not in parameter_name_set:
                    raise ValueError("filter value references an unknown fact parameter")
        boundaries = [
            self.query_requirements.time_range.start,
            self.query_requirements.time_range.end,
        ]
        for boundary in boundaries:
            if (
                boundary is not None
                and boundary.kind is FilterValueKind.PARAMETER
                and boundary.parameter_name not in parameter_name_set
            ):
                raise ValueError("time boundary references an unknown fact parameter")

        result = self.query_requirements.result
        if (
            result.data_type != self.fact.data_type
            or result.nullable != self.fact.nullable
            or result.null_policy != self.fact.null_policy
            or result.unit != self.fact.unit
        ):
            raise ValueError("query result contract must match fact result semantics")

        evidence_ids = {item.evidence_id for item in self.provenance.evidence}
        referenced_evidence = {
            *self.query_requirements.entity.evidence_ids,
            *(
                evidence
                for field in self.query_requirements.fields
                for evidence in field.evidence_ids
            ),
            *self.query_requirements.filters.evidence_ids,
            *(
                evidence
                for item in self.query_requirements.filters.items
                for evidence in item.evidence_ids
            ),
            *self.query_requirements.aggregation.evidence_ids,
            *self.query_requirements.time_range.evidence_ids,
            *(evidence for usage in self.usages for evidence in usage.evidence_ids),
            *(evidence for example in self.examples for evidence in example.evidence_ids),
            *(
                evidence
                for uncertainty in self.uncertainties
                for evidence in uncertainty.evidence_ids
            ),
        }
        if unknown_evidence := sorted(referenced_evidence - evidence_ids):
            raise ValueError(f"unknown evidenceIds: {unknown_evidence}")

        uncertainty_ids = [item.uncertainty_id for item in self.uncertainties]
        if len(uncertainty_ids) != len(set(uncertainty_ids)):
            raise ValueError("uncertainties cannot contain duplicate uncertaintyId values")
        blocking_paths = {
            uncertainty.field_path
            for uncertainty in self.uncertainties
            if uncertainty.impact is UncertaintyImpact.BLOCKING
        }
        required_paths = {
            f"/queryRequirements/fields/{index}/sourceCandidate"
            for index, field in enumerate(self.query_requirements.fields)
            if field.resolution_status is ResolutionStatus.UNRESOLVED
        }
        if self.fact.data_type is FactDataType.UNKNOWN:
            required_paths.add("/fact/dataType")
        for index, field in enumerate(self.query_requirements.fields):
            if (
                field.source_candidate is not None
                and field.source_candidate.relation_active is not True
            ):
                required_paths.add(
                    f"/queryRequirements/fields/{index}/sourceCandidate/relationActive"
                )
        if self.query_requirements.entity.key_resolution_status is ResolutionStatus.UNRESOLVED:
            required_paths.add("/queryRequirements/entity/keyParameters")
        if self.query_requirements.filters.completeness is FilterCompleteness.UNRESOLVED:
            required_paths.add("/queryRequirements/filters/completeness")
        if self.query_requirements.aggregation.resolution_status is ResolutionStatus.UNRESOLVED:
            required_paths.add("/queryRequirements/aggregation")
        if self.query_requirements.time_range.resolution_status is ResolutionStatus.UNRESOLVED:
            required_paths.add("/queryRequirements/timeRange")
        if missing_uncertainties := sorted(required_paths - blocking_paths):
            raise ValueError(
                f"unresolved query requirements need blocking uncertainties: "
                f"{missing_uncertainties}"
            )
        return self


def fact_binding_request_schema_v2() -> dict[str, object]:
    """Return the canonical Draft 2020-12 JSON Schema for contract 2.0.0."""

    return FactBindingRequestV2.model_json_schema(by_alias=True, mode="validation")


def _binding_fact(fact: RequiredFactV2) -> BindableFactV2:
    payload = fact.model_dump(mode="json", exclude={"derivation"})
    payload["derivation"] = None
    return BindableFactV2.model_validate(payload)


def _atomic_fact_codes(
    code: str,
    facts: dict[str, RequiredFactV2],
    visiting: set[str] | None = None,
) -> set[str]:
    fact = facts[code]
    if fact.fact_kind is not FactKind.DERIVED or fact.derivation is None:
        return {code}
    active = set() if visiting is None else visiting
    if code in active:
        return set()
    active.add(code)
    result: set[str] = set()
    for dependency in expression_fact_refs(fact.derivation):
        result.update(_atomic_fact_codes(dependency, facts, active))
    active.remove(code)
    return result


def _collect_usages(
    node: ConditionNodeV2,
    facts: dict[str, RequiredFactV2],
    logical_path: tuple[str, ...],
    source_pointer: str,
    target: dict[str, list[FactUsageV2]],
    condition_evidence: dict[str, BindingEvidenceV2],
) -> None:
    current_path = (*logical_path, node.id)
    if node.kind is ConditionKindV2.COMPARE:
        assert node.operator is not None
        evidence_id = f"condition.{node.id}"
        condition_evidence[evidence_id] = BindingEvidenceV2(
            evidence_id=evidence_id,
            kind=EvidenceKind.CONDITION_USAGE,
            source_path=source_pointer,
        )
        for side, expression in (("left", node.left), ("right", node.right)):
            if expression is None:
                continue
            for reference in expression_fact_refs(expression):
                fact = facts[reference]
                atomic_codes = _atomic_fact_codes(reference, facts)
                derived = fact.fact_kind is FactKind.DERIVED
                usage_side = cast(
                    Literal["left", "right", "leftDerivation", "rightDerivation"],
                    f"{side}Derivation" if derived else side,
                )
                for atomic_code in atomic_codes:
                    target.setdefault(atomic_code, []).append(
                        FactUsageV2(
                            condition_id=node.id,
                            condition_path="/".join(current_path),
                            operator=node.operator,
                            expression_side=usage_side,
                            evidence_ids=[evidence_id],
                        )
                    )
    for index, child in enumerate(node.children):
        _collect_usages(
            child,
            facts,
            current_path,
            f"{source_pointer}/children/{index}",
            target,
            condition_evidence,
        )


def _mapping_candidate(result: RuleParseResultV2, fact_code: str) -> BindingMappingCandidateV2:
    mapping = next(item for item in result.rule.field_mappings if item.fact_code == fact_code)
    return BindingMappingCandidateV2.model_validate(
        mapping.model_dump(exclude={"source_expression"})
    )


def _field_requirements(
    fact: BindableFactV2,
    mapping: BindingMappingCandidateV2,
) -> list[FieldRequirementV2]:
    source_candidate = None
    resolution: Literal[
        ResolutionStatus.CANDIDATE,
        ResolutionStatus.UNRESOLVED,
    ] = ResolutionStatus.UNRESOLVED
    if mapping.mapping_status is MappingStatus.MAPPED:
        assert mapping.view_name is not None and mapping.view_field is not None
        source_candidate = SourceFieldCandidateV2(
            relation_name=mapping.view_name,
            field_name=mapping.view_field,
            relation_active=mapping.view_active,
            review_status="candidate",
        )
        resolution = ResolutionStatus.CANDIDATE
    fields = [
        FieldRequirementV2(
            field_id="factValue",
            role=FieldRole.VALUE,
            logical_name=fact.fact_code,
            data_type=fact.data_type,
            required=True,
            source_candidate=source_candidate,
            resolution_status=resolution,
            evidence_ids=["fact.declaration", "mapping.candidate"],
        )
    ]
    fields.extend(
        FieldRequirementV2(
            field_id=f"parameter.{parameter.name}",
            role=FieldRole.FILTER,
            logical_name=parameter.name,
            data_type=parameter.data_type,
            required=parameter.required,
            source_candidate=None,
            resolution_status=ResolutionStatus.UNRESOLVED,
            evidence_ids=["fact.declaration"],
        )
        for parameter in fact.parameters
    )
    return fields


def _filters(fact: BindableFactV2) -> FilterSetV2:
    return FilterSetV2(
        items=[
            FilterRequirementV2(
                filter_id=f"parameter.{parameter.name}",
                field_id=f"parameter.{parameter.name}",
                operator=RuleOperator.EQ,
                value=ParameterFilterValueV2(
                    kind=FilterValueKind.PARAMETER,
                    parameter_name=parameter.name,
                ),
                required=parameter.required,
                resolution_status=ResolutionStatus.UNRESOLVED,
                evidence_ids=["fact.declaration"],
            )
            for parameter in fact.parameters
        ],
        completeness=FilterCompleteness.UNRESOLVED,
        evidence_ids=["fact.declaration"],
    )


def _aggregation(
    fact: BindableFactV2,
    mapping: BindingMappingCandidateV2,
) -> AggregationRequirementV2:
    if fact.fact_kind is FactKind.SOURCE:
        mode = AggregationMode.NONE
        resolution = ResolutionStatus.DECLARED
    elif mapping.mapping_status is MappingStatus.MAPPED:
        mode = AggregationMode.PRECOMPUTED
        resolution = ResolutionStatus.CANDIDATE
    elif fact.fact_kind is FactKind.EXISTS:
        mode = AggregationMode.EXISTS
        resolution = ResolutionStatus.DECLARED
    else:
        mode = AggregationMode.UNRESOLVED
        resolution = ResolutionStatus.UNRESOLVED
    return AggregationRequirementV2(
        mode=mode,
        function=None,
        input_field_ids=[],
        group_by_field_ids=[],
        distinct=None,
        resolution_status=resolution,
        evidence_ids=["fact.declaration", "mapping.candidate"],
    )


def _query_requirements(
    result: RuleParseResultV2,
    fact: BindableFactV2,
    mapping: BindingMappingCandidateV2,
) -> QueryRequirementsV2:
    return QueryRequirementsV2(
        entity=EntityRequirementV2(
            entity_type=result.rule.entity_type,
            grain=fact.grain,
            key_parameters=[],
            resolution_status=ResolutionStatus.DECLARED,
            key_resolution_status=ResolutionStatus.UNRESOLVED,
            evidence_ids=["fact.declaration"],
        ),
        fields=_field_requirements(fact, mapping),
        filters=_filters(fact),
        aggregation=_aggregation(fact, mapping),
        time_range=TimeRangeRequirementV2(
            mode=TimeRangeMode.UNRESOLVED,
            time_field_id=None,
            start=None,
            end=None,
            timezone=None,
            resolution_status=ResolutionStatus.UNRESOLVED,
            evidence_ids=["fact.declaration"],
        ),
        result=FactResultRequirementV2(
            column_name="fact_value",
            data_type=fact.data_type,
            cardinality="scalar",
            nullable=fact.nullable,
            null_policy=fact.null_policy,
            unit=fact.unit,
        ),
    )


def _uncertainties(
    result: RuleParseResultV2,
    query: QueryRequirementsV2,
) -> list[BindingUncertaintyV2]:
    uncertainties: list[BindingUncertaintyV2] = []
    if query.result.data_type is FactDataType.UNKNOWN:
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id="fact.data-type",
                code="DATA_TYPE_UNRESOLVED",
                category=UncertaintyCategory.FIELD,
                field_path="/fact/dataType",
                impact=UncertaintyImpact.BLOCKING,
                reason="The rule draft does not declare a usable logical fact data type.",
                resolution_hint="Confirm the fact and scalar result data type before generation.",
                evidence_ids=["fact.declaration"],
            )
        )
    if query.entity.key_resolution_status is ResolutionStatus.UNRESOLVED:
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id="entity.key-parameters",
                code="ENTITY_KEY_UNRESOLVED",
                category=UncertaintyCategory.ENTITY,
                field_path="/queryRequirements/entity/keyParameters",
                impact=UncertaintyImpact.BLOCKING,
                reason=(
                    "Fact parameters are lookup inputs but the rule draft does not identify "
                    "which parameters are entity identity keys."
                ),
                resolution_hint=(
                    "Resolve entity identity parameters and their fields against governed metadata."
                ),
                evidence_ids=query.entity.evidence_ids,
            )
        )
    for index, field in enumerate(query.fields):
        if field.resolution_status is not ResolutionStatus.UNRESOLVED:
            continue
        code = {
            FieldRole.VALUE: "VALUE_FIELD_UNRESOLVED",
            FieldRole.ENTITY_KEY: "ENTITY_KEY_FIELD_UNRESOLVED",
        }.get(field.role, "FILTER_FIELD_UNRESOLVED")
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id=f"field.{field.field_id}",
                code=code,
                category=UncertaintyCategory.FIELD,
                field_path=f"/queryRequirements/fields/{index}/sourceCandidate",
                impact=UncertaintyImpact.BLOCKING,
                reason="The validated rule draft does not identify an approved physical field.",
                resolution_hint="Resolve the logical field against the governed metadata snapshot.",
                evidence_ids=field.evidence_ids,
            )
        )
    for index, field in enumerate(query.fields):
        if field.source_candidate is None or field.source_candidate.relation_active is True:
            continue
        unknown_state = field.source_candidate.relation_active is None
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id=f"source-state.{field.field_id}",
                code=(
                    "MAPPING_RELATION_STATE_UNKNOWN"
                    if unknown_state
                    else "MAPPING_RELATION_INACTIVE"
                ),
                category=UncertaintyCategory.SOURCE,
                field_path=(f"/queryRequirements/fields/{index}/sourceCandidate/relationActive"),
                impact=UncertaintyImpact.BLOCKING,
                reason=(
                    "The candidate relation activity state is unknown."
                    if unknown_state
                    else "The candidate relation is marked inactive in the RuleReader catalog."
                ),
                resolution_hint="Resolve the source against an active governed metadata snapshot.",
                evidence_ids=field.evidence_ids,
            )
        )
    uncertainties.append(
        BindingUncertaintyV2(
            uncertainty_id="filter.completeness",
            code="FILTER_SET_INCOMPLETE",
            category=UncertaintyCategory.FILTER,
            field_path="/queryRequirements/filters/completeness",
            impact=UncertaintyImpact.BLOCKING,
            reason=(
                "Rule schema 2.0 declares lookup parameters but has no separate, complete "
                "fact-retrieval predicate contract."
            ),
            resolution_hint=(
                "Confirm all parameter, literal, status, and scope predicates before "
                "SQL generation."
            ),
            evidence_ids=query.filters.evidence_ids,
        )
    )
    if query.aggregation.resolution_status is ResolutionStatus.UNRESOLVED:
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id="aggregation.mode",
                code="AGGREGATION_UNRESOLVED",
                category=UncertaintyCategory.AGGREGATION,
                field_path="/queryRequirements/aggregation",
                impact=UncertaintyImpact.BLOCKING,
                reason="The aggregate fact does not declare a controlled aggregation function.",
                resolution_hint=(
                    "Resolve aggregate function, input field, distinct behavior, and grouping."
                ),
                evidence_ids=query.aggregation.evidence_ids,
            )
        )
    uncertainties.append(
        BindingUncertaintyV2(
            uncertainty_id="time-range.mode",
            code="TIME_RANGE_UNRESOLVED",
            category=UncertaintyCategory.TIME_RANGE,
            field_path="/queryRequirements/timeRange",
            impact=UncertaintyImpact.BLOCKING,
            reason=(
                "The current rule fact contract does not state whether a time range is required."
            ),
            resolution_hint=(
                "Confirm not-applicable or provide a governed time field, bounds, and timezone."
            ),
            evidence_ids=query.time_range.evidence_ids,
        )
    )
    if result.source.relative_path is None:
        uncertainties.append(
            BindingUncertaintyV2(
                uncertainty_id="source.relative-path",
                code="SOURCE_RELATIVE_PATH_UNAVAILABLE",
                category=UncertaintyCategory.SOURCE,
                field_path="/provenance/source/relativePath",
                impact=UncertaintyImpact.WARNING,
                reason=(
                    "The rule was parsed from inline input and has no document-root relative path."
                ),
                resolution_hint="Use sourceName and source SHA-256 for traceability.",
                evidence_ids=["fact.declaration"],
            )
        )
    return uncertainties


def build_fact_binding_requests_v2(
    result: RuleParseResultV2,
) -> list[FactBindingRequestV2]:
    """Export one strict contract 2.0 request for every non-derived fact."""

    facts = {fact.fact_code: fact for fact in result.rule.required_facts}
    usages: dict[str, list[FactUsageV2]] = {}
    condition_evidence: dict[str, BindingEvidenceV2] = {}
    _collect_usages(
        result.rule.root_condition,
        facts,
        (),
        "/rule/rootCondition",
        usages,
        condition_evidence,
    )
    rule_ref = BindingRuleRefV2(
        rule_id=result.rule.rule_id,
        rule_version=result.rule_version,
        schema_version="2.0.0",
        source_sha256=result.source.sha256,
    )
    requests: list[FactBindingRequestV2] = []
    for fact_index, source_fact in enumerate(result.rule.required_facts):
        if source_fact.fact_kind is FactKind.DERIVED:
            continue
        fact = _binding_fact(source_fact)
        mapping_index = next(
            index
            for index, item in enumerate(result.rule.field_mappings)
            if item.fact_code == fact.fact_code
        )
        mapping = _mapping_candidate(result, fact.fact_code)
        unique_usages = list(
            {
                (
                    usage.condition_id,
                    usage.condition_path,
                    usage.operator,
                    usage.expression_side,
                ): usage
                for usage in usages.get(fact.fact_code, [])
            }.values()
        )
        examples: list[FactExampleV2] = []
        test_evidence: list[BindingEvidenceV2] = []
        for test_index, test in enumerate(result.rule.test_cases):
            if fact.fact_code not in test.given:
                continue
            evidence_id = f"test.{test.id}"
            test_evidence.append(
                BindingEvidenceV2(
                    evidence_id=evidence_id,
                    kind=EvidenceKind.TEST_CASE,
                    source_path=f"/rule/testCases/{test_index}",
                )
            )
            examples.append(
                FactExampleV2(
                    test_case_id=test.id,
                    value=test.given[fact.fact_code],
                    expected_rule_result=test.expected.value,
                    evidence_ids=[evidence_id],
                )
            )
        query = _query_requirements(result, fact, mapping)
        used_condition_ids = {
            evidence_id for usage in unique_usages for evidence_id in usage.evidence_ids
        }
        evidence = [
            BindingEvidenceV2(
                evidence_id="fact.declaration",
                kind=EvidenceKind.FACT_DECLARATION,
                source_path=f"/rule/requiredFacts/{fact_index}",
            ),
            BindingEvidenceV2(
                evidence_id="mapping.candidate",
                kind=EvidenceKind.MAPPING_CANDIDATE,
                source_path=f"/rule/fieldMappings/{mapping_index}",
            ),
            *(condition_evidence[evidence_id] for evidence_id in sorted(used_condition_ids)),
            *test_evidence,
        ]
        requests.append(
            FactBindingRequestV2(
                contract_version=FACT_BINDING_CONTRACT_VERSION_V2,
                status="candidate",
                request_id=f"{result.rule_version}#{fact.fact_code}",
                rule_ref=rule_ref,
                fact=fact,
                query_requirements=query,
                usages=unique_usages,
                mapping_candidate=mapping,
                examples=examples,
                provenance=BindingProvenanceV2(
                    source=BindingSourceProvenanceV2(
                        source_name=result.source.source_name,
                        relative_path=result.source.relative_path,
                        sha256=result.source.sha256,
                        character_count=result.source.character_count,
                    ),
                    parser=BindingParserProvenanceV2(
                        parser_version=result.parser.parser_version,
                        prompt_version=result.parser.prompt_version,
                        provider=result.parser.provider,
                        model=result.parser.model,
                    ),
                    generated_at=result.generated_at,
                    evidence=evidence,
                ),
                uncertainties=_uncertainties(result, query),
                target_dialect="sqlserver",
                requires_metadata_snapshot=True,
                temp_table_allowed=False,
            )
        )
    return requests
