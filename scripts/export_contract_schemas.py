"""Export checked-in contract Schema and deterministic compatibility examples."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel
from tests.support import valid_candidate_v2
from tests.v3_fixtures import (
    valid_fact_binding_request_v3,
    valid_fact_catalog_v3,
    valid_rule_parse_result_v3,
    valid_rule_structure_candidate_v3,
)

from rule_reader.domain.rules.bindings import build_fact_binding_requests_v1
from rule_reader.domain.rules.bindings_v2 import (
    build_fact_binding_requests_v2,
    fact_binding_request_schema_v2,
)
from rule_reader.domain.rules.bindings_v3 import fact_binding_request_schema_v3
from rule_reader.domain.rules.catalog_v3 import fact_catalog_schema_v3
from rule_reader.domain.rules.models import ParserMetadata, SourceMetadata
from rule_reader.domain.rules.result_v3 import rule_parse_result_schema_v3
from rule_reader.domain.rules.v2 import RuleCandidateV2, RuleParseResultV2
from rule_reader.domain.rules.v3 import rule_structure_candidate_schema_v3
from rule_reader.domain.rules.validation_v2 import enrich_candidate_v2, validate_candidate_v2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACT_BINDING_V2_PATH = PROJECT_ROOT / "contracts" / "fact-binding-request-2.0.0.schema.json"
FACT_BINDING_V3_PATH = PROJECT_ROOT / "contracts" / "fact-binding-request-3.0.0.schema.json"
RULE_RESULT_V3_PATH = PROJECT_ROOT / "contracts" / "rule-parse-result-3.0.0.schema.json"
FACT_CATALOG_V3_PATH = (
    PROJECT_ROOT / "contracts" / "business-confirmed-fact-catalog-3.0.0.schema.json"
)
RULE_STRUCTURE_V3_PATH = PROJECT_ROOT / "contracts" / "rule-structure-candidate-3.0.0.schema.json"
EXAMPLES_ROOT = PROJECT_ROOT / "contracts" / "examples"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(f"{rendered}\n", encoding="utf-8")


def _example_result() -> RuleParseResultV2:
    candidate = RuleCandidateV2.model_validate(deepcopy(valid_candidate_v2()))
    validate_candidate_v2(candidate)
    return RuleParseResultV2(
        rule_version="TEST_RELEASE_002@20260824T000000000000Z-000000000000",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
        parser=ParserMetadata(
            parser_version="0.6.0",
            prompt_version="rule-parser-v6",
            model="fake-deepseek",
        ),
        source=SourceMetadata(
            source_name="test-release-rule.md",
            relative_path="examples/test-release-rule.md",
            sha256="0" * 64,
            character_count=100,
        ),
        rule=enrich_candidate_v2(candidate),
    )


def _request_payload(request: BaseModel) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(request.model_dump_json(by_alias=True)))


def main() -> None:
    _write_json(FACT_BINDING_V2_PATH, fact_binding_request_schema_v2())
    _write_json(FACT_BINDING_V3_PATH, fact_binding_request_schema_v3())
    _write_json(RULE_RESULT_V3_PATH, rule_parse_result_schema_v3())
    _write_json(FACT_CATALOG_V3_PATH, fact_catalog_schema_v3())
    _write_json(RULE_STRUCTURE_V3_PATH, rule_structure_candidate_schema_v3())

    valid_catalog_v3 = valid_fact_catalog_v3()
    _write_json(
        EXAMPLES_ROOT / "business-confirmed-fact-catalog-3.0.0.valid.json",
        valid_catalog_v3,
    )
    invalid_catalog_v3 = deepcopy(valid_catalog_v3)
    del invalid_catalog_v3["catalogDigest"]
    _write_json(
        EXAMPLES_ROOT / "business-confirmed-fact-catalog-3.0.0.invalid-missing-digest.json",
        invalid_catalog_v3,
    )

    valid_structure_v3 = valid_rule_structure_candidate_v3()
    _write_json(
        EXAMPLES_ROOT / "rule-structure-candidate-3.0.0.valid.json",
        valid_structure_v3,
    )
    invalid_structure_v3 = deepcopy(valid_structure_v3)
    del invalid_structure_v3["defaultOutcome"]
    _write_json(
        EXAMPLES_ROOT / "rule-structure-candidate-3.0.0.invalid-missing-default.json",
        invalid_structure_v3,
    )

    valid_binding_v3 = valid_fact_binding_request_v3()
    _write_json(
        EXAMPLES_ROOT / "fact-binding-request-3.0.0.valid.json",
        valid_binding_v3,
    )
    invalid_binding_v3 = deepcopy(valid_binding_v3)
    del invalid_binding_v3["queryRequirements"]
    _write_json(
        EXAMPLES_ROOT / "fact-binding-request-3.0.0.invalid-missing-query.json",
        invalid_binding_v3,
    )

    valid_result_v3 = valid_rule_parse_result_v3()
    _write_json(EXAMPLES_ROOT / "rule-parse-result-3.0.0.valid.json", valid_result_v3)
    invalid_result_v3 = deepcopy(valid_result_v3)
    del invalid_result_v3["factDeclarations"]
    _write_json(
        EXAMPLES_ROOT / "rule-parse-result-3.0.0.invalid-missing-facts.json",
        invalid_result_v3,
    )

    result = _example_result()
    request_v2 = next(
        item
        for item in build_fact_binding_requests_v2(result)
        if item.fact.fact_code == "task.settlement_fee"
    )
    valid_v2 = _request_payload(request_v2)
    _write_json(
        EXAMPLES_ROOT / "fact-binding-request-2.0.0.valid-unresolved.json",
        valid_v2,
    )
    invalid_v2 = deepcopy(valid_v2)
    del invalid_v2["queryRequirements"]["timeRange"]
    _write_json(
        EXAMPLES_ROOT / "fact-binding-request-2.0.0.invalid-missing-time-range.json",
        invalid_v2,
    )

    request_v1 = next(
        item
        for item in build_fact_binding_requests_v1(result)
        if item.fact.fact_code == "task.settlement_fee"
    )
    _write_json(
        EXAMPLES_ROOT / "fact-binding-request-1.0.0.legacy.json",
        _request_payload(request_v1),
    )


if __name__ == "__main__":
    main()
