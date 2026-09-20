"""Build the 2026-09-20 report-release V3 formula profile.

Offline only. The authoritative rule block lives outside the public repo. This
script records both the full-document SHA-256 and the extracted rule-block
SHA-256, expands eligibility into compare trees, and keeps mapping unresolved.
It does not read SqlBot, SQL Server, MongoDB, or the frozen 1402-character block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rule_reader.domain.rules.bindings_v3 import AggregationModeV3, BindableFactV3
from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    ConfirmedFactV3,
    catalog_digest_v3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.readiness_v3 import build_agent2_readiness_report_v3
from rule_reader.domain.rules.result_v3 import (
    FactDeclarationV3,
    RuleParseResultV3,
    TestCaseV3,
    build_rule_version_v3,
    candidate_payload_sha256_v3,
    export_fact_binding_requests_v3,
)
from rule_reader.domain.rules.v2 import FactKind, RuleOperator
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import (
    EVALUATION_DATE_GIVEN_KEY,
    validate_rule_reachability_witnesses_v3,
    validate_rule_structure_candidate_v3,
)

PLAN_SHA256 = "c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f"
RULE_BLOCK_SHA256 = "e04a686188f6f67393780be95a6054c06b9b50a17ff10ddd24104b5456422ff5"
RULE_BLOCK_CHARACTER_COUNT = 42_437
OLD_RULE_BLOCK_SHA256 = "f285643e5b2bb2ec7b13861716407afda4252c2fbc81eb75a4b0bb3ba4b37c6d"
PARSER_VERSION = "0.12.0-formula-fix"
PROMPT_VERSION = "report-release-v3-formula-20260920-fix"
PROVIDER = "reviewed_import"
MODEL = "reviewed-import-v3-formula"
CATALOG_ID = "REPORT_RELEASE_FORMULA_FACTS"
CATALOG_VERSION = "2026-09-20.2"
RULE_SET_ID = "REPORT_RELEASE_ALL_001"
FIXED_GENERATED_AT = datetime(2026, 9, 20, 9, 20, 0, tzinfo=UTC)
SUPERSEDED_RULE_VERSION = "REPORT_RELEASE_ALL_001@20260920T085100000000Z-e04a686188f6-fe1a673845af"
SEAL_MODELING = "A"
RULE_BLOCK_FILE_NAME = "REPORT_RELEASE_ALL_001.rule-block.txt"
_BINDING_ISSUE = "No approved V3 binding profile; mapping stays unresolved."
_CODING_WARNING = (
    "Workbook legend 4=yes/5=no is warning-only for metadataReview; active when compares Java 0/1."
)

TASK_KEY = {
    "name": "taskId",
    "role": "entityKey",
    "dataType": "string",
    "required": True,
    "description": "Formal experiment task identifier.",
}
ORDER_KEY = {
    "name": "orderId",
    "role": "entityKey",
    "dataType": "string",
    "required": True,
    "description": "Order identifier.",
}

_FACT_SPECS: list[dict[str, Any]] = [
    {
        "factCode": "report.release_status",
        "name": "报告释放状态",
        "description": "释放状态；准备释放/释放中/已释放为终态并跳过。空值继续评估。",
        "dataType": "enum",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": ["准备释放", "释放中", "已释放"],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.status_code",
        "name": "任务状态",
        "description": "任务状态码；19 为内部完工确认。空或非 19 则等待完工。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.experiment_status_code",
        "name": "任务单实验状态",
        "description": "实验状态；2 为失败线下确认收入，7 为问题项目，二者无需释放。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.offline_report_release_flag",
        "name": "线下报告释放标志",
        "description": "Java 比较 0 表示已线下释放。工作簿 4/5 不得写入 active when。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.batch_report_release_flag",
        "name": "批量报告释放标志",
        "description": "Java 比较 0 表示标记批量释放。工作簿 4/5 不得写入 active when。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.project_report_flag",
        "name": "项目报告有无",
        "description": "0 表示有项目报告；1 表示无。空或其他值进入报告待定。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.qc_report_flag",
        "name": "质控报告有无",
        "description": "0 表示有质控报告；1 表示无。与项目报告共同判定前提 3。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.raw_data_flag",
        "name": "原始数据有无",
        "description": "仅供 R4：0 表示原始数据已释放。不是原始数据释放规则集。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.completion_date",
        "name": "完工日期",
        "description": "任务完工日。R4 与阈值比较；R8 用日期相等匹配完工日加天数。",
        "dataType": "date",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.no_main_service_flag",
        "name": "无主服务标志",
        "description": "0 表示无主服务，供 R8D 与产品类型共同判定。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.product_id",
        "name": "任务产品编号",
        "description": "当前正式实验任务单的产品编号。R3 要求 759，并继续展开 70%/50% 金额树。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.product_type_code",
        "name": "任务产品类型",
        "description": (
            "当前任务的产品类型。2/12 为酵母筛库或家族库；空值可进入 R8ABC，"
            "不因 in{2,12} 变成不确定。"
        ),
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "fail",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.in_oa_process",
        "name": "任务在未结束项目报告 OA 流程中",
        "description": "存在未结束的项目报告 OA 流程时为真，命中后排除触发。",
        "dataType": "boolean",
        "nullable": False,
        "nullPolicy": "fail",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [True, False],
        "unit": None,
        "kind": FactKind.EXISTS,
    },
    {
        "factCode": "order.amount",
        "name": "订单金额",
        "description": "订单金额。R0 在等于 0 时命中。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.source_code",
        "name": "订单来源",
        "description": "订单来源。2 表示海外业务，命中 R2。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.associated_receipts_including_deposit",
        "name": "订单关联到款含押金",
        "description": "到款含押金 = 项目款 + 押金。金额比较保留 +0.1 容差。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.associated_deposit",
        "name": "订单关联押金",
        "description": "订单关联押金。用于 R6 条件 B 与 R7 押金分支。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.extraction_qc_amount",
        "name": "抽提质检金额",
        "description": "抽提质检金额。计入累计完工金额与 R3 基准金额。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "task.task_amount",
        "name": "任务单金额",
        "description": (
            "当前正式实验任务单金额（rwdje），不是订单下全部任务合计。"
            "计入累计完工与 R3 基准；R8 用其分档 5000。"
        ),
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.report_released_amount",
        "name": "订单项目报告释放金额",
        "description": "已释放项目报告金额。计入累计完工，不使用原始数据释放金额。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.invoice_amount",
        "name": "订单开票金额",
        "description": "开票金额。R8 在任务单金额小于 5000 时用是否大于 0 选择 60/75 天。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": "CNY",
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.is_framework",
        "name": "是否框架协议",
        "description": "框架协议为真当协议类型属于 {0,2}；空视为非框架。",
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [True, False],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "order.is_enterprise",
        "name": "是否企业单位",
        "description": "企业单位为真当单位类型属于 {14,16}；空视为非企业。",
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [True, False],
        "unit": None,
        "kind": FactKind.SOURCE,
    },
    {
        "factCode": "release.special_application_count",
        "name": "特殊申请已审批数量",
        "description": "项目报告类型且当前节点类型属于 {3} 的特殊申请条数；大于 0 命中 R1。",
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.AGGREGATE,
    },
    {
        "factCode": "order.in_scope_contract_count",
        "name": "范围内合同份数",
        "description": (
            "盖章范围=执行合同∪关联合同（剩余金额合计>0）的合同份数。"
            "0 表示范围为空，R6 条件 B 盖章失败，不是 INDETERMINATE。"
            "Seal modeling=A：五分支是本计数与 unsealed 计数的聚合谓词，不进入 R6 when。"
        ),
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "fail",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.AGGREGATE,
    },
    {
        "factCode": "order.unsealed_in_scope_contract_count",
        "name": "范围内未盖章合同份数",
        "description": (
            "范围内不满足 isContractSealed 五分支的合同份数。五分支互斥顺序："
            "(1) 额度类型=3 小程序确认；(2) 非范本且已盖章（签收状态∈{1,2}）；"
            "(3) 范本且额度内小金额且签收状态∈{0,1,2}；"
            "(4) 会签日>=2023-11-01 且生效方式=盖章且已盖章；"
            "(5) 其余：已盖章，或已签字未盖章且签字方式不是联系人电子签。"
            "任一份失败则本计数>=1，条件 B 失败。"
        ),
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "fail",
        "grain": "order",
        "parameters": [ORDER_KEY],
        "allowedValues": [],
        "unit": None,
        "kind": FactKind.AGGREGATE,
    },
    {
        "factCode": "report.merge_group_eligible",
        "name": "合并报告组约束满足",
        "description": (
            "非合并组，或相关任务已处于准备释放/释放中/已释放，"
            "或实时通过报告前提并命中任一报告资格规则。不含原始数据规则。"
        ),
        "dataType": "boolean",
        "nullable": False,
        "nullPolicy": "fail",
        "grain": "task",
        "parameters": [TASK_KEY],
        "allowedValues": [True, False],
        "unit": None,
        "kind": FactKind.EXISTS,
    },
]


def _fact(code: str) -> dict[str, Any]:
    return {"kind": "fact", "factCode": code, "children": []}


def _lit(value: Any) -> dict[str, Any]:
    return {"kind": "literal", "value": value, "children": []}


def _op(kind: str, *children: dict[str, Any], unit: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": kind, "children": list(children)}
    if unit is not None:
        payload["unit"] = unit
    return payload


def _add(*children: dict[str, Any]) -> dict[str, Any]:
    return _op("add", *children)


def _sub(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return _op("subtract", left, right)


def _mul(*children: dict[str, Any]) -> dict[str, Any]:
    return _op("multiply", *children)


def _date_add(date_expr: dict[str, Any], days: int) -> dict[str, Any]:
    return _op("dateAdd", date_expr, _lit(days), unit="day")


def _node(
    condition_id: str,
    kind: str,
    *,
    children: list[dict[str, Any]] | None = None,
    left: dict[str, Any] | None = None,
    operator: str | None = None,
    right: dict[str, Any] | None = None,
    null_policy: str = "indeterminate",
) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": kind,
        "description": condition_id.replace("-", " "),
        "enabled": True,
        "children": children or [],
        "left": left,
        "operator": operator,
        "right": right,
        "nullPolicy": null_policy,
    }


def _cmp(
    condition_id: str,
    left: dict[str, Any],
    operator: str,
    right: dict[str, Any] | None,
    *,
    null_policy: str = "indeterminate",
) -> dict[str, Any]:
    return _node(
        condition_id,
        "compare",
        left=left,
        operator=operator,
        right=right,
        null_policy=null_policy,
    )


def _fc(
    condition_id: str,
    fact_code: str,
    operator: str,
    value: Any = None,
    *,
    null_policy: str = "indeterminate",
) -> dict[str, Any]:
    right = None
    if not operator.startswith("is_"):
        right = _lit(value)
    return _cmp(condition_id, _fact(fact_code), operator, right, null_policy=null_policy)


def _all(condition_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return _node(condition_id, "all", children=children)


def _any(condition_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return _node(condition_id, "any", children=children)


def _not(condition_id: str, child: dict[str, Any]) -> dict[str, Any]:
    return _node(condition_id, "not", children=[child])


def _completed() -> dict[str, Any]:
    return _add(
        _fact("order.extraction_qc_amount"),
        _fact("task.task_amount"),
        _fact("order.report_released_amount"),
    )


def _paid() -> dict[str, Any]:
    return _add(_fact("order.associated_receipts_including_deposit"), _lit(0.1))


def _base_amount() -> dict[str, Any]:
    return _add(_fact("order.extraction_qc_amount"), _fact("task.task_amount"))


def _unpaid() -> dict[str, Any]:
    return _sub(_completed(), _fact("order.associated_receipts_including_deposit"))


def _not_framework() -> dict[str, Any]:
    return _not(
        "not-framework",
        _fc("is-framework", "order.is_framework", "eq", True, null_policy="fail"),
    )


def _not_enterprise() -> dict[str, Any]:
    return _not(
        "not-enterprise",
        _fc("is-enterprise", "order.is_enterprise", "eq", True, null_policy="fail"),
    )


def _not_special_product(condition_id: str) -> dict[str, Any]:
    return _any(
        condition_id,
        [
            _fc(f"{condition_id}-null", "task.product_id", "is_null"),
            _fc(f"{condition_id}-ne", "task.product_id", "ne", 759, null_policy="fail"),
        ],
    )


def _today() -> dict[str, Any]:
    return {"kind": "today", "children": []}


def _seal_all_in_scope() -> dict[str, Any]:
    return _all(
        "r6-seal-all-in-scope",
        [
            _fc(
                "r6-in-scope-contracts",
                "order.in_scope_contract_count",
                "gt",
                0,
                null_policy="fail",
            ),
            _fc(
                "r6-unsealed-none",
                "order.unsealed_in_scope_contract_count",
                "eq",
                0,
                null_policy="fail",
            ),
        ],
    )


def _r3_when() -> dict[str, Any]:
    return _all(
        "r3-special-product",
        [
            _fc("r3-product", "task.product_id", "eq", 759, null_policy="fail"),
            _any(
                "r3-amount-branches",
                [
                    _all(
                        "r3-ratio-70",
                        [
                            _cmp(
                                "r3-base-le",
                                _base_amount(),
                                "lte",
                                _lit(100000),
                                null_policy="indeterminate",
                            ),
                            _cmp(
                                "r3-paid-70",
                                _paid(),
                                "gte",
                                _mul(_completed(), _lit(0.7)),
                                null_policy="indeterminate",
                            ),
                        ],
                    ),
                    _all(
                        "r3-ratio-50",
                        [
                            _cmp(
                                "r3-base-gt",
                                _base_amount(),
                                "gt",
                                _lit(100000),
                                null_policy="indeterminate",
                            ),
                            _cmp(
                                "r3-paid-50",
                                _paid(),
                                "gte",
                                _mul(_completed(), _lit(0.5)),
                                null_policy="indeterminate",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _today_eq(days: int, condition_id: str) -> dict[str, Any]:
    return _cmp(
        condition_id,
        _today(),
        "eq",
        _date_add(_fact("task.completion_date"), days),
        null_policy="indeterminate",
    )


def _r8_when() -> dict[str, Any]:
    return _any(
        "r8-time-trigger",
        [
            _all(
                "r8d",
                [
                    _fc(
                        "r8d-yeast-type",
                        "task.product_type_code",
                        "in",
                        [2, 12],
                        null_policy="fail",
                    ),
                    _fc("r8d-no-main", "task.no_main_service_flag", "eq", 0, null_policy="fail"),
                ],
            ),
            _all(
                "r8-abc",
                [
                    _not(
                        "r8-not-yeast",
                        _fc(
                            "r8abc-yeast-type",
                            "task.product_type_code",
                            "in",
                            [2, 12],
                            null_policy="fail",
                        ),
                    ),
                    _not_special_product("r8-not-759"),
                    _any(
                        "r8-abc-amount",
                        [
                            _all(
                                "r8-under-5000",
                                [
                                    _fc(
                                        "r8-amount-lt",
                                        "task.task_amount",
                                        "lt",
                                        5000,
                                        null_policy="fail",
                                    ),
                                    _any(
                                        "r8-ab",
                                        [
                                            _all(
                                                "r8a",
                                                [
                                                    _fc(
                                                        "r8-invoiced",
                                                        "order.invoice_amount",
                                                        "gt",
                                                        0,
                                                        null_policy="fail",
                                                    ),
                                                    _today_eq(60, "r8a-today"),
                                                ],
                                            ),
                                            _all(
                                                "r8b",
                                                [
                                                    _not(
                                                        "r8-not-invoiced",
                                                        _fc(
                                                            "r8-unpaid-invoice",
                                                            "order.invoice_amount",
                                                            "gt",
                                                            0,
                                                            null_policy="fail",
                                                        ),
                                                    ),
                                                    _today_eq(75, "r8b-today"),
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            _all(
                                "r8c",
                                [
                                    _fc(
                                        "r8-amount-ge",
                                        "task.task_amount",
                                        "gte",
                                        5000,
                                        null_policy="fail",
                                    ),
                                    _today_eq(180, "r8c-today"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _r5_when() -> dict[str, Any]:
    return _all(
        "r5-enterprise",
        [
            _not_framework(),
            _fc("r5-is-enterprise", "order.is_enterprise", "eq", True, null_policy="fail"),
            _not_special_product("r5-not-759"),
            _cmp("r5-full-payment", _paid(), "gte", _completed(), null_policy="indeterminate"),
        ],
    )


def _r6_when() -> dict[str, Any]:
    return _all(
        "r6-non-enterprise",
        [
            _not_framework(),
            _not_enterprise(),
            _not_special_product("r6-not-759"),
            _any(
                "r6-or-ab",
                [
                    _cmp("r6-cond-a", _paid(), "gte", _completed(), null_policy="indeterminate"),
                    _all(
                        "r6-cond-b",
                        [
                            _cmp(
                                "r6-b-arrival",
                                _paid(),
                                "gte",
                                _mul(_completed(), _lit(0.8)),
                                null_policy="indeterminate",
                            ),
                            _cmp(
                                "r6-b-deposit",
                                _fact("order.associated_deposit"),
                                "gte",
                                _mul(_unpaid(), _lit(0.2)),
                                null_policy="indeterminate",
                            ),
                            _seal_all_in_scope(),
                        ],
                    ),
                ],
            ),
        ],
    )


def _r7_when() -> dict[str, Any]:
    return _all(
        "r7-framework",
        [
            _fc("r7-is-framework", "order.is_framework", "eq", True, null_policy="fail"),
            _any(
                "r7-or",
                [
                    _cmp(
                        "r7-arrival",
                        _paid(),
                        "gte",
                        _mul(_completed(), _lit(0.8)),
                        null_policy="indeterminate",
                    ),
                    _cmp(
                        "r7-deposit",
                        _fact("order.associated_deposit"),
                        "gte",
                        _mul(_unpaid(), _lit(0.2)),
                        null_policy="indeterminate",
                    ),
                ],
            ),
        ],
    )


def _active(
    code: str, priority: int, title: str, when: dict[str, Any], outcome: str
) -> dict[str, Any]:
    return {
        "ruleCode": code,
        "priority": priority,
        "title": title,
        "status": "active",
        "when": when,
        "outcome": outcome,
        "reasonCode": f"{code}_MATCHED",
        "failureReason": f"{title}。",
        "recommendations": ["按优化方案 Java 与 2026-09-20 裁决核对对应事实。"],
        "blockingIssueIds": [],
    }


def _availability_unknown() -> dict[str, Any]:
    has_report = _any(
        "has-any-report",
        [
            _fc("has-project-report", "task.project_report_flag", "eq", 0, null_policy="fail"),
            _fc("has-qc-report", "task.qc_report_flag", "eq", 0, null_policy="fail"),
        ],
    )
    no_report = _all(
        "both-reports-absent",
        [
            _fc("no-project-report-flag", "task.project_report_flag", "eq", 1, null_policy="fail"),
            _fc("no-qc-report-flag", "task.qc_report_flag", "eq", 1, null_policy="fail"),
        ],
    )
    return _all(
        "report-availability-unknown",
        [
            _not("not-has-any-report", has_report),
            _not("not-both-absent", no_report),
        ],
    )


_STAGES: list[dict[str, Any]] = [
    {
        "stage": "stateGuards",
        "rules": [
            {
                **_active(
                    "REPORT_STATUS_TERMINAL",
                    10,
                    "释放状态表终态检查",
                    _fc(
                        "release-status-terminal",
                        "report.release_status",
                        "in",
                        ["准备释放", "释放中", "已释放"],
                    ),
                    "SKIPPED",
                ),
                "when": {
                    **_fc(
                        "release-status-terminal",
                        "report.release_status",
                        "in",
                        ["准备释放", "释放中", "已释放"],
                    ),
                    "nullPolicy": "fail",
                },
            }
        ],
    },
    {
        "stage": "prerequisites",
        "rules": [
            _active(
                "TASK_NOT_COMPLETED",
                10,
                "任务尚未完工",
                _any(
                    "task-not-completed",
                    [
                        _fc("task-status-null", "task.status_code", "is_null"),
                        _fc("task-status-ne-19", "task.status_code", "ne", 19, null_policy="fail"),
                    ],
                ),
                "WAITING_COMPLETION",
            ),
            _active(
                "EXPERIMENT_STATUS_OFFLINE",
                20,
                "失败导致线下确认收入",
                _fc(
                    "experiment-status-offline",
                    "task.experiment_status_code",
                    "eq",
                    2,
                    null_policy="fail",
                ),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "EXPERIMENT_STATUS_PROBLEM",
                30,
                "问题项目无需释放",
                _fc(
                    "experiment-status-problem",
                    "task.experiment_status_code",
                    "eq",
                    7,
                    null_policy="fail",
                ),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "OFFLINE_REPORT_RELEASED",
                40,
                "项目报告已线下释放",
                _fc(
                    "offline-report-released",
                    "task.offline_report_release_flag",
                    "eq",
                    0,
                    null_policy="fail",
                ),
                "ALREADY_RELEASED",
            ),
            _active(
                "NO_PROJECT_REPORT",
                50,
                "任务无需项目报告",
                _all(
                    "no-project-report",
                    [
                        _fc(
                            "project-report-absent",
                            "task.project_report_flag",
                            "eq",
                            1,
                            null_policy="fail",
                        ),
                        _fc("qc-report-absent", "task.qc_report_flag", "eq", 1, null_policy="fail"),
                    ],
                ),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "REPORT_AVAILABILITY_UNKNOWN",
                60,
                "有无项目报告待定",
                _availability_unknown(),
                "WAITING_CONDITIONS",
            ),
        ],
    },
    {
        "stage": "eligibility",
        "rules": [
            _active(
                "R0_ZERO_ORDER",
                10,
                "R0 0元订单",
                _fc("r0-zero-order", "order.amount", "eq", 0, null_policy="indeterminate"),
                "READY",
            ),
            _active(
                "R1_SPECIAL_APPROVAL",
                20,
                "R1 特殊申请已审批",
                _fc(
                    "r1-special-approval",
                    "release.special_application_count",
                    "gt",
                    0,
                    null_policy="indeterminate",
                ),
                "READY",
            ),
            _active(
                "R9_BATCH_RELEASE",
                30,
                "R9 标记批量释放",
                _fc(
                    "r9-batch-release",
                    "task.batch_report_release_flag",
                    "eq",
                    0,
                    null_policy="indeterminate",
                ),
                "READY",
            ),
            _active(
                "R4_RAW_DATA_RELEASED",
                40,
                "R4 原始数据已释放",
                _all(
                    "r4-raw-data-released",
                    [
                        _fc("r4-yssj", "task.raw_data_flag", "eq", 0, null_policy="fail"),
                        _cmp(
                            "r4-wgsj",
                            _fact("task.completion_date"),
                            "gte",
                            _lit("2024-11-21"),
                            null_policy="indeterminate",
                        ),
                    ],
                ),
                "READY",
            ),
            _active(
                "R2_OVERSEAS_ORDER",
                50,
                "R2 海外业务订单",
                _fc("r2-overseas-order", "order.source_code", "eq", 2, null_policy="indeterminate"),
                "READY",
            ),
            _active(
                "R3_SPECIAL_PRODUCT",
                60,
                "R3 特殊产品金额树",
                _r3_when(),
                "READY",
            ),
            _active(
                "R8_TIME_TRIGGER",
                70,
                "R8 完工时间触发",
                _r8_when(),
                "READY",
            ),
            _active(
                "R5_ENTERPRISE",
                80,
                "R5 非框架企业单位",
                _r5_when(),
                "READY",
            ),
            _active(
                "R6_NON_ENTERPRISE",
                90,
                "R6 非框架非企业单位",
                _r6_when(),
                "READY",
            ),
            _active(
                "R7_FRAMEWORK",
                100,
                "R7 框架协议",
                _r7_when(),
                "READY",
            ),
        ],
    },
    {
        "stage": "postGates",
        "rules": [
            _active(
                "MERGED_REPORT_GATE",
                10,
                "合并报告组未齐则等待满足条件",
                _fc(
                    "merged-report-gate",
                    "report.merge_group_eligible",
                    "ne",
                    True,
                    null_policy="fail",
                ),
                "WAITING_CONDITIONS",
            )
        ],
    },
    {
        "stage": "exclusions",
        "rules": [
            _active(
                "OA_PROCESS_SCOPE",
                10,
                "在项目报告 OA 流程中则排除",
                _fc("oa-process-scope", "task.in_oa_process", "eq", True, null_policy="fail"),
                "WAITING_CONDITIONS",
            )
        ],
    },
]


def _closure_fact_codes(stages: list[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()

    def walk_expr(expression: dict[str, Any] | None) -> None:
        if not expression:
            return
        if expression.get("kind") == "fact" and expression.get("factCode"):
            codes.add(str(expression["factCode"]))
        for child in expression.get("children", []):
            walk_expr(child)

    def walk(node: dict[str, Any]) -> None:
        walk_expr(node.get("left"))
        walk_expr(node.get("right"))
        for child in node.get("children", []):
            walk(child)

    for stage in stages:
        for rule in stage["rules"]:
            when = rule.get("when")
            if when:
                walk(when)
    return sorted(codes)


def _duplicate_condition_ids(node: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    def walk(current: dict[str, Any]) -> None:
        ids.append(str(current["id"]))
        for child in current.get("children", []):
            walk(child)

    walk(node)
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in ids:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    return duplicates


def _rewrite_shared_condition_ids() -> None:
    """Give globally unique ids to helper trees reused across rules."""

    replacements = {
        "R5_ENTERPRISE": {
            "not-framework": "r5-not-framework",
            "is-framework": "r5-is-framework-check",
            "r5-not-759": "r5-not-759",
            "r5-not-759-null": "r5-not-759-null",
            "r5-not-759-ne": "r5-not-759-ne",
        },
        "R6_NON_ENTERPRISE": {
            "not-framework": "r6-not-framework",
            "is-framework": "r6-is-framework-check",
            "not-enterprise": "r6-not-enterprise",
            "is-enterprise": "r6-is-enterprise-check",
            "r6-not-759": "r6-not-759",
            "r6-not-759-null": "r6-not-759-null",
            "r6-not-759-ne": "r6-not-759-ne",
        },
        "R8_TIME_TRIGGER": {},
    }

    def rewrite(node: dict[str, Any], mapping: dict[str, str]) -> None:
        current_id = str(node["id"])
        if current_id in mapping:
            node["id"] = mapping[current_id]
            node["description"] = node["id"].replace("-", " ")
        for child in node.get("children", []):
            rewrite(child, mapping)

    for stage in _STAGES:
        for rule in stage["rules"]:
            mapping = replacements.get(str(rule["ruleCode"]), {})
            if mapping:
                rewrite(rule["when"], mapping)


_rewrite_shared_condition_ids()


def build_formula_catalog(
    *,
    plan_sha256: str = PLAN_SHA256,
    rule_block_sha256: str = RULE_BLOCK_SHA256,
) -> BusinessConfirmedFactCatalogV3:
    evidence = [
        {
            "evidenceId": "plan.full-document",
            "sourceKind": "ruleText",
            "sourceId": "optimization-plan",
            "sourceSha256": plan_sha256,
            "locator": "full-document",
            "note": "2026-09-20 用户指定的优化方案全文身份。",
        },
        {
            "evidenceId": "plan.rule-block",
            "sourceKind": "ruleText",
            "sourceId": RULE_BLOCK_FILE_NAME,
            "sourceSha256": rule_block_sha256,
            "locator": "extracted-report-side-block",
            "note": "实际送入解析器的报告侧规则块，含 1.3 树、5.2 报告 Java 与 5.5 报告金额。",
        },
    ]
    facts = []
    for spec in _FACT_SPECS:
        facts.append(
            {
                "factCode": spec["factCode"],
                "name": spec["name"],
                "description": spec["description"],
                "dataType": spec["dataType"],
                "nullable": spec["nullable"],
                "nullPolicy": spec["nullPolicy"],
                "grain": spec["grain"],
                "parameters": spec["parameters"],
                "allowedValues": spec["allowedValues"],
                "unit": spec["unit"],
                "evidenceRefs": ["plan.full-document", "plan.rule-block"],
                "bindingProfileRef": None,
                "bindingIssues": [_BINDING_ISSUE],
            }
        )
    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": CATALOG_ID,
        "catalogVersion": CATALOG_VERSION,
        "catalogDigest": "0" * 64,
        "facts": facts,
        "evidence": evidence,
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    catalog = BusinessConfirmedFactCatalogV3.model_validate(payload)
    validate_fact_catalog_v3(catalog)
    return catalog


def _eligibility_miss_priors() -> dict[str, Any]:
    return {
        "order.amount": 12000.0,
        "release.special_application_count": 0,
        "task.batch_report_release_flag": 1,
        "task.raw_data_flag": 1,
        "task.completion_date": "2024-01-01",
        "order.source_code": 1,
        "task.product_id": 1,
        "task.product_type_code": 1,
        "task.no_main_service_flag": 1,
        "task.task_amount": 10000.0,
        "order.invoice_amount": 0.0,
        EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
        "order.is_framework": False,
        "order.is_enterprise": False,
        "order.associated_receipts_including_deposit": 0.0,
        "order.associated_deposit": 0.0,
        "order.extraction_qc_amount": 0.0,
        "order.report_released_amount": 0.0,
        "order.in_scope_contract_count": 0,
        "order.unsealed_in_scope_contract_count": 0,
    }


_WITNESSES: dict[str, dict[str, Any]] = {
    "REPORT_STATUS_TERMINAL": {"report.release_status": "准备释放"},
    "TASK_NOT_COMPLETED": {"task.status_code": 226},
    "EXPERIMENT_STATUS_OFFLINE": {"task.status_code": 19, "task.experiment_status_code": 2},
    "EXPERIMENT_STATUS_PROBLEM": {"task.status_code": 19, "task.experiment_status_code": 7},
    "OFFLINE_REPORT_RELEASED": {
        "task.status_code": 19,
        "task.offline_report_release_flag": 0,
    },
    "NO_PROJECT_REPORT": {
        "task.status_code": 19,
        "task.project_report_flag": 1,
        "task.qc_report_flag": 1,
    },
    "REPORT_AVAILABILITY_UNKNOWN": {
        "task.status_code": 19,
        "task.project_report_flag": None,
        "task.qc_report_flag": None,
    },
    "R0_ZERO_ORDER": {"order.amount": 0.0},
    "R1_SPECIAL_APPROVAL": {
        "order.amount": 12000.0,
        "release.special_application_count": 1,
    },
    "R9_BATCH_RELEASE": {
        "order.amount": 12000.0,
        "release.special_application_count": 0,
        "task.batch_report_release_flag": 0,
    },
    "R4_RAW_DATA_RELEASED": {
        **_eligibility_miss_priors(),
        "task.raw_data_flag": 0,
        "task.completion_date": "2024-11-21",
    },
    "R2_OVERSEAS_ORDER": {**_eligibility_miss_priors(), "order.source_code": 2},
    "R3_SPECIAL_PRODUCT": {
        **_eligibility_miss_priors(),
        "task.product_id": 759,
        "order.extraction_qc_amount": 0.0,
        "task.task_amount": 10000.0,
        "order.report_released_amount": 0.0,
        "order.associated_receipts_including_deposit": 7000.0,
    },
    "R8_TIME_TRIGGER": {
        **_eligibility_miss_priors(),
        "task.product_type_code": 2,
        "task.no_main_service_flag": 0,
    },
    "R5_ENTERPRISE": {
        **_eligibility_miss_priors(),
        "order.is_enterprise": True,
        "order.associated_receipts_including_deposit": 10000.0,
        "task.task_amount": 10000.0,
    },
    "R6_NON_ENTERPRISE": {
        **_eligibility_miss_priors(),
        "order.associated_receipts_including_deposit": 10000.0,
        "task.task_amount": 10000.0,
    },
    "R7_FRAMEWORK": {
        **_eligibility_miss_priors(),
        "order.is_framework": True,
        "order.associated_receipts_including_deposit": 8000.0,
        "task.task_amount": 10000.0,
    },
    "MERGED_REPORT_GATE": {"report.merge_group_eligible": False},
    "OA_PROCESS_SCOPE": {"task.in_oa_process": True},
}


def build_formula_candidate(
    catalog: BusinessConfirmedFactCatalogV3,
) -> RuleStructureCandidateV3:
    seen_ids: dict[str, str] = {}
    for stage in _STAGES:
        for rule in stage["rules"]:
            duplicates = _duplicate_condition_ids(rule["when"])
            if duplicates:
                raise ValueError(f"{rule['ruleCode']} duplicate condition ids: {duplicates}")

            def _walk_ids(node: dict[str, Any], rule_code: str) -> None:
                current = str(node["id"])
                owner = seen_ids.get(current)
                if owner is not None:
                    raise ValueError(f"condition id {current} used by {owner} and {rule_code}")
                seen_ids[current] = rule_code
                for child in node.get("children", []):
                    _walk_ids(child, rule_code)

            _walk_ids(rule["when"], str(rule["ruleCode"]))
    required = _closure_fact_codes(_STAGES)
    payload = {
        "contractVersion": "3.0.0",
        "ruleSetId": RULE_SET_ID,
        "title": "有序项目报告释放规则（公式树）",
        "scope": (
            "OA 正式实验任务单项目报告释放；按 stateGuards、prerequisites、"
            "R0/R1/R9/R4/R2/R3/R8/R5/R6/R7、postGates、exclusions 顺序。不含原始数据规则。"
            "Seal modeling=A：isContractSealed 五分支写入范围内合同计数的 queryRequirements，"
            "R6 when 只比较 in_scope_contract_count>0 且 unsealed_in_scope_contract_count=0。"
            "report.merge_group_eligible 仍是未展开 exists 黑盒。"
        ),
        "catalogId": catalog.catalog_id,
        "catalogVersion": catalog.catalog_version,
        "catalogDigest": catalog.catalog_digest,
        "sourceViews": [
            "optimization-plan-section-1.3-report-tree",
            "optimization-plan-section-5.2-report-engine",
            "optimization-plan-section-5.5-report-amounts",
        ],
        "requiredFactCodes": required,
        "stages": _STAGES,
        "defaultOutcome": "WAITING_CONDITIONS",
        "defaultReasonCode": "NO_ORDERED_RELEASE_RULE_MATCHED",
        "blockingIssues": [],
        "proposedFacts": [],
    }
    candidate = RuleStructureCandidateV3.model_validate(payload)
    validate_rule_structure_candidate_v3(candidate, catalog)
    validate_rule_reachability_witnesses_v3(candidate, catalog, _WITNESSES)
    return candidate


_FACT_KINDS = {spec["factCode"]: spec["kind"] for spec in _FACT_SPECS}
_GRAIN_ENTITY = {
    "task": ("task", "taskId"),
    "order": ("order", "orderId"),
}


def _bindable_fact(fact: ConfirmedFactV3) -> BindableFactV3:
    return BindableFactV3.model_validate(
        {
            "factCode": fact.fact_code,
            "name": fact.name,
            "factKind": _FACT_KINDS[fact.fact_code].value,
            "dataType": fact.data_type.value,
            "description": fact.description,
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "grain": fact.grain,
            "parameters": [
                parameter.model_dump(mode="json", by_alias=True) for parameter in fact.parameters
            ],
            "unit": fact.unit,
            "allowedValues": fact.allowed_values,
        }
    )


def _query_requirements(fact: ConfirmedFactV3) -> dict[str, Any]:
    fact_code = fact.fact_code
    entity, key_parameter = _GRAIN_ENTITY[fact.grain]
    key_field_id = f"parameter.{key_parameter}"
    data_type = fact.data_type.value
    evidence_ids = [f"fact.{fact_code}", f"query.{fact_code}"]
    fields: list[dict[str, Any]] = [
        {
            "fieldId": "factValue",
            "role": "value",
            "logicalName": fact_code,
            "dataType": data_type,
            "required": True,
            "evidenceIds": evidence_ids,
        },
        {
            "fieldId": key_field_id,
            "role": "entityKey",
            "logicalName": key_parameter,
            "dataType": "string",
            "required": True,
            "evidenceIds": evidence_ids,
        },
    ]
    filters: list[dict[str, Any]] = [
        {
            "filterId": f"{entity}.key",
            "fieldId": key_field_id,
            "operator": RuleOperator.EQ.value,
            "value": {"kind": "parameter", "parameterName": key_parameter},
            "nullPolicy": "error",
            "required": True,
            "evidenceIds": evidence_ids,
        }
    ]
    kind = _FACT_KINDS[fact_code]
    if fact_code == "release.special_application_count":
        fields.extend(
            [
                {
                    "fieldId": "applicationType",
                    "role": "filter",
                    "logicalName": "specialApplicationType",
                    "dataType": "integer",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
                {
                    "fieldId": "currentNodeType",
                    "role": "filter",
                    "logicalName": "currentNodeType",
                    "dataType": "integer",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
                {
                    "fieldId": "applicationRow",
                    "role": "value",
                    "logicalName": "specialApplicationRow",
                    "dataType": "integer",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
            ]
        )
        filters.extend(
            [
                {
                    "filterId": "application.type",
                    "fieldId": "applicationType",
                    "operator": RuleOperator.EQ.value,
                    "value": {"kind": "literal", "literal": 1},
                    "nullPolicy": "fail",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
                {
                    "filterId": "application.node",
                    "fieldId": "currentNodeType",
                    "operator": RuleOperator.IN.value,
                    "value": {"kind": "literal", "literal": [3]},
                    "nullPolicy": "fail",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
            ]
        )
        aggregation = {
            "mode": AggregationModeV3.COMPUTE.value,
            "function": "count",
            "inputFieldIds": ["applicationRow"],
            "groupByFieldIds": [],
            "distinct": False,
            "evidenceIds": evidence_ids,
        }
    elif fact_code in {
        "order.in_scope_contract_count",
        "order.unsealed_in_scope_contract_count",
    }:
        fields.extend(
            [
                {
                    "fieldId": "contractRow",
                    "role": "value",
                    "logicalName": "inScopeContractRow",
                    "dataType": "integer",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
                {
                    "fieldId": "inScopeMembership",
                    "role": "filter",
                    "logicalName": "executionOrRelatedPositiveRemainingContract",
                    "dataType": "boolean",
                    "required": True,
                    "evidenceIds": evidence_ids,
                },
            ]
        )
        filters.append(
            {
                "filterId": "contract.in-scope",
                "fieldId": "inScopeMembership",
                "operator": RuleOperator.EQ.value,
                "value": {"kind": "literal", "literal": True},
                "nullPolicy": "fail",
                "required": True,
                "evidenceIds": evidence_ids,
            }
        )
        if fact_code == "order.unsealed_in_scope_contract_count":
            fields.append(
                {
                    "fieldId": "meetsSealCondition",
                    "role": "filter",
                    "logicalName": "contractMeetsExclusiveSealCases",
                    "dataType": "boolean",
                    "required": True,
                    "evidenceIds": evidence_ids,
                }
            )
            filters.append(
                {
                    "filterId": "contract.unsealed",
                    "fieldId": "meetsSealCondition",
                    "operator": RuleOperator.EQ.value,
                    "value": {"kind": "literal", "literal": False},
                    "nullPolicy": "fail",
                    "required": True,
                    "evidenceIds": evidence_ids,
                }
            )
        aggregation = {
            "mode": AggregationModeV3.COMPUTE.value,
            "function": "count",
            "inputFieldIds": ["contractRow"],
            "groupByFieldIds": [],
            "distinct": False,
            "evidenceIds": evidence_ids,
        }
    elif kind is FactKind.EXISTS:
        extra_field = {
            "fieldId": "existenceScope",
            "role": "filter",
            "logicalName": (
                "unfinishedProjectReportProcess"
                if fact_code == "task.in_oa_process"
                else "reportMergeGroup"
            ),
            "dataType": "boolean",
            "required": True,
            "evidenceIds": evidence_ids,
        }
        fields.append(extra_field)
        filters.append(
            {
                "filterId": f"{entity}.scope",
                "fieldId": "existenceScope",
                "operator": RuleOperator.EQ.value,
                "value": {"kind": "literal", "literal": True},
                "nullPolicy": "fail",
                "required": True,
                "evidenceIds": evidence_ids,
            }
        )
        aggregation = {
            "mode": AggregationModeV3.EXISTS.value,
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence_ids,
        }
    else:
        aggregation = {
            "mode": AggregationModeV3.NONE.value,
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence_ids,
        }
    return {
        "entity": {
            "entityType": entity,
            "grain": fact.grain,
            "keyParameters": [key_parameter],
            "evidenceIds": evidence_ids,
        },
        "fields": fields,
        "filters": {
            "items": filters,
            "completeness": "complete",
            "evidenceIds": evidence_ids,
        },
        "aggregation": aggregation,
        "timeRange": {
            "mode": "none",
            "timeFieldId": None,
            "start": None,
            "end": None,
            "timezone": None,
            "evidenceIds": evidence_ids,
        },
        "result": {
            "columnName": "fact_value",
            "dataType": data_type,
            "cardinality": "scalar",
            "nullable": fact.nullable,
            "nullPolicy": fact.null_policy.value,
            "unit": fact.unit,
        },
    }


_UNCERTAINTIES: dict[str, list[dict[str, Any]]] = {
    "task.offline_report_release_flag": [
        {
            "uncertaintyId": "coding.offline-release-flag",
            "code": "SOURCE_CODING_DIVERGENCE",
            "impact": "warning",
            "reason": _CODING_WARNING,
            "evidenceIds": ["query.task.offline_report_release_flag"],
        }
    ],
    "task.batch_report_release_flag": [
        {
            "uncertaintyId": "coding.batch-release-flag",
            "code": "SOURCE_CODING_DIVERGENCE",
            "impact": "warning",
            "reason": _CODING_WARNING,
            "evidenceIds": ["query.task.batch_report_release_flag"],
        }
    ],
}


def _declarations(catalog: BusinessConfirmedFactCatalogV3) -> list[FactDeclarationV3]:
    required = set(_closure_fact_codes(_STAGES))
    declarations: list[FactDeclarationV3] = []
    for fact in catalog.facts:
        if fact.fact_code not in required:
            continue
        declarations.append(
            FactDeclarationV3.model_validate(
                {
                    "fact": _bindable_fact(fact).model_dump(mode="json", by_alias=True),
                    "query": _query_requirements(fact),
                    "uncertainties": _UNCERTAINTIES.get(fact.fact_code, []),
                }
            )
        )
    return declarations


def _base_given() -> dict[str, Any]:
    return {
        "report.release_status": None,
        "task.status_code": 19,
        "task.experiment_status_code": 1,
        "task.offline_report_release_flag": 1,
        "task.batch_report_release_flag": 1,
        "task.project_report_flag": 0,
        "task.qc_report_flag": 1,
        "task.raw_data_flag": 1,
        "task.completion_date": "2024-01-01",
        "task.no_main_service_flag": 1,
        "task.product_id": 1,
        "task.product_type_code": 1,
        "task.in_oa_process": False,
        "order.amount": 12000.0,
        "order.source_code": 1,
        "order.associated_receipts_including_deposit": 0.0,
        "order.associated_deposit": 0.0,
        "order.extraction_qc_amount": 0.0,
        "task.task_amount": 10000.0,
        "order.report_released_amount": 0.0,
        "order.invoice_amount": 0.0,
        "order.is_framework": False,
        "order.is_enterprise": False,
        "release.special_application_count": 0,
        EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
        "order.in_scope_contract_count": 0,
        "order.unsealed_in_scope_contract_count": 0,
        "report.merge_group_eligible": True,
    }


def _case(
    case_id: str,
    description: str,
    overrides: dict[str, Any],
    outcome: str,
    matched: list[str],
    *,
    given: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if reason is None:
        if matched:
            reason = f"{matched[-1]}_MATCHED"
        elif outcome == "INDETERMINATE":
            reason = "FACT_VALUE_MISSING_OR_INVALID"
        else:
            reason = "NO_ORDERED_RELEASE_RULE_MATCHED"
    return {
        "caseId": case_id,
        "description": description,
        "given": {**(given or _base_given()), **overrides},
        "expectedOutcome": outcome,
        "expectedReasonCode": reason,
        "expectedMatchedRuleCodes": matched,
    }


def build_formula_test_cases() -> list[TestCaseV3]:
    specs = [
        _case(
            "state-terminal-skip",
            "终态跳过",
            {"report.release_status": "准备释放"},
            "SKIPPED",
            ["REPORT_STATUS_TERMINAL"],
        ),
        _case(
            "prereq-not-completed",
            "未完工",
            {"task.status_code": 226},
            "WAITING_COMPLETION",
            ["TASK_NOT_COMPLETED"],
        ),
        _case(
            "prereq-not-completed-null",
            "完工状态为空",
            {"task.status_code": None},
            "WAITING_COMPLETION",
            ["TASK_NOT_COMPLETED"],
        ),
        _case(
            "prereq-experiment-offline",
            "实验状态 2",
            {"task.experiment_status_code": 2},
            "NO_RELEASE_REQUIRED",
            ["EXPERIMENT_STATUS_OFFLINE"],
        ),
        _case(
            "prereq-experiment-problem",
            "实验状态 7",
            {"task.experiment_status_code": 7},
            "NO_RELEASE_REQUIRED",
            ["EXPERIMENT_STATUS_PROBLEM"],
        ),
        _case(
            "prereq-offline-released",
            "线下释放标志为 0",
            {"task.offline_report_release_flag": 0},
            "ALREADY_RELEASED",
            ["OFFLINE_REPORT_RELEASED"],
        ),
        _case(
            "prereq-no-report",
            "无项目报告且无质控报告",
            {"task.project_report_flag": 1, "task.qc_report_flag": 1},
            "NO_RELEASE_REQUIRED",
            ["NO_PROJECT_REPORT"],
        ),
        _case(
            "prereq-availability-unknown",
            "报告有无为空",
            {"task.project_report_flag": None, "task.qc_report_flag": None},
            "WAITING_CONDITIONS",
            ["REPORT_AVAILABILITY_UNKNOWN"],
        ),
        _case(
            "prereq-availability-other",
            "报告有无为其他值",
            {"task.project_report_flag": 2, "task.qc_report_flag": 1},
            "WAITING_CONDITIONS",
            ["REPORT_AVAILABILITY_UNKNOWN"],
        ),
        _case("r0-zero-order", "R0 首次命中", {"order.amount": 0.0}, "READY", ["R0_ZERO_ORDER"]),
        _case(
            "r1-special-approval",
            "R1 首次命中",
            {"release.special_application_count": 2},
            "READY",
            ["R1_SPECIAL_APPROVAL"],
        ),
        _case(
            "r9-batch-release",
            "R9 比较 0",
            {"task.batch_report_release_flag": 0},
            "READY",
            ["R9_BATCH_RELEASE"],
        ),
        _case(
            "r4-raw-data-released",
            "R4 yssj=0 且完工日达标",
            {"task.raw_data_flag": 0, "task.completion_date": "2024-11-21"},
            "READY",
            ["R4_RAW_DATA_RELEASED"],
        ),
        _case(
            "r2-overseas-order",
            "R2 ddly=2",
            {"order.source_code": 2},
            "READY",
            ["R2_OVERSEAS_ORDER"],
        ),
        _case(
            "r3-ratio-70-pass",
            "R3 70% 过",
            {
                "task.product_id": 759,
                "order.extraction_qc_amount": 0.0,
                "task.task_amount": 10000.0,
                "order.report_released_amount": 0.0,
                "order.associated_receipts_including_deposit": 7000.0,
            },
            "READY",
            ["R3_SPECIAL_PRODUCT"],
        ),
        _case(
            "r3-ratio-50-pass",
            "R3 50% 过",
            {
                "task.product_id": 759,
                "order.extraction_qc_amount": 0.0,
                "task.task_amount": 150000.0,
                "order.report_released_amount": 0.0,
                "order.associated_receipts_including_deposit": 75000.0,
            },
            "READY",
            ["R3_SPECIAL_PRODUCT"],
        ),
        _case(
            "r3-ratio-insufficient",
            "R3 金额不足",
            {
                "task.product_id": 759,
                "order.extraction_qc_amount": 0.0,
                "task.task_amount": 10000.0,
                "order.report_released_amount": 0.0,
                "order.associated_receipts_including_deposit": 6000.0,
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r8-exact-day",
            "R8 恰好当天命中",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 100.0,
                "task.completion_date": "2026-04-02",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r8-miss-day",
            "R8 错过当天不命中",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 100.0,
                "task.completion_date": "2026-04-01",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r8d-yeast",
            "R8D 酵母筛库无主服务",
            {"task.product_type_code": 2, "task.no_main_service_flag": 0},
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r8abc-empty-product-type",
            "产品类型为空仍可进入 R8ABC",
            {
                "task.product_type_code": None,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 100.0,
                "task.completion_date": "2026-04-02",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r8b-day-75",
            "R8B 金额小于 5000 未开票且恰好完工后 75 天",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 0.0,
                "task.completion_date": "2026-03-18",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r8b-day-74",
            "R8B 完工后 74 天不命中",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 0.0,
                "task.completion_date": "2026-03-19",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r8b-day-76",
            "R8B 完工后 76 天不命中",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 4000.0,
                "order.invoice_amount": 0.0,
                "task.completion_date": "2026-03-17",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r8c-day-180",
            "R8C 金额不少于 5000 且恰好完工后 180 天",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 5000.0,
                "task.completion_date": "2025-12-03",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r8c-day-181",
            "R8C 错过当天不命中",
            {
                "task.product_type_code": 1,
                "task.product_id": 1,
                "task.task_amount": 5000.0,
                "task.completion_date": "2025-12-02",
                EVALUATION_DATE_GIVEN_KEY: "2026-06-01",
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r5-enterprise",
            "R5 非框架企业全额到款",
            {
                "order.is_framework": False,
                "order.is_enterprise": True,
                "order.associated_receipts_including_deposit": 10000.0,
                "task.task_amount": 10000.0,
            },
            "READY",
            ["R5_ENTERPRISE"],
        ),
        _case(
            "r5-framework-excluded",
            "R5 框架单不应误入",
            {
                "order.is_framework": True,
                "order.is_enterprise": True,
                "order.associated_receipts_including_deposit": 10000.0,
                "task.task_amount": 10000.0,
            },
            "READY",
            ["R7_FRAMEWORK"],
        ),
        _case(
            "r6-condition-a",
            "R6 条件 A",
            {
                "order.is_framework": False,
                "order.is_enterprise": False,
                "order.associated_receipts_including_deposit": 10000.0,
                "task.task_amount": 10000.0,
            },
            "READY",
            ["R6_NON_ENTERPRISE"],
        ),
        _case(
            "r7-framework-pass",
            "R7 框架协议 80% 到款",
            {
                "order.is_framework": True,
                "order.is_enterprise": False,
                "order.associated_receipts_including_deposit": 8000.0,
                "task.task_amount": 10000.0,
            },
            "READY",
            ["R7_FRAMEWORK"],
        ),
        _case(
            "r6-condition-b-seal-fail",
            "R6 条件 B 盖章失败",
            {
                "order.is_framework": False,
                "order.is_enterprise": False,
                "order.associated_receipts_including_deposit": 8000.0,
                "order.associated_deposit": 400.0,
                "task.task_amount": 10000.0,
                "order.in_scope_contract_count": 1,
                "order.unsealed_in_scope_contract_count": 1,
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "r6-condition-b-seal-pass",
            "R6 条件 B 金额满足且范围内合同均盖章",
            {
                "order.is_framework": False,
                "order.is_enterprise": False,
                "order.associated_receipts_including_deposit": 8000.0,
                "order.associated_deposit": 400.0,
                "task.task_amount": 10000.0,
                "order.in_scope_contract_count": 2,
                "order.unsealed_in_scope_contract_count": 0,
            },
            "READY",
            ["R6_NON_ENTERPRISE"],
        ),
        _case(
            "r6-condition-b-empty-contracts",
            "R6 条件 B 范围为空则失败",
            {
                "order.is_framework": False,
                "order.is_enterprise": False,
                "order.associated_receipts_including_deposit": 8000.0,
                "order.associated_deposit": 400.0,
                "task.task_amount": 10000.0,
                "order.in_scope_contract_count": 0,
                "order.unsealed_in_scope_contract_count": 0,
            },
            "WAITING_CONDITIONS",
            [],
        ),
        _case(
            "postgate-merge-blocked",
            "合并门闩降级",
            {"order.amount": 0.0, "report.merge_group_eligible": False},
            "WAITING_CONDITIONS",
            ["R0_ZERO_ORDER", "MERGED_REPORT_GATE"],
        ),
        _case(
            "exclusion-oa-process",
            "OA 排除",
            {"order.amount": 0.0, "task.in_oa_process": True},
            "WAITING_CONDITIONS",
            ["R0_ZERO_ORDER", "OA_PROCESS_SCOPE"],
        ),
        _case(
            "indeterminate-missing-amount",
            "金额缺失为 INDETERMINATE",
            {"order.associated_receipts_including_deposit": None},
            "INDETERMINATE",
            [],
        ),
    ]
    return [TestCaseV3.model_validate(spec) for spec in specs]


def build_formula_result(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV3,
    generated_at: datetime,
    *,
    rule_block_sha256: str = RULE_BLOCK_SHA256,
    rule_block_characters: int = RULE_BLOCK_CHARACTER_COUNT,
) -> RuleParseResultV3:
    return RuleParseResultV3.model_validate(
        {
            "schemaVersion": "3.0.0",
            "ruleVersion": build_rule_version_v3(
                candidate.rule_set_id,
                generated_at,
                rule_block_sha256,
                catalog.catalog_digest,
            ),
            "ruleSetId": candidate.rule_set_id,
            "generatedAt": generated_at.isoformat(),
            "status": "draft",
            "executable": False,
            "source": {
                "sourceName": RULE_BLOCK_FILE_NAME,
                "relativePath": RULE_BLOCK_FILE_NAME,
                "sourceSha256": rule_block_sha256,
                "sourceCharacterCount": rule_block_characters,
                "parserVersion": PARSER_VERSION,
                "promptVersion": PROMPT_VERSION,
                "provider": PROVIDER,
                "model": MODEL,
            },
            "parser": {
                "parserVersion": PARSER_VERSION,
                "promptVersion": PROMPT_VERSION,
                "provider": PROVIDER,
                "model": MODEL,
            },
            "catalogRef": {
                "catalogId": catalog.catalog_id,
                "catalogVersion": catalog.catalog_version,
                "catalogDigest": catalog.catalog_digest,
            },
            "candidateRef": {
                "payloadSha256": candidate_payload_sha256_v3(candidate),
                "ruleBlockSha256": rule_block_sha256,
            },
            "factDeclarations": [
                declaration.model_dump(mode="json", by_alias=True)
                for declaration in _declarations(catalog)
            ],
            "testCases": [
                case.model_dump(mode="json", by_alias=True) for case in build_formula_test_cases()
            ],
            "agent2ReadinessReady": False,
        }
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_public_payload_is_safe(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    lowered = text.lower()
    for banned in ("select ", "insert ", "uf_dd", "formtable_", "v_sendreport", ".env"):
        if banned in lowered:
            raise ValueError(f"public payload contains banned token: {banned}")
    if "c:\\\\users" in lowered or "c:/users" in lowered:
        raise ValueError("public payload contains a local absolute path")


def build_formula_delivery(
    generated_at: datetime = FIXED_GENERATED_AT,
    *,
    plan_sha256: str = PLAN_SHA256,
    rule_block_sha256: str = RULE_BLOCK_SHA256,
    rule_block_characters: int = RULE_BLOCK_CHARACTER_COUNT,
) -> tuple[
    BusinessConfirmedFactCatalogV3,
    RuleStructureCandidateV3,
    RuleParseResultV3,
    list[Any],
    Any,
]:
    if rule_block_sha256 == OLD_RULE_BLOCK_SHA256 or rule_block_characters == 1402:
        raise ValueError("refusing to reuse the frozen 1402-character rule block")
    catalog = build_formula_catalog(plan_sha256=plan_sha256, rule_block_sha256=rule_block_sha256)
    candidate = build_formula_candidate(catalog)
    result = build_formula_result(
        catalog,
        candidate,
        generated_at,
        rule_block_sha256=rule_block_sha256,
        rule_block_characters=rule_block_characters,
    )
    pre_readiness = build_agent2_readiness_report_v3(candidate, catalog, result=result)
    non_export = [gate for gate in pre_readiness.gates if gate.gate != 4]
    export_gate = next(gate for gate in pre_readiness.gates if gate.gate == 4)
    if not all(gate.result.value == "pass" for gate in non_export) or (
        export_gate.result.value != "blocked"
    ):
        raise ValueError("pre-export readiness is not clean")
    ready_result = result.model_copy(update={"agent2_readiness_ready": True})
    requests = export_fact_binding_requests_v3(ready_result, candidate, catalog)
    readiness = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=ready_result,
        requests=requests,
    )
    if not readiness.ready:
        raise ValueError("post-export readiness is not ready")
    return catalog, candidate, ready_result, requests, readiness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-block-file", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-at", type=datetime.fromisoformat, default=FIXED_GENERATED_AT)
    args = parser.parse_args()
    block_text = args.rule_block_file.read_text(encoding="utf-8")
    block_sha = _file_sha256(args.rule_block_file)
    if block_text.splitlines()[0] != RULE_SET_ID:
        raise ValueError("rule block first line must be REPORT_RELEASE_ALL_001")
    if block_sha != RULE_BLOCK_SHA256 or len(block_text) != RULE_BLOCK_CHARACTER_COUNT:
        raise ValueError("rule block identity does not match the frozen 2026-09-20 extract")
    if "=== 原始数据释放前提条件" in block_text or "DataZeroAmountRule" in block_text:
        raise ValueError("rule block contains excluded data-release content")
    plan_sha = PLAN_SHA256
    if args.plan_file is not None:
        plan_sha = _file_sha256(args.plan_file)
        if plan_sha != PLAN_SHA256:
            raise ValueError(f"plan SHA-256 mismatch: {plan_sha}")
    generated_at = args.generated_at.astimezone(UTC)
    catalog, candidate, result, requests, readiness = build_formula_delivery(
        generated_at,
        plan_sha256=plan_sha,
        rule_block_sha256=block_sha,
        rule_block_characters=len(block_text),
    )
    payloads = {
        "business-confirmed-fact-catalog-3.0.0.json": catalog.model_dump(
            mode="json", by_alias=True
        ),
        "rule-structure-candidate-3.0.0.json": candidate.model_dump(mode="json", by_alias=True),
        "rule-parse-result-3.0.0.json": result.model_dump(mode="json", by_alias=True),
        "fact-binding-requests-3.0.0.json": [
            request.model_dump(mode="json", by_alias=True) for request in requests
        ],
        "v3-agent2-readiness.json": readiness.model_dump(mode="json", by_alias=True),
    }
    for payload in payloads.values():
        _assert_public_payload_is_safe(payload)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        path = args.output_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hashes[name] = _file_sha256(path)
    stages = {
        stage.stage.value: [
            {"ruleCode": rule.rule_code, "status": rule.status.value} for rule in stage.rules
        ]
        for stage in candidate.stages
    }
    facts = [
        {"factCode": fact.fact_code, "kind": _FACT_KINDS[fact.fact_code].value, "grain": fact.grain}
        for fact in catalog.facts
        if fact.fact_code in set(candidate.required_fact_codes)
    ]
    manifest = {
        "planSha256": plan_sha,
        "ruleBlockSha256": block_sha,
        "ruleBlockCharacterCount": len(block_text),
        "catalogDigest": catalog.catalog_digest,
        "candidatePayloadSha256": candidate_payload_sha256_v3(candidate),
        "ruleVersion": result.rule_version,
        "blockingCount": 0,
        "ready": readiness.ready,
        "mongodbWritten": False,
        "executable": False,
        "status": "draft",
        "factCount": len(facts),
        "facts": facts,
        "stages": stages,
        "sealModeling": SEAL_MODELING,
        "supersededRuleVersion": SUPERSEDED_RULE_VERSION,
        "fileSha256": hashes,
    }
    (args.output_dir / "delivery-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ruleBlockCharacterCount": len(block_text),
                "ruleBlockSha256": block_sha,
                "planSha256": plan_sha,
                "catalogDigest": catalog.catalog_digest,
                "candidatePayloadSha256": manifest["candidatePayloadSha256"],
                "ruleVersion": result.rule_version,
                "factCount": len(facts),
                "blockingCount": 0,
                "ready": readiness.ready,
                "mongodbWritten": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
