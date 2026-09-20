"""Project-report rule tree expanded from optimization-plan §1.3 and §5.2."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rule_reader.domain.optimization_plan import (
    CATALOG_VERSION,
    CONTRACT_COUNTERSIGN_CUTOFF,
    ENTERPRISE_ORG_TYPES,
    FRAMEWORK_TYPES,
    MONEY_COMPARISON_EPSILON,
    RATIO_20,
    RATIO_50,
    RATIO_70,
    RATIO_80,
    RAW_DATA_RELEASED_CUTOFF,
    REPORT_CATALOG_ID,
    REPORT_RULE_SET_ID,
    SPECIAL_PRODUCT_ID,
    SPECIAL_PRODUCT_TIER_THRESHOLD,
    TIME_TRIGGER_AMOUNT_THRESHOLD,
    TIMED_RELEASE_EFFECTIVE_DATE,
    YEAST_CATEGORY_CODES,
)
from rule_reader.domain.optimization_plan.expr import (
    add,
    all_of,
    any_of,
    compare,
    date_add,
    eq,
    fact,
    gt,
    gte,
    in_list,
    is_null,
    lit,
    lt,
    mul,
    ne,
    not_of,
    param,
    required_fact_codes_from_stages,
    sub,
)
from rule_reader.domain.rules.models import RuleOperator
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


def _arrival_with_epsilon() -> dict[str, Any]:
    return add(fact("order.arrival_amount_including_deposit"), lit(MONEY_COMPARISON_EPSILON))


def _report_completed_amount() -> dict[str, Any]:
    return add(
        fact("order.extraction_qc_amount"),
        fact("task.task_amount"),
        fact("order.report_release_amount"),
    )


def _r3_base_amount() -> dict[str, Any]:
    return add(fact("order.extraction_qc_amount"), fact("task.task_amount"))


def eligibility_r0() -> dict[str, Any]:
    return eq("r0-zero", "Order amount equals 0.", fact("order.amount"), 0, null_policy="fail")


def eligibility_r1() -> dict[str, Any]:
    return gt(
        "r1-count",
        "Completed special applications exist.",
        fact("release.special_application_count"),
        0,
        null_policy="indeterminate",
    )


def eligibility_r9() -> dict[str, Any]:
    return eq(
        "r9-batch", "Batch release flag hit code is 0.", fact("task.batch_report_release_flag"), 0
    )


def eligibility_r4() -> dict[str, Any]:
    return all_of(
        "r4-present-and-date",
        "Raw-data presence code is 0 and completion date is on or after the cutoff.",
        eq(
            "r4-present",
            "Raw-data presence code is 0.",
            fact("task.raw_data_present_flag"),
            0,
        ),
        gte(
            "r4-date",
            "Completion date is on or after the inclusive cutoff.",
            fact("task.completion_date"),
            param("rawDataReleasedCutoffDate"),
            null_policy="fail",
        ),
    )


def eligibility_r2() -> dict[str, Any]:
    return eq("r2-overseas", "Order source is overseas.", fact("order.source_code"), 2)


def eligibility_r3() -> dict[str, Any]:
    base = _r3_base_amount()
    total = _report_completed_amount()
    return all_of(
        "r3-special-and-tier",
        "Special product and tiered arrival threshold.",
        eq(
            "r3-product",
            "Product is the special product.",
            fact("task.product_id"),
            SPECIAL_PRODUCT_ID,
        ),
        any_of(
            "r3-tiers",
            "Low tier uses 70 percent, high tier uses 50 percent.",
            all_of(
                "r3-low",
                "Base amount at or below the tier threshold uses 70 percent.",
                compare(
                    "r3-low-base",
                    "Base amount is at most the tier threshold.",
                    base,
                    RuleOperator.LTE,
                    lit(SPECIAL_PRODUCT_TIER_THRESHOLD),
                    null_policy="indeterminate",
                ),
                gte(
                    "r3-low-pay",
                    "Arrival plus epsilon meets 70 percent of completed amount.",
                    _arrival_with_epsilon(),
                    mul(total, lit(RATIO_70)),
                    null_policy="indeterminate",
                ),
            ),
            all_of(
                "r3-high",
                "Base amount above the tier threshold uses 50 percent.",
                gt(
                    "r3-high-base",
                    "Base amount is above the tier threshold.",
                    base,
                    SPECIAL_PRODUCT_TIER_THRESHOLD,
                    null_policy="indeterminate",
                ),
                gte(
                    "r3-high-pay",
                    "Arrival plus epsilon meets 50 percent of completed amount.",
                    _arrival_with_epsilon(),
                    mul(total, lit(RATIO_50)),
                    null_policy="indeterminate",
                ),
            ),
        ),
    )


def eligibility_r8() -> dict[str, Any]:
    yeast = all_of(
        "r8-yeast",
        "Yeast library family with no master service.",
        in_list(
            "r8-yeast-cat",
            "Category is a yeast library family.",
            fact("task.product_type_code"),
            YEAST_CATEGORY_CODES,
        ),
        eq(
            "r8-yeast-master",
            "No master service flag is 0.",
            fact("task.no_main_service_flag"),
            0,
        ),
    )
    not_yeast = not_of(
        "r8-not-yeast",
        "Category is not a yeast library family, including null.",
        in_list(
            "r8-yeast-cat-neg",
            "Category is a yeast library family.",
            fact("task.product_type_code"),
            YEAST_CATEGORY_CODES,
        ),
    )
    not_special = any_of(
        "r8-not-special",
        "Product is null or not the special product.",
        is_null("r8-product-null", "Product id is null.", fact("task.product_id")),
        ne(
            "r8-product-ne",
            "Product is not the special product.",
            fact("task.product_id"),
            SPECIAL_PRODUCT_ID,
        ),
    )
    timed = all_of(
        "r8-timed",
        "Non-yeast, non-special timed branches.",
        not_yeast,
        not_special,
        any_of(
            "r8-abc",
            "60, 75, or 180 calendar-day equality.",
            all_of(
                "r8a",
                "Amount below threshold, invoiced, completion plus 60 equals evaluation date.",
                lt(
                    "r8a-amt",
                    "Task amount is below the time-trigger threshold.",
                    fact("task.task_amount"),
                    TIME_TRIGGER_AMOUNT_THRESHOLD,
                    null_policy="indeterminate",
                ),
                gt(
                    "r8a-invoiced",
                    "Invoice amount is greater than 0.",
                    fact("order.invoice_amount"),
                    0,
                ),
                compare(
                    "r8a-day",
                    "Completion plus 60 days equals the evaluation date.",
                    date_add(fact("task.completion_date"), 60),
                    RuleOperator.EQ,
                    param("evaluationDate"),
                    null_policy="indeterminate",
                ),
            ),
            all_of(
                "r8b",
                "Amount below threshold, not invoiced, completion plus 75 equals evaluation date.",
                lt(
                    "r8b-amt",
                    "Task amount is below the time-trigger threshold.",
                    fact("task.task_amount"),
                    TIME_TRIGGER_AMOUNT_THRESHOLD,
                    null_policy="indeterminate",
                ),
                not_of(
                    "r8b-not-inv",
                    "Not invoiced.",
                    gt(
                        "r8b-invoiced",
                        "Invoice amount is greater than 0.",
                        fact("order.invoice_amount"),
                        0,
                    ),
                ),
                compare(
                    "r8b-day",
                    "Completion plus 75 days equals the evaluation date.",
                    date_add(fact("task.completion_date"), 75),
                    RuleOperator.EQ,
                    param("evaluationDate"),
                    null_policy="indeterminate",
                ),
            ),
            all_of(
                "r8c",
                "Amount at or above threshold, completion plus 180 equals evaluation date.",
                gte(
                    "r8c-amt",
                    "Task amount is at least the time-trigger threshold.",
                    fact("task.task_amount"),
                    lit(TIME_TRIGGER_AMOUNT_THRESHOLD),
                    null_policy="indeterminate",
                ),
                compare(
                    "r8c-day",
                    "Completion plus 180 days equals the evaluation date.",
                    date_add(fact("task.completion_date"), 180),
                    RuleOperator.EQ,
                    param("evaluationDate"),
                    null_policy="indeterminate",
                ),
            ),
        ),
    )
    return all_of(
        "r8-effective",
        "Timed release after the plan go-live date.",
        gte(
            "r8-go-live",
            "Evaluation date is on or after the go-live date.",
            param("evaluationDate"),
            param("timedReleaseEffectiveDate"),
            null_policy="indeterminate",
        ),
        any_of("r8-branches", "Yeast exception or timed calendar equality.", yeast, timed),
    )


def _not_special_product(prefix: str) -> dict[str, Any]:
    return any_of(
        f"{prefix}-not-special",
        "Product is null or not the special product.",
        is_null(f"{prefix}-product-null", "Product id is null.", fact("task.product_id")),
        ne(
            f"{prefix}-product-ne",
            "Product is not the special product.",
            fact("task.product_id"),
            SPECIAL_PRODUCT_ID,
        ),
    )


def _non_framework(prefix: str) -> dict[str, Any]:
    return not_of(
        f"{prefix}-non-framework",
        "Framework type is not a framework code, including null.",
        in_list(
            f"{prefix}-framework",
            "Framework type is framework.",
            fact("order.framework_type"),
            FRAMEWORK_TYPES,
        ),
    )


def _enterprise(prefix: str) -> dict[str, Any]:
    return in_list(
        f"{prefix}-enterprise",
        "Customer organization is enterprise.",
        fact("order.customer_org_type"),
        ENTERPRISE_ORG_TYPES,
    )


def eligibility_r5() -> dict[str, Any]:
    total = _report_completed_amount()
    return all_of(
        "r5-all",
        "Non-framework enterprise full arrival.",
        _not_special_product("r5"),
        _non_framework("r5"),
        _enterprise("r5"),
        gte(
            "r5-pay",
            "Arrival plus epsilon meets 100 percent of completed amount.",
            _arrival_with_epsilon(),
            total,
            null_policy="indeterminate",
        ),
    )


def _contract_seal_predicate() -> dict[str, Any]:
    def mini(prefix: str) -> dict[str, Any]:
        return eq(f"{prefix}-mini", "Mini-program quota kind.", fact("contract.quota_kind"), 3)

    def non_template(prefix: str) -> dict[str, Any]:
        return eq(
            f"{prefix}-non-template", "Non-template contract.", fact("contract.template_kind"), 0
        )

    def sealed(prefix: str) -> dict[str, Any]:
        return in_list(
            f"{prefix}-sealed", "Receipt is sealed.", fact("contract.receipt_status"), [1, 2]
        )

    def signed_or_sealed(prefix: str) -> dict[str, Any]:
        return in_list(
            f"{prefix}-signed-or-sealed",
            "Receipt is signed or sealed.",
            fact("contract.receipt_status"),
            [0, 1, 2],
        )

    def small_quota(prefix: str) -> dict[str, Any]:
        return eq(f"{prefix}-small-quota", "Small-quota kind.", fact("contract.quota_kind"), 0)

    def after_cutoff(prefix: str) -> dict[str, Any]:
        return gte(
            f"{prefix}-after",
            "Countersign date is on or after the inclusive cutoff.",
            fact("contract.countersign_date"),
            param("contractCountersignCutoffDate"),
            null_policy="fail",
        )

    def seal_mode(prefix: str) -> dict[str, Any]:
        return eq(f"{prefix}-mode", "Effective mode is seal.", fact("contract.effective_mode"), 1)

    case5_receipt = any_of(
        "seal-c5-receipt",
        "Sealed or signed without contact e-sign.",
        in_list("seal-c5-sealed", "Receipt is sealed.", fact("contract.receipt_status"), [1, 2]),
        all_of(
            "seal-c5-signed",
            "Signed not sealed and sign method is not contact e-sign.",
            eq(
                "seal-c5-status0",
                "Receipt status is signed-not-sealed.",
                fact("contract.receipt_status"),
                0,
            ),
            not_of(
                "seal-c5-not-contact",
                "Sign method is not contact e-sign, including null.",
                eq(
                    "seal-c5-contact",
                    "Sign method is contact e-sign.",
                    fact("contract.sign_method"),
                    2,
                ),
            ),
        ),
    )
    return any_of(
        "seal-five",
        "Five mutually exclusive contract branches.",
        mini("c1"),
        all_of(
            "seal-c2",
            "Non-template must be sealed.",
            not_of("seal-c2-not-mini", "Not mini-program.", mini("c2")),
            non_template("c2"),
            sealed("c2"),
        ),
        all_of(
            "seal-c3",
            "Template small-quota allows signed or sealed.",
            not_of("seal-c3-not-mini", "Not mini-program.", mini("c3")),
            not_of("seal-c3-not-non-template", "Not non-template.", non_template("c3")),
            small_quota("c3"),
            signed_or_sealed("c3"),
        ),
        all_of(
            "seal-c4",
            "Template outside small-quota, after cutoff, seal mode, must be sealed.",
            not_of("seal-c4-not-mini", "Not mini-program.", mini("c4")),
            not_of("seal-c4-not-non-template", "Not non-template.", non_template("c4")),
            not_of("seal-c4-not-small", "Not small-quota.", small_quota("c4")),
            after_cutoff("c4"),
            seal_mode("c4"),
            sealed("c4"),
        ),
        all_of(
            "seal-c5",
            "Template outside small-quota before cutoff or non-seal mode.",
            not_of("seal-c5-not-mini", "Not mini-program.", mini("c5")),
            not_of("seal-c5-not-non-template", "Not non-template.", non_template("c5")),
            not_of("seal-c5-not-small", "Not small-quota.", small_quota("c5")),
            any_of(
                "seal-c5-when",
                "Before cutoff or not seal mode.",
                not_of("seal-c5-not-after", "Not after cutoff.", after_cutoff("c5")),
                not_of("seal-c5-not-mode", "Not seal mode.", seal_mode("c5")),
            ),
            case5_receipt,
        ),
    )


def eligibility_r6() -> dict[str, Any]:
    total = _report_completed_amount()
    unassociated = sub(total, fact("order.arrival_amount_including_deposit"))
    condition_a = gte(
        "r6-a",
        "Condition A: arrival plus epsilon meets 100 percent.",
        _arrival_with_epsilon(),
        total,
        null_policy="indeterminate",
    )
    condition_b = all_of(
        "r6-b",
        "Condition B: 80 percent arrival, 20 percent deposit, and all contracts sealed.",
        gte(
            "r6-b1",
            "Arrival plus epsilon meets 80 percent.",
            _arrival_with_epsilon(),
            mul(total, lit(RATIO_80)),
            null_policy="indeterminate",
        ),
        gte(
            "r6-b2",
            "Deposit meets 20 percent of unassociated arrival.",
            fact("order.deposit_amount"),
            mul(unassociated, lit(RATIO_20)),
            null_policy="indeterminate",
        ),
        {
            "id": "r6-contracts",
            "kind": "allMembers",
            "description": "Every contract in the seal scope satisfies one of five branches.",
            "collectionFactCode": "order.seal_scope_contract_ids",
            "emptyCollectionPolicy": "fail",
            "duplicateMemberPolicy": "uniquePreserveOrder",
            "missingMemberPolicy": "indeterminate",
            "memberPredicate": _contract_seal_predicate(),
        },
    )
    return all_of(
        "r6-all",
        "Non-framework non-enterprise arrival branches.",
        _not_special_product("r6"),
        _non_framework("r6"),
        not_of(
            "r6-non-enterprise",
            "Customer organization is not enterprise, including null.",
            _enterprise("r6"),
        ),
        any_of("r6-ab", "Condition A or condition B.", condition_a, condition_b),
    )


def eligibility_r7() -> dict[str, Any]:
    total = _report_completed_amount()
    unassociated = sub(total, fact("order.arrival_amount_including_deposit"))
    return all_of(
        "r7-all",
        "Framework 80 percent arrival or 20 percent deposit.",
        in_list(
            "r7-framework", "Order is framework.", fact("order.framework_type"), FRAMEWORK_TYPES
        ),
        any_of(
            "r7-or",
            "Arrival 80 percent or deposit 20 percent.",
            gte(
                "r7-pay",
                "Arrival plus epsilon meets 80 percent.",
                _arrival_with_epsilon(),
                mul(total, lit(RATIO_80)),
                null_policy="indeterminate",
            ),
            gte(
                "r7-deposit",
                "Deposit meets 20 percent of unassociated arrival.",
                fact("order.deposit_amount"),
                mul(unassociated, lit(RATIO_20)),
                null_policy="indeterminate",
            ),
        ),
    )


def all_eligibility_conditions() -> tuple[dict[str, Any], ...]:
    return (
        eligibility_r0(),
        eligibility_r1(),
        eligibility_r9(),
        eligibility_r4(),
        eligibility_r2(),
        eligibility_r3(),
        eligibility_r8(),
        eligibility_r5(),
        eligibility_r6(),
        eligibility_r7(),
    )


def _member_already_released() -> dict[str, Any]:
    return in_list(
        "member-already",
        "Member already reached a terminal report status.",
        fact("report.release_status"),
        TERMINAL_RELEASE_STATUSES,
    )


def _member_reduced_prereq() -> dict[str, Any]:
    return all_of(
        "member-prereq",
        "Member is completed and has at least one report present.",
        eq("member-completed", "Member task status is completed.", fact("task.status_code"), 19),
        any_of(
            "member-has-report",
            "Member has a project or quality report.",
            eq(
                "member-project",
                "Member project report is present.",
                fact("task.project_report_flag"),
                0,
            ),
            eq("member-qc", "Member quality report is present.", fact("task.qc_report_flag"), 0),
        ),
    )


def _prefixed(condition: dict[str, Any], prefix: str) -> dict[str, Any]:
    cloned = deepcopy(condition)

    def walk(node: dict[str, Any]) -> None:
        node["id"] = f"{prefix}{node['id']}"
        for child in node.get("children") or []:
            walk(child)
        if node.get("alreadySatisfied"):
            walk(node["alreadySatisfied"])
        if node.get("memberPredicate"):
            walk(node["memberPredicate"])

    walk(cloned)
    return cloned


def merge_group_unsatisfied() -> dict[str, Any]:
    member_hit = any_of(
        "member-any-eligibility",
        "Any eligibility rule hits for the member.",
        *[_prefixed(item, "m-") for item in all_eligibility_conditions()],
    )
    return all_of(
        "merge-unsatisfied",
        "Combined-report group is present and not every other member is satisfied.",
        eq(
            "merge-present",
            "Task belongs to a combined-report group.",
            fact("report.merge_group_present"),
            True,
        ),
        not_of(
            "merge-not-all",
            "Not every unique related member is satisfied.",
            {
                "id": "merge-all-members",
                "kind": "allMembers",
                "description": "All unique related members are already released or eligibility-ready.",
                "collectionFactCode": "report.merge_group_member_ids",
                "emptyCollectionPolicy": "pass",
                "duplicateMemberPolicy": "uniquePreserveOrder",
                "missingMemberPolicy": "indeterminate",
                "alreadySatisfied": _member_already_released(),
                "memberPredicate": all_of(
                    "member-ready",
                    "Reduced prerequisite and any eligibility hit.",
                    _member_reduced_prereq(),
                    member_hit,
                ),
            },
        ),
    )


def report_runtime_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "evaluationDate",
            "dataType": "date",
            "role": "evaluationClock",
            "required": True,
            "description": "Unified evaluation calendar date in Asia/Shanghai.",
        },
        {
            "name": "rawDataReleasedCutoffDate",
            "dataType": "date",
            "role": "cutoff",
            "required": True,
            "boundValue": RAW_DATA_RELEASED_CUTOFF,
            "inclusive": True,
            "description": "Inclusive completion-date cutoff for raw-data-released report release.",
        },
        {
            "name": "timedReleaseEffectiveDate",
            "dataType": "date",
            "role": "effectiveFrom",
            "required": True,
            "boundValue": TIMED_RELEASE_EFFECTIVE_DATE,
            "inclusive": True,
            "description": "Inclusive go-live date for timed release.",
        },
        {
            "name": "contractCountersignCutoffDate",
            "dataType": "date",
            "role": "cutoff",
            "required": True,
            "boundValue": CONTRACT_COUNTERSIGN_CUTOFF,
            "inclusive": True,
            "description": "Inclusive countersign cutoff used by contract branch 4.",
        },
    ]


def build_report_stages() -> list[dict[str, Any]]:
    both_absent = all_of(
        "both-absent",
        "Both report presence flags are absent-code 1.",
        eq("no-project", "Project report is absent.", fact("task.project_report_flag"), 1),
        eq("no-qc", "Quality report is absent.", fact("task.qc_report_flag"), 1),
    )
    pending_has_report = any_of(
        "pending-has-report",
        "Either report presence flag is present-code 0.",
        eq(
            "pending-has-project", "Project report is present.", fact("task.project_report_flag"), 0
        ),
        eq("pending-has-qc", "Quality report is present.", fact("task.qc_report_flag"), 0),
    )
    pending_both_absent = all_of(
        "pending-both-absent",
        "Both report presence flags are absent-code 1.",
        eq("pending-no-project", "Project report is absent.", fact("task.project_report_flag"), 1),
        eq("pending-no-qc", "Quality report is absent.", fact("task.qc_report_flag"), 1),
    )
    return [
        {
            "stage": "stateGuards",
            "rules": [
                _node(
                    "REPORT_STATUS_TERMINAL",
                    10,
                    "Skip when report status is already terminal.",
                    in_list(
                        "status-terminal",
                        "Report status is a terminal in-progress or released state.",
                        fact("report.release_status"),
                        TERMINAL_RELEASE_STATUSES,
                    ),
                    "SKIPPED",
                    "REPORT_STATUS_TERMINAL_MATCHED",
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
                        "not-completed",
                        "Status is null or not 19.",
                        is_null("status-null", "Task status is null.", fact("task.status_code")),
                        ne(
                            "status-ne-19",
                            "Task status is not completed.",
                            fact("task.status_code"),
                            19,
                        ),
                    ),
                    "WAITING_COMPLETION",
                    "TASK_NOT_COMPLETED_MATCHED",
                ),
                _node(
                    "EXPERIMENT_STATUS_OFFLINE",
                    20,
                    "No release when experiment status is offline confirmation.",
                    eq("exp-2", "Experiment status is 2.", fact("task.experiment_status_code"), 2),
                    "NO_RELEASE_REQUIRED",
                    "EXPERIMENT_STATUS_OFFLINE_MATCHED",
                ),
                _node(
                    "EXPERIMENT_STATUS_PROBLEM",
                    30,
                    "No release when experiment status is a problem project.",
                    eq("exp-7", "Experiment status is 7.", fact("task.experiment_status_code"), 7),
                    "NO_RELEASE_REQUIRED",
                    "EXPERIMENT_STATUS_PROBLEM_MATCHED",
                ),
                _node(
                    "OFFLINE_REPORT_RELEASED",
                    40,
                    "Already released when offline flag hit code is 0.",
                    eq(
                        "offline-0",
                        "Offline report flag is 0.",
                        fact("task.offline_report_release_flag"),
                        0,
                    ),
                    "ALREADY_RELEASED",
                    "OFFLINE_REPORT_RELEASED_MATCHED",
                ),
                _node(
                    "NO_PROJECT_REPORT",
                    50,
                    "No release when both reports are absent.",
                    both_absent,
                    "NO_RELEASE_REQUIRED",
                    "NO_PROJECT_REPORT_MATCHED",
                ),
                _node(
                    "REPORT_AVAILABILITY_PENDING",
                    60,
                    "Wait when report presence is not decided.",
                    all_of(
                        "report-pending",
                        "Neither present-code nor both-absent.",
                        not_of(
                            "not-has-report", "Neither flag is present-code 0.", pending_has_report
                        ),
                        not_of("not-both-absent", "Not both absent.", pending_both_absent),
                    ),
                    "WAITING_CONDITIONS",
                    "REPORT_AVAILABILITY_PENDING_MATCHED",
                ),
            ],
        },
        {
            "stage": "eligibility",
            "rules": [
                _node("R0", 10, "Zero-amount order.", eligibility_r0(), "READY", "R0_MATCHED"),
                _node(
                    "R1",
                    20,
                    "Completed special application.",
                    eligibility_r1(),
                    "READY",
                    "R1_MATCHED",
                ),
                _node("R9", 30, "Batch release flag.", eligibility_r9(), "READY", "R9_MATCHED"),
                _node(
                    "R4",
                    40,
                    "Raw-data presence code 0 on or after cutoff.",
                    eligibility_r4(),
                    "READY",
                    "R4_MATCHED",
                ),
                _node("R2", 50, "Overseas order source.", eligibility_r2(), "READY", "R2_MATCHED"),
                _node(
                    "R3",
                    60,
                    "Special product tiered arrival.",
                    eligibility_r3(),
                    "READY",
                    "R3_MATCHED",
                ),
                _node(
                    "R8",
                    70,
                    "Timed calendar equality or yeast exception.",
                    eligibility_r8(),
                    "READY",
                    "R8_MATCHED",
                ),
                _node(
                    "R5",
                    80,
                    "Non-framework enterprise full arrival.",
                    eligibility_r5(),
                    "READY",
                    "R5_MATCHED",
                ),
                _node(
                    "R6",
                    90,
                    "Non-framework non-enterprise arrival branches.",
                    eligibility_r6(),
                    "READY",
                    "R6_MATCHED",
                ),
                _node(
                    "R7",
                    100,
                    "Framework arrival or deposit.",
                    eligibility_r7(),
                    "READY",
                    "R7_MATCHED",
                ),
            ],
        },
        {
            "stage": "postGates",
            "rules": [
                _node(
                    "MERGE_GROUP_UNSATISFIED",
                    10,
                    "Wait when combined-report group members are not all satisfied.",
                    merge_group_unsatisfied(),
                    "WAITING_CONDITIONS",
                    "MERGE_GROUP_UNSATISFIED_MATCHED",
                )
            ],
        },
        {
            "stage": "exclusions",
            "rules": [
                _node(
                    "OA_PROCESS_SCOPE",
                    10,
                    "Wait when already in a project-report release OA instance.",
                    eq(
                        "oa-in-process",
                        "Task is in a project-report release OA instance.",
                        fact("task.in_project_report_release_oa"),
                        True,
                    ),
                    "WAITING_CONDITIONS",
                    "OA_PROCESS_SCOPE_MATCHED",
                )
            ],
        },
    ]


def build_report_candidate_payload(
    catalog_digest: str, source_identity: dict[str, Any]
) -> dict[str, Any]:
    stages = build_report_stages()
    return {
        "contractVersion": "3.1.0",
        "ruleSetId": REPORT_RULE_SET_ID,
        "title": "Optimization-plan project report release",
        "scope": "Project-report release evaluation for a completed experimental task.",
        "catalogId": REPORT_CATALOG_ID,
        "catalogVersion": CATALOG_VERSION,
        "catalogDigest": catalog_digest,
        "sourceViews": ["optimization-plan"],
        "sourceIdentity": source_identity,
        "runtimeParameters": report_runtime_parameters(),
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
