from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from tests.support import valid_candidate_v2

from rule_reader.domain.rules.bindings import FactBindingRequestV1
from rule_reader.domain.rules.bindings_v2 import (
    FACT_BINDING_SCHEMA_DIALECT,
    FACT_BINDING_SCHEMA_ID_V2,
    AggregationRequirementV2,
    FactBindingRequestV2,
    TimeRangeRequirementV2,
    build_fact_binding_requests_v2,
    fact_binding_request_schema_v2,
)
from rule_reader.domain.rules.models import ParserMetadata, SourceMetadata
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import enrich_candidate_v2, validate_candidate_v2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "fact-binding-request-2.0.0.schema.json"
EXAMPLES_ROOT = PROJECT_ROOT / "contracts" / "examples"
VALID_V2_PATH = EXAMPLES_ROOT / "fact-binding-request-2.0.0.valid-unresolved.json"
INVALID_V2_PATH = EXAMPLES_ROOT / "fact-binding-request-2.0.0.invalid-missing-time-range.json"
LEGACY_V1_PATH = EXAMPLES_ROOT / "fact-binding-request-1.0.0.legacy.json"


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load_json(SCHEMA_PATH), format_checker=FormatChecker())


def _definition_validator(name: str) -> Draft202012Validator:
    schema = _load_json(SCHEMA_PATH)
    return Draft202012Validator(
        {
            "$schema": FACT_BINDING_SCHEMA_DIALECT,
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{name}",
        }
    )


def _result() -> RuleParseResultV2:
    candidate = RuleCandidateV2.model_validate(deepcopy(valid_candidate_v2()))
    validate_candidate_v2(candidate)
    return RuleParseResultV2(
        rule_version="TEST_RELEASE_002@20260824T000000000000Z-000000000000",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
        parser=ParserMetadata(
            parser_version="0.6.0",
            prompt_version="rule-parser-v6",
            model="fake-deepseek",
        ),
        source=SourceMetadata(
            source_name="test-release-rule.md",
            relative_path="examples/test-release-rule.md",
            sha256="0" * 64,
            character_count=100,
        ),
        rule=enrich_candidate_v2(candidate),
    )


def _keys_recursively(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key) for key in value),
            *(key for item in value.values() for key in _keys_recursively(item)),
        }
    if isinstance(value, list):
        return {key for item in value for key in _keys_recursively(item)}
    return set()


def test_checked_in_schema_is_current_strict_draft_2020_12() -> None:
    artifact = _load_json(SCHEMA_PATH)

    Draft202012Validator.check_schema(artifact)

    assert artifact == fact_binding_request_schema_v2()
    assert artifact["$schema"] == FACT_BINDING_SCHEMA_DIALECT
    assert artifact["$id"] == FACT_BINDING_SCHEMA_ID_V2
    assert artifact["additionalProperties"] is False
    assert artifact["properties"]["contractVersion"]["const"] == "2.0.0"
    assert set(artifact["required"]) == {
        "contractVersion",
        "status",
        "requestId",
        "ruleRef",
        "fact",
        "queryRequirements",
        "usages",
        "mappingCandidate",
        "examples",
        "provenance",
        "uncertainties",
        "targetDialect",
        "requiresMetadataSnapshot",
        "tempTableAllowed",
    }


def test_valid_unresolved_example_passes_schema_and_domain_contract() -> None:
    payload = _load_json(VALID_V2_PATH)

    _validator().validate(payload)
    request = FactBindingRequestV2.model_validate(payload)

    query = request.query_requirements
    assert query.entity.entity_type == "formal_test_task"
    assert query.fields
    assert query.filters.items
    assert query.aggregation.mode.value == "none"
    assert query.time_range.mode.value == "unresolved"
    assert query.result.column_name == "fact_value"
    assert {item.impact.value for item in request.uncertainties} == {"blocking"}
    assert "sourceExpression" not in _keys_recursively(payload)
    assert "sqlTemplate" not in _keys_recursively(payload)


def test_schema_and_domain_reject_missing_time_range_example() -> None:
    payload = _load_json(INVALID_V2_PATH)

    with pytest.raises(JsonSchemaValidationError) as schema_error:
        _validator().validate(payload)
    assert schema_error.value.validator == "required"
    assert list(schema_error.value.path) == ["queryRequirements"]

    with pytest.raises(PydanticValidationError, match="timeRange"):
        FactBindingRequestV2.model_validate(payload)


def test_contract_v1_remains_parseable_but_is_not_v2_compatible() -> None:
    payload = _load_json(LEGACY_V1_PATH)

    legacy = FactBindingRequestV1.model_validate(payload)
    assert legacy.model_dump(by_alias=True, mode="json") == payload

    with pytest.raises(JsonSchemaValidationError):
        _validator().validate(payload)
    with pytest.raises(PydanticValidationError):
        FactBindingRequestV2.model_validate(payload)


def test_schema_rejects_unknown_sql_field_and_wrong_contract_version() -> None:
    payload = _load_json(VALID_V2_PATH)
    payload["queryRequirements"]["sqlTemplate"] = "SELECT 1"
    with pytest.raises(JsonSchemaValidationError) as extra_error:
        _validator().validate(payload)
    assert extra_error.value.validator == "additionalProperties"

    payload = _load_json(VALID_V2_PATH)
    payload["contractVersion"] = "1.0.0"
    with pytest.raises(JsonSchemaValidationError) as version_error:
        _validator().validate(payload)
    assert version_error.value.validator == "const"


def test_aggregation_and_time_range_have_structured_validated_shapes() -> None:
    aggregation = {
        "mode": "compute",
        "function": "sum",
        "inputFieldIds": ["amountInput"],
        "groupByFieldIds": ["parameter.orderId"],
        "distinct": False,
        "resolutionStatus": "candidate",
        "evidenceIds": ["fact.declaration"],
    }
    time_range = {
        "mode": "between",
        "timeFieldId": "transactionAt",
        "start": {
            "kind": "parameter",
            "parameterName": "startAt",
            "value": None,
            "inclusive": True,
        },
        "end": {
            "kind": "parameter",
            "parameterName": "endAt",
            "value": None,
            "inclusive": False,
        },
        "timezone": "Asia/Shanghai",
        "resolutionStatus": "candidate",
        "evidenceIds": ["fact.declaration"],
    }

    _definition_validator("AggregationRequirementV2").validate(aggregation)
    _definition_validator("TimeRangeRequirementV2").validate(time_range)
    AggregationRequirementV2.model_validate(aggregation)
    TimeRangeRequirementV2.model_validate(time_range)

    invalid_aggregation = {**aggregation, "function": None}
    with pytest.raises(JsonSchemaValidationError):
        _definition_validator("AggregationRequirementV2").validate(invalid_aggregation)
    with pytest.raises(PydanticValidationError):
        AggregationRequirementV2.model_validate(invalid_aggregation)

    invalid_time_range = {**time_range, "end": None}
    with pytest.raises(JsonSchemaValidationError):
        _definition_validator("TimeRangeRequirementV2").validate(invalid_time_range)
    with pytest.raises(PydanticValidationError):
        TimeRangeRequirementV2.model_validate(invalid_time_range)


def test_domain_requires_blocking_uncertainty_for_every_unresolved_requirement() -> None:
    payload = _load_json(VALID_V2_PATH)
    payload["uncertainties"] = [
        item
        for item in payload["uncertainties"]
        if item["fieldPath"] != "/queryRequirements/timeRange"
    ]

    _validator().validate(payload)
    with pytest.raises(PydanticValidationError, match="blocking uncertainties"):
        FactBindingRequestV2.model_validate(payload)


def test_exported_requests_validate_and_express_query_gaps_without_sql() -> None:
    requests = build_fact_binding_requests_v2(_result())
    validator = _validator()

    assert {request.fact.fact_code for request in requests} == {
        "task.status",
        "task.received_amount",
        "task.base_fee",
        "task.extra_fee",
        "task.settlement_fee",
    }
    for request in requests:
        payload = request.model_dump(by_alias=True, mode="json")
        validator.validate(payload)
        assert request.request_id == f"{request.rule_ref.rule_version}#{request.fact.fact_code}"
        assert request.provenance.source.sha256 == request.rule_ref.source_sha256
        assert all(item.impact.value == "blocking" for item in request.uncertainties)
        assert "sourceExpression" not in _keys_recursively(payload)
        assert "sqlTemplate" not in _keys_recursively(payload)

    aggregate = next(
        request for request in requests if request.fact.fact_code == "task.received_amount"
    )
    assert aggregate.query_requirements.aggregation.mode.value == "unresolved"
    assert "AGGREGATION_UNRESOLVED" in {item.code for item in aggregate.uncertainties}
