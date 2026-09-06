"""Persist and verify the source-bound ordered REPORT_RELEASE V3 recovery candidate."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from scripts.report_release_v3_profile import build_profile
from scripts.validate_report_release_v3_reference import (
    BUNDLE_DIGEST,
    BUNDLE_ID,
    RULE_BLOCK_CHARACTERS,
    RULE_BLOCK_SHA256,
    WORKBOOK_SHA256,
)

from rule_reader.core.config import Settings
from rule_reader.domain.rules.recovery_v3 import (
    RecoverySourceV3,
    V3RecoveryPayload,
    recovery_candidate_id_v3,
)
from rule_reader.infrastructure.migrations import (
    FACT_BINDING_HANDOFFS_COLLECTION,
    RULE_VERSIONS_COLLECTION,
    V3_RECOVERIES_COLLECTION,
)
from rule_reader.infrastructure.mongodb import MongoManager
from rule_reader.infrastructure.v3_recovery import MongoV3RecoveryRepository


def build_recovery_payload(reference_root: Path) -> V3RecoveryPayload:
    catalog, candidate, _ = build_profile(reference_root)
    source = RecoverySourceV3(
        bundle_id=BUNDLE_ID,
        bundle_digest=BUNDLE_DIGEST,
        workbook_sha256=WORKBOOK_SHA256,
        rule_block_sha256=RULE_BLOCK_SHA256,
        rule_block_characters=RULE_BLOCK_CHARACTERS,
    )
    candidate_id = recovery_candidate_id_v3(
        candidate.rule_set_id, source.rule_block_sha256, catalog.catalog_digest
    )
    return V3RecoveryPayload(
        contract_version="3.0.0",
        candidate_id=candidate_id,
        status="validatedBlockedCandidate",
        executable=False,
        source=source,
        catalog=catalog,
        candidate=candidate,
    )


async def persist_recovery(payload: V3RecoveryPayload) -> dict[str, Any]:
    settings = Settings()
    manager = MongoManager(settings)
    try:
        await manager.start()
        schema_version = await manager.initialize()
        repository = MongoV3RecoveryRepository(lambda: manager.database)
        saved = await repository.save(payload)
        stored = await repository.get(payload.candidate_id)
        if stored is None or stored != saved.record or stored.payload != payload:
            raise RuntimeError("V3 recovery read-back verification failed")
        rules = [rule for stage in payload.candidate.stages for rule in stage.rules]
        rule_version_records = await manager.database[RULE_VERSIONS_COLLECTION].count_documents({})
        handoff_records = await manager.database[FACT_BINDING_HANDOFFS_COLLECTION].count_documents(
            {}
        )
        v3_records = await manager.database[V3_RECOVERIES_COLLECTION].count_documents({})
        return {
            "status": "persistedAndVerified",
            "database": settings.mongodb_database,
            "databaseSchemaVersion": schema_version,
            "collection": V3_RECOVERIES_COLLECTION,
            "candidateId": payload.candidate_id,
            "inserted": saved.inserted,
            "payloadSha256": stored.payload_sha256,
            "catalogDigest": payload.catalog.catalog_digest,
            "confirmedFacts": len(payload.catalog.facts),
            "rules": len(rules),
            "blockingRules": sum(rule.status.value == "blocked" for rule in rules),
            "executable": payload.executable,
            "ruleVersionRecords": rule_version_records,
            "factBindingHandoffRecords": handoff_records,
            "v3RecoveryRecords": v3_records,
        }
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    args = parser.parse_args()
    payload = build_recovery_payload(args.reference_root)
    print(json.dumps(asyncio.run(persist_recovery(payload)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
