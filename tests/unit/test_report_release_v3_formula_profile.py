"""Offline tests for the 2026-09-20 report-side formula V3 profile."""

from __future__ import annotations

import json

from scripts.report_release_v3_formula_profile import (
    _FACT_SPECS,
    _STAGES,
    _WITNESSES,
    CATALOG_ID,
    CATALOG_VERSION,
    OLD_RULE_BLOCK_SHA256,
    PLAN_SHA256,
    RULE_BLOCK_CHARACTER_COUNT,
    RULE_BLOCK_SHA256,
    _assert_public_payload_is_safe,
    _base_given,
    build_formula_candidate,
    build_formula_catalog,
    build_formula_delivery,
    build_formula_test_cases,
)

from rule_reader.domain.rules.validation_v3 import (
    evaluate_rule_structure_v3,
    validate_rule_reachability_witnesses_v3,
)


def test_rule_block_identity_is_not_the_frozen_1402_block() -> None:
    assert RULE_BLOCK_CHARACTER_COUNT != 1402
    assert RULE_BLOCK_SHA256 != OLD_RULE_BLOCK_SHA256
    assert PLAN_SHA256 == "c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f"


def test_formula_candidate_is_fully_active_without_data_rules() -> None:
    catalog = build_formula_catalog()
    candidate = build_formula_candidate(catalog)
    rules = [rule for stage in candidate.stages for rule in stage.rules]
    codes = [rule.rule_code for rule in rules]
    assert catalog.catalog_id == CATALOG_ID
    assert catalog.catalog_version == CATALOG_VERSION
    assert all(rule.status.value == "active" for rule in rules)
    assert all(rule.when is not None for rule in rules)
    assert candidate.blocking_issues == []
    assert candidate.default_outcome.value == "WAITING_CONDITIONS"
    assert "DATA_RELEASE" not in codes
    assert not any(code.startswith("D") and code[1:].isdigit() for code in codes)
    assert [stage.stage.value for stage in candidate.stages] == [
        "stateGuards",
        "prerequisites",
        "eligibility",
        "postGates",
        "exclusions",
    ]
    eligibility = next(stage for stage in candidate.stages if stage.stage.value == "eligibility")
    assert [rule.rule_code for rule in eligibility.rules] == [
        "R0_ZERO_ORDER",
        "R1_SPECIAL_APPROVAL",
        "R9_BATCH_RELEASE",
        "R4_RAW_DATA_RELEASED",
        "R2_OVERSEAS_ORDER",
        "R3_SPECIAL_PRODUCT",
        "R8_TIME_TRIGGER",
        "R5_ENTERPRISE",
        "R6_NON_ENTERPRISE",
        "R7_FRAMEWORK",
    ]
    oa = next(rule for rule in rules if rule.rule_code == "OA_PROCESS_SCOPE")
    assert "在" in oa.title and "排除" in oa.title
    assert "必须位于" not in oa.title
    r9 = next(rule for rule in rules if rule.rule_code == "R9_BATCH_RELEASE")
    assert r9.when is not None
    assert r9.when.right is not None and r9.when.right.value == 0
    offline = next(rule for rule in rules if rule.rule_code == "OFFLINE_REPORT_RELEASED")
    assert offline.when is not None
    assert offline.when.right is not None and offline.when.right.value == 0


def test_formula_facts_are_not_collapsed_booleans() -> None:
    catalog = build_formula_catalog()
    candidate = build_formula_candidate(catalog)
    codes = set(candidate.required_fact_codes)
    assert "product.special_product_flag" not in codes
    assert "release.timed_release_eligible" not in codes
    assert "order.enterprise_non_framework_full_payment_eligible" not in codes
    assert "order.non_enterprise_release_eligible" not in codes
    assert "order.framework_release_eligible" not in codes
    assert "product.id" not in codes
    assert "task.product_id" in codes
    assert "task.product_type_code" in codes
    assert "task.task_amount" in codes
    assert "order.task_amount" not in codes
    assert "order.associated_receipts_including_deposit" in codes
    assert "order.in_scope_contract_count" in codes
    assert "order.unsealed_in_scope_contract_count" in codes
    assert "contract.receipt_status" not in codes
    assert "runtime.current_date" not in codes
    assert "rule.raw_data_completion_cutoff" not in codes
    grain_by_code = {spec["factCode"]: spec["grain"] for spec in _FACT_SPECS}
    assert grain_by_code["task.task_amount"] == "task"
    assert grain_by_code["task.product_id"] == "task"
    assert grain_by_code["task.product_type_code"] == "task"
    assert "evaluation" not in grain_by_code.values()
    assert "product" not in grain_by_code.values()
    kind_by_code = {spec["factCode"]: spec["kind"].value for spec in _FACT_SPECS}
    assert kind_by_code["release.special_application_count"] == "aggregate"
    assert kind_by_code["task.in_oa_process"] == "exists"
    assert kind_by_code["report.merge_group_eligible"] == "exists"
    assert all(kind_by_code[code] != "derived" for code in codes)


def test_formula_rules_have_reachability_witnesses() -> None:
    catalog = build_formula_catalog()
    candidate = build_formula_candidate(catalog)
    active_codes = {
        rule.rule_code
        for stage in candidate.stages
        for rule in stage.rules
        if rule.status.value == "active"
    }
    assert active_codes == set(_WITNESSES)
    validate_rule_reachability_witnesses_v3(candidate, catalog, _WITNESSES)


def test_formula_interpreter_cases() -> None:
    catalog = build_formula_catalog()
    candidate = build_formula_candidate(catalog)
    for case in build_formula_test_cases():
        evaluation = evaluate_rule_structure_v3(candidate, catalog, dict(case.given))
        assert evaluation.outcome is case.expected_outcome, case.case_id
        assert evaluation.reason_code == case.expected_reason_code, case.case_id
        assert list(evaluation.matched_rule_codes) == case.expected_matched_rule_codes, case.case_id


def test_formula_delivery_is_ready_and_safe() -> None:
    catalog, candidate, result, requests, readiness = build_formula_delivery()
    assert result.executable is False
    assert result.status == "draft"
    assert result.source.source_sha256 == RULE_BLOCK_SHA256
    assert result.source.source_character_count == RULE_BLOCK_CHARACTER_COUNT
    assert catalog.evidence[0].source_sha256 == PLAN_SHA256
    assert catalog.evidence[1].source_sha256 == RULE_BLOCK_SHA256
    assert readiness.ready is True
    assert readiness.blocking_count == 0
    assert result.rule_version.startswith("REPORT_RELEASE_ALL_001@")
    assert "f285643e5b2b" not in result.rule_version
    assert "82dbd05a800a" not in result.rule_version
    assert "20260920T085100" not in result.rule_version
    assert len(requests) == len(result.fact_declarations)
    grains = {request.fact.grain for request in requests}
    assert "evaluation" not in grains
    assert "product" not in grains
    assert all(request.fact.fact_code != "order.task_amount" for request in requests)
    assert all(
        not any(parameter.name == "productId" for parameter in request.fact.parameters)
        for request in requests
    )
    r6 = next(
        rule
        for stage in candidate.stages
        for rule in stage.rules
        if rule.rule_code == "R6_NON_ENTERPRISE"
    )
    dumped = json.dumps(r6.when.model_dump(mode="json", by_alias=True) if r6.when else {})
    assert "contract." not in dumped
    case_ids = {case.case_id for case in build_formula_test_cases()}
    assert {
        "r7-framework-pass",
        "r6-condition-b-seal-pass",
        "r6-condition-b-empty-contracts",
        "r8b-day-75",
        "r8c-day-180",
    } <= case_ids
    assert all(
        request.mapping_candidate.mapping_status.value == "unresolved" for request in requests
    )
    assert all(
        request.request_id == f"{result.rule_version}#{request.fact.fact_code}"
        for request in requests
    )
    _assert_public_payload_is_safe(catalog.model_dump(mode="json", by_alias=True))
    _assert_public_payload_is_safe(candidate.model_dump(mode="json", by_alias=True))
    _assert_public_payload_is_safe(result.model_dump(mode="json", by_alias=True))
    for request in requests:
        _assert_public_payload_is_safe(request.model_dump(mode="json", by_alias=True))
        assert request.query_requirements.filters.completeness == "complete"
        assert request.query_requirements.aggregation.mode.value in {
            "none",
            "precomputed",
            "compute",
            "exists",
        }
        assert request.query_requirements.time_range.mode.value in {"none", "asOf", "between"}


def test_offline_and_batch_active_compare_use_zero() -> None:
    given = _base_given()
    given["task.offline_report_release_flag"] = 4
    catalog = build_formula_catalog()
    candidate = build_formula_candidate(catalog)
    evaluation = evaluate_rule_structure_v3(candidate, catalog, given)
    assert evaluation.outcome.value != "ALREADY_RELEASED"
    given["task.offline_report_release_flag"] = 1
    given["task.batch_report_release_flag"] = 4
    evaluation = evaluate_rule_structure_v3(candidate, catalog, given)
    assert "R9_BATCH_RELEASE" not in evaluation.matched_rule_codes


def test_stage_table_covers_required_nodes() -> None:
    codes = [rule["ruleCode"] for stage in _STAGES for rule in stage["rules"]]
    assert "REPORT_STATUS_TERMINAL" in codes
    assert "MERGED_REPORT_GATE" in codes
    assert "OA_PROCESS_SCOPE" in codes
