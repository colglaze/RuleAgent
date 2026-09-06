"""Validate the private source bundle used by the ordered REPORT_RELEASE V3 profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from rule_reader.application.rule_parsing.source_v3 import (
    RuleSourceBlockV3,
    extract_delimited_rule_source_block_v3,
)

BUNDLE_ID = "PROJECT_RELEASE_REFERENCE_20260901_001"
BUNDLE_DIGEST = "6d403f1a110ea1699a72aec76f38be944583670f96767f5e3f44b2ac2e565160"
ORDERED_SOURCE_SHA256 = "c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f"
WORKBOOK_SHA256 = "872706f07792a618888a13d8944d7c59f454e5554388fa2dece511abebb30242"
RULE_BLOCK_SHA256 = "f285643e5b2bb2ec7b13861716407afda4252c2fbc81eb75a4b0bb3ba4b37c6d"
RULE_BLOCK_CHARACTERS = 1_402
RULE_SET_ID = "REPORT_RELEASE_ALL_001"
START_MARKER = "=== 项目报告释放前提条件 V2.0（规则评估前依次检查） ==="
END_MARKER = "=== 原始数据释放前提条件 V2.0（规则评估前依次检查） ==="


@dataclass(frozen=True, slots=True)
class OrderedReportReleaseReference:
    block: RuleSourceBlockV3
    workbook_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, Any]:
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("private bundle manifest must be one JSON object")
    return cast(dict[str, Any], payload)


def _source_path(root: Path, manifest: dict[str, Any], sha256: str) -> Path:
    entries = manifest.get("sourceFiles")
    if not isinstance(entries, list):
        raise ValueError("private bundle manifest has no sourceFiles")
    matches = [item for item in entries if isinstance(item, dict) and item.get("sha256") == sha256]
    if len(matches) != 1 or not isinstance(matches[0].get("repositoryPath"), str):
        raise ValueError(f"private bundle must contain exactly one source with SHA-256 {sha256}")
    path = (root / matches[0]["repositoryPath"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or _sha256(path) != sha256:
        raise ValueError("private source path or content does not match its manifest identity")
    return path


def load_ordered_report_release_reference(
    reference_root: Path,
) -> OrderedReportReleaseReference:
    root = reference_root.resolve()
    manifest = _manifest(root)
    if manifest.get("bundleId") != BUNDLE_ID:
        raise ValueError("unexpected private reference bundle ID")
    if manifest.get("contentDigestSha256") != BUNDLE_DIGEST:
        raise ValueError("unexpected private reference bundle digest")
    source = _source_path(root, manifest, ORDERED_SOURCE_SHA256)
    workbook_path = _source_path(root, manifest, WORKBOOK_SHA256)
    block = extract_delimited_rule_source_block_v3(
        source.read_text(encoding="utf-8"),
        rule_set_id=RULE_SET_ID,
        start_marker=START_MARKER,
        end_marker=END_MARKER,
    )
    if block.sha256 != RULE_BLOCK_SHA256 or block.character_count != RULE_BLOCK_CHARACTERS:
        raise ValueError("ordered REPORT_RELEASE rule block identity changed")
    return OrderedReportReleaseReference(block=block, workbook_path=workbook_path)


def load_ordered_report_release_block(reference_root: Path) -> RuleSourceBlockV3:
    return load_ordered_report_release_reference(reference_root).block


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    args = parser.parse_args()
    block = load_ordered_report_release_reference(args.reference_root).block
    print(
        json.dumps(
            {
                "status": "validated",
                "bundleId": BUNDLE_ID,
                "bundleDigest": BUNDLE_DIGEST,
                "workbookSha256": WORKBOOK_SHA256,
                "ruleSetId": block.rule_set_id,
                "ruleBlockSha256": block.sha256,
                "ruleBlockCharacters": block.character_count,
                "authority": "userConfirmedOrderedV3Source",
                "executable": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
