"""Hard gates: Agent1 3.1.0 trees must match the optimization-plan judgment."""

from __future__ import annotations

import json

from tests.optimization_plan_support import synthetic_source_identity

from rule_reader.domain.optimization_plan.coverage import COVERAGE_ROWS
from rule_reader.domain.optimization_plan.profile import build_both_deliveries
from rule_reader.domain.rules.purpose_v31 import HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION
from rule_reader.domain.rules.validation_v31 import evaluate_rule_structure_v31

_FORBIDDEN_PRIVATE_TOKENS = (
    "uf_dd",
    "formtable_",
    "v_sendreport",
    "SELECT ",
    "INSERT ",
    ".env",
    "D:\\\\Python",
)


def _walk(node: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    return found


def _rule_codes(candidate: object) -> list[str]:
    codes: list[str] = []
    for stage in candidate.stages:  # type: ignore[attr-defined]
        for rule in stage.rules:
            codes.append(rule.rule_code)
    return codes


def test_deliveries_are_unique_3_1_0_drafts() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    for delivery in (report, data):
        assert delivery.result.schema_version == "3.1.0"
        assert delivery.candidate.contract_version == "3.1.0"
        assert delivery.result.status == "draft"
        assert delivery.result.executable is False
        assert delivery.result.delivery_ref.purpose == "optimization-plan-generation"
        assert delivery.result.rule_version != HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION
        assert "f285643e5b2b" not in delivery.result.rule_version
        assert "20260917T140000" not in delivery.result.rule_version
        assert "20260920T092000" not in delivery.result.rule_version
        assert all(
            item.mapping_candidate.mapping_status.value == "unresolved"
            for item in delivery.requests
        )
    assert report.result.rule_set_id == "REPORT_RELEASE_ALL_001"
    assert data.result.rule_set_id == "RAW_DATA_RELEASE_ALL_001"
    assert report.catalog.catalog_version == "2026-09-20.3"
    assert data.catalog.catalog_version == "2026-09-20.3"


def test_r4_uses_presence_code_not_release_status() -> None:
    identity = synthetic_source_identity()
    report, _data = build_both_deliveries(identity)
    r4 = next(
        rule for stage in report.candidate.stages for rule in stage.rules if rule.rule_code == "R4"
    )
    payload = r4.when.model_dump(mode="json", by_alias=True)
    blob = json.dumps(payload)
    assert "task.raw_data_present_flag" in blob
    assert "data.release_status" not in blob
    assert "已释放" not in blob
    ids = {node.get("id") for node in _walk(payload) if isinstance(node, dict)}
    assert "r4-present" in ids
    assert "r4-date" in ids


def test_r6_seal_five_is_in_the_when_tree() -> None:
    identity = synthetic_source_identity()
    report, _data = build_both_deliveries(identity)
    r6 = next(
        rule for stage in report.candidate.stages for rule in stage.rules if rule.rule_code == "R6"
    )
    payload = r6.when.model_dump(mode="json", by_alias=True)
    kinds = {node.get("kind") for node in _walk(payload) if isinstance(node, dict)}
    ids = {node.get("id") for node in _walk(payload) if isinstance(node, dict)}
    assert "allMembers" in kinds
    assert "seal-five" in ids
    assert "r6-contracts" in ids
    members_node = next(node for node in _walk(payload) if node.get("id") == "r6-contracts")
    assert members_node["emptyCollectionPolicy"] == "fail"
    query = next(
        item
        for item in report.requests
        if item.fact.fact_code == "release.special_application_count"
    )
    field_ids = {field.field_id for field in query.query_requirements.fields}
    assert "application.type" in field_ids
    assert "approval.nodeType" in field_ids


def test_merge_group_is_all_members_not_eligible_boolean() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    codes = {fact.fact_code for fact in report.catalog.facts}
    assert "report.merge_group_eligible" not in codes
    assert "order.in_scope_contract_count" not in codes
    merge = next(
        rule
        for stage in report.candidate.stages
        for rule in stage.rules
        if rule.rule_code == "MERGE_GROUP_UNSATISFIED"
    )
    payload = merge.when.model_dump(mode="json", by_alias=True)
    members_node = next(node for node in _walk(payload) if node.get("id") == "merge-all-members")
    assert members_node["kind"] == "allMembers"
    assert members_node["emptyCollectionPolicy"] == "pass"
    assert members_node["missingMemberPolicy"] == "indeterminate"
    empty_post = next(stage for stage in data.candidate.stages if stage.stage.value == "postGates")
    assert empty_post.rules == []
    assert empty_post.empty_stage_reason is not None


def test_r5_r6_keep_non_framework_and_r8_keeps_go_live() -> None:
    identity = synthetic_source_identity()
    report, _data = build_both_deliveries(identity)
    blob = json.dumps(report.candidate.model_dump(mode="json", by_alias=True))
    assert "r5-non-framework" in blob
    assert "r6-non-framework" in blob
    assert "r8-go-live" in blob
    assert "timedReleaseEffectiveDate" in blob
    assert "0.1" in blob
    assert '"task.task_amount"' in blob
    assert '"task.product_id"' in blob
    assert '"task.product_type_code"' in blob


def test_every_rule_code_has_hit_and_miss_cases() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    for delivery in (report, data):
        for code in _rule_codes(delivery.candidate):
            hits = [
                item.case_id
                for item in delivery.result.test_cases
                if code in item.expected_matched_rule_codes
            ]
            misses = [
                item.case_id
                for item in delivery.result.test_cases
                if code not in item.expected_matched_rule_codes
            ]
            assert hits, f"{delivery.kind}:{code} has no hit case"
            assert misses, f"{delivery.kind}:{code} has no miss case"


def test_authored_case_expectations_are_verified_not_generated() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    assert COVERAGE_ROWS
    for delivery in (report, data):
        for case in delivery.result.test_cases:
            evaluation = evaluate_rule_structure_v31(
                delivery.candidate,
                delivery.catalog,
                dict(case.given),
                runtime=dict(case.runtime),
                members={item.member_key: dict(item.facts) for item in case.members},
            )
            assert evaluation.outcome == case.expected_outcome, case.case_id
            assert evaluation.reason_code == case.expected_reason_code, case.case_id
            assert list(evaluation.matched_rule_codes) == list(case.expected_matched_rule_codes), (
                case.case_id
            )


def test_synthetic_delivery_has_no_private_source_text() -> None:
    identity = synthetic_source_identity()
    report, data = build_both_deliveries(identity)
    blob = json.dumps(
        {
            "report": report.result.model_dump(mode="json", by_alias=True),
            "data": data.result.model_dump(mode="json", by_alias=True),
            "reportCandidate": report.candidate.model_dump(mode="json", by_alias=True),
            "dataCandidate": data.candidate.model_dump(mode="json", by_alias=True),
        }
    )
    lowered = blob.lower()
    for token in _FORBIDDEN_PRIVATE_TOKENS:
        assert token.lower() not in lowered, token
