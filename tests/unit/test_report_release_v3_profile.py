from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts.report_release_v3_profile import (
    _FACT_ROWS,
    _allowed_values,
    _candidate,
    validate_output_location,
)

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    catalog_digest_v3,
)
from rule_reader.domain.rules.readiness_v3 import (
    assess_v2_compatibility_v3,
    build_agent2_readiness_report_v3,
)
from rule_reader.domain.rules.validation_v3 import validate_rule_structure_candidate_v3


def _profile_catalog() -> BusinessConfirmedFactCatalogV3:
    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, fact_code in enumerate(_FACT_ROWS, start=1):
        evidence_id = f"confirmation.row.{index}"
        facts.append(
            {
                "factCode": fact_code,
                "name": f"合成事实 {index}",
                "description": "只用于有序 profile 离线测试。",
                "dataType": "string",
                "nullable": True,
                "nullPolicy": "indeterminate",
                "grain": "task",
                "parameters": [
                    {
                        "name": "taskId",
                        "role": "entityKey",
                        "dataType": "string",
                        "required": True,
                        "description": "合成任务标识。",
                    }
                ],
                "allowedValues": ["0", "1", "2", "7"],
                "unit": None,
                "evidenceRefs": [evidence_id],
                "bindingProfileRef": None,
                "bindingIssues": ["合成目录无物理绑定。"],
            }
        )
        evidence.append(
            {
                "evidenceId": evidence_id,
                "sourceKind": "businessConfirmation",
                "sourceId": "synthetic-workbook",
                "sourceSha256": "1" * 64,
                "locator": f"synthetic!A{index}",
                "note": "脱敏合成证据。",
            }
        )
    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": "REPORT_RELEASE_CONFIRMED_FACTS",
        "catalogVersion": "2026-09-05.1",
        "catalogDigest": "0" * 64,
        "facts": facts,
        "evidence": evidence,
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    return BusinessConfirmedFactCatalogV3.model_validate(payload)


def test_ordered_profile_preserves_rule_order_and_blockers() -> None:
    catalog = _profile_catalog()
    candidate = _candidate(catalog)
    validate_rule_structure_candidate_v3(candidate, catalog)
    rules = [rule for stage in candidate.stages for rule in stage.rules]
    assert len(rules) == 19
    assert sum(rule.status.value == "active" for rule in rules) == 3
    assert sum(rule.status.value == "blocked" for rule in rules) == 16
    eligibility = candidate.stages[2]
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


def test_confirmed_enum_parser_keeps_codes_as_strings_in_source_order() -> None:
    assert _allowed_values("0有1无") == ["0", "1"]
    assert _allowed_values('NORMAL = (0, "正常")\nFAILED = (2, "失败")') == ["0", "2"]


def test_profile_output_must_not_modify_fixed_private_bundle(tmp_path: Path) -> None:
    reference_root = tmp_path / "references"
    reference_root.mkdir()
    with pytest.raises(ValueError, match="outside"):
        validate_output_location(reference_root, reference_root / "derived")
    validate_output_location(reference_root, tmp_path / "recovery")


def test_current_sixteen_blockers_have_stable_classification_and_block_export() -> None:
    catalog = _profile_catalog()
    candidate = _candidate(catalog)
    report = build_agent2_readiness_report_v3(candidate, catalog)
    assert report.blocking_count == len(candidate.blocking_issues) == 16
    assert report.counts_by_code == {
        "BUSINESS_FACT_MISSING": 12,
        "SOURCE_BRANCH_UNREACHABLE_WITH_CONFIRMED_ENUM": 1,
        "SOURCE_VALUE_CONFLICT": 3,
    }
    assert {gap.stages[0] for gap in report.gaps} == {
        "stateGuards",
        "prerequisites",
        "eligibility",
        "postGates",
        "exclusions",
    }
    assert all(gap.blocks_agent2_handoff for gap in report.gaps)
    assert all(not gap.deterministic_fix_available for gap in report.gaps)
    assert report.planned_rule_versions == 0
    assert report.planned_handoffs == 0
    assert report.ready is False


def test_v2_remediation_is_rejected_for_ordered_v3_semantics() -> None:
    decision = assess_v2_compatibility_v3(
        v2_source_sha256="5" * 64,
        v3_source_sha256="6" * 64,
    )
    assert decision.selected_path == "B"
    assert decision.semantically_equivalent is False
    assert all(gate.result.value == "fail" for gate in decision.gates)
