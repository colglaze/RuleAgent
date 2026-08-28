"""Business-review remediation profile for REPORT_RELEASE_ALL_001.

The 2026-08-24 profile remains the immutable reproduction baseline. This module builds
a separate candidate for an unpersisted replacement draft and performs additional
source-specific assertions. It does not call a model, database, or network service.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from scripts.reviewed_report_release_all_001 import (
    AUTHORING_MODEL,
    RULE_ID,
    SOURCE_SHA256,
)
from scripts.reviewed_report_release_all_001 import (
    audit_candidate as audit_legacy_structure,
)
from scripts.reviewed_report_release_all_001 import (
    build_candidate_payload as build_legacy_candidate_payload,
)

from rule_reader.domain.rules.models import MappingStatus
from rule_reader.domain.rules.v2 import (
    ConditionNodeV2,
    RuleCandidateV2,
)
from rule_reader.domain.rules.validation_v2 import (
    evaluate_condition,
    validate_candidate_v2,
)

REVIEWED_IMPORT_VERSION = "reviewed-import-v2"

JsonObject = dict[str, Any]

TASK_PARAMETER = {
    "name": "taskId",
    "dataType": "integer",
    "description": "OA 正式实验任务 ID",
    "required": True,
}
TASK_NUMBER_PARAMETER = {
    "name": "taskNumber",
    "dataType": "string",
    "description": "OA 正式实验任务号 sqlc",
    "required": True,
}
EVALUATION_DATE_PARAMETER = {
    "name": "evaluationDate",
    "dataType": "date",
    "description": "本次规则求值采用的数据库日期",
    "required": True,
}

ORDER_GRAIN_FACTS = {
    "order.amount",
    "amount.receipts_total",
    "amount.deposit_amount",
    "amount.prior_report_fee",
    "amount.transferred_task_fee",
    "amount.transferred_estimated_fee",
    "amount.formal_estimated_fee",
    "amount.estimated_work_fee",
    "contract.current_order_meet_flag",
    "order.framework_type",
    "order.effective_framework_type",
    "order.unit_attribute",
    "order.effective_unit_attribute",
    "order.source_code",
}
REJECTED_MAPPING_FACTS = {
    "amount.receipts_total",
    "amount.deposit_amount",
    "amount.transferred_task_fee",
    "amount.current_task_fee",
    "amount.transferred_estimated_fee",
    "amount.formal_estimated_fee",
}
RETAINED_MAPPING_FACTS = {
    "order.amount",
    "contract.current_order_meet_flag",
}


def _facts_by_code(payload: JsonObject) -> dict[str, JsonObject]:
    return {str(fact["factCode"]): fact for fact in payload["requiredFacts"]}


def _replace_raw_data_fact(payload: JsonObject) -> None:
    facts = payload["requiredFacts"]
    old_index = next(
        index
        for index, fact in enumerate(facts)
        if fact["factCode"] == "release.raw_data_record_approved"
    )
    facts[old_index : old_index + 1] = [
        {
            "factCode": "task.raw_data_flag",
            "name": "原始数据标志",
            "factKind": "source",
            "dataType": "integer",
            "description": "正式实验任务字段 yssj；值等于 0 才可进入原始数据记录直接路径。",
            "nullable": True,
            "nullPolicy": "fail",
            "grain": "formal_test_task",
            "parameters": [deepcopy(TASK_PARAMETER)],
            "unit": None,
            "allowedValues": [],
            "defaultValue": None,
            "derivation": None,
        },
        {
            "factCode": "release.has_approved_raw_data_record",
            "name": "存在已批准原始数据释放记录",
            "factKind": "exists",
            "dataType": "boolean",
            "description": (
                "按任务号 sqlc 关联 uf_yssjsf.zssyrwd，是否存在 zt=1 且 "
                "fssj 不早于 2024-11-21 的记录。"
            ),
            "nullable": False,
            "nullPolicy": "error",
            "grain": "formal_test_task",
            "parameters": [deepcopy(TASK_NUMBER_PARAMETER)],
            "unit": None,
            "allowedValues": [],
            "defaultValue": None,
            "derivation": None,
        },
    ]


def _replace_raw_data_condition(node: JsonObject) -> bool:
    if node["id"] == "raw-data-record-path":
        node.clear()
        node.update(
            {
                "id": "raw-data-record-path",
                "kind": "all",
                "description": "任务原始数据标志为 0 且存在符合日期和状态的释放记录。",
                "children": [
                    {
                        "id": "raw-data-flag-zero",
                        "kind": "compare",
                        "description": "任务原始数据标志 yssj 等于 0。",
                        "left": {"kind": "fact", "factCode": "task.raw_data_flag"},
                        "operator": "eq",
                        "right": {"kind": "literal", "value": 0},
                        "nullPolicy": "fail",
                    },
                    {
                        "id": "approved-raw-data-record-exists",
                        "kind": "compare",
                        "description": "存在符合状态和日期边界的原始数据释放记录。",
                        "left": {
                            "kind": "fact",
                            "factCode": "release.has_approved_raw_data_record",
                        },
                        "operator": "eq",
                        "right": {"kind": "literal", "value": True},
                        "nullPolicy": "error",
                    },
                ],
            }
        )
        return True
    return any(_replace_raw_data_condition(child) for child in node.get("children", []))


def _repair_fact_contracts(payload: JsonObject) -> None:
    facts = _facts_by_code(payload)
    for fact_code in ORDER_GRAIN_FACTS:
        facts[fact_code]["grain"] = "order"

    facts["merged.other_order_fee_failure_count"]["grain"] = "merge_report_order"
    facts["contract.merged_orders_meet_flag"]["grain"] = "merge_report"
    facts["runtime.current_date"]["grain"] = "rule_evaluation"
    facts["runtime.current_date"]["parameters"] = [deepcopy(EVALUATION_DATE_PARAMETER)]
    facts["workflow.has_unfinished_report_release"]["parameters"] = [
        deepcopy(TASK_NUMBER_PARAMETER)
    ]
    facts["release.special_application_approved"]["parameters"] = [deepcopy(TASK_NUMBER_PARAMETER)]
    facts["report.merge_flag"]["allowedValues"] = []

    facts["amount.receipts_total"]["description"] = (
        "金额 R：主视图按订单聚合 uf_dd_dt3.syje 与 uf_dd_dt4.syje，包含押金；"
        "所有覆盖比较在 R 上增加 0.1 容差。"
    )
    facts["amount.deposit_amount"]["description"] = (
        "金额 D：主视图按订单聚合 uf_dd_dt3 中 zxmk=1 的 syje。"
    )
    facts["amount.transferred_task_fee"]["description"] = (
        "金额 E：订单下承接转交任务最终费用。有已确认结算时采用结算值；否则任务状态"
        "不为 4 且完成数量为空时使用下单数量，其余情况使用完成数量，空值按 0。"
    )
    facts["amount.current_task_fee"]["description"] = (
        "金额 C：当前正式实验任务最终费用。有已确认结算时采用结算值；否则任务状态"
        "不为 19 且完成数量为空时使用下单数量，其余情况使用完成数量，空值按 0。"
    )
    facts["amount.transferred_estimated_fee"]["description"] = (
        "订单下承接转交预估完工费：任务状态不为 4 且完成数量为空时使用下单数量，"
        "其余情况使用完成数量，空值按 0，再乘订单服务单价后汇总。"
    )
    facts["amount.formal_estimated_fee"]["description"] = (
        "订单下正式实验预估完工费：任务状态不为 19 且完成数量为空时使用下单数量，"
        "其余情况使用完成数量，空值按 0，再乘订单服务单价后汇总。"
    )
    facts["contract.current_order_meet_flag"]["description"] = str(
        facts["contract.current_order_meet_flag"]["description"]
    ).replace("七个互斥签署分支之一", "七个可选签署分支之一")


def _repair_test_inputs(payload: JsonObject) -> None:
    for test in payload["testCases"]:
        given = test["given"]
        if "release.raw_data_record_approved" not in given:
            continue
        approved = bool(given.pop("release.raw_data_record_approved"))
        given["task.raw_data_flag"] = 0 if approved else 1
        given["release.has_approved_raw_data_record"] = approved


def _common_inputs() -> JsonObject:
    return {
        "task.status": 19,
        "task.data_usage_status": 0,
        "task.report_release_date": "",
        "task.online_release_flag": 1,
        "task.project_report_flag": 0,
        "task.periodic_report_flag": 1,
        "workflow.has_unfinished_report_release": False,
        "report.merge_flag": None,
        "report.is_first_task_in_merge": False,
    }


def _direct_failures() -> JsonObject:
    return {
        "release.special_application_approved": False,
        "task.batch_release_flag": 1,
        "task.raw_data_flag": 1,
        "release.has_approved_raw_data_record": False,
        "order.source_code": 0,
        "task.business_scope_flag": 1,
    }


def _ordinary_base() -> JsonObject:
    return {
        **_common_inputs(),
        **_direct_failures(),
        "product.id": 100,
        "product.type": 2,
        "merged.other_order_fee_failure_count": 0,
    }


def _money_inputs(*, receipts: float) -> JsonObject:
    return {
        "amount.receipts_total": receipts,
        "amount.prior_report_fee": 10,
        "amount.transferred_task_fee": 20,
        "amount.current_task_fee": 30,
        "amount.merged_other_task_fee": 40,
    }


def _case(
    case_id: str,
    category: str,
    description: str,
    given: JsonObject,
    expected: str,
    rationale: str,
) -> JsonObject:
    return {
        "id": case_id,
        "category": category,
        "description": description,
        "given": given,
        "expected": expected,
        "rationale": rationale,
    }


def _coverage_cases() -> list[JsonObject]:
    common_direct = {**_common_inputs(), "release.special_application_approved": True}
    ordinary_contracts = {
        "contract.current_order_meet_flag": 1,
        "contract.merged_orders_meet_flag": 1,
    }
    return [
        _case(
            "common-task-status-fail",
            "failure",
            "任务状态不是 19 时共同前置失败。",
            {**common_direct, "task.status": 18},
            "fail",
            "直接路径不能绕过任务状态门禁。",
        ),
        _case(
            "common-data-status-fail",
            "failure",
            "数据使用状态为 2 时共同前置失败。",
            {**common_direct, "task.data_usage_status": 2},
            "fail",
            "rwdsyzt=2 被共同前置拒绝。",
        ),
        _case(
            "common-release-date-fail",
            "failure",
            "报告释放日期非空时共同前置失败。",
            {**common_direct, "task.report_release_date": "2026-08-27"},
            "fail",
            "已存在报告释放日期不能再次释放。",
        ),
        _case(
            "common-online-release-fail",
            "failure",
            "线上释放标志为 0 时共同前置失败。",
            {**common_direct, "task.online_release_flag": 0},
            "fail",
            "sfxxsf=0 不满足共同前置。",
        ),
        _case(
            "common-report-type-fail",
            "failure",
            "项目报告和周期报告标志均非 0 时共同前置失败。",
            {
                **common_direct,
                "task.project_report_flag": 1,
                "task.periodic_report_flag": 1,
            },
            "fail",
            "xmbg=0 或 zkqcbg=0 均未满足。",
        ),
        _case(
            "common-periodic-report-alternative-pass",
            "normal",
            "仅周期报告标志为 0 时共同前置通过。",
            {
                **common_direct,
                "task.project_report_flag": 1,
                "task.periodic_report_flag": 0,
            },
            "pass",
            "共同前置中的报告类型条件是或关系。",
        ),
        _case(
            "merge-flag-one-pass",
            "normal",
            "合并报告标志为 1 时无需组内首条判断。",
            {**common_direct, "report.merge_flag": 1},
            "pass",
            "sfhbbg=1 的任务全部保留。",
        ),
        _case(
            "merge-first-task-pass",
            "normal",
            "其他合并标志的组内首条任务保留。",
            {
                **common_direct,
                "report.merge_flag": 2,
                "report.is_first_task_in_merge": True,
            },
            "pass",
            "其他 sfhbbg 值只保留 hbbglc 组内 ID 最小任务。",
        ),
        _case(
            "ordinary-nonframework-unit14-contract-pass",
            "normal",
            "非框架、单位属性 14、合同通过且全额覆盖。",
            {
                **_ordinary_base(),
                **ordinary_contracts,
                **_money_inputs(receipts=99.9),
                "order.amount": 1000,
                "order.framework_type": 1,
                "order.unit_attribute": 14,
            },
            "pass",
            "保留来源案例 1，并实际通过单位属性 14 合同金额分支。",
        ),
        _case(
            "ordinary-framework-eighty-percent-pass",
            "boundary",
            "框架协议在 80% 精确边界通过。",
            {
                **_ordinary_base(),
                **ordinary_contracts,
                **_money_inputs(receipts=79.9),
                "order.amount": 1000,
                "order.framework_type": 0,
                "order.unit_attribute": 14,
            },
            "pass",
            "框架协议进入 80%/押金分支，R+0.1=F*80%。",
        ),
        _case(
            "ordinary-current-pass-cross-order-fail",
            "failure",
            "当前订单全额覆盖但跨订单费用失败。",
            {
                **_ordinary_base(),
                **_money_inputs(receipts=99.9),
                "order.amount": 1000,
                "merged.other_order_fee_failure_count": 1,
            },
            "fail",
            "保留来源案例 6，跨订单费用门禁先于当前订单放行分支。",
        ),
    ]


def _repair_mappings(payload: JsonObject) -> None:
    mappings = {str(mapping["factCode"]): mapping for mapping in payload["fieldMappings"]}
    mappings.pop("release.raw_data_record_approved")
    for fact_code in (
        "task.raw_data_flag",
        "release.has_approved_raw_data_record",
    ):
        mappings[fact_code] = {
            "factCode": fact_code,
            "mappingStatus": "unresolved",
            "viewName": None,
            "viewField": None,
            "note": "当前字段目录不能安全确认该事实的物理输出，保持未决。",
        }
    for fact_code in REJECTED_MAPPING_FACTS:
        mappings[fact_code] = {
            "factCode": fact_code,
            "mappingStatus": "unresolved",
            "viewName": None,
            "viewField": None,
            "note": "主视图与目录候选口径不能证明等价，业务审核后恢复为未决。",
        }
    payload["fieldMappings"] = [
        mappings[str(fact["factCode"])] for fact in payload["requiredFacts"]
    ]


def build_candidate_payload() -> JsonObject:
    payload = deepcopy(build_legacy_candidate_payload())
    _replace_raw_data_fact(payload)
    if not _replace_raw_data_condition(payload["rootCondition"]):
        raise ValueError("raw-data-record-path was not found")
    _repair_fact_contracts(payload)
    _repair_test_inputs(payload)
    payload["testCases"].extend(_coverage_cases())
    _repair_mappings(payload)
    payload["warnings"] = [
        warning for warning in payload["warnings"] if "reviewed import" not in warning
    ]
    payload["warnings"].extend(
        [
            "当前主视图字段不在四视图目录中，无法证明等价的金额与费用映射保持未决。",
            "该 reviewed-import-v2 结果仍是未持久化、不可执行、待再次业务审核的草稿。",
        ]
    )
    return payload


def _walk_conditions(node: ConditionNodeV2) -> list[ConditionNodeV2]:
    return [node, *(item for child in node.children for item in _walk_conditions(child))]


def audit_candidate(candidate: RuleCandidateV2) -> dict[str, int]:
    """Validate the remediated profile and every business-review closure condition."""

    validate_candidate_v2(candidate)
    legacy_summary = audit_legacy_structure(candidate)
    facts = {fact.fact_code: fact for fact in candidate.required_facts}
    conditions = _walk_conditions(candidate.root_condition)

    expected = {
        "facts": 42,
        "nonDerivedFacts": 34,
        "derivedFacts": 8,
        "conditions": 67,
        "testCases": 31,
        "mappedFacts": 2,
    }
    if legacy_summary != expected:
        raise ValueError(f"unexpected remediation counts: {legacy_summary}")

    kinds = Counter(condition.kind.value for condition in conditions)
    if kinds != Counter({"compare": 43, "all": 14, "any": 9, "not": 1}):
        raise ValueError(f"unexpected remediation condition kinds: {dict(kinds)}")

    fact_kinds = Counter(fact.fact_kind.value for fact in candidate.required_facts)
    if fact_kinds != Counter({"source": 18, "aggregate": 12, "exists": 4, "derived": 8}):
        raise ValueError(f"unexpected remediation fact kinds: {dict(fact_kinds)}")

    for fact_code in ORDER_GRAIN_FACTS:
        fact = facts[fact_code]
        if fact.grain != "order":
            raise ValueError(f"{fact_code} must use order grain")
        expected_parameters = [] if fact.derivation is not None else ["orderId"]
        if [parameter.name for parameter in fact.parameters] != expected_parameters:
            raise ValueError(f"{fact_code} has the wrong order parameters")
    cross_order = facts["merged.other_order_fee_failure_count"]
    if cross_order.grain != "merge_report_order" or [
        parameter.name for parameter in cross_order.parameters
    ] != ["mergeReportId", "orderId"]:
        raise ValueError("cross-order failure count must use merge_report_order grain")
    merged_contract = facts["contract.merged_orders_meet_flag"]
    if merged_contract.grain != "merge_report" or [
        parameter.name for parameter in merged_contract.parameters
    ] != ["mergeReportId"]:
        raise ValueError("merged contract fact must use merge_report grain")
    runtime = facts["runtime.current_date"]
    if runtime.grain != "rule_evaluation" or [
        parameter.name for parameter in runtime.parameters
    ] != ["evaluationDate"]:
        raise ValueError("runtime.current_date must use evaluationDate context")
    for fact_code in (
        "workflow.has_unfinished_report_release",
        "release.special_application_approved",
        "release.has_approved_raw_data_record",
    ):
        if [parameter.name for parameter in facts[fact_code].parameters] != ["taskNumber"]:
            raise ValueError(f"{fact_code} must use taskNumber")
    if [parameter.name for parameter in facts["task.raw_data_flag"].parameters] != ["taskId"]:
        raise ValueError("task.raw_data_flag must use taskId")
    if facts["report.merge_flag"].allowed_values:
        raise ValueError("report.merge_flag must not restrict undocumented other values")
    if "release.raw_data_record_approved" in facts:
        raise ValueError("legacy composite raw-data fact must be removed")

    mappings = {mapping.fact_code: mapping for mapping in candidate.field_mappings}
    mapped = {
        code for code, mapping in mappings.items() if mapping.mapping_status is MappingStatus.MAPPED
    }
    if mapped != RETAINED_MAPPING_FACTS:
        raise ValueError(f"unexpected retained mappings: {sorted(mapped)}")
    if any(
        mappings[code].mapping_status is not MappingStatus.UNRESOLVED
        for code in REJECTED_MAPPING_FACTS
    ):
        raise ValueError("rejected amount/fee mappings must remain unresolved")

    by_id = {condition.id: condition for condition in conditions}
    raw_path = by_id["raw-data-record-path"]
    if raw_path.kind.value != "all" or {child.id for child in raw_path.children} != {
        "raw-data-flag-zero",
        "approved-raw-data-record-exists",
    }:
        raise ValueError("raw data path must be an explicit two-condition all")

    fact_lookup = {fact.fact_code: fact for fact in candidate.required_facts}
    uncovered: list[str] = []
    for condition in conditions:
        outcomes = {
            evaluate_condition(condition, test.given, fact_lookup).value
            for test in candidate.test_cases
        }
        if not {"pass", "fail"}.issubset(outcomes):
            uncovered.append(condition.id)
    if uncovered:
        raise ValueError(f"conditions without pass/fail coverage: {sorted(uncovered)}")

    return {
        **legacy_summary,
        "bidirectionallyCoveredConditions": len(conditions),
    }


__all__ = [
    "AUTHORING_MODEL",
    "REVIEWED_IMPORT_VERSION",
    "RULE_ID",
    "SOURCE_SHA256",
    "audit_candidate",
    "build_candidate_payload",
]
