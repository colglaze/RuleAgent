"""Load and persist Schema 3.1.0 complete-delivery packages from disk."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rule_reader.application.v3_persistence.ports import (
    V3PersistenceError,
    V3PersistenceUnavailableError,
)
from rule_reader.application.v31_persistence.ports import PersistedV31Delivery
from rule_reader.application.v31_persistence.service import (
    V31PersistenceService,
    prepare_v31_delivery,
)
from rule_reader.core.config import Settings
from rule_reader.domain.optimization_plan import OPTIMIZATION_PLAN_FILE_SHA256
from rule_reader.domain.rules.bindings_v31 import FactBindingRequestV31
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.purpose_v31 import HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION
from rule_reader.domain.rules.result_v31 import RuleParseResultV31
from rule_reader.domain.rules.v31 import RuleStructureCandidateV31
from rule_reader.infrastructure.migrations import OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION
from rule_reader.infrastructure.mongodb import MongoManager, MongoStartupError
from rule_reader.infrastructure.v31_persistence import MongoV31PersistenceRepository

APPROVED_SOURCE_FILE_SHA256 = OPTIMIZATION_PLAN_FILE_SHA256
FORBIDDEN_RULE_VERSION = HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def persist_summary(persisted: PersistedV31Delivery, result: RuleParseResultV31) -> dict[str, Any]:
    return {
        "batchInserted": persisted.batch_inserted,
        "batchSha256": persisted.batch_sha256,
        "candidatePayloadSha256": persisted.candidate_payload_sha256,
        "catalogDigest": result.catalog_ref.catalog_digest,
        "catalogPayloadSha256": persisted.catalog_payload_sha256,
        "consumable": persisted.consumable,
        "executable": result.executable,
        "legacyCountsAfter": persisted.legacy_counts_after,
        "legacyCountsBefore": persisted.legacy_counts_before,
        "missing": list(persisted.missing),
        "parseInputSha256": result.source.parse_input_sha256,
        "purpose": result.delivery_ref.purpose,
        "requestCount": persisted.request_count,
        "ruleInserted": persisted.rule_inserted,
        "rulePayloadSha256": persisted.rule_payload_sha256,
        "ruleVersion": persisted.rule_version,
        "schemaTarget": OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION,
        "schemaVersion": result.schema_version,
        "sourceFileSha256": result.source.source_sha256,
        "status": result.status,
    }


def load_v31_artifact_dir(
    artifact_dir: Path,
) -> tuple[
    BusinessConfirmedFactCatalogV3,
    RuleStructureCandidateV31,
    RuleParseResultV31,
    list[FactBindingRequestV31],
    dict[str, Any],
]:
    manifest = _read_json(artifact_dir / "manifest.json")
    catalog = BusinessConfirmedFactCatalogV3.model_validate(
        _read_json(artifact_dir / "catalog.json")
    )
    candidate = RuleStructureCandidateV31.model_validate(
        _read_json(artifact_dir / "candidate.json")
    )
    result = RuleParseResultV31.model_validate(_read_json(artifact_dir / "result.json"))
    requests = [
        FactBindingRequestV31.model_validate(item)
        for item in _read_json(artifact_dir / "requests.json")
    ]
    if result.rule_version == FORBIDDEN_RULE_VERSION:
        raise V3PersistenceError("Historical 2026-09-05 delivery cannot be persisted by this entry")
    if result.source.source_sha256 != APPROVED_SOURCE_FILE_SHA256:
        raise V3PersistenceError("Delivery source file hash is not the frozen optimization plan")
    for name, key in (
        ("catalog.json", "catalog.json"),
        ("candidate.json", "candidate.json"),
        ("result.json", "result.json"),
        ("requests.json", "requests.json"),
    ):
        recorded = manifest.get("fileSha256", {}).get(key)
        actual = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest()
        if recorded != actual:
            raise V3PersistenceError(f"Artifact {name} does not match the manifest hash")
    prepare_v31_delivery(catalog, candidate, result, requests)
    return catalog, candidate, result, requests, manifest


async def persist_v31_artifact_dir(
    artifact_dir: Path,
    service: V31PersistenceService,
) -> dict[str, Any]:
    catalog, candidate, result, requests, _manifest = load_v31_artifact_dir(artifact_dir)
    persisted = await service.persist(catalog, candidate, result, requests)
    return persist_summary(persisted, result)


async def persist_optimization_plan_output(
    output_dir: Path,
    service: V31PersistenceService,
) -> dict[str, Any]:
    report = await persist_v31_artifact_dir(output_dir / "report", service)
    data = await persist_v31_artifact_dir(output_dir / "data", service)
    return {"data": data, "report": report}


def mark_packages_persisted(output_dir: Path, persist: dict[str, Any]) -> dict[str, Any]:
    summary_path = output_dir / "summary.json"
    summary = _read_json(summary_path)
    summary["mongodbWritten"] = True
    summary["persist"] = persist
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


async def persist_optimization_plan_packages(
    output_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    manager = MongoManager(settings)
    try:
        try:
            await manager.start()
            await manager.initialize(target_version=OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION)
        except MongoStartupError as error:
            raise V3PersistenceUnavailableError(
                "Optimization-plan persistence is unavailable"
            ) from error
        repository = MongoV31PersistenceRepository(lambda: manager.database)
        service = V31PersistenceService(repository, repository, repository)
        persist = await persist_optimization_plan_output(output_dir, service)
    finally:
        await manager.close()
    return mark_packages_persisted(output_dir, persist)
