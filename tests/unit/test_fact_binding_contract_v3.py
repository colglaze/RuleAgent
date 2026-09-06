from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from scripts.build_agent2_metadata_review_package import _validated_requests
from tests.v3_fixtures import valid_fact_binding_request_v3

from rule_reader.domain.rules.bindings_v3 import (
    FACT_BINDING_SCHEMA_ID_V3,
    FactBindingRequestV3,
    fact_binding_request_schema_v3,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "fact-binding-request-3.0.0.schema.json"
VALID_PATH = PROJECT_ROOT / "contracts" / "examples" / "fact-binding-request-3.0.0.valid.json"
INVALID_PATH = (
    PROJECT_ROOT
    / "contracts"
    / "examples"
    / "fact-binding-request-3.0.0.invalid-missing-query.json"
)


def test_v3_binding_checked_in_schema_and_examples_are_current() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    valid = json.loads(VALID_PATH.read_text(encoding="utf-8"))
    invalid = json.loads(INVALID_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == fact_binding_request_schema_v3()
    assert schema["$id"] == FACT_BINDING_SCHEMA_ID_V3
    validator = Draft202012Validator(schema)
    validator.validate(valid)
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(invalid)
    assert FactBindingRequestV3.model_validate(valid).contract_version == "3.0.0"


def test_v3_binding_requires_exact_rule_and_fact_identity() -> None:
    payload = valid_fact_binding_request_v3()
    payload["requestId"] += "-changed"
    with pytest.raises(ValidationError, match="ruleVersion#factCode"):
        FactBindingRequestV3.model_validate(payload)


def test_v3_binding_rejects_blocking_uncertainty_and_derived_fact() -> None:
    blocked = valid_fact_binding_request_v3()
    blocked["uncertainties"] = [
        {
            "uncertaintyId": "business.blocker",
            "code": "BUSINESS_FACT_MISSING",
            "impact": "blocking",
            "reason": "合成阻断。",
            "evidenceIds": ["fact.declaration"],
        }
    ]
    with pytest.raises(ValidationError, match="warning"):
        FactBindingRequestV3.model_validate(blocked)

    derived = deepcopy(valid_fact_binding_request_v3())
    derived["fact"]["factKind"] = "derived"
    with pytest.raises(ValidationError, match=r"source.*aggregate.*exists"):
        FactBindingRequestV3.model_validate(derived)


def test_v3_binding_requires_complete_evidence_closure() -> None:
    payload = valid_fact_binding_request_v3()
    payload["evidence"] = [
        item for item in payload["evidence"] if item["evidenceId"] != "condition.usage"
    ]
    with pytest.raises(ValidationError, match="unknown evidence"):
        FactBindingRequestV3.model_validate(payload)

    missing_document = valid_fact_binding_request_v3()
    del missing_document["evidence"][0]["sourceDocument"]
    with pytest.raises(ValidationError, match="sourceDocument"):
        FactBindingRequestV3.model_validate(missing_document)


def test_v3_binding_closes_provenance_and_rejects_unused_evidence() -> None:
    provenance_mismatch = valid_fact_binding_request_v3()
    provenance_mismatch["provenance"]["sourceSha256"] = "9" * 64
    with pytest.raises(ValidationError, match="sourceSha256"):
        FactBindingRequestV3.model_validate(provenance_mismatch)

    unused = valid_fact_binding_request_v3()
    unused["evidence"].append(
        {
            "evidenceId": "unused.entry",
            "kind": "sourceProvenance",
            "sourceDocument": "ruleResult",
            "sourcePath": "/source",
        }
    )
    with pytest.raises(ValidationError, match="unreferenced evidence"):
        FactBindingRequestV3.model_validate(unused)


def test_metadata_review_package_revalidates_requests_and_batch_identity() -> None:
    valid = valid_fact_binding_request_v3()
    assert len(_validated_requests([valid])) == 1
    with pytest.raises(ValueError, match="duplicate request IDs"):
        _validated_requests([valid, deepcopy(valid)])
    tampered = deepcopy(valid)
    tampered["requestId"] += "-tampered"
    with pytest.raises(ValidationError, match="ruleVersion#factCode"):
        _validated_requests([tampered])


def test_v3_binding_rejects_unknown_filter_parameter() -> None:
    payload = valid_fact_binding_request_v3()
    payload["queryRequirements"]["filters"]["items"][0]["value"]["parameterName"] = (
        "unknownParameter"
    )
    with pytest.raises(ValidationError, match="unknown fact parameter"):
        FactBindingRequestV3.model_validate(payload)
