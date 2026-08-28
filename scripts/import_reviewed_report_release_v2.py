"""Validate, persist, read back, and export the reviewed REPORT_RELEASE_ALL_001 rule."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from scripts.reviewed_report_release_all_001 import (
    AUTHORING_MODEL,
    RULE_ID,
    SOURCE_SHA256,
    audit_candidate,
    build_candidate_payload,
)

from rule_reader.application.rule_parsing.reviewed_import import build_reviewed_rule_result
from rule_reader.core.config import Settings
from rule_reader.domain.rules.bindings_v2 import (
    FactBindingRequestV2,
    build_fact_binding_requests_v2,
    fact_binding_request_schema_v2,
)
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import validate_safe_structured_payload
from rule_reader.infrastructure.documents import LocalDocumentReader
from rule_reader.infrastructure.mongodb import MongoManager
from rule_reader.infrastructure.rule_versions import MongoRuleVersionRepository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import the explicitly reviewed REPORT_RELEASE_ALL_001 Schema 2.0 draft."
    )
    parser.add_argument("--document-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--generated-at",
        required=True,
        help="Fixed timezone-aware ISO timestamp used for idempotent replay.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Write the fully validated immutable draft to the configured MongoDB.",
    )
    return parser.parse_args()


def _generated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include an explicit timezone")
    return parsed


def _validate_requests(
    requests: list[FactBindingRequestV2],
) -> None:
    validator = Draft202012Validator(
        fact_binding_request_schema_v2(),
        format_checker=FormatChecker(),
    )
    for request in requests:
        payload = request.model_dump(by_alias=True, mode="json")
        validator.validate(payload)
        validate_safe_structured_payload(payload)


async def _persist_and_read_back(
    settings: Settings,
    result: RuleParseResultV2,
) -> tuple[RuleParseResultV2, bool, str]:
    manager = MongoManager(settings)
    try:
        await manager.start()
        await manager.initialize()
        repository = MongoRuleVersionRepository(lambda: manager.database)
        saved = await repository.save(result)
        stored = await repository.get(result.rule_version)
        if stored is None:
            raise RuntimeError("persisted rule could not be read back")
        if not isinstance(stored.document, RuleParseResultV2):
            raise RuntimeError("read-back rule is not Schema 2.0.0")
        if stored.document != result:
            raise RuntimeError("read-back rule does not exactly match the validated draft")
        return stored.document, saved.inserted, stored.stored_at.isoformat()
    finally:
        await manager.close()


def _export(
    output_dir: Path,
    result: RuleParseResultV2,
    requests: list[FactBindingRequestV2],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rule_path = output_dir / f"{result.rule_version}.rule.json"
    bindings_path = output_dir / f"{result.rule_version}.fact-binding-requests.json"
    rule_path.write_text(result.to_json(indent=2) + "\n", encoding="utf-8")
    bindings_path.write_text(
        json.dumps(
            {
                "ruleVersion": result.rule_version,
                "requests": [
                    request.model_dump(by_alias=True, mode="json") for request in requests
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return rule_path.resolve(), bindings_path.resolve()


def main() -> None:
    args = _arguments()
    settings = Settings()
    reader = LocalDocumentReader(
        args.document_root,
        max_characters=settings.rule_max_characters,
    )
    document = reader.read(args.source)
    candidate = RuleCandidateV2.model_validate(build_candidate_payload())
    audit = audit_candidate(candidate)
    generated_at = _generated_at(args.generated_at)
    result = build_reviewed_rule_result(
        candidate,
        source_text=document.text,
        source_name=document.source_name,
        relative_path=document.relative_path,
        authoring_model=AUTHORING_MODEL,
        max_characters=settings.rule_max_characters,
        clock=lambda: generated_at,
    )
    if result.rule.rule_id != RULE_ID or result.source.sha256 != SOURCE_SHA256:
        raise RuntimeError("reviewed profile does not match the authorized source identity")
    validate_safe_structured_payload(result.model_dump(by_alias=True, mode="json"))
    requests = build_fact_binding_requests_v2(result)
    if len(requests) != audit["nonDerivedFacts"]:
        raise RuntimeError("fact request count does not match non-derived fact count")
    _validate_requests(requests)

    if not args.persist:
        print(
            json.dumps(
                {
                    "status": "validated_not_persisted",
                    "ruleVersion": result.rule_version,
                    "audit": audit,
                    "factBindingRequests": len(requests),
                },
                ensure_ascii=False,
            )
        )
        return

    stored, inserted, stored_at = asyncio.run(_persist_and_read_back(settings, result))
    stored_requests = build_fact_binding_requests_v2(stored)
    _validate_requests(stored_requests)
    if stored_requests != requests:
        raise RuntimeError("read-back fact requests differ from pre-persistence export")
    rule_path, bindings_path = _export(args.output_dir, stored, stored_requests)
    blocking_requests = sum(
        any(item.impact.value == "blocking" for item in request.uncertainties)
        for request in stored_requests
    )
    print(
        json.dumps(
            {
                "status": "persisted_and_verified",
                "inserted": inserted,
                "storedAt": stored_at,
                "ruleVersion": stored.rule_version,
                "schemaVersion": stored.schema_version,
                "sourceSha256": stored.source.sha256,
                "parserProvider": stored.parser.provider.value,
                "authoringModel": stored.parser.model,
                "audit": audit,
                "factBindingRequests": len(stored_requests),
                "blockingRequests": blocking_requests,
                "ruleArtifact": str(rule_path),
                "bindingsArtifact": str(bindings_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
