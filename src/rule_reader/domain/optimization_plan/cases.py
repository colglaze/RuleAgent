"""Independently authored evaluation cases for the optimization-plan deliveries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rule_reader.domain.rules.v3 import RuleOutcomeV3

EVAL_DATE = "2026-09-17"
REPORT_RUNTIME = {"evaluationDate": EVAL_DATE}
DATA_RUNTIME = {"evaluationDate": EVAL_DATE}


def _case(
    case_id: str,
    description: str,
    given: dict[str, Any],
    outcome: str,
    reason: str,
    matched: list[str],
    *,
    runtime: dict[str, Any] | None = None,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "caseId": case_id,
        "description": description,
        "given": given,
        "runtime": runtime or dict(REPORT_RUNTIME),
        "members": members or [],
        "expectedOutcome": outcome,
        "expectedReasonCode": reason,
        "expectedMatchedRuleCodes": matched,
    }


def _overlay(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    payload = deepcopy(base)
    payload.update(changes)
    return payload


def _without(base: dict[str, Any], *keys: str) -> dict[str, Any]:
    payload = deepcopy(base)
    for key in keys:
        payload.pop(key, None)
    return payload


REPORT_BASE: dict[str, Any] = {
    "report.release_status": "等待满足条件",
    "task.status_code": 19,
    "task.experiment_status_code": 0,
    "task.offline_report_release_flag": 1,
    "task.batch_report_release_flag": 1,
    "task.project_report_flag": 0,
    "task.qc_report_flag": 1,
    "order.amount": 1000,
    "release.special_application_count": 0,
    "data.release_status": "等待满足条件",
    "task.completion_date": "2025-01-01",
    "order.source_code": 1,
    "product.id": 1,
    "product.category_code": 3,
    "product.no_master_service_flag": 1,
    "order.extraction_qc_amount": 0,
    "task.amount": 1000,
    "order.report_release_amount": 0,
    "order.arrival_amount_including_deposit": 0,
    "order.deposit_amount": 0,
    "order.invoice_amount": 0,
    "order.framework_type": 1,
    "order.customer_org_type": 1,
    "report.merge_group_present": False,
    "report.merge_group_member_ids": [],
    "order.seal_scope_contract_ids": [],
    "contract.template_kind": 1,
    "contract.effective_mode": 0,
    "contract.quota_kind": 1,
    "contract.countersign_date": "2022-01-01",
    "contract.receipt_status": 3,
    "contract.sign_method": 0,
    "task.in_project_report_release_oa": False,
}

DATA_BASE: dict[str, Any] = {
    "data.release_status": "等待满足条件",
    "task.status_code": 19,
    "task.data_lost_flag": 0,
    "task.offline_data_release_flag": 0,
    "task.raw_data_present_flag": 0,
    "order.amount": 1000,
    "release.special_application_count": 0,
    "order.source_code": 1,
    "order.closed_loop_status": 0,
    "order.extraction_qc_amount": 0,
    "task.amount": 1000,
    "order.data_release_amount": 0,
    "order.arrival_amount_including_deposit": 0,
    "product.category_code": 3,
    "order.closed_flag": 1,
    "order.experiment_run_status": 0,
    "order.sequencing_services_complete": False,
    "task.in_raw_data_release_oa": False,
}

_READY = RuleOutcomeV3.READY.value
_WAIT = RuleOutcomeV3.WAITING_CONDITIONS.value
_WAIT_DONE = RuleOutcomeV3.WAITING_COMPLETION.value
_NONE = RuleOutcomeV3.NO_RELEASE_REQUIRED.value
_ALREADY = RuleOutcomeV3.ALREADY_RELEASED.value
_SKIP = RuleOutcomeV3.SKIPPED.value
_IND = RuleOutcomeV3.INDETERMINATE.value


def _mini_contract() -> dict[str, Any]:
    return {
        "contract.quota_kind": 3,
        "contract.template_kind": 1,
        "contract.effective_mode": 0,
        "contract.countersign_date": "2024-01-01",
        "contract.receipt_status": 3,
        "contract.sign_method": 2,
    }


def report_test_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    flags = [
        (0, 0, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
        (0, 1, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
        (0, None, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
        (1, 0, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
        (1, 1, _NONE, "NO_PROJECT_REPORT_MATCHED", ["NO_PROJECT_REPORT"]),
        (1, None, _WAIT, "REPORT_AVAILABILITY_PENDING_MATCHED", ["REPORT_AVAILABILITY_PENDING"]),
        (None, 0, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
        (None, 1, _WAIT, "REPORT_AVAILABILITY_PENDING_MATCHED", ["REPORT_AVAILABILITY_PENDING"]),
        (None, None, _WAIT, "REPORT_AVAILABILITY_PENDING_MATCHED", ["REPORT_AVAILABILITY_PENDING"]),
        (2, 2, _WAIT, "REPORT_AVAILABILITY_PENDING_MATCHED", ["REPORT_AVAILABILITY_PENDING"]),
        (2, 0, _WAIT, "NO_ORDERED_RELEASE_RULE_MATCHED", []),
    ]
    for project, quality, outcome, reason, matched in flags:
        label = f"{project}-{quality}".replace("None", "null")
        cases.append(
            _case(
                f"report-flags-{label}",
                f"Report presence matrix project={project} quality={quality}.",
                _overlay(
                    REPORT_BASE,
                    **{"task.project_report_flag": project, "task.qc_report_flag": quality},
                ),
                outcome,
                reason,
                matched,
            )
        )
    cases.extend(
        [
            _case(
                "report-flags-missing-both",
                "Missing presence fields are undecided, not both-absent.",
                _without(REPORT_BASE, "task.project_report_flag", "task.qc_report_flag"),
                _WAIT,
                "REPORT_AVAILABILITY_PENDING_MATCHED",
                ["REPORT_AVAILABILITY_PENDING"],
            ),
            _case(
                "report-flags-0-missing",
                "Present-code 0 plus a missing peer still passes the present-OR.",
                _without(
                    _overlay(REPORT_BASE, **{"task.project_report_flag": 0}),
                    "task.qc_report_flag",
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "report-offline-4-not-already",
                "Workbook code 4 is not the optimization-plan offline hit code.",
                _overlay(REPORT_BASE, **{"task.offline_report_release_flag": 4}),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r9-batch-5-not-hit",
                "Workbook code 5 is not the optimization-plan batch hit code.",
                _overlay(REPORT_BASE, **{"task.batch_report_release_flag": 5}),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "report-terminal",
                "Terminal report status skips evaluation.",
                _overlay(REPORT_BASE, **{"report.release_status": "已释放"}),
                _SKIP,
                "REPORT_STATUS_TERMINAL_MATCHED",
                ["REPORT_STATUS_TERMINAL"],
            ),
            _case(
                "report-not-completed",
                "Null task status waits for completion.",
                _overlay(REPORT_BASE, **{"task.status_code": None}),
                _WAIT_DONE,
                "TASK_NOT_COMPLETED_MATCHED",
                ["TASK_NOT_COMPLETED"],
            ),
            _case(
                "report-experiment-offline",
                "Experiment status 2 requires no release.",
                _overlay(REPORT_BASE, **{"task.experiment_status_code": 2}),
                _NONE,
                "EXPERIMENT_STATUS_OFFLINE_MATCHED",
                ["EXPERIMENT_STATUS_OFFLINE"],
            ),
            _case(
                "report-experiment-problem",
                "Experiment status 7 requires no release.",
                _overlay(REPORT_BASE, **{"task.experiment_status_code": 7}),
                _NONE,
                "EXPERIMENT_STATUS_PROBLEM_MATCHED",
                ["EXPERIMENT_STATUS_PROBLEM"],
            ),
            _case(
                "report-offline-0",
                "Offline report flag 0 is already released.",
                _overlay(REPORT_BASE, **{"task.offline_report_release_flag": 0}),
                _ALREADY,
                "OFFLINE_REPORT_RELEASED_MATCHED",
                ["OFFLINE_REPORT_RELEASED"],
            ),
            _case(
                "r0-zero",
                "Order amount 0 hits R0.",
                _overlay(REPORT_BASE, **{"order.amount": 0}),
                _READY,
                "R0_MATCHED",
                ["R0"],
            ),
            _case(
                "r0-null-continues",
                "Null order amount does not hit R0 and continues.",
                _overlay(REPORT_BASE, **{"order.amount": None}),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r1-count-positive",
                "Completed special-application count greater than 0 hits R1.",
                _overlay(REPORT_BASE, **{"release.special_application_count": 1}),
                _READY,
                "R1_MATCHED",
                ["R1"],
            ),
            _case(
                "r1-duplicate-nodes",
                "Join-row count 2 from duplicate nodes still hits R1.",
                _overlay(REPORT_BASE, **{"release.special_application_count": 2}),
                _READY,
                "R1_MATCHED",
                ["R1"],
            ),
            _case(
                "r1-no-match",
                "Count 0 is no match, not unknown.",
                _overlay(REPORT_BASE, **{"release.special_application_count": 0}),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r1-unknown",
                "Missing special-application count is unknown.",
                _overlay(REPORT_BASE, **{"release.special_application_count": None}),
                _IND,
                "FACT_VALUE_MISSING_OR_INVALID",
                [],
            ),
            _case(
                "r9-batch-0",
                "Batch flag 0 hits R9.",
                _overlay(REPORT_BASE, **{"task.batch_report_release_flag": 0}),
                _READY,
                "R9_MATCHED",
                ["R9"],
            ),
            _case(
                "r4-on-cutoff",
                "Released raw data on the inclusive cutoff hits R4.",
                _overlay(
                    REPORT_BASE,
                    **{"data.release_status": "已释放", "task.completion_date": "2024-11-21"},
                ),
                _READY,
                "R4_MATCHED",
                ["R4"],
            ),
            _case(
                "r4-after-cutoff",
                "Released raw data after the cutoff hits R4.",
                _overlay(
                    REPORT_BASE,
                    **{"data.release_status": "已释放", "task.completion_date": "2024-11-22"},
                ),
                _READY,
                "R4_MATCHED",
                ["R4"],
            ),
            _case(
                "r4-before-cutoff",
                "Released raw data before the cutoff does not hit R4.",
                _overlay(
                    REPORT_BASE,
                    **{"data.release_status": "已释放", "task.completion_date": "2024-11-20"},
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r2-overseas",
                "Order source 2 hits R2.",
                _overlay(REPORT_BASE, **{"order.source_code": 2}),
                _READY,
                "R2_MATCHED",
                ["R2"],
            ),
            _case(
                "r3-low-endpoint",
                "Special product at 100000 uses 70 percent and meets the boundary.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "product.id": 759,
                        "task.amount": 100000,
                        "order.arrival_amount_including_deposit": 69999.9,
                    },
                ),
                _READY,
                "R3_MATCHED",
                ["R3"],
            ),
            _case(
                "r3-low-insufficient",
                "Special product 70 percent just below the boundary does not hit.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "product.id": 759,
                        "task.amount": 100000,
                        "order.arrival_amount_including_deposit": 69999.8,
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r3-high-endpoint",
                "Special product above 100000 uses 50 percent and meets the boundary.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "product.id": 759,
                        "task.amount": 100001,
                        "order.arrival_amount_including_deposit": 50000.4,
                    },
                ),
                _READY,
                "R3_MATCHED",
                ["R3"],
            ),
            _case(
                "r3-high-insufficient",
                "Special product 50 percent just below the boundary does not hit.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "product.id": 759,
                        "task.amount": 100001,
                        "order.arrival_amount_including_deposit": 50000.3,
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r3-null-arrival",
                "Special product with null arrival is unknown at R3.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "product.id": 759,
                        "task.amount": 100000,
                        "order.arrival_amount_including_deposit": None,
                    },
                ),
                _IND,
                "FACT_VALUE_MISSING_OR_INVALID",
                [],
            ),
            _case(
                "r8a-day-n",
                "Invoiced amount below 5000 hits R8 when completion plus 60 equals evaluation date.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 10,
                        "task.completion_date": "2026-04-02",
                    },
                ),
                _READY,
                "R8_MATCHED",
                ["R8"],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8a-day-n-minus-1",
                "Completion plus 60 on N-1 does not hit R8.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 10,
                        "task.completion_date": "2026-04-01",
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8a-day-n-plus-1",
                "Completion plus 60 on N+1 does not hit R8.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 10,
                        "task.completion_date": "2026-04-03",
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8a-datetime-shanghai",
                "Datetime time component is reduced to Asia/Shanghai calendar date.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 10,
                        "task.completion_date": "2026-04-02T22:00:00+08:00",
                    },
                ),
                _READY,
                "R8_MATCHED",
                ["R8"],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8b-day-n",
                "Not invoiced amount below 5000 hits R8 when completion plus 75 equals evaluation date.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 0,
                        "task.completion_date": "2026-03-18",
                    },
                ),
                _READY,
                "R8_MATCHED",
                ["R8"],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8c-day-n",
                "Amount at 5000 hits R8 when completion plus 180 equals evaluation date.",
                _overlay(
                    REPORT_BASE,
                    **{"task.amount": 5000, "task.completion_date": "2025-12-03"},
                ),
                _READY,
                "R8_MATCHED",
                ["R8"],
                runtime={"evaluationDate": "2026-06-01"},
            ),
            _case(
                "r8-yeast",
                "Yeast family with no master service hits R8 without calendar equality.",
                _overlay(
                    REPORT_BASE,
                    **{"product.category_code": 2, "product.no_master_service_flag": 0},
                ),
                _READY,
                "R8_MATCHED",
                ["R8"],
            ),
            _case(
                "r8-before-go-live",
                "Timed branch does not hit before the go-live date.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "task.amount": 4999,
                        "order.invoice_amount": 10,
                        "task.completion_date": "2026-02-13",
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
                runtime={"evaluationDate": "2026-04-14"},
            ),
            _case(
                "r5-full-arrival",
                "Non-framework enterprise 100 percent arrival hits R5.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.customer_org_type": 14,
                        "order.arrival_amount_including_deposit": 1000,
                    },
                ),
                _READY,
                "R5_MATCHED",
                ["R5"],
            ),
            _case(
                "r5-boundary",
                "Enterprise arrival plus epsilon equals completed amount.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.customer_org_type": 14,
                        "order.arrival_amount_including_deposit": 999.9,
                    },
                ),
                _READY,
                "R5_MATCHED",
                ["R5"],
            ),
            _case(
                "r5-insufficient",
                "Enterprise arrival just below 100 percent does not hit R5.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.customer_org_type": 14,
                        "order.arrival_amount_including_deposit": 999.8,
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r6-condition-a",
                "Non-enterprise non-framework 100 percent arrival hits R6 condition A.",
                _overlay(REPORT_BASE, **{"order.arrival_amount_including_deposit": 1000}),
                _READY,
                "R6_MATCHED",
                ["R6"],
            ),
            _case(
                "r6-condition-b",
                "R6 condition B: 80 percent arrival, 20 percent deposit, mini-program contract.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": ["C-MINI"],
                    },
                ),
                _READY,
                "R6_MATCHED",
                ["R6"],
                members=[{"memberKey": "C-MINI", "facts": _mini_contract()}],
            ),
            _case(
                "r6-empty-contracts",
                "R6 condition B fails on an empty seal scope.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": [],
                    },
                ),
                _WAIT,
                "NO_ORDERED_RELEASE_RULE_MATCHED",
                [],
            ),
            _case(
                "r6-contract-non-template",
                "R6 condition B non-template branch requires sealed receipt.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": ["C-NT"],
                    },
                ),
                _READY,
                "R6_MATCHED",
                ["R6"],
                members=[
                    {
                        "memberKey": "C-NT",
                        "facts": {
                            "contract.quota_kind": 1,
                            "contract.template_kind": 0,
                            "contract.receipt_status": 1,
                            "contract.effective_mode": 0,
                            "contract.countersign_date": "2024-01-01",
                            "contract.sign_method": 0,
                        },
                    }
                ],
            ),
            _case(
                "r6-contract-small-quota",
                "R6 condition B small-quota branch allows signed-not-sealed.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": ["C-SQ"],
                    },
                ),
                _READY,
                "R6_MATCHED",
                ["R6"],
                members=[
                    {
                        "memberKey": "C-SQ",
                        "facts": {
                            "contract.quota_kind": 0,
                            "contract.template_kind": 1,
                            "contract.receipt_status": 0,
                            "contract.effective_mode": 0,
                            "contract.countersign_date": "2024-01-01",
                            "contract.sign_method": 2,
                        },
                    }
                ],
            ),
            _case(
                "r6-contract-after-cutoff-seal",
                "R6 condition B after cutoff seal mode requires sealed receipt.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": ["C-C4"],
                    },
                ),
                _READY,
                "R6_MATCHED",
                ["R6"],
                members=[
                    {
                        "memberKey": "C-C4",
                        "facts": {
                            "contract.quota_kind": 1,
                            "contract.template_kind": 1,
                            "contract.receipt_status": 2,
                            "contract.effective_mode": 1,
                            "contract.countersign_date": "2023-11-01",
                            "contract.sign_method": 0,
                        },
                    }
                ],
            ),
            _case(
                "r6-contract-before-cutoff",
                "R6 condition B before cutoff allows sealed receipt.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.arrival_amount_including_deposit": 800,
                        "order.deposit_amount": 40,
                        "order.seal_scope_contract_ids": ["C-C5"],
                    },
                ),
                _READY,
                "R6_MATCHED",
                ["R6"],
                members=[
                    {
                        "memberKey": "C-C5",
                        "facts": {
                            "contract.quota_kind": 1,
                            "contract.template_kind": 1,
                            "contract.receipt_status": 1,
                            "contract.effective_mode": 1,
                            "contract.countersign_date": "2023-10-31",
                            "contract.sign_method": 2,
                        },
                    }
                ],
            ),
            _case(
                "r7-arrival-80",
                "Framework 80 percent arrival hits R7.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.framework_type": 0,
                        "order.arrival_amount_including_deposit": 800,
                    },
                ),
                _READY,
                "R7_MATCHED",
                ["R7"],
            ),
            _case(
                "r7-deposit-20",
                "Framework deposit 20 percent of unassociated arrival hits R7.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.framework_type": 2,
                        "order.arrival_amount_including_deposit": 100,
                        "order.deposit_amount": 180,
                    },
                ),
                _READY,
                "R7_MATCHED",
                ["R7"],
            ),
            _case(
                "first-hit-r0-over-r1",
                "R0 wins when R0 and R1 would both match.",
                _overlay(
                    REPORT_BASE, **{"order.amount": 0, "release.special_application_count": 3}
                ),
                _READY,
                "R0_MATCHED",
                ["R0"],
            ),
            _case(
                "merge-partial",
                "Preliminary R0 is blocked when a related member is unsatisfied.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.amount": 0,
                        "report.merge_group_present": True,
                        "report.merge_group_member_ids": ["T-OPEN"],
                    },
                ),
                _WAIT,
                "MERGE_GROUP_UNSATISFIED_MATCHED",
                ["R0", "MERGE_GROUP_UNSATISFIED"],
                members=[
                    {
                        "memberKey": "T-OPEN",
                        "facts": _overlay(
                            REPORT_BASE,
                            **{"task.status_code": 10, "report.release_status": "等待满足条件"},
                        ),
                    }
                ],
            ),
            _case(
                "merge-unknown-member",
                "Missing member snapshot makes the merge gate unknown.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.amount": 0,
                        "report.merge_group_present": True,
                        "report.merge_group_member_ids": ["T-MISSING"],
                    },
                ),
                _IND,
                "FACT_VALUE_MISSING_OR_INVALID",
                ["R0"],
            ),
            _case(
                "merge-empty",
                "Empty related-member set does not block R0.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.amount": 0,
                        "report.merge_group_present": True,
                        "report.merge_group_member_ids": [],
                    },
                ),
                _READY,
                "R0_MATCHED",
                ["R0"],
            ),
            _case(
                "merge-duplicate-and-released",
                "Duplicate member keys are unique-evaluated; released member is satisfied.",
                _overlay(
                    REPORT_BASE,
                    **{
                        "order.amount": 0,
                        "report.merge_group_present": True,
                        "report.merge_group_member_ids": ["T-REL", "T-REL"],
                    },
                ),
                _READY,
                "R0_MATCHED",
                ["R0"],
                members=[
                    {
                        "memberKey": "T-REL",
                        "facts": _overlay(REPORT_BASE, **{"report.release_status": "已释放"}),
                    }
                ],
            ),
            _case(
                "oa-blocks-ready",
                "Preliminary R0 is blocked by project-report OA exclusion.",
                _overlay(
                    REPORT_BASE,
                    **{"order.amount": 0, "task.in_project_report_release_oa": True},
                ),
                _WAIT,
                "OA_PROCESS_SCOPE_MATCHED",
                ["R0", "OA_PROCESS_SCOPE"],
            ),
        ]
    )
    return cases


def data_test_cases() -> list[dict[str, Any]]:
    return [
        _case(
            "data-terminal",
            "Terminal raw-data status skips evaluation.",
            _overlay(DATA_BASE, **{"data.release_status": "释放中"}),
            _SKIP,
            "DATA_STATUS_TERMINAL_MATCHED",
            ["DATA_STATUS_TERMINAL"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-not-completed",
            "Uncompleted task waits.",
            _overlay(DATA_BASE, **{"task.status_code": 10}),
            _WAIT_DONE,
            "TASK_NOT_COMPLETED_MATCHED",
            ["TASK_NOT_COMPLETED"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-lost",
            "Data-lost flag 1 requires no release.",
            _overlay(DATA_BASE, **{"task.data_lost_flag": 1}),
            _NONE,
            "DATA_LOST_MATCHED",
            ["DATA_LOST"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-offline-1",
            "Offline raw-data flag 1 is already released.",
            _overlay(DATA_BASE, **{"task.offline_data_release_flag": 1}),
            _ALREADY,
            "OFFLINE_DATA_RELEASED_MATCHED",
            ["OFFLINE_DATA_RELEASED"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-absent",
            "Raw-data absent-code 1 requires no release.",
            _overlay(DATA_BASE, **{"task.raw_data_present_flag": 1}),
            _NONE,
            "NO_RAW_DATA_MATCHED",
            ["NO_RAW_DATA"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-pending-flag",
            "Unknown raw-data presence waits.",
            _overlay(DATA_BASE, **{"task.raw_data_present_flag": 2}),
            _WAIT,
            "RAW_DATA_AVAILABILITY_PENDING_MATCHED",
            ["RAW_DATA_AVAILABILITY_PENDING"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d0-zero",
            "Zero-amount order hits D0.",
            _overlay(DATA_BASE, **{"order.amount": 0}),
            _READY,
            "D0_MATCHED",
            ["D0"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d0-null-continues",
            "Null amount does not hit D0.",
            _overlay(DATA_BASE, **{"order.amount": None}),
            _WAIT,
            "NO_ORDERED_RELEASE_RULE_MATCHED",
            [],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d1-count",
            "Completed raw-data special applications hit D1.",
            _overlay(DATA_BASE, **{"release.special_application_count": 1}),
            _READY,
            "D1_MATCHED",
            ["D1"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d2-overseas",
            "Overseas source hits D2.",
            _overlay(DATA_BASE, **{"order.source_code": 2}),
            _READY,
            "D2_MATCHED",
            ["D2"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d3-closed-loop",
            "Closed-loop status 2 hits D3.",
            _overlay(DATA_BASE, **{"order.closed_loop_status": 2}),
            _READY,
            "D3_MATCHED",
            ["D3"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d4-non-single-cell",
            "Non-single-cell 100 percent arrival hits D4.",
            _overlay(DATA_BASE, **{"order.arrival_amount_including_deposit": 1000}),
            _READY,
            "D4_MATCHED",
            ["D4"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d4-single-cell-blocked",
            "Single-cell 100 percent arrival without experiment complete does not hit D4.",
            _overlay(
                DATA_BASE,
                **{
                    "product.category_code": 1,
                    "order.arrival_amount_including_deposit": 1000,
                },
            ),
            _WAIT,
            "NO_ORDERED_RELEASE_RULE_MATCHED",
            [],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d4-single-cell-closed",
            "Single-cell extra branch passes when the order is closed.",
            _overlay(
                DATA_BASE,
                **{
                    "product.category_code": 14,
                    "order.arrival_amount_including_deposit": 1000,
                    "order.closed_flag": 0,
                },
            ),
            _READY,
            "D4_MATCHED",
            ["D4"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d4-single-cell-sequencing",
            "Single-cell extra branch passes when sequencing services are complete.",
            _overlay(
                DATA_BASE,
                **{
                    "product.category_code": 1,
                    "order.arrival_amount_including_deposit": 999.9,
                    "order.sequencing_services_complete": True,
                },
            ),
            _READY,
            "D4_MATCHED",
            ["D4"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "d4-insufficient",
            "Arrival just below 100 percent does not hit D4.",
            _overlay(DATA_BASE, **{"order.arrival_amount_including_deposit": 999.8}),
            _WAIT,
            "NO_ORDERED_RELEASE_RULE_MATCHED",
            [],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-first-hit-d0",
            "D0 wins when D0 and D1 would both match.",
            _overlay(DATA_BASE, **{"order.amount": 0, "release.special_application_count": 4}),
            _READY,
            "D0_MATCHED",
            ["D0"],
            runtime=dict(DATA_RUNTIME),
        ),
        _case(
            "data-oa-blocks",
            "Preliminary D0 is blocked by raw-data OA exclusion.",
            _overlay(DATA_BASE, **{"order.amount": 0, "task.in_raw_data_release_oa": True}),
            _WAIT,
            "OA_PROCESS_SCOPE_MATCHED",
            ["D0", "OA_PROCESS_SCOPE"],
            runtime=dict(DATA_RUNTIME),
        ),
    ]
