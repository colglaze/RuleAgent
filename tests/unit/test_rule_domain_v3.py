from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from tests.v3_fixtures import (
    blocked_rule_structure_candidate_v3,
    valid_fact_catalog_v3,
    valid_rule_structure_candidate_v3,
)

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    FactCatalogValidationErrorV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.v3 import RuleOutcomeV3, RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import (
    SemanticValidationErrorV3,
    evaluate_rule_structure_v3,
    validate_rule_reachability_witnesses_v3,
    validate_rule_structure_candidate_v3,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _contracts() -> tuple[BusinessConfirmedFactCatalogV3, RuleStructureCandidateV3]:
    catalog = BusinessConfirmedFactCatalogV3.model_validate(valid_fact_catalog_v3())
    candidate = RuleStructureCandidateV3.model_validate(valid_rule_structure_candidate_v3())
    return catalog, candidate


def test_v3_catalog_and_candidate_validate_together() -> None:
    catalog, candidate = _contracts()
    validate_fact_catalog_v3(catalog)
    validate_rule_structure_candidate_v3(candidate, catalog)


@pytest.mark.parametrize(
    ("schema_name", "valid_name", "invalid_name"),
    [
        (
            "business-confirmed-fact-catalog-3.0.0.schema.json",
            "business-confirmed-fact-catalog-3.0.0.valid.json",
            "business-confirmed-fact-catalog-3.0.0.invalid-missing-digest.json",
        ),
        (
            "rule-structure-candidate-3.0.0.schema.json",
            "rule-structure-candidate-3.0.0.valid.json",
            "rule-structure-candidate-3.0.0.invalid-missing-default.json",
        ),
    ],
)
def test_v3_checked_in_schema_accepts_valid_and_rejects_invalid_examples(
    schema_name: str, valid_name: str, invalid_name: str
) -> None:
    schema = json.loads((PROJECT_ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
    examples = PROJECT_ROOT / "contracts" / "examples"
    valid = json.loads((examples / valid_name).read_text(encoding="utf-8"))
    invalid = json.loads((examples / invalid_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(valid)
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(invalid)


def test_v3_catalog_digest_is_content_bound() -> None:
    payload = valid_fact_catalog_v3()
    payload["facts"][0]["description"] = "被修改"
    catalog = BusinessConfirmedFactCatalogV3.model_validate(payload)
    with pytest.raises(FactCatalogValidationErrorV3, match="catalogDigest"):
        validate_fact_catalog_v3(catalog)


def test_v3_rejects_duplicate_rule_codes_across_stages() -> None:
    catalog_payload = valid_fact_catalog_v3()
    candidate_payload = valid_rule_structure_candidate_v3()
    candidate_payload["stages"][4]["rules"][0]["ruleCode"] = "STATE_INVALID"
    catalog = BusinessConfirmedFactCatalogV3.model_validate(catalog_payload)
    candidate = RuleStructureCandidateV3.model_validate(candidate_payload)
    with pytest.raises(SemanticValidationErrorV3, match="duplicate ruleCode"):
        validate_rule_structure_candidate_v3(candidate, catalog)


def test_v3_rejects_unconfirmed_fact_in_active_condition() -> None:
    catalog, _ = _contracts()
    payload = valid_rule_structure_candidate_v3()
    payload["stages"][2]["rules"][0]["when"]["left"]["factCode"] = "report.unknown"
    payload["requiredFactCodes"].append("report.unknown")
    candidate = RuleStructureCandidateV3.model_validate(payload)
    with pytest.raises(SemanticValidationErrorV3, match="unconfirmed facts"):
        validate_rule_structure_candidate_v3(candidate, catalog)


def test_v3_blocked_rule_cannot_contain_when() -> None:
    payload = blocked_rule_structure_candidate_v3()
    payload["stages"][2]["rules"][0]["when"] = deepcopy(
        valid_rule_structure_candidate_v3()["stages"][2]["rules"][0]["when"]
    )
    with pytest.raises(ValidationError, match="blocked rules cannot"):
        RuleStructureCandidateV3.model_validate(payload)


def test_v3_candidate_level_blocker_is_indeterminate() -> None:
    catalog = BusinessConfirmedFactCatalogV3.model_validate(valid_fact_catalog_v3())
    candidate = RuleStructureCandidateV3.model_validate(blocked_rule_structure_candidate_v3())
    result = evaluate_rule_structure_v3(
        candidate,
        catalog,
        {"task.status_code": 19, "order.received_amount": 100},
    )
    assert result.outcome is RuleOutcomeV3.INDETERMINATE
    assert result.reason_code == "BUSINESS_CONFIRMATION_REQUIRED"


def test_v3_post_gate_can_downgrade_eligibility() -> None:
    catalog, candidate = _contracts()
    ready = evaluate_rule_structure_v3(
        candidate,
        catalog,
        {"task.status_code": 19, "order.received_amount": 100},
    )
    not_ready = evaluate_rule_structure_v3(
        candidate,
        catalog,
        {"task.status_code": 19, "order.received_amount": 5},
    )
    assert ready.outcome is RuleOutcomeV3.READY
    assert not_ready.outcome is RuleOutcomeV3.WAITING_CONDITIONS
    assert "LOW_AMOUNT_GATE" in not_ready.matched_rule_codes


def test_v3_state_guard_cannot_be_overridden_by_later_eligibility() -> None:
    catalog, candidate = _contracts()
    result = evaluate_rule_structure_v3(
        candidate,
        catalog,
        {"task.status_code": 20, "order.received_amount": 100},
    )
    assert result.outcome is RuleOutcomeV3.NO_RELEASE_REQUIRED
    assert result.matched_rule_codes == ("STATE_INVALID",)


def test_v3_missing_fact_is_not_treated_as_null() -> None:
    catalog, candidate = _contracts()
    result = evaluate_rule_structure_v3(candidate, catalog, {"task.status_code": 19})
    assert result.outcome is RuleOutcomeV3.INDETERMINATE
    assert result.reason_code == "FACT_VALUE_MISSING_OR_INVALID"


def test_v3_external_witnesses_prove_first_match_reachability() -> None:
    catalog, candidate = _contracts()
    validate_rule_reachability_witnesses_v3(
        candidate,
        catalog,
        {
            "STATE_INVALID": {"task.status_code": 20, "order.received_amount": 100},
            "AMOUNT_NEGATIVE": {"task.status_code": 19, "order.received_amount": -1},
            "AMOUNT_THRESHOLD": {"task.status_code": 19, "order.received_amount": 100},
            "LOW_AMOUNT_GATE": {"task.status_code": 19, "order.received_amount": 5},
            "CLOSED_TASK_EXCLUSION": {
                "task.status_code": 20,
                "order.received_amount": 100,
            },
        },
    )
