"""Build the business-confirmed V3 profile after the 2026-09-06 blocker adjudications.

Offline only: reads the fixed private reference bundle, applies the recorded business
decisions from BIZ-20260906-01, and writes a fully active candidate, its RuleParseResultV3,
the exported FactBindingRequest 3.0.0 list, and the readiness report outside the bundle.
No MongoDB, DeepSeek, SQL Server, or SqlBot access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.report_release_v3_profile import (
    _FACT_ROWS,
    _allowed_values,
    _xlsx_cells,
    validate_output_location,
)
from scripts.validate_report_release_v3_reference import (
    BUNDLE_ID,
    RULE_BLOCK_SHA256,
    WORKBOOK_SHA256,
    load_ordered_report_release_reference,
)

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
    validate_rule_reachability_witnesses_v3,
    validate_rule_structure_candidate_v3,
)

OPTIMIZATION_PLAN_SHA256 = "c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f"
# confirmed 产物的 parser provenance 冻结为生成该 profile 时的版本, 不得随应用包版本变化,
# 否则同一 ruleVersion 会因版本升级产生不同 payload/hash。见 BUG-20260906-02。
CONFIRMED_PROFILE_PARSER_VERSION = "0.11.0"
CONFIRMED_CATALOG_VERSION = "2026-09-06.1"
_ADJUDICATION_NOTE = "2026-09-06 业务裁决（BIZ-20260906-01）。"
_STATUS_CODE_SUPPLEMENT = "19"
_LEGEND_PATTERN = re.compile(r"^(\d+)(\D+)(\d+)(\D+)$")

_ADDED_FACT_SECTIONS = {
    "report.release_status": "一、1.3 前提-1；三、3.2 状态表",
    "order.amount": "一、1.3 规则R0；五、5.2 ReportZeroAmountRule",
    "release.special_application_count": "一、1.3 规则R1；五、5.2 ReportSpecialApprovalRule",
    "release.raw_data_released_after_cutoff": "一、1.3 规则R4；五、5.2 ReportRawDataReleasedRule",
    "order.source_code": "一、1.3 规则R2；五、5.2 ReportOrderSourceRule",
    "product.special_product_flag": "一、1.3 规则R3；五、5.2 SpecialProductRule",
    "release.timed_release_eligible": "一、1.3 规则R8；五、5.2 ReportTimeTriggerRule",
    "order.enterprise_non_framework_full_payment_eligible": (
        "一、1.3 规则R5；五、5.2 NonFrameworkEnterpriseRule"
    ),
    "order.non_enterprise_release_eligible": (
        "一、1.3 规则R6；五、5.2 NonFrameworkNonEnterpriseRule"
    ),
    "order.framework_release_eligible": "一、1.3 规则R7；五、5.2 FrameworkRule",
    "report.merge_group_eligible": "一、1.3 合并报告约束；五、5.2 ReleaseRuleEngine",
    "task.in_oa_process": "一、1.3 排除条件；四、4.2 触发集成",
}

_ADDED_FACT_SPECS: list[dict[str, Any]] = [
    {
        "factCode": "report.release_status",
        "name": "报告释放状态",
        "description": (
            "释放状态表当前状态；处于准备释放/释放中/已释放任一终态时跳过本次评估，"
            "空值或其余状态继续评估。"
        ),
        "dataType": "enum",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "allowedValues": ["准备释放", "释放中", "已释放"],
        "unit": None,
    },
    {
        "factCode": "order.amount",
        "name": "订单金额",
        "description": "订单金额；为 0 时命中 R0 直接释放，空值继续评估后续规则。",
        "dataType": "money",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "allowedValues": [],
        "unit": "CNY",
    },
    {
        "factCode": "release.special_application_count",
        "name": "特殊申请已审批数量",
        "description": (
            "项目报告释放类型且审批流程已完成的特殊申请数量；大于 0 时命中 R1 直接释放，"
            "统计范围在查询阶段固定。"
        ),
        "dataType": "integer",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "allowedValues": [],
        "unit": None,
    },
    {
        "factCode": "release.raw_data_released_after_cutoff",
        "name": "原始数据已释放且过截止日",
        "description": (
            "原始数据已释放且完工日期不早于 2024-11-21 时为真，命中 R4 直接释放；"
            "截止日为固定业务参数。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "order.source_code",
        "name": "订单来源",
        "description": (
            "订单来源编码；当前确认值域仅含规则引用值 2=海外业务，命中 R2 直接释放，"
            "其余值域待业务补充。"
        ),
        "dataType": "enum",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "allowedValues": ["2"],
        "unit": None,
    },
    {
        "factCode": "product.special_product_flag",
        "name": "特殊产品标记",
        "description": (
            "产品属于多组学创新科学研究（产品编号 759）时为真，命中 R3 后按基准金额分档"
            "适用释放比例；该标记同时是 R5/R6 的排除前置。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "release.timed_release_eligible",
        "name": "完工时间触发满足",
        "description": (
            "完工时间触发规则已到期时为真：酵母筛库/家族库且无主服务完工即满足；"
            "其余产品按任务单金额与开票状态适用完工后 60/75/180 天；2026-04-15 起适用，"
            "命中 R8 直接释放。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "task",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "order.enterprise_non_framework_full_payment_eligible",
        "name": "非框架企业单位全额到款满足",
        "description": (
            "非框架协议且企业单位、订单关联到款（含押金）不低于累计完工金额"
            "（抽提质检、任务单与项目报告释放金额之和）的 100% 时为真，命中 R5 直接释放。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "order.non_enterprise_release_eligible",
        "name": "非框架非企业单位释放满足",
        "description": (
            "非框架协议且非企业单位，订单关联到款（含押金）不低于累计完工金额的 100%，"
            "或不低于 80% 且订单关联押金不低于未关联到款金额的 20% 并满足合同盖章条件时为真，"
            "命中 R6 直接释放。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "order.framework_release_eligible",
        "name": "框架协议释放满足",
        "description": (
            "框架协议（科研/公司）订单，关联到款（含押金）不低于累计完工金额的 80%，"
            "或订单关联押金不低于未关联到款金额的 20% 时为真，命中 R7 直接释放。"
        ),
        "dataType": "boolean",
        "nullable": True,
        "nullPolicy": "indeterminate",
        "grain": "order",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "report.merge_group_eligible",
        "name": "合并报告组释放约束满足",
        "description": (
            "本任务单实时命中释放规则，且（非合并报告，或同一合并报告下所有相关任务单"
            "均处于可释放终态或实时命中释放规则）时为真；为假时合并组约束未满足，"
            "释放降级为等待满足条件。该事实不可为空。"
        ),
        "dataType": "boolean",
        "nullable": False,
        "nullPolicy": "fail",
        "grain": "task",
        "allowedValues": [True, False],
        "unit": None,
    },
    {
        "factCode": "task.in_oa_process",
        "name": "任务在 OA 流程中",
        "description": (
            "任务单当前处于项目报告释放 OA 流程中时为真，命中排除条件后跳过触发；该事实不可为空。"
        ),
        "dataType": "boolean",
        "nullable": False,
        "nullPolicy": "fail",
        "grain": "task",
        "allowedValues": [True, False],
        "unit": None,
    },
]

_ADJUSTED_FACT_ROWS = {
    "task.status_code": 8,
    "task.offline_report_release_flag": 22,
    "task.batch_report_release_flag": 23,
}

_ADJUSTED_FACT_NOTES = {
    "task.status_code": (
        "值域补录 19（内部完工确认），以有序规则为准；字段描述本身写明主释放任务要求 19。"
    ),
    "task.offline_report_release_flag": (
        "值域含义取自确认工作簿：4=是（已线下释放）、5=否；现行视图比较编码差异留待物理绑定复核。"
    ),
    "task.batch_report_release_flag": (
        "值域含义取自确认工作簿：4=是（已标记批量释放）、5=否；现行视图比较编码差异"
        "留待物理绑定复核。"
    ),
}


def _legend_values(raw: str) -> dict[str, str]:
    match = _LEGEND_PATTERN.fullmatch(raw.strip())
    if match is None:
        raise ValueError(f"confirmed value legend is not parsable: {raw!r}")
    return {match.group(1): match.group(2), match.group(3): match.group(4)}


def _task_parameter() -> dict[str, Any]:
    return {
        "name": "taskId",
        "role": "entityKey",
        "dataType": "string",
        "required": True,
        "description": "正式实验任务标识。",
    }


def _order_parameter() -> dict[str, Any]:
    return {
        "name": "orderId",
        "role": "entityKey",
        "dataType": "string",
        "required": True,
        "description": "订单标识。",
    }


def _added_fact_payloads() -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for spec in _ADDED_FACT_SPECS:
        fact_code = spec["factCode"]
        grain = spec["grain"]
        payloads.append(
            {
                "factCode": fact_code,
                "name": spec["name"],
                "description": spec["description"],
                "dataType": spec["dataType"],
                "nullable": spec["nullable"],
                "nullPolicy": spec["nullPolicy"],
                "grain": grain,
                "parameters": [_order_parameter() if grain == "order" else _task_parameter()],
                "allowedValues": spec["allowedValues"],
                "unit": spec["unit"],
                "evidenceRefs": [f"plan.section.{fact_code.replace('.', '-')}"],
                "bindingProfileRef": None,
                "bindingIssues": ["固定 bundle 不包含已批准的 V3 binding profile。"],
            }
        )
    return payloads


def _confirmed_catalog(workbook_path: Path, plan_sha256: str) -> BusinessConfirmedFactCatalogV3:
    addresses = {f"{column}{row}" for row in _FACT_ROWS.values() for column in ("G", "H", "I", "L")}
    cells = _xlsx_cells(workbook_path, "字段清单", addresses)
    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for fact_code, row in _FACT_ROWS.items():
        if cells[f"I{row}"].strip().lower() != "varchar":
            raise ValueError(f"confirmed data type changed at 字段清单!I{row}")
        allowed_values = _allowed_values(cells[f"L{row}"])
        description = cells[f"G{row}"]
        if fact_code in _ADJUSTED_FACT_ROWS:
            if fact_code == "task.status_code":
                if _STATUS_CODE_SUPPLEMENT not in allowed_values:
                    allowed_values = [*allowed_values, _STATUS_CODE_SUPPLEMENT]
            else:
                legend = _legend_values(cells[f"L{row}"])
                description = (
                    f"{description}；确认值域含义："
                    + "、".join(f"{code}={meaning}" for code, meaning in legend.items())
                    + "；空值按否处理。"
                )
            description = f"{description}（{_ADJUSTED_FACT_NOTES[fact_code]}）"
        evidence_id = f"workbook.row.{row}"
        evidence.append(
            {
                "evidenceId": evidence_id,
                "sourceKind": "businessConfirmation",
                "sourceId": f"{BUNDLE_ID}/field-catalog",
                "sourceSha256": WORKBOOK_SHA256,
                "locator": f"字段清单!G{row}:L{row}",
                "note": "用户确认已填写单元格有效；调整项另有 2026-09-06 裁决记录。",
            }
        )
        facts.append(
            {
                "factCode": fact_code,
                "name": cells[f"H{row}"],
                "description": description,
                "dataType": "string",
                "nullable": True,
                "nullPolicy": "indeterminate",
                "grain": "task",
                "parameters": [_task_parameter()],
                "allowedValues": allowed_values,
                "unit": None,
                "evidenceRefs": [evidence_id],
                "bindingProfileRef": None,
                "bindingIssues": ["固定 bundle 不包含已批准的 V3 binding profile。"],
            }
        )

    for fact_payload in _added_fact_payloads():
        fact_code = fact_payload["factCode"]
        evidence.append(
            {
                "evidenceId": fact_payload["evidenceRefs"][0],
                "sourceKind": "ruleText",
                "sourceId": f"{BUNDLE_ID}/optimization-plan",
                "sourceSha256": plan_sha256,
                "locator": _ADDED_FACT_SECTIONS[fact_code],
                "note": f"用户指定有序方案为权威结构来源；{_ADJUDICATION_NOTE}",
            }
        )
        facts.append(fact_payload)

    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": "REPORT_RELEASE_CONFIRMED_FACTS",
        "catalogVersion": CONFIRMED_CATALOG_VERSION,
        "catalogDigest": "0" * 64,
        "facts": facts,
        "evidence": evidence,
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    catalog = BusinessConfirmedFactCatalogV3.model_validate(payload)
    validate_fact_catalog_v3(catalog)
    return catalog


def _fact(code: str) -> dict[str, Any]:
    return {"kind": "fact", "factCode": code, "children": []}


def _literal(value: Any) -> dict[str, Any]:
    return {"kind": "literal", "value": value, "children": []}


def _compare(condition_id: str, fact_code: str, operator: str, value: Any) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "compare",
        "description": condition_id.replace("-", " "),
        "enabled": True,
        "children": [],
        "left": _fact(fact_code),
        "operator": operator,
        "right": _literal(value),
        "nullPolicy": "indeterminate",
    }


def _null_check(condition_id: str, fact_code: str) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "compare",
        "description": condition_id.replace("-", " "),
        "enabled": True,
        "children": [],
        "left": _fact(fact_code),
        "operator": "is_null",
        "right": None,
        "nullPolicy": "indeterminate",
    }


def _combine(kind: str, condition_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": kind,
        "description": condition_id.replace("-", " "),
        "enabled": True,
        "children": children,
        "left": None,
        "operator": None,
        "right": None,
        "nullPolicy": "indeterminate",
    }


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
        "recommendations": ["按有序来源与 2026-09-06 裁决核对对应事实。"],
        "blockingIssueIds": [],
    }


_STAGE_TERMINAL_VALUES = ["准备释放", "释放中", "已释放"]

_STAGE_GUARD_TERMINAL = {
    **_active(
        "REPORT_STATUS_TERMINAL",
        10,
        "释放状态表终态检查",
        _compare(
            "release-status-terminal",
            "report.release_status",
            "in",
            list(_STAGE_TERMINAL_VALUES),
        ),
        "SKIPPED",
    ),
    "when": {
        **_compare(
            "release-status-terminal",
            "report.release_status",
            "in",
            list(_STAGE_TERMINAL_VALUES),
        ),
        "nullPolicy": "fail",
    },
}
_STAGES: list[dict[str, Any]] = [
    {"stage": "stateGuards", "rules": [_STAGE_GUARD_TERMINAL]},
    {
        "stage": "prerequisites",
        "rules": [
            _active(
                "TASK_NOT_COMPLETED",
                10,
                "任务尚未完工",
                _compare("task-not-completed", "task.status_code", "ne", "19"),
                "WAITING_COMPLETION",
            ),
            _active(
                "EXPERIMENT_STATUS_OFFLINE",
                20,
                "失败导致线下确认收入",
                _compare("experiment-status-offline", "task.experiment_status_code", "eq", "2"),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "EXPERIMENT_STATUS_PROBLEM",
                30,
                "问题项目无需释放",
                _compare("experiment-status-problem", "task.experiment_status_code", "eq", "7"),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "OFFLINE_REPORT_RELEASED",
                40,
                "项目报告已线下释放",
                _compare("offline-report-released", "task.offline_report_release_flag", "eq", "4"),
                "ALREADY_RELEASED",
            ),
            _active(
                "NO_PROJECT_REPORT",
                50,
                "任务无需项目报告",
                _combine(
                    "all",
                    "no-project-report",
                    [
                        _compare("project-report-absent", "task.project_report_flag", "eq", "1"),
                        _compare("qc-report-absent", "task.qc_report_flag", "eq", "1"),
                    ],
                ),
                "NO_RELEASE_REQUIRED",
            ),
            _active(
                "REPORT_AVAILABILITY_UNKNOWN",
                60,
                "有无项目报告待定",
                _combine(
                    "any",
                    "report-availability-unknown",
                    [
                        _null_check("project-report-unknown", "task.project_report_flag"),
                        _null_check("qc-report-unknown", "task.qc_report_flag"),
                    ],
                ),
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
                _compare("r0-zero-order", "order.amount", "eq", 0),
                "READY",
            ),
            _active(
                "R1_SPECIAL_APPROVAL",
                20,
                "R1 特殊申请已审批",
                _compare("r1-special-approval", "release.special_application_count", "gt", 0),
                "READY",
            ),
            _active(
                "R9_BATCH_RELEASE",
                30,
                "R9 标记批量释放",
                _compare("r9-batch-release", "task.batch_report_release_flag", "eq", "4"),
                "READY",
            ),
            _active(
                "R4_RAW_DATA_RELEASED",
                40,
                "R4 原始数据已释放",
                _compare(
                    "r4-raw-data-released",
                    "release.raw_data_released_after_cutoff",
                    "eq",
                    True,
                ),
                "READY",
            ),
            _active(
                "R2_OVERSEAS_ORDER",
                50,
                "R2 海外业务订单",
                _compare("r2-overseas-order", "order.source_code", "eq", "2"),
                "READY",
            ),
            _active(
                "R3_SPECIAL_PRODUCT",
                60,
                "R3 特殊产品",
                _compare("r3-special-product", "product.special_product_flag", "eq", True),
                "READY",
            ),
            _active(
                "R8_TIME_TRIGGER",
                70,
                "R8 完工时间触发",
                _compare("r8-time-trigger", "release.timed_release_eligible", "eq", True),
                "READY",
            ),
            _active(
                "R5_ENTERPRISE",
                80,
                "R5 非框架企业单位",
                _compare(
                    "r5-enterprise",
                    "order.enterprise_non_framework_full_payment_eligible",
                    "eq",
                    True,
                ),
                "READY",
            ),
            _active(
                "R6_NON_ENTERPRISE",
                90,
                "R6 非框架非企业单位",
                _compare(
                    "r6-non-enterprise",
                    "order.non_enterprise_release_eligible",
                    "eq",
                    True,
                ),
                "READY",
            ),
            _active(
                "R7_FRAMEWORK",
                100,
                "R7 框架协议",
                _compare("r7-framework", "order.framework_release_eligible", "eq", True),
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
                "合并报告组全部满足",
                _compare(
                    "merged-report-gate",
                    "report.merge_group_eligible",
                    "ne",
                    True,
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
                "任务必须位于OA流程",
                _compare("oa-process-scope", "task.in_oa_process", "eq", True),
                "WAITING_CONDITIONS",
            )
        ],
    },
]


def _closure_fact_codes(stages: list[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        for side in ("left", "right"):
            expression = node.get(side)
            if expression and expression.get("kind") == "fact" and expression.get("factCode"):
                codes.add(expression["factCode"])
        for child in node.get("children", []):
            walk(child)

    for stage in stages:
        for rule in stage["rules"]:
            when = rule.get("when")
            if when:
                walk(when)
    return sorted(codes)


def _confirmed_candidate(catalog: BusinessConfirmedFactCatalogV3) -> RuleStructureCandidateV3:
    required = _closure_fact_codes(_STAGES)
    payload = {
        "contractVersion": "3.0.0",
        "ruleSetId": "REPORT_RELEASE_ALL_001",
        "title": "有序项目报告释放规则",
        "scope": "OA 正式实验任务单项目报告释放；按前提和 R0/R1/R9/R4/R2/R3/R8/R5/R6/R7 顺序。",
        "catalogId": catalog.catalog_id,
        "catalogVersion": catalog.catalog_version,
        "catalogDigest": catalog.catalog_digest,
        "sourceViews": [
            "v_sendreport_trigger",
            "v_ReportReleaseSealCondition",
            "v_OrderFormaltestsettlement",
            "v_ReportDataReleaseRules",
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


_WITNESSES: dict[str, dict[str, Any]] = {
    "REPORT_STATUS_TERMINAL": {"report.release_status": "准备释放"},
    "TASK_NOT_COMPLETED": {"task.status_code": "226"},
    "EXPERIMENT_STATUS_OFFLINE": {"task.status_code": "19", "task.experiment_status_code": "2"},
    "EXPERIMENT_STATUS_PROBLEM": {"task.status_code": "19", "task.experiment_status_code": "7"},
    "OFFLINE_REPORT_RELEASED": {
        "task.status_code": "19",
        "task.offline_report_release_flag": "4",
    },
    "NO_PROJECT_REPORT": {
        "task.status_code": "19",
        "task.project_report_flag": "1",
        "task.qc_report_flag": "1",
    },
    "REPORT_AVAILABILITY_UNKNOWN": {
        "task.status_code": "19",
        "task.project_report_flag": None,
        "task.qc_report_flag": None,
    },
    "R0_ZERO_ORDER": {"order.amount": 0},
    "R1_SPECIAL_APPROVAL": {"release.special_application_count": 1},
    "R9_BATCH_RELEASE": {"task.batch_report_release_flag": "4"},
    "R4_RAW_DATA_RELEASED": {"release.raw_data_released_after_cutoff": True},
    "R2_OVERSEAS_ORDER": {"order.source_code": "2"},
    "R3_SPECIAL_PRODUCT": {"product.special_product_flag": True},
    "R8_TIME_TRIGGER": {"release.timed_release_eligible": True},
    "R5_ENTERPRISE": {"order.enterprise_non_framework_full_payment_eligible": True},
    "R6_NON_ENTERPRISE": {"order.non_enterprise_release_eligible": True},
    "R7_FRAMEWORK": {"order.framework_release_eligible": True},
    "MERGED_REPORT_GATE": {"report.merge_group_eligible": False},
    "OA_PROCESS_SCOPE": {"task.in_oa_process": True},
}


_FACT_KINDS: dict[str, FactKind] = {
    **{code: FactKind.SOURCE for code in _FACT_ROWS},
    **{spec["factCode"]: FactKind.SOURCE for spec in _ADDED_FACT_SPECS},
    "release.special_application_count": FactKind.AGGREGATE,
    "task.in_oa_process": FactKind.EXISTS,
}

_ENTITY_BY_GRAIN = {"task": "task", "order": "order"}
_KEY_PARAMETER_BY_GRAIN = {"task": "taskId", "order": "orderId"}

_CODING_UNCERTAINTY_REASON = (
    "XLSX 确认值域为 4=是、5=否；现行视图 SQL 使用 0/1 比较，物理绑定阶段需复核编码映射。"
)


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
    grain = fact.grain
    entity = _ENTITY_BY_GRAIN[grain]
    key_parameter = _KEY_PARAMETER_BY_GRAIN[grain]
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
    if fact_code == "release.raw_data_released_after_cutoff":
        fields.append(
            {
                "fieldId": "completion.date",
                "role": "time",
                "logicalName": "完工日期",
                "dataType": "date",
                "required": True,
                "evidenceIds": evidence_ids,
            }
        )
        filters.append(
            {
                "filterId": "completion.cutoff",
                "fieldId": "completion.date",
                "operator": RuleOperator.GTE.value,
                "value": {"kind": "literal", "literal": "2024-11-21"},
                "nullPolicy": "indeterminate",
                "required": True,
                "evidenceIds": evidence_ids,
            }
        )
    if _FACT_KINDS[fact_code] is FactKind.AGGREGATE:
        aggregation = {
            "mode": AggregationModeV3.COMPUTE.value,
            "function": "count",
            "inputFieldIds": ["factValue"],
            "groupByFieldIds": [],
            "distinct": False,
            "evidenceIds": evidence_ids,
        }
    elif _FACT_KINDS[fact_code] is FactKind.EXISTS:
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
            "mode": "none",
            "function": None,
            "inputFieldIds": [],
            "groupByFieldIds": [],
            "distinct": None,
            "evidenceIds": evidence_ids,
        }
    return {
        "entity": {
            "entityType": entity,
            "grain": grain,
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
            "reason": _CODING_UNCERTAINTY_REASON,
            "evidenceIds": ["query.task.offline_report_release_flag"],
        }
    ],
    "task.batch_report_release_flag": [
        {
            "uncertaintyId": "coding.batch-release-flag",
            "code": "SOURCE_CODING_DIVERGENCE",
            "impact": "warning",
            "reason": _CODING_UNCERTAINTY_REASON,
            "evidenceIds": ["query.task.batch_report_release_flag"],
        }
    ],
    "order.source_code": [
        {
            "uncertaintyId": "domain.order-source-code",
            "code": "CONFIRMED_VALUE_DOMAIN_MINIMAL",
            "impact": "warning",
            "reason": "当前确认值域仅含 2=海外业务；其余编码待业务补充后扩展目录。",
            "evidenceIds": ["query.order.source_code"],
        }
    ],
}


def _declarations(
    catalog: BusinessConfirmedFactCatalogV3,
) -> list[FactDeclarationV3]:
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
    if len(declarations) != 18:
        raise ValueError(f"expected 18 fact declarations, found {len(declarations)}")
    return declarations


def _base_given(order_amount: float) -> dict[str, Any]:
    return {
        "report.release_status": None,
        "task.status_code": "19",
        "task.experiment_status_code": "1",
        "task.offline_report_release_flag": "5",
        "task.batch_report_release_flag": "5",
        "task.project_report_flag": "0",
        "task.qc_report_flag": "0",
        "order.amount": order_amount,
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


def _case(
    case_id: str,
    description: str,
    overrides: dict[str, Any],
    outcome: str,
    matched: list[str],
) -> dict[str, Any]:
    return {
        "caseId": case_id,
        "description": description,
        "given": {**_base_given(12000.0), **overrides},
        "expectedOutcome": outcome,
        "expectedReasonCode": (
            f"{matched[-1]}_MATCHED" if matched else "FACT_VALUE_MISSING_OR_INVALID"
        ),
        "expectedMatchedRuleCodes": matched,
    }


def _test_cases() -> list[TestCaseV3]:
    specs: list[dict[str, Any]] = [
        _case(
            "state-terminal-skip",
            "前提-1：释放状态已为终态时跳过评估",
            {"report.release_status": "准备释放"},
            "SKIPPED",
            ["REPORT_STATUS_TERMINAL"],
        ),
        _case(
            "prereq-not-completed",
            "前提0：任务未完工等待完工",
            {"task.status_code": "226"},
            "WAITING_COMPLETION",
            ["TASK_NOT_COMPLETED"],
        ),
        _case(
            "prereq-experiment-offline",
            "前提1：失败导致线下确认收入",
            {"task.experiment_status_code": "2"},
            "NO_RELEASE_REQUIRED",
            ["EXPERIMENT_STATUS_OFFLINE"],
        ),
        _case(
            "prereq-experiment-problem",
            "前提1：问题项目无需释放",
            {"task.experiment_status_code": "7"},
            "NO_RELEASE_REQUIRED",
            ["EXPERIMENT_STATUS_PROBLEM"],
        ),
        _case(
            "prereq-offline-released",
            "前提2：项目报告已线下释放",
            {"task.offline_report_release_flag": "4"},
            "ALREADY_RELEASED",
            ["OFFLINE_REPORT_RELEASED"],
        ),
        _case(
            "prereq-no-report",
            "前提3：无项目报告且无质控报告",
            {"task.project_report_flag": "1", "task.qc_report_flag": "1"},
            "NO_RELEASE_REQUIRED",
            ["NO_PROJECT_REPORT"],
        ),
        _case(
            "prereq-availability-unknown",
            "前提3：报告有无待定时等待满足条件",
            {"task.project_report_flag": None, "task.qc_report_flag": None},
            "WAITING_CONDITIONS",
            ["REPORT_AVAILABILITY_UNKNOWN"],
        ),
        _case(
            "r0-zero-order",
            "R0：0元订单直接就绪",
            {"order.amount": 0.0},
            "READY",
            ["R0_ZERO_ORDER"],
        ),
        _case(
            "r1-special-approval",
            "R1：特殊申请已审批直接就绪",
            {"release.special_application_count": 3},
            "READY",
            ["R1_SPECIAL_APPROVAL"],
        ),
        _case(
            "r9-batch-release",
            "R9：标记批量释放直接就绪",
            {"task.batch_report_release_flag": "4"},
            "READY",
            ["R9_BATCH_RELEASE"],
        ),
        _case(
            "r4-raw-data-released",
            "R4：原始数据已释放且过截止日",
            {"release.raw_data_released_after_cutoff": True},
            "READY",
            ["R4_RAW_DATA_RELEASED"],
        ),
        _case(
            "r2-overseas-order",
            "R2：海外业务订单直接就绪",
            {"order.source_code": "2"},
            "READY",
            ["R2_OVERSEAS_ORDER"],
        ),
        _case(
            "r3-special-product",
            "R3：特殊产品命中",
            {"product.special_product_flag": True},
            "READY",
            ["R3_SPECIAL_PRODUCT"],
        ),
        _case(
            "r8-time-trigger",
            "R8：完工时间触发到期",
            {"release.timed_release_eligible": True},
            "READY",
            ["R8_TIME_TRIGGER"],
        ),
        _case(
            "r5-enterprise",
            "R5：非框架企业单位全额到款",
            {"order.enterprise_non_framework_full_payment_eligible": True},
            "READY",
            ["R5_ENTERPRISE"],
        ),
        _case(
            "r6-non-enterprise",
            "R6：非框架非企业单位满足",
            {"order.non_enterprise_release_eligible": True},
            "READY",
            ["R6_NON_ENTERPRISE"],
        ),
        _case(
            "r7-framework",
            "R7：框架协议满足",
            {"order.framework_release_eligible": True},
            "READY",
            ["R7_FRAMEWORK"],
        ),
        _case(
            "postgate-merge-blocked",
            "合并报告组未满足时 postGate 降级",
            {"order.amount": 0.0, "report.merge_group_eligible": False},
            "WAITING_CONDITIONS",
            ["R0_ZERO_ORDER", "MERGED_REPORT_GATE"],
        ),
        _case(
            "exclusion-oa-process",
            "任务在 OA 流程中时排除触发",
            {"order.amount": 0.0, "task.in_oa_process": True},
            "WAITING_CONDITIONS",
            ["R0_ZERO_ORDER", "OA_PROCESS_SCOPE"],
        ),
        {
            "caseId": "indeterminate-missing-eligibility",
            "description": "资格事实缺失时结果为 INDETERMINATE，不补造结论",
            "given": {
                **_base_given(12000.0),
                "release.special_application_count": None,
                "release.raw_data_released_after_cutoff": None,
                "order.source_code": None,
                "product.special_product_flag": None,
                "release.timed_release_eligible": None,
                "order.enterprise_non_framework_full_payment_eligible": None,
                "order.non_enterprise_release_eligible": None,
                "order.framework_release_eligible": None,
            },
            "expectedOutcome": "INDETERMINATE",
            "expectedReasonCode": "FACT_VALUE_MISSING_OR_INVALID",
            "expectedMatchedRuleCodes": [],
        },
    ]
    return [TestCaseV3.model_validate(spec) for spec in specs]


def _build_result(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV3,
    generated_at: datetime,
) -> RuleParseResultV3:
    return RuleParseResultV3.model_validate(
        {
            "schemaVersion": "3.0.0",
            "ruleVersion": build_rule_version_v3(
                candidate.rule_set_id,
                generated_at,
                RULE_BLOCK_SHA256,
                catalog.catalog_digest,
            ),
            "ruleSetId": candidate.rule_set_id,
            "generatedAt": generated_at.isoformat(),
            "status": "draft",
            "executable": False,
            "source": {
                "sourceName": "项目报告和原始数据释放优化方案.md",
                "relativePath": "sources/project-release-rules/项目报告和原始数据释放优化方案.md",
                "sourceSha256": RULE_BLOCK_SHA256,
                "sourceCharacterCount": 1402,
                "parserVersion": CONFIRMED_PROFILE_PARSER_VERSION,
                "promptVersion": "rule-structure-v3.1",
                "provider": "reviewed_import",
                "model": "reviewed-import-v3-adjudication",
            },
            "parser": {
                "parserVersion": CONFIRMED_PROFILE_PARSER_VERSION,
                "promptVersion": "rule-structure-v3.1",
                "provider": "reviewed_import",
                "model": "reviewed-import-v3-adjudication",
            },
            "catalogRef": {
                "catalogId": catalog.catalog_id,
                "catalogVersion": catalog.catalog_version,
                "catalogDigest": catalog.catalog_digest,
            },
            "candidateRef": {
                "payloadSha256": candidate_payload_sha256_v3(candidate),
                "ruleBlockSha256": RULE_BLOCK_SHA256,
            },
            "factDeclarations": [
                declaration.model_dump(mode="json", by_alias=True)
                for declaration in _declarations(catalog)
            ],
            "testCases": [case.model_dump(mode="json", by_alias=True) for case in _test_cases()],
            "agent2ReadinessReady": False,
        }
    )


def build_confirmed_profile(
    reference_root: Path,
) -> tuple[BusinessConfirmedFactCatalogV3, RuleStructureCandidateV3, dict[str, Any]]:
    reference = load_ordered_report_release_reference(reference_root)
    manifest = json.loads((reference_root / "manifest.json").read_text(encoding="utf-8"))
    plan_files = [
        item
        for item in manifest.get("sourceFiles", [])
        if str(item.get("repositoryPath", "")).endswith("优化方案.md")
    ]
    if len(plan_files) != 1 or plan_files[0].get("sha256") != OPTIMIZATION_PLAN_SHA256:
        raise ValueError("optimization plan identity does not match the recorded decision")
    catalog = _confirmed_catalog(reference.workbook_path, OPTIMIZATION_PLAN_SHA256)
    candidate = _confirmed_candidate(catalog)
    metadata = {
        "bundleId": BUNDLE_ID,
        "workbookSha256": WORKBOOK_SHA256,
        "ruleBlockSha256": RULE_BLOCK_SHA256,
        "optimizationPlanSha256": OPTIMIZATION_PLAN_SHA256,
        "catalogDigest": catalog.catalog_digest,
        "ruleCount": sum(len(stage.rules) for stage in candidate.stages),
        "activeRuleCount": sum(
            rule.status.value == "active" for stage in candidate.stages for rule in stage.rules
        ),
        "blockedRuleCount": sum(
            rule.status.value == "blocked" for stage in candidate.stages for rule in stage.rules
        ),
        "authority": "userConfirmedOrderedV3SourcePlus20260906Adjudication",
        "status": "businessConfirmedUnblockedCandidate",
        "executable": False,
        "adjudication": "BIZ-20260906-01",
    }
    return catalog, candidate, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--generated-at",
        type=datetime.fromisoformat,
        default=None,
        help="UTC timestamp for the immutable rule version; defaults to now",
    )
    args = parser.parse_args()
    validate_output_location(args.reference_root, args.output_dir)
    generated_at = (
        args.generated_at.astimezone(UTC) if args.generated_at is not None else datetime.now(UTC)
    )
    catalog, candidate, metadata = build_confirmed_profile(args.reference_root)

    result = _build_result(catalog, candidate, generated_at)
    pre_readiness = build_agent2_readiness_report_v3(candidate, catalog, result=result)
    non_export_gates = [gate for gate in pre_readiness.gates if gate.gate != 4]
    export_gate = next(gate for gate in pre_readiness.gates if gate.gate == 4)
    if not all(gate.result.value == "pass" for gate in non_export_gates) or (
        export_gate.result.value != "blocked"
    ):
        raise ValueError(
            "pre-export readiness is not clean: "
            + json.dumps(
                [
                    {"gate": gate.gate, "name": gate.name, "result": gate.result.value}
                    for gate in pre_readiness.gates
                ],
                ensure_ascii=False,
            )
        )
    ready_result = result.model_copy(update={"agent2_readiness_ready": True})
    requests = export_fact_binding_requests_v3(ready_result, candidate, catalog)
    readiness = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=ready_result,
        requests=requests,
    )
    if not readiness.ready:
        raise ValueError("post-export readiness is not ready; artifacts are not written")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output_dir / "business-confirmed-fact-catalog-3.0.0.json"
    candidate_path = args.output_dir / "rule-structure-candidate-3.0.0.json"
    result_path = args.output_dir / "rule-parse-result-3.0.0.json"
    requests_path = args.output_dir / "fact-binding-requests-3.0.0.json"
    readiness_path = args.output_dir / "v3-agent2-readiness-confirmed.json"
    catalog_path.write_text(
        catalog.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    candidate_path.write_text(
        candidate.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    result_path.write_text(
        ready_result.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    requests_path.write_text(
        json.dumps(
            [request.model_dump(mode="json", by_alias=True) for request in requests],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    readiness_path.write_text(
        json.dumps(readiness.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    metadata["catalogFileSha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    metadata["candidateFileSha256"] = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    metadata["resultFileSha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    metadata["requestsFileSha256"] = hashlib.sha256(requests_path.read_bytes()).hexdigest()
    metadata["readinessFileSha256"] = hashlib.sha256(readiness_path.read_bytes()).hexdigest()
    metadata["ruleVersion"] = ready_result.rule_version
    metadata["generatedAtUtc"] = ready_result.generated_at.isoformat()
    metadata["requestCount"] = len(requests)
    metadata["testCaseCount"] = len(ready_result.test_cases)
    metadata["agent2ReadinessReady"] = readiness.ready
    metadata["plannedRuleVersions"] = readiness.planned_rule_versions
    metadata["plannedHandoffs"] = readiness.planned_handoffs
    (args.output_dir / "confirmed-recovery-manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "catalogDigest": catalog.catalog_digest,
                "ruleVersion": ready_result.rule_version,
                "ruleCount": metadata["ruleCount"],
                "activeRuleCount": metadata["activeRuleCount"],
                "blockedRuleCount": metadata["blockedRuleCount"],
                "requestCount": len(requests),
                "testCaseCount": len(ready_result.test_cases),
                "ready": readiness.ready,
                "blockingCount": readiness.blocking_count,
                "plannedRuleVersions": readiness.planned_rule_versions,
                "plannedHandoffs": readiness.planned_handoffs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
