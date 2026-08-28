from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from scripts.reviewed_report_release_all_001 import (
    audit_candidate as audit_legacy_candidate,
)
from scripts.reviewed_report_release_all_001 import (
    build_candidate_payload as build_legacy_candidate_payload,
)
from scripts.reviewed_report_release_all_001_remediation import (
    AUTHORING_MODEL,
    REVIEWED_IMPORT_VERSION,
    audit_candidate,
    build_candidate_payload,
)

from rule_reader.application.rule_parsing.reviewed_import import build_reviewed_rule_result
from rule_reader.domain.rules.bindings_v2 import (
    build_fact_binding_requests_v2,
    fact_binding_request_schema_v2,
)
from rule_reader.domain.rules.models import MappingStatus, ParserProvider
from rule_reader.domain.rules.v2 import (
    FactKind,
    RuleCandidateV2,
)
from rule_reader.domain.rules.v2 import (
    TestCategoryV2 as RuleTestCategory,
)
from rule_reader.domain.rules.validation_v2 import (
    SemanticValidationErrorV2,
    enrich_candidate_v2,
    validate_safe_structured_payload,
)


def _candidate() -> RuleCandidateV2:
    return RuleCandidateV2.model_validate(build_candidate_payload())


def test_frozen_20260824_profile_remains_reconstructable_but_is_now_rejected() -> None:
    candidate = RuleCandidateV2.model_validate(build_legacy_candidate_payload())
    rule = enrich_candidate_v2(candidate)
    canonical = json.dumps(
        rule.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        "a14796cf8231fffb485aca0fbf0f6c686f5dc7fb531a4d4c3cc7bedba71b9472"
    )
    with pytest.raises(SemanticValidationErrorV2, match="allowedValues"):
        audit_legacy_candidate(candidate)


def test_remediated_report_release_profile_passes_source_specific_audit() -> None:
    candidate = _candidate()

    summary = audit_candidate(candidate)

    assert summary == {
        "facts": 42,
        "nonDerivedFacts": 34,
        "derivedFacts": 8,
        "conditions": 67,
        "testCases": 31,
        "mappedFacts": 2,
        "bidirectionallyCoveredConditions": 67,
    }
    assert Counter(fact.fact_kind.value for fact in candidate.required_facts) == Counter(
        {"source": 18, "aggregate": 12, "exists": 4, "derived": 8}
    )
    assert {test.category for test in candidate.test_cases} == set(RuleTestCategory)
    assert candidate.root_condition.kind.value == "all"
    assert {
        mapping.fact_code
        for mapping in candidate.field_mappings
        if mapping.mapping_status is MappingStatus.MAPPED
    } == {"order.amount", "contract.current_order_meet_flag"}


def test_remediated_report_release_exports_every_non_derived_fact_as_strict_v2() -> None:
    candidate = _candidate()
    result = build_reviewed_rule_result(
        candidate,
        source_text="# reviewed remediation test source",
        source_name="项目报告释放规则.md",
        relative_path="项目报告释放规则.md",
        authoring_model=AUTHORING_MODEL,
        max_characters=100_000,
        reviewed_import_version=REVIEWED_IMPORT_VERSION,
        clock=lambda: datetime(2026, 8, 27, 0, 30, tzinfo=UTC),
    )

    requests = build_fact_binding_requests_v2(result)
    non_derived = {
        fact.fact_code
        for fact in candidate.required_facts
        if fact.fact_kind is not FactKind.DERIVED
    }
    validator = Draft202012Validator(
        fact_binding_request_schema_v2(),
        format_checker=FormatChecker(),
    )

    assert result.parser.provider is ParserProvider.REVIEWED_IMPORT
    assert result.parser.prompt_version == REVIEWED_IMPORT_VERSION
    assert all(mapping.review_status == "candidate" for mapping in result.rule.field_mappings)
    assert len(requests) == len(non_derived) == 34
    assert {request.fact.fact_code for request in requests} == non_derived
    assert all(request.contract_version == "2.0.0" for request in requests)
    assert all(
        any(item.impact.value == "blocking" for item in request.uncertainties)
        for request in requests
    )
    assert all(request.usages for request in requests)
    for request in requests:
        payload = request.model_dump(by_alias=True, mode="json")
        validator.validate(payload)
        validate_safe_structured_payload(payload)
        assert "sourceExpression" not in str(payload)

    rule_payload = result.model_dump(by_alias=True, mode="json")
    validate_safe_structured_payload(rule_payload)
    assert "sourceExpression" not in str(rule_payload)
