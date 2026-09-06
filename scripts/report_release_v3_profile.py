"""Build the source-bound ordered REPORT_RELEASE V3 catalog and blocked candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from scripts.validate_report_release_v3_reference import (
    BUNDLE_ID,
    RULE_BLOCK_SHA256,
    WORKBOOK_SHA256,
    load_ordered_report_release_reference,
)

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    catalog_digest_v3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import validate_rule_structure_candidate_v3

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CATALOG_ID = "REPORT_RELEASE_CONFIRMED_FACTS"
CATALOG_VERSION = "2026-09-05.1"

_FACT_ROWS = {
    "task.status_code": 8,
    "task.project_report_flag": 17,
    "task.experiment_status_code": 20,
    "task.offline_report_release_flag": 22,
    "task.batch_report_release_flag": 23,
    "task.qc_report_flag": 24,
    "task.has_primary_service_flag": 27,
}


def _xlsx_cells(path: Path, sheet_name: str, addresses: set[str]) -> dict[str, str]:
    """Read cached cell text without executing workbook formulas or macros."""

    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation_targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
        }
        sheet = next(
            (
                item
                for item in workbook.findall(f".//{{{_MAIN_NS}}}sheet")
                if item.attrib.get("name") == sheet_name
            ),
            None,
        )
        if sheet is None:
            raise ValueError(f"workbook is missing sheet {sheet_name}")
        relation_id = sheet.attrib[f"{{{_DOC_REL_NS}}}id"]
        target = PurePosixPath(relation_targets[relation_id])
        sheet_path = target if target.is_absolute() else PurePosixPath("xl") / target
        normalized_sheet_path = str(sheet_path).lstrip("/")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(f".//{{{_MAIN_NS}}}t"))
                for item in shared.findall(f"{{{_MAIN_NS}}}si")
            ]

        xml = ElementTree.fromstring(archive.read(normalized_sheet_path))
        values: dict[str, str] = {}
        for cell in xml.findall(f".//{{{_MAIN_NS}}}c"):
            address = cell.attrib.get("r")
            if address not in addresses:
                continue
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(f".//{{{_MAIN_NS}}}t"))
            else:
                value_node = cell.find(f"{{{_MAIN_NS}}}v")
                raw = value_node.text if value_node is not None and value_node.text else ""
                value = shared_strings[int(raw)] if cell_type == "s" and raw else raw
            values[address] = value
        missing = sorted(addresses - set(values))
        if missing:
            raise ValueError(f"confirmed workbook cells are missing: {missing}")
        return values


def _allowed_values(raw: str) -> list[str]:
    enum_codes = re.findall(r"=\s*\(\s*[\"']?(\d+)[\"']?\s*,", raw)
    candidates = enum_codes or re.findall(r"(?<!\d)(\d+)(?!\d)", raw)
    return list(dict.fromkeys(candidates))


def _catalog(workbook_path: Path) -> BusinessConfirmedFactCatalogV3:
    addresses = {f"{column}{row}" for row in _FACT_ROWS.values() for column in ("G", "H", "I", "L")}
    cells = _xlsx_cells(workbook_path, "字段清单", addresses)
    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for fact_code, row in _FACT_ROWS.items():
        if cells[f"I{row}"].strip().lower() != "varchar":
            raise ValueError(f"confirmed data type changed at 字段清单!I{row}")
        evidence_id = f"workbook.row.{row}"
        evidence.append(
            {
                "evidenceId": evidence_id,
                "sourceKind": "businessConfirmation",
                "sourceId": f"{BUNDLE_ID}/field-catalog",
                "sourceSha256": WORKBOOK_SHA256,
                "locator": f"字段清单!G{row}:L{row}",
                "note": "用户确认已填写单元格有效；核对状态列未同步更新。",
            }
        )
        facts.append(
            {
                "factCode": fact_code,
                "name": cells[f"H{row}"],
                "description": cells[f"G{row}"],
                "dataType": "string",
                "nullable": True,
                "nullPolicy": "indeterminate",
                "grain": "task",
                "parameters": [
                    {
                        "name": "taskId",
                        "role": "entityKey",
                        "dataType": "string",
                        "required": True,
                        "description": "正式实验任务标识。",
                    }
                ],
                "allowedValues": _allowed_values(cells[f"L{row}"]),
                "unit": None,
                "evidenceRefs": [evidence_id],
                "bindingProfileRef": None,
                "bindingIssues": ["固定 bundle 不包含已批准的 V3 binding profile。"],
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


def _fact(code: str) -> dict[str, Any]:
    return {"kind": "fact", "factCode": code, "children": []}


def _literal(value: str | list[str]) -> dict[str, Any]:
    return {"kind": "literal", "value": value, "children": []}


def _compare(condition_id: str, fact_code: str, operator: str, value: str) -> dict[str, Any]:
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


def _all(condition_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": condition_id,
        "kind": "all",
        "description": condition_id.replace("-", " "),
        "enabled": True,
        "children": children,
        "left": None,
        "operator": None,
        "right": None,
        "nullPolicy": "indeterminate",
    }


def _active(
    code: str,
    priority: int,
    title: str,
    when: dict[str, Any],
    outcome: str,
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
        "recommendations": ["按有序来源核对对应任务状态。"],
        "blockingIssueIds": [],
    }


def _blocked(code: str, priority: int, title: str, issue_id: str) -> dict[str, Any]:
    return {
        "ruleCode": code,
        "priority": priority,
        "title": title,
        "status": "blocked",
        "when": None,
        "outcome": None,
        "reasonCode": None,
        "failureReason": f"{title}缺少无冲突的确认事实契约。",
        "recommendations": ["保留来源差异并完成业务事实确认。"],
        "blockingIssueIds": [issue_id],
    }


def _candidate(catalog: BusinessConfirmedFactCatalogV3) -> RuleStructureCandidateV3:
    issue_specs = [
        ("release.status", "BUSINESS_FACT_MISSING", ["report.release_status"]),
        ("task.status.code", "SOURCE_VALUE_CONFLICT", ["task.status_code"]),
        (
            "task.offline.code",
            "SOURCE_VALUE_CONFLICT",
            ["task.offline_report_release_flag"],
        ),
        (
            "report.availability.other",
            "SOURCE_BRANCH_UNREACHABLE_WITH_CONFIRMED_ENUM",
            ["task.project_report_flag", "task.qc_report_flag"],
        ),
        ("rule.r0", "BUSINESS_FACT_MISSING", ["order.amount"]),
        ("rule.r1", "BUSINESS_FACT_MISSING", ["release.special_application_count"]),
        (
            "rule.r9",
            "SOURCE_VALUE_CONFLICT",
            ["task.batch_report_release_flag"],
        ),
        ("rule.r4", "BUSINESS_FACT_MISSING", ["release.raw_data_released_after_cutoff"]),
        ("rule.r2", "BUSINESS_FACT_MISSING", ["order.source_code"]),
        ("rule.r3", "BUSINESS_FACT_MISSING", ["product.special_product_flag"]),
        ("rule.r8", "BUSINESS_FACT_MISSING", ["release.timed_release_eligible"]),
        (
            "rule.r5",
            "BUSINESS_FACT_MISSING",
            ["order.enterprise_non_framework_full_payment_eligible"],
        ),
        (
            "rule.r6",
            "BUSINESS_FACT_MISSING",
            ["order.non_enterprise_release_eligible"],
        ),
        ("rule.r7", "BUSINESS_FACT_MISSING", ["order.framework_release_eligible"]),
        ("report.merge", "BUSINESS_FACT_MISSING", ["report.merge_group_eligible"]),
        ("task.oa.scope", "BUSINESS_FACT_MISSING", ["task.in_oa_process"]),
    ]
    catalog_codes = {fact.fact_code for fact in catalog.facts}
    blocking_issues = [
        {
            "issueId": issue_id,
            "code": code,
            "message": f"有序规则节点 {issue_id} 尚不能构造 active 条件。",
            "factCodes": fact_codes,
            "resolutionHint": "确认逻辑事实的类型、值域、粒度、参数和来源差异。",
        }
        for issue_id, code, fact_codes in issue_specs
    ]
    proposed_facts = [
        {
            "factCode": fact_code,
            "name": fact_code,
            "dataTypeHint": None,
            "reason": "有序规则引用该概念，但确认目录中尚无完整契约。",
            "sourceLocator": "ordered-report-release-v2.0",
        }
        for _, _, fact_codes in issue_specs
        for fact_code in fact_codes
        if fact_code not in catalog_codes
    ]
    stages = [
        {
            "stage": "stateGuards",
            "rules": [
                _blocked("REPORT_STATUS_TERMINAL", 10, "释放状态表终态检查", "release.status")
            ],
        },
        {
            "stage": "prerequisites",
            "rules": [
                _blocked("TASK_NOT_COMPLETED", 10, "任务尚未完工", "task.status.code"),
                _active(
                    "EXPERIMENT_STATUS_OFFLINE",
                    20,
                    "失败导致线下确认收入",
                    _compare(
                        "experiment-status-offline",
                        "task.experiment_status_code",
                        "eq",
                        "2",
                    ),
                    "NO_RELEASE_REQUIRED",
                ),
                _active(
                    "EXPERIMENT_STATUS_PROBLEM",
                    30,
                    "问题项目无需释放",
                    _compare(
                        "experiment-status-problem",
                        "task.experiment_status_code",
                        "eq",
                        "7",
                    ),
                    "NO_RELEASE_REQUIRED",
                ),
                _blocked(
                    "OFFLINE_REPORT_RELEASED",
                    40,
                    "项目报告已线下释放",
                    "task.offline.code",
                ),
                _active(
                    "NO_PROJECT_REPORT",
                    50,
                    "任务无需项目报告",
                    _all(
                        "no-project-report",
                        [
                            _compare(
                                "project-report-absent",
                                "task.project_report_flag",
                                "eq",
                                "1",
                            ),
                            _compare(
                                "qc-report-absent",
                                "task.qc_report_flag",
                                "eq",
                                "1",
                            ),
                        ],
                    ),
                    "NO_RELEASE_REQUIRED",
                ),
                _blocked(
                    "REPORT_AVAILABILITY_UNKNOWN",
                    60,
                    "有无项目报告待定",
                    "report.availability.other",
                ),
            ],
        },
        {
            "stage": "eligibility",
            "rules": [
                _blocked("R0_ZERO_ORDER", 10, "R0 0元订单", "rule.r0"),
                _blocked("R1_SPECIAL_APPROVAL", 20, "R1 特殊申请已审批", "rule.r1"),
                _blocked("R9_BATCH_RELEASE", 30, "R9 标记批量释放", "rule.r9"),
                _blocked("R4_RAW_DATA_RELEASED", 40, "R4 原始数据已释放", "rule.r4"),
                _blocked("R2_OVERSEAS_ORDER", 50, "R2 海外业务订单", "rule.r2"),
                _blocked("R3_SPECIAL_PRODUCT", 60, "R3 特殊产品", "rule.r3"),
                _blocked("R8_TIME_TRIGGER", 70, "R8 完工时间触发", "rule.r8"),
                _blocked("R5_ENTERPRISE", 80, "R5 非框架企业单位", "rule.r5"),
                _blocked("R6_NON_ENTERPRISE", 90, "R6 非框架非企业单位", "rule.r6"),
                _blocked("R7_FRAMEWORK", 100, "R7 框架协议", "rule.r7"),
            ],
        },
        {
            "stage": "postGates",
            "rules": [_blocked("MERGED_REPORT_GATE", 10, "合并报告组全部满足", "report.merge")],
        },
        {
            "stage": "exclusions",
            "rules": [_blocked("OA_PROCESS_SCOPE", 10, "任务必须位于OA流程", "task.oa.scope")],
        },
    ]
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
        "requiredFactCodes": [
            "task.experiment_status_code",
            "task.project_report_flag",
            "task.qc_report_flag",
        ],
        "stages": stages,
        "defaultOutcome": "WAITING_CONDITIONS",
        "defaultReasonCode": "NO_ORDERED_RELEASE_RULE_MATCHED",
        "blockingIssues": blocking_issues,
        "proposedFacts": proposed_facts,
    }
    candidate = RuleStructureCandidateV3.model_validate(payload)
    validate_rule_structure_candidate_v3(candidate, catalog)
    return candidate


def build_profile(
    reference_root: Path,
) -> tuple[BusinessConfirmedFactCatalogV3, RuleStructureCandidateV3, dict[str, Any]]:
    reference = load_ordered_report_release_reference(reference_root)
    catalog = _catalog(reference.workbook_path)
    candidate = _candidate(catalog)
    metadata = {
        "bundleId": BUNDLE_ID,
        "workbookSha256": WORKBOOK_SHA256,
        "ruleBlockSha256": RULE_BLOCK_SHA256,
        "catalogDigest": catalog.catalog_digest,
        "ruleCount": sum(len(stage.rules) for stage in candidate.stages),
        "activeRuleCount": sum(
            rule.status.value == "active" for stage in candidate.stages for rule in stage.rules
        ),
        "blockedRuleCount": sum(
            rule.status.value == "blocked" for stage in candidate.stages for rule in stage.rules
        ),
        "authority": "userConfirmedOrderedV3Source",
        "status": "validatedBlockedCandidate",
        "executable": False,
    }
    return catalog, candidate, metadata


def validate_output_location(reference_root: Path, output_dir: Path) -> None:
    if output_dir.resolve().is_relative_to(reference_root.resolve()):
        raise ValueError("output directory must be outside the fixed private bundle repository")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_output_location(args.reference_root, args.output_dir)
    catalog, candidate, metadata = build_profile(args.reference_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output_dir / "business-confirmed-fact-catalog-3.0.0.json"
    candidate_path = args.output_dir / "rule-structure-candidate-3.0.0.json"
    catalog_path.write_text(
        catalog.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    candidate_path.write_text(
        candidate.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    metadata["catalogFileSha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    metadata["candidateFileSha256"] = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    (args.output_dir / "recovery-manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
