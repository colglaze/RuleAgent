"""Write Schema 3.1.0 complete-delivery packages without logging private source text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rule_reader.application.rule_parsing.workflow_v31 import OptimizationPlanAgentRun
from rule_reader.domain.optimization_plan import (
    OPTIMIZATION_PLAN_BUNDLE_COMMIT,
    OPTIMIZATION_PLAN_BUNDLE_DIGEST,
)
from rule_reader.domain.optimization_plan.profile import OptimizationPlanDelivery


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_complete_delivery(directory: Path, delivery: OptimizationPlanDelivery) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "catalog.json": delivery.catalog.model_dump(mode="json", by_alias=True),
        "candidate.json": delivery.candidate.model_dump(mode="json", by_alias=True),
        "result.json": delivery.result.model_dump(mode="json", by_alias=True),
        "requests.json": [item.model_dump(mode="json", by_alias=True) for item in delivery.requests],
    }
    hashes: dict[str, str] = {}
    for name, payload in files.items():
        path = directory / name
        _write_json(path, payload)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "kind": delivery.kind,
        "ruleSetId": delivery.result.rule_set_id,
        "ruleVersion": delivery.result.rule_version,
        "schemaVersion": "3.1.0",
        "purpose": "optimization-plan-generation",
        "executable": False,
        "status": "draft",
        "sourceFileSha256": delivery.result.source.source_sha256,
        "parseInputSha256": delivery.result.source.parse_input_sha256,
        "catalogDigest": delivery.catalog.catalog_digest,
        "candidatePayloadSha256": delivery.result.candidate_ref.payload_sha256,
        "catalogPayloadSha256": delivery.result.catalog_ref.payload_sha256,
        "requestCount": len(delivery.requests),
        "testCaseCount": len(delivery.result.test_cases),
        "fileSha256": hashes,
        "bundleCommit": OPTIMIZATION_PLAN_BUNDLE_COMMIT,
        "bundleDigest": OPTIMIZATION_PLAN_BUNDLE_DIGEST,
    }
    _write_json(directory / "manifest.json", manifest)
    return hashes


def write_optimization_plan_packages(
    output_dir: Path,
    run: OptimizationPlanAgentRun,
) -> dict[str, Any]:
    report_hashes = write_complete_delivery(output_dir / "report", run.report)
    data_hashes = write_complete_delivery(output_dir / "data", run.data)
    summary = {
        "sourceFileSha256": run.report.result.source.source_sha256,
        "parseInputSha256": run.report.result.source.parse_input_sha256,
        "reportRuleVersion": run.report.result.rule_version,
        "dataRuleVersion": run.data.result.rule_version,
        "reportRequestCount": len(run.report.requests),
        "dataRequestCount": len(run.data.requests),
        "reportFiles": report_hashes,
        "dataFiles": data_hashes,
        "provider": run.report.result.parser.provider,
        "model": run.report.result.parser.model,
        "promptVersion": run.report.result.parser.prompt_version,
        "auditOutcome": run.audit.attempts[0].outcome_code if run.audit.attempts else None,
        "mongodbWritten": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary
