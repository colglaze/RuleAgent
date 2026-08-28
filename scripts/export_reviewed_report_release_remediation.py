"""Validate and locally export the remediated REPORT_RELEASE_ALL_001 draft.

This command deliberately has no persistence option and imports no application settings,
model provider, MongoDB adapter, or network client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from scripts.reviewed_report_release_all_001_remediation import (
    AUTHORING_MODEL,
    REVIEWED_IMPORT_VERSION,
    RULE_ID,
    SOURCE_SHA256,
    audit_candidate,
    build_candidate_payload,
)

from rule_reader.application.rule_parsing.reviewed_import import build_reviewed_rule_result
from rule_reader.domain.rules.bindings_v2 import (
    FactBindingRequestV2,
    build_fact_binding_requests_v2,
    fact_binding_request_schema_v2,
)
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import validate_safe_structured_payload
from rule_reader.infrastructure.documents import LocalDocumentReader

MAX_SOURCE_CHARACTERS = 100_000


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and locally export the unpersisted REPORT_RELEASE_ALL_001 "
            "business-review remediation draft."
        )
    )
    parser.add_argument("--document-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--generated-at",
        required=True,
        help="Fixed timezone-aware ISO timestamp used for reproducible local export.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _generated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include an explicit timezone")
    return parsed


def _validate_requests(requests: list[FactBindingRequestV2]) -> None:
    schema = fact_binding_request_schema_v2()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for request in requests:
        payload = request.model_dump(by_alias=True, mode="json")
        FactBindingRequestV2.model_validate(payload)
        validator.validate(payload)
        validate_safe_structured_payload(payload)
        if not any(item.impact.value == "blocking" for item in request.uncertainties):
            raise ValueError(f"request {request.request_id} must remain blocking")


def build_validated_export(
    *,
    source_text: str,
    source_name: str,
    relative_path: str | None,
    generated_at: datetime,
) -> tuple[RuleParseResultV2, list[FactBindingRequestV2], dict[str, int]]:
    candidate = RuleCandidateV2.model_validate(build_candidate_payload())
    audit = audit_candidate(candidate)
    result = build_reviewed_rule_result(
        candidate,
        source_text=source_text,
        source_name=source_name,
        relative_path=relative_path,
        authoring_model=AUTHORING_MODEL,
        max_characters=MAX_SOURCE_CHARACTERS,
        reviewed_import_version=REVIEWED_IMPORT_VERSION,
        clock=lambda: generated_at,
    )
    if result.rule.rule_id != RULE_ID or result.source.sha256 != SOURCE_SHA256:
        raise ValueError("remediation profile does not match the authorized source identity")
    validate_safe_structured_payload(result.model_dump(by_alias=True, mode="json"))
    requests = build_fact_binding_requests_v2(result)
    if len(requests) != audit["nonDerivedFacts"]:
        raise ValueError("fact request count does not match non-derived fact count")
    _validate_requests(requests)
    return result, requests, audit


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_files(
    *,
    output_dir: Path,
    result: RuleParseResultV2,
    requests: list[FactBindingRequestV2],
) -> tuple[Path, Path, str, str]:
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
    return rule_path, bindings_path, _sha256(rule_path), _sha256(bindings_path)


def main() -> None:
    args = _arguments()
    document = LocalDocumentReader(
        args.document_root,
        max_characters=MAX_SOURCE_CHARACTERS,
    ).read(args.source)
    result, requests, audit = build_validated_export(
        source_text=document.text,
        source_name=document.source_name,
        relative_path=document.relative_path,
        generated_at=_generated_at(args.generated_at),
    )
    rule_path, bindings_path, rule_sha256, bindings_sha256 = export_files(
        output_dir=args.output_dir,
        result=result,
        requests=requests,
    )
    print(
        json.dumps(
            {
                "status": "validated_not_persisted",
                "ruleVersion": result.rule_version,
                "schemaVersion": result.schema_version,
                "sourceSha256": result.source.sha256,
                "parserProvider": result.parser.provider.value,
                "reviewedImportVersion": result.parser.prompt_version,
                "authoringModel": result.parser.model,
                "audit": audit,
                "factBindingRequests": len(requests),
                "blockingRequests": sum(
                    any(item.impact.value == "blocking" for item in request.uncertainties)
                    for request in requests
                ),
                "ruleArtifact": str(rule_path.resolve()),
                "ruleArtifactSha256": rule_sha256,
                "bindingsArtifact": str(bindings_path.resolve()),
                "bindingsArtifactSha256": bindings_sha256,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
