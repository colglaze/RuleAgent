"""Persist one optimization-plan 3.1.0 complete delivery into MongoDB Schema v6.

Trust is anchored on the frozen optimization-plan file hash and the artifact
manifest hashes. This command is explicit; tests and CI do not invoke it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rule_reader.application.v31_persistence.packages import persist_v31_artifact_dir
from rule_reader.application.v31_persistence.service import V31PersistenceService
from rule_reader.core.config import Settings
from rule_reader.infrastructure.migrations import OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION
from rule_reader.infrastructure.mongodb import MongoManager
from rule_reader.infrastructure.v31_persistence import MongoV31PersistenceRepository


async def _persist(artifact_dir: Path) -> dict[str, object]:
    settings = Settings()
    manager = MongoManager(settings)
    try:
        await manager.start()
        await manager.initialize(target_version=OPTIMIZATION_PLAN_PERSISTENCE_SCHEMA_VERSION)
        repository = MongoV31PersistenceRepository(lambda: manager.database)
        service = V31PersistenceService(repository, repository, repository)
        return await persist_v31_artifact_dir(artifact_dir, service)
    finally:
        await manager.close()


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
