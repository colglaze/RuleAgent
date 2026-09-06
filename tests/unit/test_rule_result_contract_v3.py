from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from tests.v3_fixtures import valid_rule_parse_result_v3

from rule_reader.domain.rules.result_v3 import (
    RULE_PARSE_RESULT_SCHEMA_ID_V3,
    RuleParseResultV3,
    rule_parse_result_schema_v3,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "rule-parse-result-3.0.0.schema.json"
VALID_PATH = PROJECT_ROOT / "contracts" / "examples" / "rule-parse-result-3.0.0.valid.json"
INVALID_PATH = (
    PROJECT_ROOT / "contracts" / "examples" / "rule-parse-result-3.0.0.invalid-missing-facts.json"
)


def test_rule_result_v3_checked_in_schema_and_examples_are_current() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    valid = json.loads(VALID_PATH.read_text(encoding="utf-8"))
    invalid = json.loads(INVALID_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == rule_parse_result_schema_v3()
    assert schema["$id"] == RULE_PARSE_RESULT_SCHEMA_ID_V3
    Draft202012Validator(schema).validate(valid)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(invalid)
    assert RuleParseResultV3.model_validate(valid).schema_version == "3.0.0"


def test_rule_result_v3_schema_rejects_missing_fact_declarations() -> None:
    invalid = valid_rule_parse_result_v3()
    del invalid["factDeclarations"]
    with pytest.raises(ValidationError, match="factDeclarations"):
        RuleParseResultV3.model_validate(invalid)
