"""Explicit one-request V3 ruleStructure entry for externally supplied governed inputs."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

from rule_reader.application.rule_parsing.source_v3 import extract_rule_source_block_v3
from rule_reader.application.rule_parsing.workflow_v3 import RuleStructureParsingServiceV3
from rule_reader.core.config import Settings
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.infrastructure.deepseek import DeepSeekChatModel

RULE_SET_ID = "REPORT_RELEASE_ALL_001"


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(dict[str, Any], value)


async def _run(rule_text: str, catalog_payload: dict[str, Any]) -> dict[str, object]:
    block = extract_rule_source_block_v3(rule_text, rule_set_id=RULE_SET_ID)
    catalog = BusinessConfirmedFactCatalogV3.model_validate(catalog_payload)
    settings = Settings()
    model = DeepSeekChatModel(settings)
    service = RuleStructureParsingServiceV3(model, catalog, max_attempts=1)
    try:
        await service.start()
        result = await service.parse_rule_structure(block.text)
    finally:
        await service.close()
    return {
        "source": {"sha256": block.sha256, "characterCount": block.character_count},
        "candidate": result.candidate.model_dump(mode="json", by_alias=True),
        "audit": result.audit.model_dump(mode="json", by_alias=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-file", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--allow-provider", action="store_true")
    args = parser.parse_args()
    if not args.allow_provider:
        parser.error("--allow-provider is required; this command sends rule text to DeepSeek")
    rule_text = args.rule_file.read_text(encoding="utf-8")
    catalog_payload = _object(args.catalog)
    print(json.dumps(asyncio.run(_run(rule_text, catalog_payload)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
