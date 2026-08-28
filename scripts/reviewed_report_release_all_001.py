"""Reviewed Schema 2.0 candidate and audit profile for REPORT_RELEASE_ALL_001.

This module is an explicitly authorized, source-hash-bound governance artifact. It is
not a general parser and does not call a model, generate SQL, or access a database.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from rule_reader.domain.rules.v2 import (
    ConditionNodeV2,
    ExpressionKind,
    FactKind,
    RuleCandidateV2,
    TestCategoryV2,
)
from rule_reader.domain.rules.validation_v2 import validate_candidate_v2

RULE_ID = "REPORT_RELEASE_ALL_001"
SOURCE_SHA256 = "562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d"
AUTHORING_MODEL = "codex-gpt-5"

JsonObject = dict[str, Any]


def _parameter(name: str, data_type: str, description: str) -> JsonObject:
    return {
        "name": name,
        "dataType": data_type,
        "description": description,
        "required": True,
    }


TASK_PARAMETER = _parameter("taskId", "integer", "OA 正式实验任务 ID")
ORDER_PARAMETER = _parameter("orderId", "integer", "任务所属 OA 订单 ID")
MERGE_PARAMETER = _parameter("mergeReportId", "integer", "合并报告流程 ID")
CONTRACT_PARAMETER = _parameter("executionContractId", "integer", "订单执行合同 ID")


def _fact(
    code: str,
    name: str,
    kind: str,
    data_type: str,
    description: str,
    *,
    grain: str = "formal_test_task",
    parameters: list[JsonObject] | None = None,
    nullable: bool = False,
    null_policy: str = "error",
    unit: str | None = None,
    allowed_values: list[Any] | None = None,
    default_value: Any = None,
    derivation: JsonObject | None = None,
) -> JsonObject:
    return {
        "factCode": code,
        "name": name,
        "factKind": kind,
        "dataType": data_type,
        "description": description,
        "nullable": nullable,
        "nullPolicy": null_policy,
        "grain": grain,
        "parameters": parameters if parameters is not None else [TASK_PARAMETER],
        "unit": unit,
        "allowedValues": allowed_values or [],
        "defaultValue": default_value,
        "derivation": derivation,
    }


def _derived(
    code: str,
    name: str,
    data_type: str,
    description: str,
    derivation: JsonObject,
    *,
    unit: str | None = None,
    allowed_values: list[Any] | None = None,
) -> JsonObject:
    return _fact(
        code,
        name,
        "derived",
        data_type,
        description,
        parameters=[],
        unit=unit,
        allowed_values=allowed_values,
        derivation=derivation,
    )


def _ref(code: str) -> JsonObject:
    return {"kind": "fact", "factCode": code}


def _literal(value: Any) -> JsonObject:
    return {"kind": "literal", "value": value}


def _operation(kind: str, *children: JsonObject, unit: str | None = None) -> JsonObject:
    expression: JsonObject = {"kind": kind, "children": list(children)}
    if unit is not None:
        expression["unit"] = unit
    return expression


def _compare(
    condition_id: str,
    description: str,
    left: JsonObject,
    operator: str,
    right: JsonObject | None = None,
    *,
    null_policy: str = "fail",
) -> JsonObject:
    condition: JsonObject = {
        "id": condition_id,
        "kind": "compare",
        "description": description,
        "left": left,
        "operator": operator,
        "nullPolicy": null_policy,
    }
    if right is not None:
        condition["right"] = right
    return condition


def _all(condition_id: str, description: str, *children: JsonObject) -> JsonObject:
    return {
        "id": condition_id,
        "kind": "all",
        "description": description,
        "children": list(children),
    }


def _any(condition_id: str, description: str, *children: JsonObject) -> JsonObject:
    return {
        "id": condition_id,
        "kind": "any",
        "description": description,
        "children": list(children),
    }


def _not(condition_id: str, description: str, child: JsonObject) -> JsonObject:
    return {
        "id": condition_id,
        "kind": "not",
        "description": description,
        "children": [child],
    }


def _required_facts() -> list[JsonObject]:
    return [
        _fact(
            "task.status",
            "任务状态",
            "source",
            "integer",
            "正式实验任务状态 rwzt；所有释放路径要求等于 19。",
            allowed_values=[],
        ),
        _fact(
            "task.data_usage_status",
            "任务数据使用状态",
            "source",
            "integer",
            "任务字段 rwdsyzt 的原始值；规则判断前空值按 0。",
            nullable=True,
            default_value=0,
        ),
        _derived(
            "task.effective_data_usage_status",
            "有效任务数据使用状态",
            "integer",
            "ISNULL(rwdsyzt,0) 的确定性表达。",
            _operation(
                "coalesce",
                _ref("task.data_usage_status"),
                _literal(0),
            ),
        ),
        _fact(
            "task.report_release_date",
            "报告释放日期",
            "source",
            "string",
            "任务字段 bgsfrq；为空字符串或 NULL 时尚未释放。",
            nullable=True,
        ),
        _fact(
            "task.online_release_flag",
            "是否线上释放",
            "source",
            "integer",
            "任务字段 sfxxsf 的原始值；规则判断前空值按 1。",
            nullable=True,
            allowed_values=[0, 1],
            default_value=1,
        ),
        _derived(
            "task.effective_online_release_flag",
            "有效线上释放标志",
            "integer",
            "ISNULL(sfxxsf,1) 的确定性表达。",
            _operation(
                "coalesce",
                _ref("task.online_release_flag"),
                _literal(1),
            ),
            allowed_values=[0, 1],
        ),
        _fact(
            "task.project_report_flag",
            "项目报告标志",
            "source",
            "integer",
            "任务字段 xmbg；xmbg=0 或 zkqcbg=0 至少满足一项。",
            allowed_values=[0, 1],
        ),
        _fact(
            "task.periodic_report_flag",
            "周期报告标志",
            "source",
            "integer",
            "任务字段 zkqcbg；xmbg=0 或 zkqcbg=0 至少满足一项。",
            allowed_values=[0, 1],
        ),
        _fact(
            "workflow.has_unfinished_report_release",
            "存在未结束报告释放流程",
            "exists",
            "boolean",
            (
                "按任务号同时检查 formtable_main_227.zssyrwd 和明细 "
                "formtable_main_227_dt3.zssyrwdlc，任一 currentnodetype 不等于 0 "
                "的项目报告释放流程即为 true。"
            ),
        ),
        _fact(
            "report.merge_flag",
            "合并报告标志",
            "source",
            "integer",
            "主视图字段 sfhbbg；NULL 或 1 时不执行合并组首条去重。",
            nullable=True,
            allowed_values=[0, 1],
        ),
        _fact(
            "report.is_first_task_in_merge",
            "是否合并报告组首条任务",
            "aggregate",
            "boolean",
            "按 hbbglc 分组并按任务 ID 升序编号后，当前任务是否为第一条。",
            grain="merge_report_task",
            parameters=[MERGE_PARAMETER, TASK_PARAMETER],
        ),
        _fact(
            "product.id",
            "产品 ID",
            "source",
            "integer",
            "当前正式实验任务对应的产品 ID；759 使用独立释放路径。",
        ),
        _fact(
            "product.type",
            "产品类型",
            "source",
            "integer",
            "当前产品类型代码；2 和 12 使用业务组服务直接路径。",
        ),
        _fact(
            "order.amount",
            "订单金额",
            "source",
            "money",
            "订单金额 A，即 yhhje，空值按 0。",
            parameters=[ORDER_PARAMETER],
            unit="CNY",
            default_value=0,
        ),
        _fact(
            "amount.receipts_total",
            "订单累计关联金额",
            "aggregate",
            "money",
            "金额 R，即订单普通到款与押金之和；所有覆盖比较在 R 上增加 0.1 容差。",
            parameters=[ORDER_PARAMETER],
            nullable=True,
            null_policy="fail",
            unit="CNY",
        ),
        _fact(
            "amount.deposit_amount",
            "订单关联押金",
            "aggregate",
            "money",
            "金额 D，即订单关联记录中 zxmk=1 的押金金额。",
            parameters=[ORDER_PARAMETER],
            nullable=True,
            null_policy="fail",
            unit="CNY",
        ),
        _fact(
            "amount.prior_report_fee",
            "历史报告释放费用",
            "aggregate",
            "money",
            (
                "金额 B：已计入报告释放范围的历史正式实验费用；任务范围包括 "
                "sfxxsf=0、rwdsyzt 属于 2/7 或 uf_xmbgsf.zt 不等于 2，按订单汇总且任务号去重。"
            ),
            parameters=[ORDER_PARAMETER],
            unit="CNY",
        ),
        _fact(
            "amount.transferred_task_fee",
            "承接转交任务费用",
            "aggregate",
            "money",
            "金额 E：订单下承接转交任务最终采用的结算或预估完工费用。",
            parameters=[ORDER_PARAMETER],
            unit="CNY",
        ),
        _fact(
            "amount.current_task_fee",
            "当前正式实验任务费用",
            "aggregate",
            "money",
            (
                "金额 C：当前任务最终采用费用；有已确认结算时使用结算值，否则使用数量乘"
                "订单服务单价的预估完工费。"
            ),
            unit="CNY",
        ),
        _fact(
            "amount.merged_other_task_fee",
            "合并报告其他任务费用",
            "aggregate",
            "money",
            "金额 M：同一订单、同一合并报告中除当前任务外的正式实验任务费用。",
            grain="merge_report_task",
            parameters=[ORDER_PARAMETER, MERGE_PARAMETER, TASK_PARAMETER],
            unit="CNY",
        ),
        _derived(
            "amount.required_fee",
            "累计应覆盖费用",
            "money",
            "金额 F=B+E+C+M。",
            _operation(
                "add",
                _ref("amount.prior_report_fee"),
                _ref("amount.transferred_task_fee"),
                _ref("amount.current_task_fee"),
                _ref("amount.merged_other_task_fee"),
            ),
            unit="CNY",
        ),
        _derived(
            "amount.task_fee",
            "任务费用",
            "money",
            "金额 T=E+C+M，不包含历史报告释放费用 B。",
            _operation(
                "add",
                _ref("amount.transferred_task_fee"),
                _ref("amount.current_task_fee"),
                _ref("amount.merged_other_task_fee"),
            ),
            unit="CNY",
        ),
        _fact(
            "amount.transferred_estimated_fee",
            "承接转交预估完工费",
            "aggregate",
            "money",
            "订单下承接转交任务的估算完工费合计。",
            parameters=[ORDER_PARAMETER],
            unit="CNY",
        ),
        _fact(
            "amount.formal_estimated_fee",
            "正式实验预估完工费",
            "aggregate",
            "money",
            "订单下正式实验任务的估算完工费合计。",
            parameters=[ORDER_PARAMETER],
            unit="CNY",
        ),
        _derived(
            "amount.estimated_work_fee",
            "订单预估完工费合计",
            "money",
            "金额 W=承接转交预估完工费+正式实验预估完工费。",
            _operation(
                "add",
                _ref("amount.transferred_estimated_fee"),
                _ref("amount.formal_estimated_fee"),
            ),
            unit="CNY",
        ),
        _fact(
            "merged.other_order_fee_failure_count",
            "跨订单费用失败数",
            "aggregate",
            "integer",
            (
                "同一合并报告中其他订单未通过费用规则的数量。每个其他订单在金额为 0，或"
                "非框架且单位属性 14 时 R2+0.1 覆盖 B2+E2+M2，或其他单位/框架时达到"
                "80% 或 D2 覆盖 (W2-R2)*20% 时通过；R2 已含押金。"
            ),
            grain="merge_report_task",
            parameters=[MERGE_PARAMETER, ORDER_PARAMETER],
            null_policy="fail",
        ),
        _fact(
            "contract.current_order_meet_flag",
            "当前订单合同条件通过标志",
            "aggregate",
            "integer",
            (
                "当前订单所有范围内合同的 dd_ismeet。范围包括使用金额大于 0 的关联合同与"
                "执行合同，只判断状态 0；每份合同须命中框架协议、小程序确认，或按单位属性、"
                "范本、额度、2023-11-01 会签边界、生效方式、原件状态和签字方式组成的七个"
                "互斥签署分支之一。无合同或任一合同失败时为 0。"
            ),
            parameters=[ORDER_PARAMETER],
            allowed_values=[0, 1],
            null_policy="fail",
        ),
        _fact(
            "contract.merged_orders_meet_flag",
            "合并关联订单合同条件通过标志",
            "aggregate",
            "integer",
            "合并报告关联订单中 dd_ismeet=0 的数量为 0 时取 1，否则取 0。",
            grain="merge_report_task",
            parameters=[MERGE_PARAMETER],
            allowed_values=[0, 1],
            null_policy="fail",
        ),
        _fact(
            "order.framework_type",
            "是否框架协议原始值",
            "source",
            "integer",
            "订单字段 sfdls 的原始值；0/2 为框架协议，空值按 1。",
            parameters=[ORDER_PARAMETER],
            nullable=True,
            allowed_values=[0, 1, 2],
            default_value=1,
        ),
        _derived(
            "order.effective_framework_type",
            "有效框架协议类型",
            "integer",
            "ISNULL(sfdls,1) 的确定性表达。",
            _operation("coalesce", _ref("order.framework_type"), _literal(1)),
            allowed_values=[0, 1, 2],
        ),
        _fact(
            "order.unit_attribute",
            "单位属性原始值",
            "source",
            "integer",
            "订单单位属性原始值；空值按 -1，14 为普通产品合同金额分支的特殊单位。",
            parameters=[ORDER_PARAMETER],
            nullable=True,
            default_value=-1,
        ),
        _derived(
            "order.effective_unit_attribute",
            "有效单位属性",
            "integer",
            "单位属性空值按 -1 的确定性表达。",
            _operation("coalesce", _ref("order.unit_attribute"), _literal(-1)),
        ),
        _fact(
            "release.special_application_approved",
            "报告释放特殊申请通过",
            "exists",
            "boolean",
            (
                "是否存在 formtable_main_655.sqlx=1、currentnodetype=3 且明细关联当前任务号"
                "的报告释放特殊申请。"
            ),
        ),
        _fact(
            "task.batch_release_flag",
            "是否批量释放原始值",
            "source",
            "integer",
            "任务字段 sfplsf 的原始值；空值按 1，等于 0 时直接放行。",
            nullable=True,
            allowed_values=[0, 1],
            default_value=1,
        ),
        _derived(
            "task.effective_batch_release_flag",
            "有效批量释放标志",
            "integer",
            "ISNULL(sfplsf,1) 的确定性表达。",
            _operation("coalesce", _ref("task.batch_release_flag"), _literal(1)),
            allowed_values=[0, 1],
        ),
        _fact(
            "release.raw_data_record_approved",
            "原始数据释放记录通过",
            "exists",
            "boolean",
            "yssj=0 且存在当前任务 zt=1、fssj 不早于 2024-11-21 的 uf_yssjsf 记录。",
        ),
        _fact(
            "order.source_code",
            "订单来源",
            "source",
            "integer",
            "订单来源字段 ddly；等于 2 时直接放行。",
            parameters=[ORDER_PARAMETER],
        ),
        _fact(
            "invoice.has_unissued_positive_amount",
            "存在未开票正金额发票",
            "exists",
            "boolean",
            "执行合同下是否存在 fpzt=0 且开票金额合计大于 0 的发票。",
            grain="execution_contract",
            parameters=[CONTRACT_PARAMETER],
        ),
        _fact(
            "task.completion_date",
            "任务完工日期",
            "source",
            "date",
            "定时释放使用的正式实验任务完工日期。",
        ),
        _fact(
            "runtime.current_date",
            "数据库当天日期",
            "source",
            "date",
            "规则求值对应的数据库当天日期；定时释放只比较日期相等。",
        ),
        _fact(
            "task.business_scope_flag",
            "业务组服务标志",
            "source",
            "integer",
            "任务字段 ywzfw；产品类型为 2/12 且该值为 0 时直接放行。",
            allowed_values=[0, 1],
        ),
    ]


def _full_coverage(condition_id: str) -> JsonObject:
    return _compare(
        condition_id,
        "订单累计关联金额增加 0.1 容差后覆盖累计应覆盖费用。",
        _operation("add", _ref("amount.receipts_total"), _literal(0.1)),
        "gte",
        _ref("amount.required_fee"),
    )


def _root_condition() -> JsonObject:
    common = _all(
        "common-prerequisites",
        "所有释放路径共同满足的任务前置条件、未结束流程门禁和合并报告去重。",
        _compare(
            "task-status-19",
            "任务状态必须为 19。",
            _ref("task.status"),
            "eq",
            _literal(19),
        ),
        _compare(
            "task-data-status-allowed",
            "空值按 0 后的数据使用状态不得为 2 或 7。",
            _ref("task.effective_data_usage_status"),
            "not_in",
            _literal([2, 7]),
        ),
        _compare(
            "report-release-date-empty",
            "报告释放日期必须为空字符串或 NULL。",
            _ref("task.report_release_date"),
            "is_blank",
            null_policy="error",
        ),
        _compare(
            "online-release-enabled",
            "空值按 1 后的线上释放标志必须为 1。",
            _ref("task.effective_online_release_flag"),
            "eq",
            _literal(1),
        ),
        _any(
            "report-type-eligible",
            "项目报告标志或周期报告标志至少一个为 0。",
            _compare(
                "project-report-zero",
                "项目报告标志为 0。",
                _ref("task.project_report_flag"),
                "eq",
                _literal(0),
            ),
            _compare(
                "periodic-report-zero",
                "周期报告标志为 0。",
                _ref("task.periodic_report_flag"),
                "eq",
                _literal(0),
            ),
        ),
        _not(
            "no-unfinished-report-release",
            "不得存在未结束的项目报告释放流程。",
            _compare(
                "unfinished-report-release-exists",
                "任务号命中任一未结束的项目报告释放流程。",
                _ref("workflow.has_unfinished_report_release"),
                "eq",
                _literal(True),
                null_policy="error",
            ),
        ),
        _any(
            "merge-output-deduplication",
            "非合并标志任务全部保留；其他合并任务只保留组内 ID 最小的一条。",
            _compare(
                "merge-flag-null",
                "合并报告标志为 NULL。",
                _ref("report.merge_flag"),
                "is_null",
                null_policy="error",
            ),
            _compare(
                "merge-flag-one",
                "合并报告标志为 1。",
                _ref("report.merge_flag"),
                "eq",
                _literal(1),
            ),
            _compare(
                "merge-first-task",
                "当前任务为合并报告组内 ID 最小任务。",
                _ref("report.is_first_task_in_merge"),
                "eq",
                _literal(True),
            ),
        ),
    )

    ordinary_contract_money = _all(
        "ordinary-contract-and-money",
        "当前订单及合并关联订单合同均通过，并命中对应订单类型的金额分支。",
        _compare(
            "current-order-contracts-met",
            "当前订单范围内合同条件全部通过。",
            _ref("contract.current_order_meet_flag"),
            "eq",
            _literal(1),
        ),
        _compare(
            "merged-orders-contracts-met",
            "合并报告关联订单合同条件全部通过。",
            _ref("contract.merged_orders_meet_flag"),
            "eq",
            _literal(1),
        ),
        _any(
            "ordinary-contract-amount-paths",
            "根据框架协议和单位属性选择互斥金额分支。",
            _all(
                "ordinary-nonframework-unit14",
                "非框架协议且单位属性为 14 时要求全额覆盖。",
                _compare(
                    "ordinary-nonframework",
                    "订单不是框架协议公司或科研类型。",
                    _ref("order.effective_framework_type"),
                    "not_in",
                    _literal([0, 2]),
                ),
                _compare(
                    "ordinary-unit14",
                    "单位属性为 14。",
                    _ref("order.effective_unit_attribute"),
                    "eq",
                    _literal(14),
                ),
                _full_coverage("ordinary-contract-unit14-full-coverage"),
            ),
            _all(
                "ordinary-other-unit-or-framework",
                "单位属性不为 14 或属于框架协议时采用 80%/押金二选一。",
                _any(
                    "ordinary-other-unit-or-framework-selector",
                    "单位属性不为 14，或者订单为框架协议。",
                    _compare(
                        "ordinary-unit-not14",
                        "单位属性不为 14。",
                        _ref("order.effective_unit_attribute"),
                        "ne",
                        _literal(14),
                    ),
                    _compare(
                        "ordinary-framework",
                        "订单为框架协议公司或科研类型。",
                        _ref("order.effective_framework_type"),
                        "in",
                        _literal([0, 2]),
                    ),
                ),
                _any(
                    "ordinary-eighty-or-deposit",
                    "到款达到 80% 或押金达到当前订单门槛。",
                    _compare(
                        "ordinary-eighty-percent",
                        "R+0.1 大于等于 F 的 80%。",
                        _operation(
                            "add",
                            _ref("amount.receipts_total"),
                            _literal(0.1),
                        ),
                        "gte",
                        _operation(
                            "multiply",
                            _ref("amount.required_fee"),
                            _literal(0.8),
                        ),
                    ),
                    _compare(
                        "ordinary-deposit-threshold",
                        "D 大于等于 W 减 R 的 20%。",
                        _ref("amount.deposit_amount"),
                        "gte",
                        _operation(
                            "subtract",
                            _ref("amount.estimated_work_fee"),
                            _operation(
                                "multiply",
                                _ref("amount.receipts_total"),
                                _literal(0.2),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    ordinary = _all(
        "ordinary-product-path",
        "产品 ID 非 759 时先通过跨订单费用门禁，再命中零金额、全额覆盖或合同金额分支。",
        _compare(
            "ordinary-product-not759",
            "普通产品 ID 不等于 759。",
            _ref("product.id"),
            "ne",
            _literal(759),
        ),
        _compare(
            "cross-order-fees-met",
            "跨订单合并报告的其他订单费用失败数必须为 0。",
            _ref("merged.other_order_fee_failure_count"),
            "eq",
            _literal(0),
        ),
        _any(
            "ordinary-release-alternatives",
            "普通产品命中零金额、独立全额覆盖或合同金额路径之一。",
            _compare(
                "ordinary-zero-order-amount",
                "订单金额为 0。",
                _ref("order.amount"),
                "eq",
                _literal(0),
            ),
            _full_coverage("ordinary-full-coverage"),
            ordinary_contract_money,
        ),
    )

    product_759 = _all(
        "product-759-path",
        "产品 ID 759 使用独立的两档互斥金额规则。",
        _compare(
            "product-is759",
            "产品 ID 等于 759。",
            _ref("product.id"),
            "eq",
            _literal(759),
        ),
        _any(
            "product-759-paths",
            "任务费用十万元及以下使用 70%，超过十万元使用 50%。",
            _all(
                "product-759-lower-band",
                "T 不超过 100000 的 70% 分支。",
                _compare(
                    "product-759-task-fee-lte-100000",
                    "T 小于等于 100000。",
                    _ref("amount.task_fee"),
                    "lte",
                    _literal(100000),
                ),
                _compare(
                    "product-759-seventy-percent",
                    "R+0.1 大于等于 F 的 70%。",
                    _operation(
                        "add",
                        _ref("amount.receipts_total"),
                        _literal(0.1),
                    ),
                    "gte",
                    _operation(
                        "multiply",
                        _ref("amount.required_fee"),
                        _literal(0.7),
                    ),
                ),
            ),
            _all(
                "product-759-upper-band",
                "T 超过 100000 的 50% 分支。",
                _compare(
                    "product-759-task-fee-gt-100000",
                    "T 大于 100000。",
                    _ref("amount.task_fee"),
                    "gt",
                    _literal(100000),
                ),
                _compare(
                    "product-759-fifty-percent",
                    "R+0.1 大于等于 F 的 50%。",
                    _operation(
                        "add",
                        _ref("amount.receipts_total"),
                        _literal(0.1),
                    ),
                    "gte",
                    _operation(
                        "multiply",
                        _ref("amount.required_fee"),
                        _literal(0.5),
                    ),
                ),
            ),
        ),
    )

    timed = _all(
        "timed-release-path",
        "非 2/12 产品且产品 ID 非 759 时，按完工后精确日期进入定时释放。",
        _compare(
            "timed-product-type",
            "产品类型不属于 2 或 12。",
            _ref("product.type"),
            "not_in",
            _literal([2, 12]),
        ),
        _compare(
            "timed-product-not759",
            "产品 ID 不等于 759。",
            _ref("product.id"),
            "ne",
            _literal(759),
        ),
        _any(
            "timed-release-days",
            "精确命中完工后第 60、75 或 180 天之一。",
            _all(
                "timed-release-day60",
                "T 小于 5000、有未开票正金额发票且恰好为第 60 天。",
                _compare(
                    "timed-day60-task-fee",
                    "T 小于 5000。",
                    _ref("amount.task_fee"),
                    "lt",
                    _literal(5000),
                ),
                _compare(
                    "timed-day60-invoice",
                    "存在未开票且金额大于 0 的发票。",
                    _ref("invoice.has_unissued_positive_amount"),
                    "eq",
                    _literal(True),
                    null_policy="error",
                ),
                _compare(
                    "timed-day60-exact-date",
                    "当天日期恰好等于完工日期加 60 天。",
                    _ref("runtime.current_date"),
                    "eq",
                    _operation(
                        "dateAdd",
                        _ref("task.completion_date"),
                        _literal(60),
                        unit="day",
                    ),
                    null_policy="error",
                ),
            ),
            _all(
                "timed-release-day75",
                "T 小于 5000 且恰好为第 75 天，不要求未开票。",
                _compare(
                    "timed-day75-task-fee",
                    "T 小于 5000。",
                    _ref("amount.task_fee"),
                    "lt",
                    _literal(5000),
                ),
                _compare(
                    "timed-day75-exact-date",
                    "当天日期恰好等于完工日期加 75 天。",
                    _ref("runtime.current_date"),
                    "eq",
                    _operation(
                        "dateAdd",
                        _ref("task.completion_date"),
                        _literal(75),
                        unit="day",
                    ),
                    null_policy="error",
                ),
            ),
            _compare(
                "timed-day180-exact-date",
                "当天日期恰好等于完工日期加 180 天，不限制 T。",
                _ref("runtime.current_date"),
                "eq",
                _operation(
                    "dateAdd",
                    _ref("task.completion_date"),
                    _literal(180),
                    unit="day",
                ),
                null_policy="error",
            ),
        ),
    )

    release_paths = _any(
        "release-paths",
        "满足普通产品、759 产品或任一直接放行路径。",
        ordinary,
        product_759,
        _compare(
            "special-application-path",
            "报告释放特殊申请已经通过。",
            _ref("release.special_application_approved"),
            "eq",
            _literal(True),
            null_policy="error",
        ),
        _compare(
            "batch-release-path",
            "空值按 1 后的批量释放标志等于 0。",
            _ref("task.effective_batch_release_flag"),
            "eq",
            _literal(0),
        ),
        _compare(
            "raw-data-record-path",
            "存在符合日期和状态条件的原始数据释放记录。",
            _ref("release.raw_data_record_approved"),
            "eq",
            _literal(True),
            null_policy="error",
        ),
        _compare(
            "order-source-path",
            "订单来源等于 2。",
            _ref("order.source_code"),
            "eq",
            _literal(2),
        ),
        timed,
        _all(
            "business-scope-path",
            "产品类型为 2/12 且业务组服务标志为 0。",
            _compare(
                "business-scope-product-type",
                "产品类型属于 2 或 12。",
                _ref("product.type"),
                "in",
                _literal([2, 12]),
            ),
            _compare(
                "business-scope-zero",
                "业务组服务标志等于 0。",
                _ref("task.business_scope_flag"),
                "eq",
                _literal(0),
            ),
        ),
    )
    return _all(
        "report-release-root",
        "共同前置条件和至少一条释放路径均满足时输出项目报告释放任务。",
        common,
        release_paths,
    )


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
        "release.raw_data_record_approved": False,
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


def _money_inputs(
    *,
    receipts: float,
    prior: float = 10,
    transferred: float = 20,
    current: float = 30,
    merged: float = 40,
) -> JsonObject:
    return {
        "amount.receipts_total": receipts,
        "amount.prior_report_fee": prior,
        "amount.transferred_task_fee": transferred,
        "amount.current_task_fee": current,
        "amount.merged_other_task_fee": merged,
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


def _test_cases() -> list[JsonObject]:
    ordinary_contracts = {
        "contract.current_order_meet_flag": 1,
        "contract.merged_orders_meet_flag": 1,
        "order.framework_type": 1,
        "order.unit_attribute": 13,
    }
    product_759_base = {
        **_common_inputs(),
        **_direct_failures(),
        "product.id": 759,
        "product.type": 2,
        "amount.prior_report_fee": 0,
        "amount.transferred_task_fee": 0,
        "amount.merged_other_task_fee": 0,
    }
    timed_base = {
        **_common_inputs(),
        **_direct_failures(),
        "product.id": 100,
        "product.type": 3,
        "merged.other_order_fee_failure_count": 1,
        "amount.transferred_task_fee": 0,
        "amount.current_task_fee": 4000,
        "amount.merged_other_task_fee": 0,
        "task.completion_date": "2026-01-01",
    }
    return [
        _case(
            "ordinary-full-coverage-contract-fail-pass",
            "normal",
            "普通产品全额覆盖独立于合同条件通过。",
            {
                **_ordinary_base(),
                **_money_inputs(receipts=99.9),
                "order.amount": 1000,
                "contract.current_order_meet_flag": 0,
                "contract.merged_orders_meet_flag": 0,
            },
            "pass",
            "R+0.1 恰好等于 F，独立全额覆盖分支不要求合同通过。",
        ),
        _case(
            "ordinary-eighty-percent-boundary-pass",
            "boundary",
            "普通产品在 80% 精确边界通过。",
            {
                **_ordinary_base(),
                **ordinary_contracts,
                **_money_inputs(receipts=79.9),
                "order.amount": 1000,
                "amount.deposit_amount": 0,
                "amount.transferred_estimated_fee": 100,
                "amount.formal_estimated_fee": 100,
            },
            "pass",
            "R+0.1=80，等于 F*80%。",
        ),
        _case(
            "ordinary-deposit-boundary-pass",
            "boundary",
            "普通产品到款不足 80% 但押金精确达到门槛。",
            {
                **_ordinary_base(),
                **ordinary_contracts,
                **_money_inputs(receipts=50),
                "order.amount": 1000,
                "amount.deposit_amount": 190,
                "amount.transferred_estimated_fee": 100,
                "amount.formal_estimated_fee": 100,
            },
            "pass",
            "D=190，恰好等于 W-R*20%=200-10。",
        ),
        _case(
            "ordinary-zero-amount-cross-order-fail",
            "failure",
            "订单金额为零但跨订单费用门禁失败。",
            {
                **_ordinary_base(),
                "order.amount": 0,
                "merged.other_order_fee_failure_count": 1,
            },
            "fail",
            "普通产品必须先满足跨订单费用失败数为零。",
        ),
        _case(
            "ordinary-contract-and-money-fail",
            "failure",
            "普通产品未全额覆盖且合同不通过。",
            {
                **_ordinary_base(),
                **_money_inputs(receipts=0),
                "order.amount": 1000,
                "contract.current_order_meet_flag": 0,
                "contract.merged_orders_meet_flag": 1,
            },
            "fail",
            "零金额、全额覆盖和合同金额三条路径均未命中。",
        ),
        _case(
            "product-759-lower-boundary-pass",
            "mutuallyExclusiveBranch",
            "产品 759 在 T=100000 时只进入 70% 分支。",
            {
                **product_759_base,
                "amount.current_task_fee": 100000,
                "amount.receipts_total": 69999.9,
            },
            "pass",
            "T=100000 命中小于等于分支，R+0.1 等于 F*70%。",
        ),
        _case(
            "product-759-upper-boundary-pass",
            "mutuallyExclusiveBranch",
            "产品 759 在 T>100000 时进入 50% 分支。",
            {
                **product_759_base,
                "amount.current_task_fee": 100001,
                "amount.receipts_total": 50000.4,
            },
            "pass",
            "T=100001 只命中大于分支，R+0.1 等于 F*50%。",
        ),
        _case(
            "product-759-upper-insufficient-fail",
            "failure",
            "产品 759 超过十万元但未达到 50%。",
            {
                **product_759_base,
                "amount.current_task_fee": 100001,
                "amount.receipts_total": 49999,
            },
            "fail",
            "R+0.1 小于 F*50%，且其他直接路径全部关闭。",
        ),
        _case(
            "special-application-pass",
            "normal",
            "特殊申请通过时直接放行。",
            {**_common_inputs(), "release.special_application_approved": True},
            "pass",
            "共同前置满足且特殊申请存在。",
        ),
        _case(
            "null-defaults-pass",
            "null",
            "共同前置空值默认与空报告日期按来源口径处理。",
            {
                **_common_inputs(),
                "task.data_usage_status": None,
                "task.online_release_flag": None,
                "task.report_release_date": None,
                "release.special_application_approved": True,
            },
            "pass",
            "rwdsyzt 空值按 0、sfxxsf 空值按 1、bgsfrq NULL 视为空。",
        ),
        _case(
            "raw-data-record-pass",
            "normal",
            "指定原始数据释放记录直接放行。",
            {**_common_inputs(), "release.raw_data_record_approved": True},
            "pass",
            "共同前置满足且存在符合状态和日期条件的记录。",
        ),
        _case(
            "order-source-pass",
            "normal",
            "订单来源等于 2 时直接放行。",
            {**_common_inputs(), "order.source_code": 2},
            "pass",
            "订单来源直接路径命中。",
        ),
        _case(
            "business-scope-pass",
            "normal",
            "产品类型 2 且业务组服务标志为 0 时直接放行。",
            {
                **_common_inputs(),
                "product.type": 2,
                "task.business_scope_flag": 0,
            },
            "pass",
            "产品类型与业务组服务条件同时满足。",
        ),
        _case(
            "batch-release-pass",
            "normal",
            "批量释放标志为 0 时直接放行。",
            {**_common_inputs(), "task.batch_release_flag": 0},
            "pass",
            "sfplsf=0 的独立路径命中。",
        ),
        _case(
            "timed-day60-pass",
            "timeBoundary",
            "T 小于 5000 且有未开票正金额发票，在第 60 天通过。",
            {
                **timed_base,
                "invoice.has_unissued_positive_amount": True,
                "runtime.current_date": "2026-03-02",
            },
            "pass",
            "2026-01-01 加 60 天为 2026-03-02。",
        ),
        _case(
            "timed-day61-fail",
            "timeBoundary",
            "错过第 60 天后不会持续命中。",
            {
                **timed_base,
                "invoice.has_unissued_positive_amount": True,
                "runtime.current_date": "2026-03-03",
            },
            "fail",
            "第 61 天不等于 60、75 或 180 天边界。",
        ),
        _case(
            "timed-day75-invoiced-pass",
            "timeBoundary",
            "第 75 天路径不要求未开票。",
            {
                **timed_base,
                "invoice.has_unissued_positive_amount": False,
                "runtime.current_date": "2026-03-17",
            },
            "pass",
            "2026-01-01 加 75 天为 2026-03-17，发票事实不参与该分支。",
        ),
        _case(
            "timed-day180-high-fee-pass",
            "timeBoundary",
            "第 180 天路径不限制 T。",
            {
                **timed_base,
                "amount.current_task_fee": 6000,
                "invoice.has_unissued_positive_amount": False,
                "runtime.current_date": "2026-06-30",
            },
            "pass",
            "2026-01-01 加 180 天为 2026-06-30，T 可大于 5000。",
        ),
        _case(
            "unfinished-flow-blocks-direct-path",
            "failure",
            "直接放行条件也不能绕过未结束流程。",
            {
                **_common_inputs(),
                "workflow.has_unfinished_report_release": True,
                "release.special_application_approved": True,
            },
            "fail",
            "共同前置中的 NOT 未结束流程门禁失败。",
        ),
        _case(
            "merge-deduplication-fail",
            "failure",
            "合并报告非首条任务不进入最终输出。",
            {
                **_common_inputs(),
                "report.merge_flag": 2,
                "report.is_first_task_in_merge": False,
                "release.special_application_approved": True,
            },
            "fail",
            "合并标志非 NULL/1 且不是组内首条。",
        ),
    ]


def _field_mappings(facts: list[JsonObject]) -> list[JsonObject]:
    mapped = {
        "order.amount": ("v_OrderFormaltestsettlement", "yhhje"),
        "amount.receipts_total": ("v_ReportDataReleaseRules", "ddgldk_total"),
        "amount.deposit_amount": ("v_ReportDataReleaseRules", "ddglyj"),
        "amount.transferred_task_fee": ("v_ReportDataReleaseRules", "ctzjjsfy"),
        "amount.current_task_fee": ("v_OrderFormaltestsettlement", "zssyjsfy"),
        "amount.transferred_estimated_fee": ("v_ReportDataReleaseRules", "ctwgfy"),
        "amount.formal_estimated_fee": ("v_ReportDataReleaseRules", "zssywgfy"),
        "contract.current_order_meet_flag": (
            "v_ReportReleaseSealCondition",
            "dd_ismeet",
        ),
    }
    mappings: list[JsonObject] = []
    for fact in facts:
        code = str(fact["factCode"])
        if code in mapped:
            view_name, view_field = mapped[code]
            mappings.append(
                {
                    "factCode": code,
                    "mappingStatus": "mapped",
                    "viewName": view_name,
                    "viewField": view_field,
                    "note": "来源文档明确给出该视图输出字段；仍为待审核候选。",
                }
            )
        else:
            mappings.append(
                {
                    "factCode": code,
                    "mappingStatus": "unresolved",
                    "viewName": None,
                    "viewField": None,
                    "note": "来源未提供可安全确认的目录输出字段，保持未决。",
                }
            )
    return mappings


def build_candidate_payload() -> JsonObject:
    facts = _required_facts()
    return {
        "ruleId": RULE_ID,
        "title": "OA 正式实验任务项目报告自动释放规则",
        "scope": "适用于 OA 正式实验任务单的项目报告自动释放与合并报告结果去重。",
        "entityType": "formal_test_task",
        "sourceViews": [
            "v_sendreport_trigger",
            "v_ReportReleaseSealCondition",
            "v_OrderFormaltestsettlement",
            "v_ReportDataReleaseRules",
        ],
        "requiredFacts": facts,
        "rootCondition": _root_condition(),
        "exceptionNotes": [
            "订单金额为 0 仅绕过当前订单合同和金额条件，不能绕过跨订单费用门禁。",
            "普通产品全额覆盖是独立分支，可绕过合同门禁，但不能绕过跨订单费用门禁。",
            "特殊申请、批量释放、指定原始数据记录、订单来源、定时释放和业务组服务是独立直接路径。",
            "所有直接路径仍受共同前置、未结束流程和合并报告去重约束。",
            "第 60、75、180 天使用日期相等，不使用达到或超过。",
        ],
        "failureReasons": [
            "任务共同前置字段不符合要求或报告已释放。",
            "当前任务存在未结束的项目报告释放流程。",
            "普通产品当前订单到款或押金不足。",
            "当前订单或合并关联订单合同条件未全部通过。",
            "跨订单合并报告存在费用校验失败的其他订单。",
            "产品 759 未达到对应 70% 或 50% 覆盖比例。",
            "定时释放未处于完工后第 60、75 或 180 天的当天。",
            "合并报告任务不是最终保留的组内首条记录。",
        ],
        "recommendations": [
            "核对任务状态、释放日期、数据状态、线上释放和报告类型字段。",
            "检查并结束或撤销当前任务未结束的项目报告释放流程。",
            "核对累计关联金额、押金、任务费用、减免金额和合并报告任务范围。",
            "逐份核对合同额度、范本、签署日期、生效方式、原件状态和签字方式。",
            "逐个核对合并报告其他订单的费用门禁。",
            "涉及产品和单位属性代码时先与 OA 当前枚举字典核对。",
        ],
        "responsibleRoles": ["流程创建人", "产品项目负责人", "项目报告释放人"],
        "testCases": _test_cases(),
        "fieldMappings": _field_mappings(facts),
        "warnings": [
            "v_ReportDataReleaseRules 引用的 v_sto 定义缺失，内部来源必须由元数据审核解决。",
            "合同逐份分支和跨订单逐单费用计算作为聚合事实定义交接，查询筛选与聚合保持阻断未决。",
            "产品、产品类型和单位属性代码的显示名称必须以 OA 当前枚举字典为准。",
            "该 reviewed import 只是不可执行待审核草稿，不代表业务批准或可生成查询。",
        ],
    }


def _walk_conditions(node: ConditionNodeV2) -> list[ConditionNodeV2]:
    return [node, *(item for child in node.children for item in _walk_conditions(child))]


def _fact_children(expression: Any) -> list[str]:
    if expression is None:
        return []
    return [
        child.fact_code
        for child in expression.children
        if child.kind is ExpressionKind.FACT and child.fact_code is not None
    ]


def audit_candidate(candidate: RuleCandidateV2) -> dict[str, int]:
    """Run source-specific assertions that the generic Schema cannot infer."""

    validate_candidate_v2(candidate)
    if candidate.rule_id != RULE_ID:
        raise ValueError(f"unexpected ruleId: {candidate.rule_id}")

    conditions = _walk_conditions(candidate.root_condition)
    by_id = {condition.id: condition for condition in conditions}
    if len(by_id) != len(conditions):
        raise ValueError("condition IDs are not unique")
    if {condition.kind.value for condition in conditions} != {
        "all",
        "any",
        "not",
        "compare",
    }:
        raise ValueError("condition tree must exercise all/any/not/compare")

    full = by_id["ordinary-full-coverage"]
    if full.operator is None or full.operator.value != "gte":
        raise ValueError("ordinary full coverage must use gte")
    if full.left is None or full.left.kind is not ExpressionKind.ADD:
        raise ValueError("ordinary full coverage left side must be add")
    left_facts = _fact_children(full.left)
    left_literals = [
        child.value for child in full.left.children if child.kind is ExpressionKind.LITERAL
    ]
    if left_facts != ["amount.receipts_total"] or left_literals != [0.1]:
        raise ValueError("ordinary full coverage must encode R + 0.1")
    if full.right is None or full.right.fact_code != "amount.required_fee":
        raise ValueError("ordinary full coverage must compare against F")

    facts = {fact.fact_code: fact for fact in candidate.required_facts}
    required_fee = facts["amount.required_fee"]
    if required_fee.derivation is None or _fact_children(required_fee.derivation) != [
        "amount.prior_report_fee",
        "amount.transferred_task_fee",
        "amount.current_task_fee",
        "amount.merged_other_task_fee",
    ]:
        raise ValueError("F must be the structured B + E + C + M derivation")
    task_fee = facts["amount.task_fee"]
    if task_fee.derivation is None or _fact_children(task_fee.derivation) != [
        "amount.transferred_task_fee",
        "amount.current_task_fee",
        "amount.merged_other_task_fee",
    ]:
        raise ValueError("T must be the structured E + C + M derivation")

    product_paths = by_id["product-759-paths"]
    if product_paths.kind.value != "any":
        raise ValueError("product 759 bands must be separate any branches")
    if {child.id for child in product_paths.children} != {
        "product-759-lower-band",
        "product-759-upper-band",
    }:
        raise ValueError("product 759 lower and upper bands are incomplete")
    if by_id["product-759-task-fee-lte-100000"].operator.value != "lte":
        raise ValueError("product 759 lower band must include T <= 100000")
    if by_id["product-759-task-fee-gt-100000"].operator.value != "gt":
        raise ValueError("product 759 upper band must include T > 100000")

    unfinished = by_id["no-unfinished-report-release"]
    if unfinished.kind.value != "not" or len(unfinished.children) != 1:
        raise ValueError("unfinished flow requirement must be an explicit NOT")

    for days in (60, 75, 180):
        timed = by_id[f"timed-day{days}-exact-date"]
        if timed.operator is None or timed.operator.value != "eq":
            raise ValueError(f"day {days} boundary must use equality")
        if timed.right is None or timed.right.kind is not ExpressionKind.DATE_ADD:
            raise ValueError(f"day {days} boundary must use dateAdd")
        literals = [
            child.value for child in timed.right.children if child.kind is ExpressionKind.LITERAL
        ]
        if literals != [days]:
            raise ValueError(f"day {days} boundary has the wrong offset")

    categories = {test.category for test in candidate.test_cases}
    required_categories = set(TestCategoryV2)
    if missing_categories := required_categories - categories:
        missing = sorted(item.value for item in missing_categories)
        raise ValueError(f"missing test categories: {missing}")
    derived_codes = {
        fact.fact_code for fact in candidate.required_facts if fact.fact_kind is FactKind.DERIVED
    }
    for test in candidate.test_cases:
        if supplied_derived := sorted(set(test.given) & derived_codes):
            raise ValueError(
                f"test {test.id} bypasses derivation with supplied values: {supplied_derived}"
            )
    non_derived = [
        fact for fact in candidate.required_facts if fact.fact_kind is not FactKind.DERIVED
    ]
    if any(not fact.parameters for fact in non_derived):
        raise ValueError("all non-derived facts must declare query parameters")

    return {
        "facts": len(candidate.required_facts),
        "nonDerivedFacts": len(non_derived),
        "derivedFacts": len(candidate.required_facts) - len(non_derived),
        "conditions": len(conditions),
        "testCases": len(candidate.test_cases),
        "mappedFacts": Counter(
            mapping.mapping_status.value for mapping in candidate.field_mappings
        )["mapped"],
    }
