from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.support import valid_candidate

from rule_reader.domain.rules.catalog import resolve_catalog_field
from rule_reader.domain.rules.models import RuleCandidate
from rule_reader.domain.rules.validation import (
    SemanticValidationError,
    enrich_candidate,
    validate_candidate,
)


def test_candidate_is_validated_and_catalogue_mapping_is_enriched() -> None:
    candidate = RuleCandidate.model_validate(valid_candidate())

    validate_candidate(candidate)
    parsed = enrich_candidate(candidate)

    mapping = next(item for item in parsed.field_mappings if item.fact_key == "settlement_fee")
    assert mapping.source_expression is not None
    assert "bcjsfy" in mapping.source_expression
    assert mapping.view_active is True
    assert mapping.review_status == "candidate"


def test_unknown_catalogue_field_is_rejected() -> None:
    payload = valid_candidate()
    payload["fieldMappings"][1]["viewField"] = "invented_field"
    candidate = RuleCandidate.model_validate(payload)

    with pytest.raises(SemanticValidationError, match="unknown catalogue field"):
        validate_candidate(candidate)


def test_unknown_condition_fact_is_rejected() -> None:
    payload = valid_candidate()
    payload["rootCondition"]["children"][0]["factKey"] = "missing_fact"
    candidate = RuleCandidate.model_validate(payload)

    with pytest.raises(SemanticValidationError, match="unknown facts"):
        validate_candidate(candidate)


def test_model_cannot_inject_trusted_version_metadata() -> None:
    payload = valid_candidate()
    payload["ruleVersion"] = "MODEL_CONTROLLED"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RuleCandidate.model_validate(payload)


def test_data_release_contract_view_is_catalogued_as_inactive() -> None:
    resolved = resolve_catalog_field("v_DataReleaseSealCondition", "dd_ismeet")

    assert resolved is not None
    view, field = resolved
    assert view.active is False
    assert "count_nomeet" in field.expression
