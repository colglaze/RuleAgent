"""Build offline 3.1.0 optimization-plan delivery packages.

Does not connect to MongoDB or call a model. Private source bytes stay on the caller
machine; this script writes JSON packages only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rule_reader.domain.optimization_plan import (
    OPTIMIZATION_PLAN_BUNDLE_COMMIT,
    OPTIMIZATION_PLAN_BUNDLE_DIGEST,
    OPTIMIZATION_PLAN_FILE_SHA256,
    OPTIMIZATION_PLAN_RELATIVE_PATH,
)
from rule_reader.domain.optimization_plan.extractor import build_source_identity
from rule_reader.domain.optimization_plan.profile import (
    OptimizationPlanDelivery,
    build_both_deliveries,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dump_delivery(directory: Path, delivery: OptimizationPlanDelivery) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    catalog = delivery.catalog.model_dump(mode="json", by_alias=True)
    candidate = delivery.candidate.model_dump(mode="json", by_alias=True)
    result = delivery.result.model_dump(mode="json", by_alias=True)
    requests = [item.model_dump(mode="json", by_alias=True) for item in delivery.requests]
    files = {
        "catalog.json": catalog,
        "candidate.json": candidate,
        "result.json": result,
        "requests.json": requests,
    }
    hashes: dict[str, str] = {}
    for name, payload in files.items():
        path = directory / name
        _write_json(path, payload)
        hashes[name] = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Private RuleDataReferences checkout root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the two complete delivery packages.",
    )
    args = parser.parse_args()
    source_path = args.source_root / OPTIMIZATION_PLAN_RELATIVE_PATH
    file_bytes = source_path.read_bytes()
    source_text = file_bytes.decode("utf-8")
    _extracted, identity = build_source_identity(
        file_bytes,
        source_text,
        expected_file_sha256=OPTIMIZATION_PLAN_FILE_SHA256,
    )
    report, data = build_both_deliveries(identity)
    report_hashes = _dump_delivery(args.output_dir / "report", report)
    data_hashes = _dump_delivery(args.output_dir / "data", data)
    summary = {
        "sourceFileSha256": identity.source_file_sha256,
        "parseInputSha256": identity.parse_input_sha256,
        "reportRuleVersion": report.result.rule_version,
        "dataRuleVersion": data.result.rule_version,
        "reportRequestCount": len(report.requests),
        "dataRequestCount": len(data.requests),
        "reportFiles": report_hashes,
        "dataFiles": data_hashes,
    }
    _write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
