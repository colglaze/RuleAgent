"""Round 3: Runtime falsification tests.

Executes the REAL V3 evaluator to verify/deny semantic discrepancies.
Does NOT modify production code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import evaluate_rule_structure_v3

CONFIRMED_DIR = (
    Path(__file__).resolve().parents[2] / "generated-rules" / "report-release-v3-confirmed"
)


@pytest.fixture(scope="module")
def catalog() -> BusinessConfirmedFactCatalogV3:
    with open(CONFIRMED_DIR / "business-confirmed-fact-catalog-3.0.0.json", encoding="utf-8") as f:
        return BusinessConfirmedFactCatalogV3.model_validate(json.load(f))


@pytest.fixture(scope="module")
def candidate() -> RuleStructureCandidateV3:
    with open(CONFIRMED_DIR / "rule-structure-candidate-3.0.0.json", encoding="utf-8") as f:
        return RuleStructureCandidateV3.model_validate(json.load(f))


def _base_given() -> dict:
    return {
        "report.release_status": None,
        "task.status_code": "19",
        "task.experiment_status_code": "1",
        "task.offline_report_release_flag": "5",
        "task.batch_report_release_flag": "5",
        "task.project_report_flag": "0",
        "task.qc_report_flag": "0",
        "order.amount": 12000.0,
        "release.special_application_count": 0,
        "release.raw_data_released_after_cutoff": False,
        "order.source_code": None,
        "product.special_product_flag": False,
        "release.timed_release_eligible": False,
        "order.enterprise_non_framework_full_payment_eligible": False,
        "order.non_enterprise_release_eligible": False,
        "order.framework_release_eligible": False,
        "report.merge_group_eligible": True,
        "task.in_oa_process": False,
    }


# =============================================================================
# BUG-A: Report Flag Combination Semantics
# =============================================================================


class TestBugA_ReportFlagSemantics:
    """Authority: xmbg=0 OR zkqcbg=0 -> PASS."""

    def test_both_zero_passes(self, catalog, candidate):
        given = _base_given()
        given["task.project_report_flag"] = "0"
        given["task.qc_report_flag"] = "0"
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        # Should NOT be WAITING_CONDITIONS; should continue to eligibility
        assert result.outcome.value != "WAITING_CONDITIONS", (
            f"Both flags 0 should pass prerequisite, got {result.outcome.value}"
        )

    def test_project_zero_qc_null(self, catalog, candidate):
        """Authority: hasXmbg=true -> PASS.
        V3 Profile: REPORT_AVAILABILITY_UNKNOWN matches -> WAITING."""
        given = _base_given()
        given["task.project_report_flag"] = "0"
        given["task.qc_report_flag"] = None
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        # THIS IS THE MISMATCH CASE
        # Authority says PASS, V3 outputs WAITING
        print(
            f"\n[BUG-A] (project=0, qc=null): outcome={result.outcome.value}, "
            f"matched={result.matched_rule_codes}"
        )
        # We assert what the SYSTEM actually does, not what it should do
        assert result.outcome.value == "WAITING_CONDITIONS"
        assert "REPORT_AVAILABILITY_UNKNOWN" in result.matched_rule_codes

    def test_project_null_qc_zero(self, catalog, candidate):
        """Authority: hasZkqcbg=true -> PASS.
        V3 Profile: REPORT_AVAILABILITY_UNKNOWN matches -> WAITING."""
        given = _base_given()
        given["task.project_report_flag"] = None
        given["task.qc_report_flag"] = "0"
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        print(
            f"\n[BUG-A] (project=null, qc=0): outcome={result.outcome.value}, "
            f"matched={result.matched_rule_codes}"
        )
        assert result.outcome.value == "WAITING_CONDITIONS"
        assert "REPORT_AVAILABILITY_UNKNOWN" in result.matched_rule_codes

    def test_both_one_no_release(self, catalog, candidate):
        given = _base_given()
        given["task.project_report_flag"] = "1"
        given["task.qc_report_flag"] = "1"
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        assert result.outcome.value == "NO_RELEASE_REQUIRED"
        assert "NO_PROJECT_REPORT" in result.matched_rule_codes


# =============================================================================
# BUG-E: R3 Compound Amount Condition
# =============================================================================


class TestBugE_R3CompoundAmount:
    """Authority: cpId==759 AND compound amount condition.
    V3 Profile: special_product_flag==True -> READY (no amount check)."""

    def test_flag_true_outputs_ready(self, catalog, candidate):
        """V3 outputs READY when flag is True, regardless of amount."""
        given = _base_given()
        given["product.special_product_flag"] = True
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        print(
            f"\n[BUG-E] flag=True: outcome={result.outcome.value}, "
            f"matched={result.matched_rule_codes}"
        )
        # V3 outputs READY based on flag alone
        assert result.outcome.value == "READY"
        assert "R3_SPECIAL_PRODUCT" in result.matched_rule_codes

    def test_flag_false_no_match(self, catalog, candidate):
        given = _base_given()
        given["product.special_product_flag"] = False
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        # R3 should not match
        assert "R3_SPECIAL_PRODUCT" not in result.matched_rule_codes


# =============================================================================
# BUG-D: R1 Special Application Count Scope
# =============================================================================


class TestBugD_R1CountScope:
    """Authority: sqlx=1 AND currentnodetype IN (3) AND zssyrwdlc=?
    V3 Profile: count > 0 -> READY (filtering claimed in description)."""

    def test_count_positive_outputs_ready(self, catalog, candidate):
        given = _base_given()
        given["release.special_application_count"] = 3
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        print(
            f"\n[BUG-D] count=3: outcome={result.outcome.value}, "
            f"matched={result.matched_rule_codes}"
        )
        assert result.outcome.value == "READY"
        assert "R1_SPECIAL_APPROVAL" in result.matched_rule_codes

    def test_count_zero_no_match(self, catalog, candidate):
        given = _base_given()
        given["release.special_application_count"] = 0
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        assert "R1_SPECIAL_APPROVAL" not in result.matched_rule_codes

    def test_count_null_indeterminate(self, catalog, candidate):
        given = _base_given()
        given["release.special_application_count"] = None
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        # Null count should make the rule INDETERMINATE
        assert result.outcome.value == "INDETERMINATE"
