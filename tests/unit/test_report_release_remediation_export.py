from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import export_reviewed_report_release_remediation as exporter


def test_remediation_export_is_validated_draft_without_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_text = "# local remediation source"
    source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
    monkeypatch.setattr(exporter, "SOURCE_SHA256", source_sha256)

    result, requests, audit = exporter.build_validated_export(
        source_text=source_text,
        source_name="项目报告释放规则.md",
        relative_path="项目报告释放规则.md",
        generated_at=datetime(2026, 8, 27, 1, 2, 3, 456789, tzinfo=UTC),
    )

    assert result.rule_version == (
        f"REPORT_RELEASE_ALL_001@20260827T010203456789Z-{source_sha256[:12]}"
    )
    assert result.status == "draft"
    assert result.executable is False
    assert result.parser.provider.value == "reviewed_import"
    assert result.parser.prompt_version == "reviewed-import-v2"
    assert audit["nonDerivedFacts"] == len(requests) == 34
    assert all(
        any(item.impact.value == "blocking" for item in request.uncertainties)
        for request in requests
    )

    output_dir = tmp_path / "validated-only"
    rule_path, bindings_path, rule_sha256, bindings_sha256 = exporter.export_files(
        output_dir=output_dir,
        result=result,
        requests=requests,
    )

    rule_payload = json.loads(rule_path.read_text(encoding="utf-8"))
    bindings_payload = json.loads(bindings_path.read_text(encoding="utf-8"))
    assert set(output_dir.iterdir()) == {rule_path, bindings_path}
    assert rule_payload["ruleVersion"] == result.rule_version
    assert rule_payload["status"] == "draft"
    assert rule_payload["executable"] is False
    assert bindings_payload["ruleVersion"] == result.rule_version
    assert len(bindings_payload["requests"]) == 34
    assert rule_sha256 == hashlib.sha256(rule_path.read_bytes()).hexdigest()
    assert bindings_sha256 == hashlib.sha256(bindings_path.read_bytes()).hexdigest()


def test_remediation_export_rejects_non_authorized_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exporter, "SOURCE_SHA256", "0" * 64)

    with pytest.raises(ValueError, match="authorized source identity"):
        exporter.build_validated_export(
            source_text="# different source",
            source_name="项目报告释放规则.md",
            relative_path="项目报告释放规则.md",
            generated_at=datetime(2026, 8, 27, tzinfo=UTC),
        )


def test_remediation_export_requires_timezone_aware_generated_at() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        exporter._generated_at("2026-08-27T01:02:03")
