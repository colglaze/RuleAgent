"""Persist one optimization-plan 3.1.0 complete delivery into MongoDB Schema v6.

Trust is anchored on the frozen optimization-plan file hash and the artifact
manifest hashes. This command is explicit; tests and CI do not invoke it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from rule_reader.application.v3_persistence.ports import V3PersistenceError
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
from rule_reader.infrastructure.mongodb import MongoManager
from rule_reader.infrastructure.v31_persistence import MongoV31PersistenceRepository

APPROVED_SOURCE_FILE_SHA256 = OPTIMIZATION_PLAN_FILE_SHA256
FORBIDDEN_RULE_VERSION = HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_delivery(
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


async def _persist(artifact_dir: Path) -> dict[str, Any]:
    catalog, candidate, result, requests, _manifest = load_delivery(artifact_dir)
    settings = Settings()
    manager = MongoManager(settings)
    try:
        await manager.start()
        await manager.initialize(target_version=OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION)
        repository = MongoV31PersistenceRepository(lambda: manager.database)
        service = V31PersistenceService(repository, repository, repository)
        persisted = await service.persist(catalog, candidate, result, requests)
    finally:
        await manager.close()
    return {
        "ruleVersion": persisted.rule_version,
        "consumable": persisted.consumable,
        "ruleInserted": persisted.rule_inserted,
        "batchInserted": persisted.batch_inserted,
        "requestCount": persisted.request_count,
        "missing": list(persisted.missing),
        "schemaTarget": OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = asyncio.run(_persist(args.artifact_dir))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
