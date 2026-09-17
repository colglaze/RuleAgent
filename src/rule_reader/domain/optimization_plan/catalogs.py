"""Confirmed fact catalogs for the optimization-plan 3.1.0 deliveries."""

from __future__ import annotations

from typing import Any

from rule_reader.domain.optimization_plan import (
    CATALOG_VERSION,
    DATA_CATALOG_ID,
    EXTRACTOR_VERSION,
    OPTIMIZATION_PLAN_FILE_SHA256,
    REPORT_CATALOG_ID,
)
from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    catalog_digest_v3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.v2 import FactKind


def _parameter(grain: str) -> dict[str, Any]:
    name = "taskId" if grain in {"task", "contract"} else "orderId"
    if grain == "contract":
        name = "contractId"
    return {
        "name": name,
        "role": "entityKey",
        "dataType": "string",
        "required": True,
        "description": f"Logical {grain} key.",
    }


def _fact(
    code: str,
    name: str,
    description: str,
    data_type: str,
    grain: str,
    *,
    nullable: bool = True,
    null_policy: str = "indeterminate",
    unit: str | None = None,
    allowed_values: list[Any] | None = None,
    evidence: str = "plan.structure",
) -> dict[str, Any]:
    return {
        "factCode": code,
        "name": name,
        "description": description,
        "dataType": data_type,
        "nullable": nullable,
        "nullPolicy": null_policy,
        "grain": grain,
        "parameters": [_parameter(grain)],
        "allowedValues": allowed_values or [],
        "unit": unit,
        "evidenceRefs": [evidence],
        "bindingProfileRef": None,
        "bindingIssues": ["Physical mapping is owned by metadataReview."],
    }


REPORT_FACT_KINDS: dict[str, FactKind] = {
    "release.special_application_count": FactKind.AGGREGATE,
    "report.merge_group_member_ids": FactKind.AGGREGATE,
    "order.seal_scope_contract_ids": FactKind.AGGREGATE,
    "task.in_project_report_release_oa": FactKind.EXISTS,
}

DATA_FACT_KINDS: dict[str, FactKind] = {
    "release.special_application_count": FactKind.AGGREGATE,
    "order.sequencing_services_complete": FactKind.EXISTS,
    "task.in_raw_data_release_oa": FactKind.EXISTS,
}


def _evidence(source_file_sha256: str) -> list[dict[str, Any]]:
    return [
        {
            "evidenceId": "plan.structure",
            "sourceKind": "ruleText",
            "sourceId": "optimization-plan-v2.0",
            "sourceSha256": source_file_sha256,
            "locator": "section:1.3+5.1+5.2",
            "note": f"Extractor {EXTRACTOR_VERSION}; formulas expanded into the condition tree.",
        }
    ]


def report_facts() -> list[dict[str, Any]]:
    money: dict[str, Any] = {"unit": "CNY", "null_policy": "indeterminate"}
    return [
        _fact(
            "report.release_status",
            "Report release status",
            "Current report release status; terminal states skip evaluation.",
            "enum",
            "task",
            allowed_values=["准备释放", "释放中", "已释放", "等待完工", "等待满足条件", "无需释放"],
        ),
        _fact(
            "task.status_code",
            "Task status code",
            "Internal completion code; 19 means completed. Null is treated as not completed.",
            "integer",
            "task",
        ),
        _fact(
            "task.experiment_status_code",
            "Task experiment status",
            "Experiment status; 2 and 7 mean no report release is required.",
            "integer",
            "task",
        ),
        _fact(
            "task.offline_report_release_flag",
            "Offline report release flag",
            "Plan hit code 0 means already released offline.",
            "integer",
            "task",
        ),
        _fact(
            "task.batch_report_release_flag",
            "Batch report release flag",
            "Plan hit code 0 means marked for batch release.",
            "integer",
            "task",
        ),
        _fact(
            "task.project_report_flag",
            "Project report presence",
            "Plan code 0 means present, 1 means absent; other values are undecided.",
            "integer",
            "task",
        ),
        _fact(
            "task.qc_report_flag",
            "Quality report presence",
            "Plan code 0 means present, 1 means absent; other values are undecided.",
            "integer",
            "task",
        ),
        _fact(
            "order.amount",
            "Order amount",
            "Order amount; 0 hits R0, null continues.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "release.special_application_count",
            "Completed special application count",
            "Count of special applications for this task with application type and completed approval node filters. Join rows are not de-duplicated; no match is 0.",
            "integer",
            "task",
        ),
        _fact(
            "data.release_status",
            "Raw-data release status",
            "Raw-data release status used by R4 as the released flag.",
            "enum",
            "task",
            allowed_values=["准备释放", "释放中", "已释放", "等待完工", "等待满足条件", "无需释放"],
        ),
        _fact(
            "task.completion_date",
            "Completion date",
            "Task completion calendar date. Raw date facts are not pre-filtered.",
            "date",
            "task",
        ),
        _fact(
            "order.source_code",
            "Order source code",
            "Source code 2 means overseas business.",
            "integer",
            "order",
        ),
        _fact(
            "product.id",
            "Product id",
            "Product identifier; 759 is the special product.",
            "integer",
            "task",
        ),
        _fact(
            "product.category_code",
            "Product category code",
            "Category codes 2 and 12 are yeast library families; 1 and 14 are single-cell.",
            "integer",
            "task",
        ),
        _fact(
            "product.no_master_service_flag",
            "No master service flag",
            "Plan hit code 0 means no master service.",
            "integer",
            "task",
        ),
        _fact(
            "order.extraction_qc_amount",
            "Extraction and QC amount",
            "Extraction and QC completed amount.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "task.amount", "Task amount", "Task-level completed amount.", "money", "task", **money
        ),
        _fact(
            "order.report_release_amount",
            "Report release amount",
            "Completed amount attributed to project-report release.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "order.arrival_amount_including_deposit",
            "Arrival including deposit",
            "Order arrival that already includes deposit.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "order.deposit_amount",
            "Deposit amount",
            "Deposit portion of arrival.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "order.invoice_amount",
            "Invoice amount",
            "Invoiced amount; greater than 0 means invoiced.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "order.framework_type",
            "Framework agreement type",
            "0 and 2 are framework; 1 and null are non-framework.",
            "integer",
            "order",
        ),
        _fact(
            "order.customer_org_type",
            "Customer organization type",
            "14 and 16 are enterprise; other values and null are non-enterprise.",
            "integer",
            "order",
        ),
        _fact(
            "report.merge_group_present",
            "Combined-report group present",
            "True when this task belongs to a combined-report group.",
            "boolean",
            "task",
        ),
        _fact(
            "report.merge_group_member_ids",
            "Combined-report group member keys",
            "Related member task keys excluding self, unique by member key.",
            "list",
            "task",
        ),
        _fact(
            "order.seal_scope_contract_ids",
            "Seal-scope contract keys",
            "Execution contract plus related contracts with remaining amount greater than 0.",
            "list",
            "order",
        ),
        _fact(
            "contract.template_kind",
            "Contract template kind",
            "0 means non-template contract; 1 or null means template contract.",
            "integer",
            "contract",
        ),
        _fact(
            "contract.effective_mode",
            "Contract effective mode",
            "1 means seal effective mode; 0 or null means the other effective mode.",
            "integer",
            "contract",
        ),
        _fact(
            "contract.quota_kind",
            "Contract quota kind",
            "0 small-quota, 1/null outside quota, 2 inside non-core, 3 mini-program.",
            "integer",
            "contract",
        ),
        _fact(
            "contract.countersign_date",
            "Contract countersign date",
            "Countersign calendar date compared with the bound cutoff.",
            "date",
            "contract",
        ),
        _fact(
            "contract.receipt_status",
            "Contract receipt status",
            "0 signed-not-sealed, 1/2 sealed, 3 or null not received.",
            "integer",
            "contract",
        ),
        _fact(
            "contract.sign_method",
            "Contract sign method",
            "2 is contact e-sign, which branch 5 excludes when receipt status is 0.",
            "integer",
            "contract",
        ),
        _fact(
            "task.in_project_report_release_oa",
            "In project-report release OA",
            "Exists in an in-progress project-report release OA instance only. Scheduler, callback, and write actions are out of scope.",
            "boolean",
            "task",
        ),
    ]


def data_facts() -> list[dict[str, Any]]:
    money: dict[str, Any] = {"unit": "CNY", "null_policy": "indeterminate"}
    return [
        _fact(
            "data.release_status",
            "Raw-data release status",
            "Current raw-data release status; terminal states skip evaluation.",
            "enum",
            "task",
            allowed_values=["准备释放", "释放中", "已释放", "等待完工", "等待满足条件", "无需释放"],
        ),
        _fact(
            "task.status_code",
            "Task status code",
            "19 means completed. Null is not completed.",
            "integer",
            "task",
        ),
        _fact(
            "task.data_lost_flag",
            "Data lost flag",
            "Plan hit code 1 means marked data lost and no release is required.",
            "integer",
            "task",
        ),
        _fact(
            "task.offline_data_release_flag",
            "Offline raw-data release flag",
            "Plan hit code 1 means already released offline.",
            "integer",
            "task",
        ),
        _fact(
            "task.raw_data_present_flag",
            "Raw data presence",
            "Plan code 0 means present, 1 means absent; other values are undecided.",
            "integer",
            "task",
        ),
        _fact(
            "order.amount",
            "Order amount",
            "Order amount; 0 hits D0, null continues.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "release.special_application_count",
            "Completed special application count",
            "Count of raw-data special applications with type and completed approval node filters. Join rows are not de-duplicated.",
            "integer",
            "task",
        ),
        _fact(
            "order.source_code",
            "Order source code",
            "Source code 2 means overseas business.",
            "integer",
            "order",
        ),
        _fact(
            "order.closed_loop_status",
            "Order closed-loop status",
            "1 closed, 2 terminated closed, 3 intervened closed.",
            "integer",
            "order",
        ),
        _fact(
            "order.extraction_qc_amount",
            "Extraction and QC amount",
            "Extraction and QC completed amount.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "task.amount", "Task amount", "Task-level completed amount.", "money", "task", **money
        ),
        _fact(
            "order.data_release_amount",
            "Raw-data release amount",
            "Completed amount attributed to raw-data release.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "order.arrival_amount_including_deposit",
            "Arrival including deposit",
            "Order arrival that already includes deposit.",
            "money",
            "order",
            **money,
        ),
        _fact(
            "product.category_code",
            "Product category code",
            "1 and 14 are single-cell categories.",
            "integer",
            "task",
        ),
        _fact(
            "order.closed_flag",
            "Order closed flag",
            "0 means closed; missing values are treated as 1 by coalesce.",
            "integer",
            "order",
        ),
        _fact(
            "order.experiment_run_status",
            "Order experiment run status",
            "1 means terminated experiment; missing values are treated as 0 by coalesce.",
            "integer",
            "order",
        ),
        _fact(
            "order.sequencing_services_complete",
            "Sequencing services complete",
            "True when every sequencing service completed quantity is at least requested and at least one sequencing service exists.",
            "boolean",
            "order",
        ),
        _fact(
            "task.in_raw_data_release_oa",
            "In raw-data release OA",
            "Exists in an in-progress raw-data release OA instance only.",
            "boolean",
            "task",
        ),
    ]


def build_catalog(
    catalog_id: str,
    facts: list[dict[str, Any]],
    *,
    source_file_sha256: str = OPTIMIZATION_PLAN_FILE_SHA256,
) -> BusinessConfirmedFactCatalogV3:
    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": catalog_id,
        "catalogVersion": CATALOG_VERSION,
        "catalogDigest": "0" * 64,
        "facts": facts,
        "evidence": _evidence(source_file_sha256),
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    catalog = BusinessConfirmedFactCatalogV3.model_validate(payload)
    validate_fact_catalog_v3(catalog)
    return catalog


def build_report_catalog(
    *, source_file_sha256: str = OPTIMIZATION_PLAN_FILE_SHA256
) -> BusinessConfirmedFactCatalogV3:
    return build_catalog(REPORT_CATALOG_ID, report_facts(), source_file_sha256=source_file_sha256)


def build_data_catalog(
    *, source_file_sha256: str = OPTIMIZATION_PLAN_FILE_SHA256
) -> BusinessConfirmedFactCatalogV3:
    return build_catalog(DATA_CATALOG_ID, data_facts(), source_file_sha256=source_file_sha256)
