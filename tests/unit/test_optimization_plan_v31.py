"""Offline tests for optimization-plan 3.1.0 identity, evaluation, and delivery."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError
from tests.optimization_plan_support import (
    SYNTHETIC_OPTIMIZATION_PLAN,
    synthetic_source_identity,
)

from rule_reader.domain.optimization_plan import (
    HISTORICAL_BLOCK_SHA256,
    OPTIMIZATION_PLAN_FILE_SHA256,
    REPORT_SPECIAL_APPLICATION_TYPE,
)
from rule_reader.domain.optimization_plan.coverage import COVERAGE_ROWS
from rule_reader.domain.optimization_plan.extractor import (
    SourceIdentityError,
    build_source_identity,
    extract_optimization_plan_sections,
    hash_file_bytes,
)
from rule_reader.domain.optimization_plan.profile import build_both_deliveries
from rule_reader.domain.optimization_plan.queries import build_query_for_fact
from rule_reader.domain.rules.purpose_v31 import (
    HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
    DeliveryPurposeDeniedError,
    DeliveryPurposeV31,
    assert_delivery_purpose_allowed,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v31 import evaluate_rule_structure_v31


def test_extractor_rejects_tampered_file_hash() -> None:
    payload = SYNTHETIC_OPTIMIZATION_PLAN.encode("utf-8")
    with pytest.raises(SourceIdentityError, match="source file hash"):
        build_source_identity(payload, SYNTHETIC_OPTIMIZATION_PLAN)


def test_extractor_requires_section_5_2_examples() -> None:
    text = SYNTHETIC_OPTIMIZATION_PLAN.replace("ReportZeroAmountRule", "MissingExample")
    payload = text.encode("utf-8")
    with pytest.raises(SourceIdentityError, match=r"5\.2"):
        build_source_identity(payload, text, expected_file_sha256=hash_file_bytes(payload))


def test_parse_input_hash_is_not_file_hash_or_historical_block() -> None:
    identity = synthetic_source_identity()
    assert identity.source_file_sha256 != identity.parse_input_sha256
    assert identity.source_file_sha256 != HISTORICAL_BLOCK_SHA256
    assert identity.parse_input_sha256 != HISTORICAL_BLOCK_SHA256
    assert identity.parse_input_sha256 != OPTIMIZATION_PLAN_FILE_SHA256
    extracted = extract_optimization_plan_sections(SYNTHETIC_OPTIMIZATION_PLAN)
    assert hashlib.sha256(extracted.encode("utf-8")).hexdigest() == identity.parse_input_sha256
    assert "### 5.6" not in extracted


def test_purpose_gate_rejects_historical_version_for_generation() -> None:
    with pytest.raises(DeliveryPurposeDeniedError):
        assert_delivery_purpose_allowed(
            HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        )
    assert_delivery_purpose_allowed(
        HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
        DeliveryPurposeV31.HISTORICAL_AUDIT,
    )


def test_frozen_3_0_0_rejects_runtime_parameter_and_all_members() -> None:
    with pytest.raises(ValidationError):
        RuleStructureCandidateV3.model_validate(
            {
                "contractVersion": "3.0.0",
                "runtimeParameters": [{"name": "evaluationDate"}],
            }
        )


def test_deliveries_export_and_independently_authored_cases_pass() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    assert report.result.executable is False and report.result.status == "draft"
    assert data.result.executable is False and data.result.status == "draft"
    assert report.result.rule_version != data.result.rule_version
    assert report.result.rule_version.startswith("REPORT_RELEASE_ALL_001@")
    assert data.result.rule_version.startswith("RAW_DATA_RELEASE_ALL_001@")
    assert report.result.source.source_sha256 == identity.source_file_sha256
    assert report.result.source.parse_input_sha256 == identity.parse_input_sha256
    assert identity.source_file_sha256[:12] in report.result.rule_version
    assert HISTORICAL_BLOCK_SHA256[:12] not in report.result.rule_version
    assert not any(item.uncertainties for item in report.result.fact_declarations)
    special = next(
        item
        for item in report.requests
        if item.fact.fact_code == "release.special_application_count"
    )
    filters = {item.filter_id: item for item in special.query_requirements.filters.items}
    assert filters["application-type"].value.literal == REPORT_SPECIAL_APPLICATION_TYPE
    assert filters["completed-approval-node"].value.literal == [3]
    assert special.query_requirements.aggregation.distinct is False
    merge = next(
        item for item in report.requests if item.fact.fact_code == "report.merge_group_member_ids"
    )
    assert merge.query_requirements.result.cardinality == "set"
    cutoff = next(
        item
        for item in report.candidate.runtime_parameters
        if item.name == "rawDataReleasedCutoffDate"
    )
    assert cutoff.bound_value == "2024-11-21"
    assert all(
        item.mapping_candidate.mapping_status.value == "unresolved" for item in report.requests
    )
    empty_post = next(stage for stage in data.candidate.stages if stage.stage.value == "postGates")
    assert empty_post.rules == []
    assert empty_post.empty_stage_reason is not None


def test_report_first_hit_and_post_gate_are_not_collapsed() -> None:
    identity = synthetic_source_identity()
    report, _data = build_both_deliveries(identity)
    first = next(
        item for item in report.result.test_cases if item.case_id == "first-hit-r0-over-r1"
    )
    evaluation = evaluate_rule_structure_v31(
        report.candidate,
        report.catalog,
        dict(first.given),
        runtime=dict(first.runtime),
        members={item.member_key: dict(item.facts) for item in first.members},
    )
    assert list(evaluation.matched_rule_codes) == ["R0"]
    blocked = next(item for item in report.result.test_cases if item.case_id == "oa-blocks-ready")
    blocked_eval = evaluate_rule_structure_v31(
        report.candidate,
        report.catalog,
        dict(blocked.given),
        runtime=dict(blocked.runtime),
        members={},
    )
    assert list(blocked_eval.matched_rule_codes) == ["R0", "OA_PROCESS_SCOPE"]


def test_r1_query_is_more_than_a_task_key() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    for delivery, expected_type in ((report, 1), (data, 2)):
        fact = next(
            item
            for item in delivery.catalog.facts
            if item.fact_code == "release.special_application_count"
        )
        query = build_query_for_fact(fact, rule_set=delivery.kind)
        field_ids = {field["fieldId"] for field in query["fields"]}
        assert {"application.type", "approval.nodeType", "application.rowId"} <= field_ids
        assert query["filters"]["items"][0]["value"]["literal"] == expected_type


def test_coverage_rows_point_at_real_cases() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    ids = {item.case_id for item in report.result.test_cases} | {
        item.case_id for item in data.result.test_cases
    }
    for _source, _rules, _facts, cases in COVERAGE_ROWS:
        for token in cases.split(","):
            token = token.strip()
            if token.endswith("*"):
                prefix = token[:-1]
                assert any(case_id.startswith(prefix) for case_id in ids), token
            else:
                assert token in ids, token
    assert report.catalog.catalog_digest != data.catalog.catalog_digest
    assert {fact.fact_code for fact in report.catalog.facts}.isdisjoint(
        {"task.raw_data_present_flag", "order.closed_loop_status"}
    )


def test_workbook_codes_are_not_plan_hit_codes() -> None:
    identity = synthetic_source_identity()
    report, _data = build_both_deliveries(identity)
    offline = next(
        item for item in report.result.test_cases if item.case_id == "report-offline-4-not-already"
    )
    batch = next(item for item in report.result.test_cases if item.case_id == "r9-batch-5-not-hit")
    assert offline.expected_reason_code == "NO_ORDERED_RELEASE_RULE_MATCHED"
    assert batch.expected_reason_code == "NO_ORDERED_RELEASE_RULE_MATCHED"
