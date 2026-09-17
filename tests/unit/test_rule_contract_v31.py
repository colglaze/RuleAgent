from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from tests.v31_fixtures import (
    valid_fact_binding_request_v31,
    valid_rule_parse_result_v31,
    valid_rule_structure_candidate_v31,
)

from rule_reader.domain.rules.bindings_v31 import (
    FACT_BINDING_SCHEMA_ID_V31,
    FactBindingRequestV31,
    fact_binding_request_schema_v31,
)
from rule_reader.domain.rules.result_v31 import (
    RULE_PARSE_RESULT_SCHEMA_ID_V31,
    RuleParseResultV31,
    rule_parse_result_schema_v31,
)
from rule_reader.domain.rules.v31 import (
    RULE_STRUCTURE_SCHEMA_ID_V31,
    RuleStructureCandidateV31,
    rule_structure_candidate_schema_v31,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("schema_name", "valid_name", "invalid_name", "schema_factory", "schema_id"),
    [
        (
            "rule-structure-candidate-3.1.0.schema.json",
            "rule-structure-candidate-3.1.0.valid.json",
            "rule-structure-candidate-3.1.0.invalid-missing-runtime.json",
            rule_structure_candidate_schema_v31,
            RULE_STRUCTURE_SCHEMA_ID_V31,
        ),
        (
            "fact-binding-request-3.1.0.schema.json",
            "fact-binding-request-3.1.0.valid.json",
            "fact-binding-request-3.1.0.invalid-missing-query.json",
            fact_binding_request_schema_v31,
            FACT_BINDING_SCHEMA_ID_V31,
        ),
        (
            "rule-parse-result-3.1.0.schema.json",
            "rule-parse-result-3.1.0.valid.json",
            "rule-parse-result-3.1.0.invalid-missing-delivery.json",
            rule_parse_result_schema_v31,
            RULE_PARSE_RESULT_SCHEMA_ID_V31,
        ),
    ],
)
def test_v31_checked_in_schema_and_examples_are_current(
    schema_name: str,
    valid_name: str,
    invalid_name: str,
    schema_factory: object,
    schema_id: str,
) -> None:
    schema = json.loads((PROJECT_ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
    examples = PROJECT_ROOT / "contracts" / "examples"
    valid = json.loads((examples / valid_name).read_text(encoding="utf-8"))
    invalid = json.loads((examples / invalid_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == schema_factory()  # type: ignore[operator]
    assert schema["$id"] == schema_id
    Draft202012Validator(schema).validate(valid)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(invalid)


def test_v31_models_accept_synthetic_fixtures() -> None:
    candidate = RuleStructureCandidateV31.model_validate(valid_rule_structure_candidate_v31())
    request = FactBindingRequestV31.model_validate(valid_fact_binding_request_v31())
    result = RuleParseResultV31.model_validate(valid_rule_parse_result_v31())
    assert candidate.contract_version == "3.1.0"
    assert request.contract_version == "3.1.0"
    assert result.schema_version == "3.1.0"
    with pytest.raises(ValidationError):
        payload = valid_rule_structure_candidate_v31()
        del payload["runtimeParameters"]
        RuleStructureCandidateV31.model_validate(payload)
