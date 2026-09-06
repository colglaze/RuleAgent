"""Generate non-sensitive offline V2/V3 compatibility and Agent 2 readiness reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.report_release_v3_profile import build_profile, validate_output_location
from scripts.reviewed_report_release_all_001_remediation import SOURCE_SHA256 as V2_SOURCE_SHA256
from scripts.validate_report_release_v3_reference import RULE_BLOCK_SHA256

from rule_reader.domain.rules.readiness_v3 import (
    Agent2ReadinessReportV3,
    assess_v2_compatibility_v3,
    build_agent2_readiness_report_v3,
)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _confirmation_markdown(report: Agent2ReadinessReportV3) -> str:
    lines = [
        "# V3 Agent 2 业务确认清单",
        "",
        "该清单不包含私有规则正文、物理字段或 SQL。所有项目均阻止 Agent 2 交接。",
        "",
        "| Issue | 阶段 | 规则 | 缺少的逻辑事实 | 需确认内容 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for gap in report.gaps:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{gap.issue_id} / {gap.issue_code}",
                    ", ".join(gap.stages),
                    ", ".join(gap.rule_codes),
                    ", ".join(gap.missing_fact_codes) or "来源冲突，无新增事实",
                    "确认类型、粒度、参数、值域、空值及完整查询语义；冲突来源需显式裁决。",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "确定性代码不会删除、降级或补造上述问题。确认后必须生成新的 catalog/candidate digest。",
        ]
    )
    return "\n".join(lines) + "\n"


def _persistence_plan(report: Agent2ReadinessReportV3) -> dict[str, Any]:
    return {
        "status": "blockedPlanOnly",
        "selectedPath": "B",
        "writesAuthorized": False,
        "plannedNow": {"ruleVersions": 0, "handoffs": 0},
        "futureWhenReady": {
            "ruleVersions": 1,
            "handoffs": "one per non-derived required fact",
            "ruleVersion": ("<ruleSetId>@<UTC timestamp>-<sourceSha256[:12]>-<catalogDigest[:12]>"),
            "sourceSha256": RULE_BLOCK_SHA256,
            "ruleSchemaVersion": "3.0.0",
            "handoffContractVersion": "3.0.0",
            "canonicalHash": (
                "UTF-8 sorted-key compact camelCase JSON; Unicode preserved; NaN forbidden"
            ),
            "migration": "planned Schema v5",
            "collections": ["rule_versions_v3", "fact_binding_handoff_batches_v3"],
            "indexes": [
                "unique ruleVersion",
                "unique source/catalog identity",
                "unique batch ruleVersion",
            ],
            "batchAtomicity": (
                "one immutable batch document contains every validated request wrapper"
            ),
            "idempotentReplay": "same identity and batch hash returns the original record",
            "conflict": "same identity with different hash fails without overwrite",
            "readBack": "revalidate rule, every request, identity closure, counts, and hashes",
            "prePostCounts": (
                "read-only counts captured immediately before and after a future authorized write"
            ),
            "v3CandidateProtection": (
                "rule_structure_candidates_v3 is read-only input and is never updated"
            ),
        },
        "readinessGateResults": [
            gate.model_dump(mode="json", by_alias=True) for gate in report.gates
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_output_location(args.reference_root, args.output_dir)
    catalog, candidate, _ = build_profile(args.reference_root)
    compatibility = assess_v2_compatibility_v3(
        v2_source_sha256=V2_SOURCE_SHA256,
        v3_source_sha256=RULE_BLOCK_SHA256,
    )
    readiness = build_agent2_readiness_report_v3(candidate, catalog)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        args.output_dir / "v2-v3-compatibility.json",
        compatibility.model_dump(mode="json", by_alias=True),
    )
    _write_json(
        args.output_dir / "v3-agent2-readiness.json",
        readiness.model_dump(mode="json", by_alias=True),
    )
    _write_json(args.output_dir / "mongodb-persistence-plan.json", _persistence_plan(readiness))
    (args.output_dir / "business-confirmation-checklist.md").write_text(
        _confirmation_markdown(readiness), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "selectedPath": compatibility.selected_path,
                "ready": readiness.ready,
                "blockingCount": readiness.blocking_count,
                "plannedRuleVersions": readiness.planned_rule_versions,
                "plannedHandoffs": readiness.planned_handoffs,
                "requiresSqlBotContractUpgrade": readiness.requires_sqlbot_contract_upgrade,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
