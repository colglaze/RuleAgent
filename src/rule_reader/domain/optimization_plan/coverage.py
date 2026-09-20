"""Source-node to condition to fact to case coverage for optimization-plan 3.1.0."""

from __future__ import annotations

from typing import NamedTuple


class CoverageRow(NamedTuple):
    source_node: str
    condition_ids: str
    facts: str
    hit_cases: tuple[str, ...]
    miss_cases: tuple[str, ...]
    matched_rule: str


COVERAGE_ROWS: tuple[CoverageRow, ...] = (
    CoverageRow(
        "§1.3 report flags 3x3 + unknown",
        "NO_PROJECT_REPORT / REPORT_AVAILABILITY_PENDING / both-absent / pending-has-report",
        "task.project_report_flag, task.qc_report_flag",
        ("report-flags-1-1", "report-flags-missing-both", "report-flags-0-missing"),
        ("report-flags-0-1", "report-flags-0-0"),
        "",
    ),
    CoverageRow(
        "§1.3 / §5.2 offline/batch code 0",
        "OFFLINE_REPORT_RELEASED / r9-batch",
        "task.offline_report_release_flag, task.batch_report_release_flag",
        ("report-offline-0", "r9-batch-0"),
        ("report-offline-4-not-already", "r9-batch-5-not-hit"),
        "",
    ),
    CoverageRow(
        "§5.2 R0 zero amount, null continues",
        "r0-zero",
        "order.amount",
        ("r0-zero",),
        ("r0-null-continues",),
        "R0",
    ),
    CoverageRow(
        "§5.2 R1 type+completed node, no de-dup",
        "r1-count",
        "release.special_application_count; query filters application type and completed node",
        ("r1-count-positive", "r1-duplicate-nodes"),
        ("r1-no-match", "r1-unknown"),
        "R1",
    ),
    CoverageRow(
        "§5.2 R4 presence code 0 + inclusive cutoff",
        "r4-present / r4-date",
        "task.raw_data_present_flag, task.completion_date, runtime rawDataReleasedCutoffDate",
        ("r4-on-cutoff", "r4-after-cutoff"),
        ("r4-before-cutoff", "r4-presence-1-on-cutoff", "r4-null-flag", "r4-null-date"),
        "R4",
    ),
    CoverageRow(
        "§5.2 R2 source 2",
        "r2-overseas",
        "order.source_code",
        ("r2-overseas",),
        ("r2-not-overseas",),
        "R2",
    ),
    CoverageRow(
        "§5.2 R3 70/50 tier formulas",
        "r3-special-and-tier / r3-low / r3-high",
        "task.product_id, order.extraction_qc_amount, task.task_amount, order.report_release_amount, order.arrival_amount_including_deposit",
        ("r3-low-endpoint", "r3-high-endpoint"),
        (
            "r3-low-insufficient",
            "r3-high-insufficient",
            "r3-null-arrival",
            "r3-insufficient-enterprise-not-r5",
        ),
        "R3",
    ),
    CoverageRow(
        "§5.2 R8 day equality, yeast, go-live",
        "r8-effective / r8a-day / r8b-day / r8c-day / r8-yeast",
        "task.completion_date, task.task_amount, order.invoice_amount, task.product_type_code, task.no_main_service_flag, runtime evaluationDate, timedReleaseEffectiveDate",
        (
            "r8a-day-n",
            "r8a-datetime-shanghai",
            "r8b-day-n",
            "r8c-day-n",
            "r8-yeast",
            "r8-yeast-on-go-live",
        ),
        ("r8a-day-n-minus-1", "r8a-day-n-plus-1", "r8-before-go-live", "r8-yeast-before-go-live"),
        "R8",
    ),
    CoverageRow(
        "§5.2 R5 enterprise 100% with non-framework preface",
        "r5-all / r5-non-framework / r5-pay",
        "order.customer_org_type, order.framework_type, arrival and completed amounts",
        ("r5-full-arrival", "r5-boundary"),
        ("r5-insufficient", "r5-framework-skips-to-r7", "r3-insufficient-enterprise-not-r5"),
        "R5",
    ),
    CoverageRow(
        "§5.2 R6 A/B and five contract branches",
        "r6-all / r6-a / r6-b / r6-contracts / seal-five",
        "arrival, deposit, order.seal_scope_contract_ids, contract.*",
        (
            "r6-condition-a",
            "r6-condition-b",
            "r6-contract-non-template",
            "r6-contract-small-quota",
            "r6-contract-after-cutoff-seal",
            "r6-contract-before-cutoff",
        ),
        (
            "r6-empty-contracts",
            "r6-contract-unsealed",
            "r6-contract-contact-esign-blocked",
            "r6-framework-skips-to-r7",
        ),
        "R6",
    ),
    CoverageRow(
        "§5.2 R7 framework 80% or deposit 20%",
        "r7-all / r7-pay / r7-deposit",
        "order.framework_type, arrival, deposit",
        ("r7-arrival-80", "r7-deposit-20", "r5-framework-skips-to-r7"),
        ("r7-insufficient",),
        "R7",
    ),
    CoverageRow(
        "§1.3 combined-report all members",
        "MERGE_GROUP_UNSATISFIED / merge-all-members",
        "report.merge_group_present, report.merge_group_member_ids, member snapshots",
        ("merge-partial",),
        ("merge-empty", "merge-duplicate-and-released", "merge-unknown-member"),
        "MERGE_GROUP_UNSATISFIED",
    ),
    CoverageRow(
        "§1.3 project-report OA only",
        "oa-in-process",
        "task.in_project_report_release_oa",
        ("oa-blocks-ready",),
        ("r0-zero",),
        "OA_PROCESS_SCOPE",
    ),
    CoverageRow(
        "eligibility first match then post-gates",
        "R0 then OA/merge",
        "order.amount plus post-gate facts",
        ("first-hit-r0-over-r1",),
        ("oa-blocks-ready", "merge-partial"),
        "",
    ),
    CoverageRow(
        "§1.3 D prerequisites and D0-D4",
        "DATA_* / d0-zero / d1-count / d2-overseas / d3-closed / d4-all",
        "data catalog facts",
        (
            "data-terminal",
            "data-not-completed",
            "data-lost",
            "data-offline-1",
            "data-absent",
            "d0-zero",
            "d1-count",
            "d2-overseas",
            "d3-closed-loop",
            "d4-non-single-cell",
        ),
        (
            "data-offline-0-not-already",
            "data-presence-null",
            "d0-null-continues",
            "d1-no-match",
            "d2-not-overseas",
            "d3-not-closed",
            "d4-insufficient",
        ),
        "",
    ),
    CoverageRow(
        "§5.2 D4 single-cell extra branch",
        "d4-single-cell / d4-experiment-complete",
        "task.product_type_code, order.closed_flag, order.experiment_run_status, order.sequencing_services_complete",
        ("d4-single-cell-closed", "d4-single-cell-sequencing", "d4-single-cell-terminated"),
        ("d4-single-cell-blocked", "d4-null-arrival"),
        "D4",
    ),
)
