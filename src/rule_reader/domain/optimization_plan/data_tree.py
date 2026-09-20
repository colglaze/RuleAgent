"""Raw-data rule tree expanded from optimization-plan §1.3 and §5.2."""

from __future__ import annotations

from typing import Any

from rule_reader.domain.optimization_plan import (
    CATALOG_VERSION,
    CLOSED_LOOP_STATUSES,
    DATA_CATALOG_ID,
    DATA_RULE_SET_ID,
    MONEY_COMPARISON_EPSILON,
    SINGLE_CELL_CATEGORY_CODES,
)
from rule_reader.domain.optimization_plan.expr import (
    add,
    all_of,
    any_of,
    coalesce,
    eq,
    fact,
    gt,
    gte,
    in_list,
    is_null,
    lit,
    ne,
    not_of,
    required_fact_codes_from_stages,
)
from rule_reader.domain.rules.v31 import default_stage_semantics_v31

TERMINAL_RELEASE_STATUSES = ["准备释放", "释放中", "已释放"]


def _node(
    code: str,
    priority: int,
    title: str,
    when: dict[str, Any],
    outcome: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ruleCode": code,
        "priority": priority,
        "title": title,
        "status": "active",
        "when": when,
        "outcome": outcome,
        "reasonCode": reason,
        "failureReason": title,
        "recommendations": ["Review against the optimization plan structure and examples."],
        "blockingIssueIds": [],
    }


def _data_completed_amount() -> dict[str, Any]:
    return add(
        fact("order.extraction_qc_amount"),
        fact("task.task_amount"),
        fact("order.data_release_amount"),
    )


def eligibility_d0() -> dict[str, Any]:
    return eq("d0-zero", "Order amount equals 0.", fact("order.amount"), 0, null_policy="fail")


def eligibility_d1() -> dict[str, Any]:
    return gt(
        "d1-count",
        "Completed raw-data special applications exist.",
        fact("release.special_application_count"),
        0,
        null_policy="indeterminate",
    )


def eligibility_d2() -> dict[str, Any]:
    return eq("d2-overseas", "Order source is overseas.", fact("order.source_code"), 2)


def eligibility_d3() -> dict[str, Any]:
    return in_list(
        "d3-closed",
        "Order closed-loop status is closed, terminated closed, or intervened closed.",
        fact("order.closed_loop_status"),
        list(CLOSED_LOOP_STATUSES),
    )


def eligibility_d4() -> dict[str, Any]:
    total = _data_completed_amount()
    single_cell = in_list(
        "d4-single-cell",
        "Product category is single-cell.",
        fact("task.product_type_code"),
        list(SINGLE_CELL_CATEGORY_CODES),
    )
    single_cell_extra = in_list(
        "d4-single-cell-extra",
        "Product category is single-cell.",
        fact("task.product_type_code"),
        list(SINGLE_CELL_CATEGORY_CODES),
    )
    experiment_complete = any_of(
        "d4-experiment-complete",
        "Closed, terminated, or every sequencing service is complete.",
        eq(
            "d4-closed-flag",
            "Order closed flag coalesced missing-as-1 equals 0.",
            coalesce(fact("order.closed_flag"), lit(1)),
            0,
        ),
        eq(
            "d4-terminated",
            "Experiment run status coalesced missing-as-0 equals 1.",
            coalesce(fact("order.experiment_run_status"), lit(0)),
            1,
        ),
        eq(
            "d4-seq-complete",
            "Sequencing services are complete.",
            fact("order.sequencing_services_complete"),
            True,
        ),
    )
    return all_of(
        "d4-all",
        "Full arrival, with an extra experiment-complete branch for single-cell.",
        gte(
            "d4-pay",
            "Arrival plus epsilon meets 100 percent of completed amount.",
            add(fact("order.arrival_amount_including_deposit"), lit(MONEY_COMPARISON_EPSILON)),
            total,
            null_policy="indeterminate",
        ),
        any_of(
            "d4-cell-gate",
            "Non-single-cell passes on amount; single-cell also needs experiment complete.",
            not_of(
                "d4-not-single-cell", "Category is not single-cell, including null.", single_cell
            ),
            all_of(
                "d4-single-extra",
                "Single-cell extra experiment branch.",
                single_cell_extra,
                experiment_complete,
            ),
        ),
    )


def data_runtime_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "evaluationDate",
            "dataType": "date",
            "role": "evaluationClock",
            "required": True,
            "description": "Unified evaluation calendar date in Asia/Shanghai used for as-of reads.",
        }
    ]


def build_data_stages() -> list[dict[str, Any]]:
    return [
        {
            "stage": "stateGuards",
            "rules": [
                _node(
                    "DATA_STATUS_TERMINAL",
                    10,
                    "Skip when raw-data status is already terminal.",
                    in_list(
                        "data-status-terminal",
                        "Raw-data status is a terminal in-progress or released state.",
                        fact("data.release_status"),
                        TERMINAL_RELEASE_STATUSES,
                    ),
                    "SKIPPED",
                    "DATA_STATUS_TERMINAL_MATCHED",
                )
            ],
        },
        {
            "stage": "prerequisites",
            "rules": [
                _node(
                    "TASK_NOT_COMPLETED",
                    10,
                    "Wait when the task is not completed.",
                    any_of(
                        "data-not-completed",
                        "Status is null or not 19.",
                        is_null(
                            "data-status-null", "Task status is null.", fact("task.status_code")
                        ),
                        ne(
                            "data-status-ne-19",
                            "Task status is not completed.",
                            fact("task.status_code"),
                            19,
                        ),
                    ),
                    "WAITING_COMPLETION",
                    "TASK_NOT_COMPLETED_MATCHED",
                ),
                _node(
                    "DATA_LOST",
                    20,
                    "No release when data-lost flag hit code is 1.",
                    eq("data-lost-1", "Data-lost flag is 1.", fact("task.data_lost_flag"), 1),
                    "NO_RELEASE_REQUIRED",
                    "DATA_LOST_MATCHED",
                ),
                _node(
                    "OFFLINE_DATA_RELEASED",
                    30,
                    "Already released when offline raw-data flag hit code is 1.",
                    eq(
                        "offline-data-1",
                        "Offline raw-data flag is 1.",
                        fact("task.offline_data_release_flag"),
                        1,
                    ),
                    "ALREADY_RELEASED",
                    "OFFLINE_DATA_RELEASED_MATCHED",
                ),
                _node(
                    "NO_RAW_DATA",
                    40,
                    "No release when raw data is absent-code 1.",
                    eq(
                        "raw-absent",
                        "Raw-data presence is absent.",
                        fact("task.raw_data_present_flag"),
                        1,
                    ),
                    "NO_RELEASE_REQUIRED",
                    "NO_RAW_DATA_MATCHED",
                ),
                _node(
                    "RAW_DATA_AVAILABILITY_PENDING",
                    50,
                    "Wait when raw-data presence is not decided.",
                    all_of(
                        "raw-pending",
                        "Neither present-code 0 nor absent-code 1.",
                        not_of(
                            "not-raw-present",
                            "Raw data is not present-code 0.",
                            eq(
                                "raw-present",
                                "Raw-data presence is present.",
                                fact("task.raw_data_present_flag"),
                                0,
                            ),
                        ),
                        not_of(
                            "not-raw-absent",
                            "Raw data is not absent-code 1.",
                            eq(
                                "raw-absent-pending",
                                "Raw-data presence is absent.",
                                fact("task.raw_data_present_flag"),
                                1,
                            ),
                        ),
                    ),
                    "WAITING_CONDITIONS",
                    "RAW_DATA_AVAILABILITY_PENDING_MATCHED",
                ),
            ],
        },
        {
            "stage": "eligibility",
            "rules": [
                _node("D0", 10, "Zero-amount order.", eligibility_d0(), "READY", "D0_MATCHED"),
                _node(
                    "D1",
                    20,
                    "Completed special application.",
                    eligibility_d1(),
                    "READY",
                    "D1_MATCHED",
                ),
                _node("D2", 30, "Overseas order source.", eligibility_d2(), "READY", "D2_MATCHED"),
                _node(
                    "D3", 40, "Closed-loop order status.", eligibility_d3(), "READY", "D3_MATCHED"
                ),
                _node(
                    "D4",
                    50,
                    "Full arrival with single-cell extra branch.",
                    eligibility_d4(),
                    "READY",
                    "D4_MATCHED",
                ),
            ],
        },
        {
            "stage": "postGates",
            "rules": [],
            "emptyStageReason": "Raw-data release has no merge-group post-gate in the optimization plan.",
        },
        {
            "stage": "exclusions",
            "rules": [
                _node(
                    "OA_PROCESS_SCOPE",
                    10,
                    "Wait when already in a raw-data release OA instance.",
                    eq(
                        "data-oa-in-process",
                        "Task is in a raw-data release OA instance.",
                        fact("task.in_raw_data_release_oa"),
                        True,
                    ),
                    "WAITING_CONDITIONS",
                    "OA_PROCESS_SCOPE_MATCHED",
                )
            ],
        },
    ]


def build_data_candidate_payload(
    catalog_digest: str, source_identity: dict[str, Any]
) -> dict[str, Any]:
    stages = build_data_stages()
    return {
        "contractVersion": "3.1.0",
        "ruleSetId": DATA_RULE_SET_ID,
        "title": "Optimization-plan raw data release",
        "scope": "Raw-data release evaluation for a completed experimental task.",
        "catalogId": DATA_CATALOG_ID,
        "catalogVersion": CATALOG_VERSION,
        "catalogDigest": catalog_digest,
        "sourceViews": ["optimization-plan"],
        "sourceIdentity": source_identity,
        "runtimeParameters": data_runtime_parameters(),
        "evaluationTimezone": "Asia/Shanghai",
        "requiredFactCodes": required_fact_codes_from_stages(stages),
        "stages": stages,
        "stageSemantics": {
            name: item.model_dump(mode="json", by_alias=True)
            for name, item in default_stage_semantics_v31().items()
        },
        "defaultOutcome": "WAITING_CONDITIONS",
        "defaultReasonCode": "NO_ORDERED_RELEASE_RULE_MATCHED",
        "blockingIssues": [],
        "proposedFacts": [],
    }
