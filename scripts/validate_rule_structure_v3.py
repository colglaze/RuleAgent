"""Validate public V3 contracts and optionally identify an external rule source block."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from rule_reader.application.rule_parsing.source_v3 import extract_rule_source_block_v3
from rule_reader.domain.rules.catalog_v3 import (
    BusinessConfirmedFactCatalogV3,
    validate_fact_catalog_v3,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3
from rule_reader.domain.rules.validation_v3 import validate_rule_structure_candidate_v3


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(dict[str, Any], value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--rule-file", type=Path)
    parser.add_argument("--rule-set-id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    catalog = BusinessConfirmedFactCatalogV3.model_validate(_object(args.catalog))
    candidate = RuleStructureCandidateV3.model_validate(_object(args.candidate))
    validate_fact_catalog_v3(catalog)
    validate_rule_structure_candidate_v3(candidate, catalog)
    result: dict[str, object] = {
        "status": "valid",
        "ruleSetId": candidate.rule_set_id,
        "catalogDigest": catalog.catalog_digest,
        "rules": sum(len(stage.rules) for stage in candidate.stages),
        "blockingIssues": len(candidate.blocking_issues),
    }
    if (args.rule_file is None) != (args.rule_set_id is None):
        raise ValueError("--rule-file and --rule-set-id must be provided together")
    if args.rule_file is not None:
        block = extract_rule_source_block_v3(
            args.rule_file.read_text(encoding="utf-8"), rule_set_id=args.rule_set_id
        )
        result["source"] = {
            "sha256": block.sha256,
            "characterCount": block.character_count,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
