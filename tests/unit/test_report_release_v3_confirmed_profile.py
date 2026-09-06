"""Offline tests for the business-confirmed V3 profile after the 2026-09-06 adjudications."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest
from pydantic import ValidationError
from scripts.report_release_v3_confirmed_profile import (
    _ADDED_FACT_SPECS,
    _WITNESSES,
    _added_fact_payloads,
    _confirmed_candidate,
    _legend_values,
)

from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    catalog_digest_v3,
)
from rule_reader.domain.rules.readiness_v3 import build_agent2_readiness_report_v3
from rule_reader.domain.rules.validation_v3 import (
    evaluate_rule_structure_v3,
    validate_rule_reachability_witnesses_v3,
)

_BASE_FACT_VALUES: dict[str, list[str]] = {
    "task.status_code": ["19", "226"],
    "task.project_report_flag": ["0", "1"],
    "task.experiment_status_code": ["0", "1", "2", "7"],
    "task.offline_report_release_flag": ["4", "5"],
    "task.batch_report_release_flag": ["4", "5"],
    "task.qc_report_flag": ["0", "1"],
    "task.has_primary_service_flag": ["0", "1"],
}


def _confirmed_catalog() -> BusinessConfirmedFactCatalogV3:
    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, (fact_code, allowed_values) in enumerate(_BASE_FACT_VALUES.items(), start=1):
        evidence_id = f"confirmation.row.{index}"
        facts.append(
            {
                "factCode": fact_code,
                "name": f"合成基础事实 {index}",
                "description": "只用于确认后 profile 离线测试。",
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
                        "description": "合成任务标识。",
                    }
                ],
                "allowedValues": allowed_values,
                "unit": None,
                "evidenceRefs": [evidence_id],
                "bindingProfileRef": None,
                "bindingIssues": ["合成目录无物理绑定。"],
            }
        )
        evidence.append(
            {
                "evidenceId": evidence_id,
                "sourceKind": "businessConfirmation",
                "sourceId": "synthetic-workbook",
                "sourceSha256": "2" * 64,
                "locator": f"synthetic!A{index}",
                "note": "脱敏合成证据。",
            }
        )
    facts.extend(_added_fact_payloads())
    for spec in _ADDED_FACT_SPECS:
        evidence.append(
            {
                "evidenceId": f"plan.section.{spec['factCode'].replace('.', '-')}",
                "sourceKind": "ruleText",
                "sourceId": "synthetic-plan",
                "sourceSha256": "3" * 64,
                "locator": "synthetic-section",
                "note": "脱敏合成证据。",
            }
        )
    payload: dict[str, Any] = {
        "contractVersion": "3.0.0",
        "catalogId": "REPORT_RELEASE_CONFIRMED_FACTS",
        "catalogVersion": "2026-09-06.1",
        "catalogDigest": "0" * 64,
        "facts": facts,
        "evidence": evidence,
    }
    payload["catalogDigest"] = catalog_digest_v3(payload)
    return BusinessConfirmedFactCatalogV3.model_validate(payload)


def test_confirmed_candidate_is_fully_active_with_empty_blockers() -> None:
    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    rules = [rule for stage in candidate.stages for rule in stage.rules]
    assert len(rules) == 19
    assert all(rule.status.value == "active" for rule in rules)
    assert all(rule.when is not None and rule.outcome is not None for rule in rules)
    assert candidate.blocking_issues == []
    assert candidate.proposed_facts == []
    # requiredFactCodes 必须等于 active 条件引用闭包, 目录中的主服务标志未被规则引用。
    assert "task.has_primary_service_flag" not in candidate.required_fact_codes
    assert len(candidate.required_fact_codes) == 18
    assert candidate.catalog_digest == catalog.catalog_digest


def test_confirmed_rules_have_reachability_witnesses() -> None:
    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    active_codes = {
        rule.rule_code
        for stage in candidate.stages
        for rule in stage.rules
        if rule.status.value == "active"
    }
    assert active_codes == set(_WITNESSES)
    validate_rule_reachability_witnesses_v3(candidate, catalog, _WITNESSES)


def test_legend_values_come_from_confirmed_workbook_format() -> None:
    assert _legend_values("4是5否") == {"4": "是", "5": "否"}
    assert _legend_values("0有1无") == {"0": "有", "1": "无"}
    with pytest.raises(ValueError, match="legend"):
        _legend_values("0有")


def test_interpreter_end_to_end_scenarios() -> None:
    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)

    def evaluate(given: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
        result = evaluate_rule_structure_v3(candidate, catalog, given)
        return result.outcome.value, result.reason_code, result.matched_rule_codes

    # 前提-1 终态跳过, 不再评估。
    assert evaluate({"report.release_status": "准备释放"}) == (
        "SKIPPED",
        "REPORT_STATUS_TERMINAL_MATCHED",
        ("REPORT_STATUS_TERMINAL",),
    )
    # 前提0 未完工等待完工。
    assert evaluate({"task.status_code": "226"})[0] == "WAITING_COMPLETION"
    # 前提1 失败导致线下确认收入。
    assert evaluate({"task.status_code": "19", "task.experiment_status_code": "2"})[0] == (
        "NO_RELEASE_REQUIRED"
    )
    # 前提2 XLSX 确认值域 4=是/已线下释放。
    assert evaluate({"task.status_code": "19", "task.offline_report_release_flag": "4"})[0] == (
        "ALREADY_RELEASED"
    )
    # 前提3 空值=待定, 保留分支。
    assert (
        evaluate(
            {
                "task.status_code": "19",
                "task.project_report_flag": None,
                "task.qc_report_flag": None,
            }
        )[0]
        == "WAITING_CONDITIONS"
    )
    # R0 首个命中优先级, 0 元订单直接就绪。
    outcome, _, matched = evaluate(_ready_path_given(order_amount=0))
    assert (outcome, matched[0]) == ("READY", "R0_ZERO_ORDER")
    # R2 海外订单命中。
    outcome, _, matched = evaluate(
        {
            **_ready_path_given(order_amount=5000),
            "release.special_application_count": 0,
            "task.batch_report_release_flag": "5",
            "release.raw_data_released_after_cutoff": False,
            "order.source_code": "2",
        }
    )
    assert (outcome, matched[0]) == ("READY", "R2_OVERSEAS_ORDER")
    # 合并报告组未满足, postGates 命中并降级。
    given = {**_ready_path_given(order_amount=0), "report.merge_group_eligible": False}
    assert evaluate(given)[0] == "WAITING_CONDITIONS"
    # 排除条件: 任务在 OA 流程中时不触发新释放, 等待流程完成。
    given = {**_ready_path_given(order_amount=0), "task.in_oa_process": True}
    assert evaluate(given)[0] == "WAITING_CONDITIONS"
    # 资格事实缺失时结果为 INDETERMINATE, 不会被补成看似有效的结论。
    # 确认值域最小化(订单来源仅确认 2)使默认路径在完整流程中不可达。
    incomplete = {**_ready_path_given(order_amount=1), "order.source_code": None}
    assert evaluate(incomplete)[0] == "INDETERMINATE"


def _ready_path_given(order_amount: float) -> dict[str, Any]:
    return {
        "task.status_code": "19",
        "task.experiment_status_code": "1",
        "task.offline_report_release_flag": "5",
        "task.project_report_flag": "0",
        "task.qc_report_flag": "0",
        "order.amount": order_amount,
        "report.merge_group_eligible": True,
        "task.in_oa_process": False,
    }


def test_confirmed_readiness_report_shows_unblocked_candidate() -> None:
    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    report = build_agent2_readiness_report_v3(candidate, catalog)
    assert report.blocking_count == 0
    assert report.gaps == []
    assert report.ready is False
    assert report.planned_rule_versions == 0
    assert report.planned_handoffs == 0
    assert report.requires_sqlbot_contract_upgrade is True
    gates = {gate.name: gate for gate in report.gates}
    assert gates["noBusinessBlocking"].result.value == "pass"
    assert gates["requiredFactsComplete"].result.value == "pass"
    assert gates["entityGrainKeys"].result.value == "pass"
    assert gates["stableConditionUsage"].result.value == "pass"
    assert gates["evidenceClosure"].result.value == "pass"
    assert gates["provenanceComplete"].result.value == "pass"
    assert gates["candidateNonExecutable"].result.value == "pass"
    assert gates["immutableRuleVersion"].result.value == "fail"
    assert gates["immutableRuleVersion"].evidence == "No RuleParseResultV3 exists."
    for name in (
        "stableFields",
        "filtersComplete",
        "filterSemantics",
        "aggregationComplete",
        "timeRangeComplete",
        "scalarResult",
    ):
        assert gates[name].result.value == "fail"
        assert gates[name].evidence == "Query requirements await RuleParseResultV3 (Slice 3-6)."
    assert gates["oneRequestPerAtomicFact"].result.value == "blocked"
    assert gates["derivedFactsExcluded"].result.value == "blocked"


def test_result_export_and_full_green_readiness() -> None:
    from datetime import datetime

    from scripts.report_release_v3_confirmed_profile import _build_result

    from rule_reader.domain.rules.result_v3 import export_fact_binding_requests_v3

    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    result = _build_result(catalog, candidate, datetime(2026, 9, 6, tzinfo=UTC))
    assert result.agent2_readiness_ready is False

    pre = build_agent2_readiness_report_v3(candidate, catalog, result=result)
    export_gate = next(gate for gate in pre.gates if gate.gate == 4)
    non_export = [gate for gate in pre.gates if gate.gate != 4]
    assert export_gate.result.value == "blocked"
    assert all(gate.result.value == "pass" for gate in non_export)
    with pytest.raises(ValueError, match="not allowed"):
        export_fact_binding_requests_v3(result, candidate, catalog)

    ready_result = result.model_copy(update={"agent2_readiness_ready": True})
    requests = export_fact_binding_requests_v3(ready_result, candidate, catalog)
    assert len(requests) == 18
    assert all(
        request.request_id == f"{ready_result.rule_version}#{request.fact.fact_code}"
        for request in requests
    )
    assert all(
        uncertainty.impact == "warning"
        for request in requests
        for uncertainty in request.uncertainties
    )
    assert len([request for request in requests if request.uncertainties]) == 3

    documents = {
        "ruleResult": ready_result.model_dump(mode="json", by_alias=True),
        "candidate": candidate.model_dump(mode="json", by_alias=True),
        "catalog": catalog.model_dump(mode="json", by_alias=True),
    }

    def resolve_pointer(document: object, pointer: str) -> object:
        current = document
        for raw_token in pointer.removeprefix("/").split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise AssertionError(f"pointer traversed a scalar at {token}")
        return current

    for request in requests:
        for evidence in request.evidence:
            assert (
                resolve_pointer(documents[evidence.source_document], evidence.source_path)
                is not None
            )

    final = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=ready_result,
        requests=requests,
    )
    assert final.ready is True
    assert final.blocking_count == 0
    assert all(gate.result.value == "pass" for gate in final.gates)
    gate_names = {gate.name: gate.evidence for gate in final.gates}
    assert gate_names["immutableRuleVersion"] == (
        "Immutable rule version closes to source and catalog identity."
    )
    assert gate_names["oneRequestPerAtomicFact"] == (
        "One request per non-derived fact with closed identity."
    )
    assert gate_names["filtersComplete"] == "Filter sets are complete on every fact declaration."


def test_result_and_export_reject_broken_hash_and_parser_closure() -> None:
    from datetime import datetime

    from scripts.report_release_v3_confirmed_profile import _build_result

    from rule_reader.domain.rules.result_v3 import export_fact_binding_requests_v3

    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    result = _build_result(catalog, candidate, datetime(2026, 9, 6, tzinfo=UTC))
    result_payload = result.model_dump(mode="json", by_alias=True)
    result_payload["parser"]["parserVersion"] = "different-parser"
    with pytest.raises(ValidationError, match="source and parser provenance"):
        type(result).model_validate(result_payload)

    timestamp_mismatch = result.model_dump(mode="json", by_alias=True)
    timestamp_mismatch["generatedAt"] = "2026-09-07T00:00:00Z"
    with pytest.raises(ValidationError, match="timestamp"):
        type(result).model_validate(timestamp_mismatch)

    ready_result = result.model_copy(update={"agent2_readiness_ready": True})
    changed_candidate = candidate.model_copy(update={"title": "Changed candidate"})
    with pytest.raises(ValueError, match="payload hash"):
        export_fact_binding_requests_v3(ready_result, changed_candidate, catalog)

    changed_result_data = ready_result.model_dump(mode="json", by_alias=True)
    changed_result_data["factDeclarations"][0]["fact"]["parameters"][0]["description"] = (
        "Changed parameter semantics"
    )
    changed_result = type(result).model_validate(changed_result_data)
    with pytest.raises(ValueError, match="catalog semantics"):
        export_fact_binding_requests_v3(changed_result, candidate, catalog)


def test_confirmed_profile_parser_version_is_frozen() -> None:
    from datetime import datetime

    from scripts.report_release_v3_confirmed_profile import (
        CONFIRMED_PROFILE_PARSER_VERSION,
        _build_result,
    )

    catalog = _confirmed_catalog()
    candidate = _confirmed_candidate(catalog)
    result = _build_result(catalog, candidate, datetime(2026, 9, 6, tzinfo=UTC))
    # parser provenance 冻结为既有不可变产物使用的版本, 不随应用包版本升级。见 BUG-20260906-02。
    assert CONFIRMED_PROFILE_PARSER_VERSION == "0.11.0"
    assert result.source.parser_version == CONFIRMED_PROFILE_PARSER_VERSION
    assert result.parser.parser_version == CONFIRMED_PROFILE_PARSER_VERSION


def test_confirmed_profile_script_does_not_bind_app_version() -> None:
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "report_release_v3_confirmed_profile.py"
    )
    source = script.read_text(encoding="utf-8")
    assert "rule_reader.core.version" not in source
    assert "__version__" not in source
