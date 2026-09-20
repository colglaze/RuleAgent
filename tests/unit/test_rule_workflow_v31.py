"""Agent1 LangGraph generation of Schema 3.1.0 optimization-plan deliveries."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.optimization_plan_support import (
    SYNTHETIC_OPTIMIZATION_PLAN,
    synthetic_source_identity,
)

from rule_reader.application.rule_parsing.workflow_v31 import OptimizationPlanParsingService
from rule_reader.cli import _parser, run
from rule_reader.domain.optimization_plan.extractor import hash_file_bytes
from rule_reader.domain.optimization_plan.profile import build_both_deliveries
from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError
from rule_reader.domain.rules.result_v31 import (
    candidate_payload_sha256_v31,
    catalog_payload_sha256_v31,
)
from rule_reader.infrastructure.optimization_plan_artifacts import (
    write_optimization_plan_packages,
)
from rule_reader.infrastructure.optimization_plan_source import read_optimization_plan_source


def _workflow_source() -> str:
    return Path("src/rule_reader/application/rule_parsing/workflow_v31.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_agent1_matches_domain_builder_for_synthetic_identity() -> None:
    identity = synthetic_source_identity()
    expected_report, expected_data = build_both_deliveries(identity)
    service = OptimizationPlanParsingService()
    run_result = await service.generate(identity)

    assert run_result.audit.attempt_count == 1
    assert run_result.audit.attempts[0].outcome_code == "SUCCESS"
    assert run_result.audit.total_token_usage is None
    for actual, expected in (
        (run_result.report, expected_report),
        (run_result.data, expected_data),
    ):
        assert actual.result.rule_version == expected.result.rule_version
        assert actual.catalog.catalog_digest == expected.catalog.catalog_digest
        assert len(actual.requests) == len(expected.requests)
        assert catalog_payload_sha256_v31(actual.catalog) == catalog_payload_sha256_v31(
            expected.catalog
        )
        assert candidate_payload_sha256_v31(actual.candidate) == candidate_payload_sha256_v31(
            expected.candidate
        )
        assert actual.result.status == "draft"
        assert actual.result.executable is False
        assert actual.result.delivery_ref.purpose == "optimization-plan-generation"
        assert actual.result.parser.provider == "reviewed_import"


@pytest.mark.asyncio
async def test_agent1_rejects_wrong_extractor_version() -> None:
    identity = synthetic_source_identity().model_copy(update={"extractor_version": "other-v1"})
    with pytest.raises(RuleParsingError) as caught:
        await OptimizationPlanParsingService().generate(identity)
    assert caught.value.issue.code is ParseErrorCode.CANDIDATE_SEMANTIC_INVALID
    assert caught.value.issue.audit is not None
    assert caught.value.issue.audit.attempts[0].outcome_code == "CANDIDATE_SEMANTIC_INVALID"


@pytest.mark.asyncio
async def test_agent1_rejects_frozen_hash_mismatch_on_source_bytes() -> None:
    payload = SYNTHETIC_OPTIMIZATION_PLAN.encode("utf-8")
    with pytest.raises(RuleParsingError) as caught:
        await OptimizationPlanParsingService().generate_from_source_bytes(
            payload, SYNTHETIC_OPTIMIZATION_PLAN
        )
    assert caught.value.issue.code is ParseErrorCode.CANDIDATE_SEMANTIC_INVALID


@pytest.mark.asyncio
async def test_agent1_generates_from_matching_source_bytes() -> None:
    payload = SYNTHETIC_OPTIMIZATION_PLAN.encode("utf-8")
    run_result = await OptimizationPlanParsingService().generate_from_source_bytes(
        payload,
        SYNTHETIC_OPTIMIZATION_PLAN,
        expected_file_sha256=hash_file_bytes(payload),
    )
    assert run_result.report.result.rule_set_id == "REPORT_RELEASE_ALL_001"
    assert run_result.data.result.rule_set_id == "RAW_DATA_RELEASE_ALL_001"
    assert run_result.report.catalog.catalog_digest != run_result.data.catalog.catalog_digest


@pytest.mark.asyncio
async def test_artifact_writer_emits_both_packages(tmp_path: Path) -> None:
    identity = synthetic_source_identity()
    run_result = await OptimizationPlanParsingService().generate(identity)
    summary = write_optimization_plan_packages(tmp_path, run_result)
    assert summary["mongodbWritten"] is False
    assert (tmp_path / "report" / "manifest.json").is_file()
    assert (tmp_path / "data" / "requests.json").is_file()
    assert summary["reportRequestCount"] == len(run_result.report.requests)
    assert summary["dataRequestCount"] == len(run_result.data.requests)


def test_source_reader_rejects_missing_plan(tmp_path: Path) -> None:
    with pytest.raises(RuleParsingError) as caught:
        read_optimization_plan_source(tmp_path)
    assert caught.value.issue.code is ParseErrorCode.DOCUMENT_NOT_FOUND


def test_workflow_module_does_not_import_deepseek() -> None:
    source = _workflow_source().lower()
    assert "deepseek" not in source
    assert "rulecandidatemodel" not in source
    assert "generate_candidate" not in source


def test_cli_exposes_parse_optimization_plan() -> None:
    args = _parser().parse_args(
        [
            "parse-optimization-plan",
            "--source-root",
            "D:/private/RuleDataReferences",
            "--output-dir",
            "generated-rules/out",
        ]
    )
    assert args.command == "parse-optimization-plan"
    assert args.source_root == Path("D:/private/RuleDataReferences")
    assert args.persist is False


def test_cli_parse_optimization_plan_persist_flag_is_opt_in() -> None:
    args = _parser().parse_args(
        [
            "parse-optimization-plan",
            "--source-root",
            "D:/private/RuleDataReferences",
            "--output-dir",
            "generated-rules/out",
            "--persist",
        ]
    )
    assert args.persist is True


def test_cli_parse_optimization_plan_missing_source_returns_error(tmp_path: Path) -> None:
    output = tmp_path / "out"
    code = run(
        [
            "parse-optimization-plan",
            "--source-root",
            str(tmp_path),
            "--output-dir",
            str(output),
        ]
    )
    assert code == 1
    assert not output.exists()
