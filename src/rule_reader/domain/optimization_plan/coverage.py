"""Source-node to condition to fact to case coverage for optimization-plan 3.1.0."""

from __future__ import annotations

COVERAGE_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "§1.3 report flags 3x3 + unknown",
        "NO_PROJECT_REPORT / REPORT_AVAILABILITY_PENDING",
        "task.project_report_flag, task.qc_report_flag",
        "report-flags-*, report-flags-missing-both, report-flags-0-missing",
    ),
    (
        "§1.3 / §5.2 offline/batch code 0",
        "OFFLINE_REPORT_RELEASED / R9",
        "task.offline_report_release_flag, task.batch_report_release_flag",
        "report-offline-0, report-offline-4-not-already, r9-batch-0, r9-batch-5-not-hit",
    ),
    ("§5.2 R0 zero amount, null continues", "R0", "order.amount", "r0-zero, r0-null-continues"),
    (
        "§5.2 R1 type+completed node, no de-dup",
        "R1",
        "release.special_application_count",
        "r1-count-positive, r1-duplicate-nodes, r1-no-match, r1-unknown",
    ),
    (
        "§5.2 R4 released + inclusive cutoff",
        "R4",
        "data.release_status, task.completion_date, runtime rawDataReleasedCutoffDate",
        "r4-on-cutoff, r4-after-cutoff, r4-before-cutoff",
    ),
    ("§5.2 R2 source 2", "R2", "order.source_code", "r2-overseas"),
    (
        "§5.2 R3 70/50 tier formulas",
        "R3",
        "product.id, order.extraction_qc_amount, task.amount, order.report_release_amount, order.arrival_amount_including_deposit",
        "r3-low-endpoint, r3-low-insufficient, r3-high-endpoint, r3-high-insufficient, r3-null-arrival",
    ),
    (
        "§5.2 R8 day equality and yeast branch",
        "R8",
        "task.completion_date, task.amount, order.invoice_amount, product.category_code, product.no_master_service_flag, runtime evaluationDate",
        "r8a-day-n, r8a-day-n-minus-1, r8a-day-n-plus-1, r8a-datetime-shanghai, r8b-day-n, r8c-day-n, r8-yeast, r8-before-go-live",
    ),
    (
        "§5.2 R5 enterprise 100%",
        "R5",
        "order.customer_org_type, order.framework_type, arrival and completed amounts",
        "r5-full-arrival, r5-boundary, r5-insufficient",
    ),
    (
        "§5.2 R6 A/B and five contract branches",
        "R6",
        "arrival, deposit, order.seal_scope_contract_ids, contract.*",
        "r6-condition-a, r6-condition-b, r6-empty-contracts, r6-contract-*",
    ),
    (
        "§5.2 R7 framework 80% or deposit 20%",
        "R7",
        "order.framework_type, arrival, deposit",
        "r7-arrival-80, r7-deposit-20",
    ),
    (
        "§1.3 combined-report all members",
        "MERGE_GROUP_UNSATISFIED",
        "report.merge_group_present, report.merge_group_member_ids, member snapshots",
        "merge-partial, merge-unknown-member, merge-empty, merge-duplicate-and-released",
    ),
    (
        "§1.3 project-report OA only",
        "OA_PROCESS_SCOPE",
        "task.in_project_report_release_oa",
        "oa-blocks-ready",
    ),
    (
        "eligibility first match then post-gates",
        "R0 then OA/merge",
        "order.amount plus post-gate facts",
        "first-hit-r0-over-r1, oa-blocks-ready, merge-partial",
    ),
    (
        "§1.3 D prerequisites and D0-D4",
        "DATA_* / D0-D4",
        "data catalog facts",
        "data-*, d0-*, d1-count, d2-overseas, d3-closed-loop, d4-*",
    ),
    (
        "§5.2 D4 single-cell extra branch",
        "D4",
        "product.category_code, order.closed_flag, order.sequencing_services_complete",
        "d4-single-cell-blocked, d4-single-cell-closed, d4-single-cell-sequencing",
    ),
)
