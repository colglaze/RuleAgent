"""Persist the confirmed REPORT_RELEASE V3 delivery into MongoDB Schema v5.

Reads and validates the confirmed offline artifacts from ``--artifact-dir`` (catalog,
candidate, result, requests, readiness report, and recovery manifest), re-runs every
write-ahead gate offline, and only then initializes MongoDB and calls the immutable
persistence service. Output is a sanitized summary: statuses, versions, hashes, counts,
and inserted/existing flags — never payloads, rule bodies, SQL, URIs, or credentials.

This command is explicit and user-authorized; it is not invoked by tests or CI.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rule_reader.application.v3_persistence.ports import (
    PersistedV3Delivery,
    V3PersistenceContractError,
    V3PersistenceError,
    V3PersistenceUnavailableError,
)
from rule_reader.application.v3_persistence.service import (
    V3PersistenceService,
    prepare_v3_delivery,
)
from rule_reader.core.config import Settings
from rule_reader.domain.rules.bindings_v3 import FactBindingRequestV3
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.readiness_v3 import Agent2ReadinessReportV3
from rule_reader.domain.rules.result_v3 import RuleParseResultV3
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.infrastructure.migrations import V3_PERSISTENCE_SCHEMA_VERSION
from rule_reader.infrastructure.mongodb import MongoManager, MongoStartupError
from rule_reader.infrastructure.v3_persistence import MongoV3PersistenceRepository

CATALOG_FILE = "business-confirmed-fact-catalog-3.0.0.json"
CANDIDATE_FILE = "rule-structure-candidate-3.0.0.json"
RESULT_FILE = "rule-parse-result-3.0.0.json"
REQUESTS_FILE = "fact-binding-requests-3.0.0.json"
READINESS_FILE = "v3-agent2-readiness-confirmed.json"
MANIFEST_FILE = "confirmed-recovery-manifest.json"

# The only delivery identity this script may persist (BIZ-20260906-02 revision). The
# manifest file hash is the trust anchor; offline tests may monkeypatch these module
# constants for synthetic deliveries, but production defaults are immutable.
APPROVED_DELIVERY_MANIFEST_SHA256 = (
    "0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4"
)
APPROVED_DELIVERY_RULE_VERSION = (
    "REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a"
)
APPROVED_DELIVERY_REQUEST_COUNT = 18
APPROVED_DELIVERY_TEST_CASE_COUNT = 20

_MANIFEST_HASH_KEYS = {
    CATALOG_FILE: "catalogFileSha256",
    CANDIDATE_FILE: "candidateFileSha256",
    RESULT_FILE: "resultFileSha256",
    REQUESTS_FILE: "requestsFileSha256",
    READINESS_FILE: "readinessFileSha256",
}


@dataclass(frozen=True, slots=True)
class V3DeliveryArtifacts:
    catalog: BusinessConfirmedFactCatalogV3
    candidate: RuleStructureCandidateV3
    result: RuleParseResultV3
    requests: tuple[FactBindingRequestV3, ...]
    readiness: Agent2ReadinessReportV3
    manifest: dict[str, Any]


def _read_json(artifact_dir: Path, name: str) -> Any:
    path = artifact_dir / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V3PersistenceError(f"Confirmed V3 artifact {name} could not be read") from error


def _assert_manifest_hashes(artifact_dir: Path, manifest: dict[str, Any]) -> None:
    for name, key in _MANIFEST_HASH_KEYS.items():
        recorded = manifest.get(key)
        if not isinstance(recorded, str):
            raise V3PersistenceError(f"Confirmed V3 manifest does not record a hash for {name}")
        try:
            actual = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest()
        except OSError as error:
            raise V3PersistenceError(f"Confirmed V3 artifact {name} could not be read") from error
        if actual != recorded:
            raise V3PersistenceError(
                f"Confirmed V3 artifact {name} does not match the manifest hash"
            )


def _assert_approved_manifest(artifact_dir: Path) -> None:
    """Anchor trust on the manifest file itself before its content is read."""

    try:
        manifest_sha256 = hashlib.sha256((artifact_dir / MANIFEST_FILE).read_bytes()).hexdigest()
    except OSError as error:
        raise V3PersistenceError(
            f"Confirmed V3 manifest {MANIFEST_FILE} could not be read"
        ) from error
    if manifest_sha256 != APPROVED_DELIVERY_MANIFEST_SHA256:
        raise V3PersistenceError(
            "Confirmed V3 manifest does not match the approved delivery identity"
        )


def load_and_validate_delivery(artifact_dir: Path) -> V3DeliveryArtifacts:
    """Load the confirmed artifacts and run every validation that needs no database."""

    _assert_approved_manifest(artifact_dir)
    try:
        catalog = BusinessConfirmedFactCatalogV3.model_validate(
            _read_json(artifact_dir, CATALOG_FILE)
        )
        candidate = RuleStructureCandidateV3.model_validate(
            _read_json(artifact_dir, CANDIDATE_FILE)
        )
        result = RuleParseResultV3.model_validate(_read_json(artifact_dir, RESULT_FILE))
        raw_requests = _read_json(artifact_dir, REQUESTS_FILE)
        readiness = Agent2ReadinessReportV3.model_validate(_read_json(artifact_dir, READINESS_FILE))
        manifest = _read_json(artifact_dir, MANIFEST_FILE)
    except V3PersistenceError:
        raise
    except Exception as error:
        raise V3PersistenceError(
            "Confirmed V3 artifacts failed to parse against the frozen contracts"
        ) from error
    if not isinstance(raw_requests, list) or not raw_requests:
        raise V3PersistenceError("Confirmed V3 requests artifact must be a non-empty JSON array")
    parsed_requests: list[FactBindingRequestV3] = []
    for index, item in enumerate(raw_requests):
        try:
            parsed_requests.append(FactBindingRequestV3.model_validate(item))
        except Exception as error:
            raise V3PersistenceContractError(
                f"Confirmed V3 request payload at index {index} failed to parse "
                "against the frozen contract"
            ) from error
    requests = tuple(parsed_requests)
    if not isinstance(manifest, dict):
        raise V3PersistenceError("Confirmed V3 manifest must be a JSON object")

    _assert_manifest_hashes(artifact_dir, manifest)
    if manifest.get("ruleVersion") != result.rule_version:
        raise V3PersistenceError("Manifest rule version does not match the result")
    if manifest.get("requestCount") != len(requests):
        raise V3PersistenceError("Manifest request count does not match the requests")
    if manifest.get("testCaseCount") != len(result.test_cases):
        raise V3PersistenceError("Manifest test case count does not match the result")
    if manifest.get("agent2ReadinessReady") is not True or not result.agent2_readiness_ready:
        raise V3PersistenceError("Confirmed V3 delivery is not marked ready for Agent 2 handoff")
    if result.rule_version != APPROVED_DELIVERY_RULE_VERSION:
        raise V3PersistenceError(
            "Confirmed V3 result rule version does not match the approved delivery identity"
        )
    if len(requests) != APPROVED_DELIVERY_REQUEST_COUNT:
        raise V3PersistenceError("Approved delivery request count does not match the requests")
    if len(result.test_cases) != APPROVED_DELIVERY_TEST_CASE_COUNT:
        raise V3PersistenceError("Approved delivery test case count does not match the result")
    if result.status != "draft" or result.executable is not False:
        raise V3PersistenceError("Approved delivery must remain a non-executable draft")
    if readiness.blocking_count != 0:
        raise V3PersistenceError("Approved delivery readiness must report zero blockers")
    if readiness.rule_set_id != result.rule_set_id:
        raise V3PersistenceError("Readiness report does not match the result rule set")
    if (
        not readiness.ready
        or len(readiness.gates) != 16
        or any(gate.result.value != "pass" for gate in readiness.gates)
    ):
        raise V3PersistenceError("Confirmed V3 readiness report is not 16/16 pass")

    # Re-run the full write-ahead closure offline so any artifact defect fails before
    # MongoDB is initialized. The service re-checks the same gates before writing.
    prepare_v3_delivery(catalog, candidate, result, requests)
    return V3DeliveryArtifacts(
        catalog=catalog,
        candidate=candidate,
        result=result,
        requests=requests,
        readiness=readiness,
        manifest=manifest,
    )


def delivery_summary(delivery: PersistedV3Delivery) -> dict[str, Any]:
    """Reduce the persistence result to a sanitized, payload-free summary."""

    if delivery.rule_inserted:
        status = "persistedAndVerified"
    elif delivery.batch_inserted:
        # The rule write was idempotent and the batch was completed on this retry.
        status = "recoveredAndVerified"
    else:
        status = "existingAndVerified"
    return {
        "status": status,
        "ruleVersion": delivery.rule_version,
        "requestCount": delivery.request_count,
        "rulePayloadSha256": delivery.rule_payload_sha256,
        "batchSha256": delivery.batch_sha256,
        "requestIds": list(delivery.request_ids),
        "ruleInserted": delivery.rule_inserted,
        "batchInserted": delivery.batch_inserted,
        "legacyCollectionCounts": dict(delivery.legacy_counts_after),
    }


async def _persist_with_service(
    delivery: V3DeliveryArtifacts,
    service: V3PersistenceService,
) -> dict[str, Any]:
    persisted = await service.persist(
        delivery.catalog,
        delivery.candidate,
        delivery.result,
        delivery.requests,
    )
    return delivery_summary(persisted)


async def _persist_via_mongodb(delivery: V3DeliveryArtifacts) -> dict[str, Any]:
    try:
        settings = Settings()
    except ValidationError as error:
        # 配置错误同样脱敏: cause 保留给内部测试, CLI 只输出固定安全消息。
        raise V3PersistenceUnavailableError("V3 persistence configuration is invalid") from error
    manager = MongoManager(settings)
    try:
        try:
            await manager.start()
            schema_version = await manager.initialize(target_version=V3_PERSISTENCE_SCHEMA_VERSION)
        except MongoStartupError as error:
            raise V3PersistenceUnavailableError(
                "MongoDB is unavailable; the confirmed V3 delivery was not written"
            ) from error
        repository = MongoV3PersistenceRepository(lambda: manager.database)
        service = V3PersistenceService(repository, repository, repository)
        summary = await _persist_with_service(delivery, service)
        summary["database"] = settings.mongodb_database
        summary["databaseSchemaVersion"] = schema_version
        return summary
    finally:
        await manager.close()


def run(
    artifact_dir: Path,
    *,
    service_factory: Callable[[], V3PersistenceService] | None = None,
) -> dict[str, Any]:
    """Validate the artifacts and persist them; injectable for offline tests only."""

    delivery = load_and_validate_delivery(artifact_dir)
    if service_factory is not None:
        return asyncio.run(_persist_with_service(delivery, service_factory()))
    return asyncio.run(_persist_via_mongodb(delivery))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help="Directory holding the confirmed V3 offline delivery artifacts",
    )
    args = parser.parse_args()
    try:
        summary = run(args.artifact_dir)
    except V3PersistenceError as error:
        sanitized = {
            "code": error.code,
            "message": str(error),
            "retryable": error.retryable,
            "details": [],
        }
        print(json.dumps(sanitized, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
