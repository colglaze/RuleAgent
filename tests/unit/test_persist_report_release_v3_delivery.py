"""Offline tests for the explicit V3 delivery persistence script."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from scripts import persist_report_release_v3_delivery as script
from scripts.persist_report_release_v3_delivery import (
    CANDIDATE_FILE,
    CATALOG_FILE,
    MANIFEST_FILE,
    READINESS_FILE,
    REQUESTS_FILE,
    RESULT_FILE,
    delivery_summary,
    run,
)
from tests.v3_delivery_fixtures import synthetic_ready_delivery_v3

from rule_reader.application.v3_persistence.ports import (
    PersistedV3Delivery,
    V3PersistenceError,
)

LEGACY_COUNTS = {
    "rule_versions": 2,
    "fact_binding_handoffs": 33,
    "rule_structure_candidates_v3": 1,
}


@dataclass
class FakeV3PersistenceService:
    calls: list[tuple[Any, Any, Any, Any]] = field(default_factory=list)

    async def persist(
        self,
        catalog: Any,
        candidate: Any,
        result: Any,
        requests: Any,
    ) -> PersistedV3Delivery:
        self.calls.append((catalog, candidate, result, tuple(requests)))
        return PersistedV3Delivery(
            rule_version=result.rule_version,
            rule_inserted=True,
            batch_inserted=True,
            request_count=len(requests),
            rule_payload_sha256="a" * 64,
            batch_sha256="b" * 64,
            request_ids=tuple(sorted(request.request_id for request in requests)),
            legacy_counts_before=dict(LEGACY_COUNTS),
            legacy_counts_after=dict(LEGACY_COUNTS),
        )


class FailingMongoManager:
    """Stands in for MongoManager and simulates an unavailable database."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.closed = 0

    async def start(self) -> None:
        from rule_reader.infrastructure.mongodb import MongoStartupError

        raise MongoStartupError("MongoDB is unavailable; check the configured container")

    async def close(self) -> None:
        self.closed += 1


def _write_delivery(artifact_dir: Path) -> dict[str, Any]:
    catalog, candidate, result, requests = synthetic_ready_delivery_v3()
    from rule_reader.domain.rules.readiness_v3 import build_agent2_readiness_report_v3

    readiness = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=result,
        requests=list(requests),
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / CATALOG_FILE).write_text(
        catalog.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    (artifact_dir / CANDIDATE_FILE).write_text(
        candidate.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    (artifact_dir / RESULT_FILE).write_text(
        result.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    (artifact_dir / REQUESTS_FILE).write_text(
        json.dumps(
            [request.model_dump(mode="json", by_alias=True) for request in requests],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / READINESS_FILE).write_text(
        json.dumps(readiness.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    manifest: dict[str, Any] = {
        "ruleVersion": result.rule_version,
        "requestCount": len(requests),
        "testCaseCount": len(result.test_cases),
        "agent2ReadinessReady": readiness.ready,
    }
    manifest_hash_keys = {
        CATALOG_FILE: "catalogFileSha256",
        CANDIDATE_FILE: "candidateFileSha256",
        RESULT_FILE: "resultFileSha256",
        REQUESTS_FILE: "requestsFileSha256",
        READINESS_FILE: "readinessFileSha256",
    }
    for name, key in manifest_hash_keys.items():
        manifest[key] = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest()
    (artifact_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_sha256 = hashlib.sha256((artifact_dir / MANIFEST_FILE).read_bytes()).hexdigest()
    return {
        "ruleVersion": result.rule_version,
        "requestCount": len(requests),
        "testCaseCount": len(result.test_cases),
        "manifestSha256": manifest_sha256,
    }


def _patch_approved_identity(monkeypatch: pytest.MonkeyPatch, identity: dict[str, Any]) -> None:
    monkeypatch.setattr(script, "APPROVED_DELIVERY_MANIFEST_SHA256", identity["manifestSha256"])
    monkeypatch.setattr(script, "APPROVED_DELIVERY_RULE_VERSION", identity["ruleVersion"])
    monkeypatch.setattr(script, "APPROVED_DELIVERY_REQUEST_COUNT", identity["requestCount"])
    monkeypatch.setattr(script, "APPROVED_DELIVERY_TEST_CASE_COUNT", identity["testCaseCount"])


def test_production_defaults_pin_the_approved_delivery_identity() -> None:
    assert script.APPROVED_DELIVERY_MANIFEST_SHA256 == (
        "0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4"
    )
    assert script.APPROVED_DELIVERY_RULE_VERSION == (
        "REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a"
    )
    assert script.APPROVED_DELIVERY_REQUEST_COUNT == 18
    assert script.APPROVED_DELIVERY_TEST_CASE_COUNT == 20


def test_script_rejects_artifacts_outside_approved_identity(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "confirmed"
    _write_delivery(artifact_dir)
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="approved"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_script_rejects_rule_version_outside_approved_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    monkeypatch.setattr(script, "APPROVED_DELIVERY_RULE_VERSION", "OTHER@000000000000Z")
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="rule version"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_script_rejects_request_count_outside_approved_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    monkeypatch.setattr(script, "APPROVED_DELIVERY_REQUEST_COUNT", 99)
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="request count"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_script_persists_valid_artifacts_with_sanitized_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    service = FakeV3PersistenceService()

    summary = run(artifact_dir, service_factory=lambda: service)

    assert len(service.calls) == 1
    _catalog, _candidate, result, requests = service.calls[0]
    assert result.rule_version == identity["ruleVersion"]
    assert len(requests) == identity["requestCount"]

    assert summary["status"] == "persistedAndVerified"
    assert summary["ruleVersion"] == identity["ruleVersion"]
    assert summary["requestCount"] == identity["requestCount"]
    assert summary["rulePayloadSha256"] == "a" * 64
    assert summary["batchSha256"] == "b" * 64
    assert summary["requestIds"] == sorted(request.request_id for request in requests)
    assert summary["ruleInserted"] is True
    assert summary["batchInserted"] is True
    assert summary["legacyCollectionCounts"] == LEGACY_COUNTS
    # 摘要不得携带 payload、规则正文或结构化载荷字段。
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "queryRequirements" not in serialized
    assert "factDeclarations" not in serialized
    assert "evidenceIds" not in serialized


def test_script_rejects_manifest_hash_mismatch_before_any_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    catalog_path = artifact_dir / CATALOG_FILE
    catalog_path.write_text(
        catalog_path.read_text(encoding="utf-8").replace("SYNTHETIC", "TAMPERED"),
        encoding="utf-8",
    )
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="manifest hash"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_script_rejects_not_ready_readiness_before_any_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    readiness = json.loads((artifact_dir / READINESS_FILE).read_text(encoding="utf-8"))
    readiness["ready"] = False
    (artifact_dir / READINESS_FILE).write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = json.loads((artifact_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["readinessFileSha256"] = hashlib.sha256(
        (artifact_dir / READINESS_FILE).read_bytes()
    ).hexdigest()
    (artifact_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identity["manifestSha256"] = hashlib.sha256(
        (artifact_dir / MANIFEST_FILE).read_bytes()
    ).hexdigest()
    _patch_approved_identity(monkeypatch, identity)
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="16/16"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_script_rejects_empty_requests_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    (artifact_dir / REQUESTS_FILE).write_text("[]", encoding="utf-8")
    manifest = json.loads((artifact_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["requestsFileSha256"] = hashlib.sha256(
        (artifact_dir / REQUESTS_FILE).read_bytes()
    ).hexdigest()
    (artifact_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identity["manifestSha256"] = hashlib.sha256(
        (artifact_dir / MANIFEST_FILE).read_bytes()
    ).hexdigest()
    _patch_approved_identity(monkeypatch, identity)
    service = FakeV3PersistenceService()

    with pytest.raises(V3PersistenceError, match="non-empty"):
        run(artifact_dir, service_factory=lambda: service)

    assert service.calls == []


def test_delivery_summary_states_cover_persist_recovery_and_existing() -> None:
    base = dict[str, Any](
        rule_version="RV",
        request_count=2,
        rule_payload_sha256="a" * 64,
        batch_sha256="b" * 64,
        request_ids=("RV#f1", "RV#f2"),
        legacy_counts_before=dict(LEGACY_COUNTS),
        legacy_counts_after=dict(LEGACY_COUNTS),
    )
    persisted = delivery_summary(
        PersistedV3Delivery(rule_inserted=True, batch_inserted=True, **base)
    )
    recovered = delivery_summary(
        PersistedV3Delivery(rule_inserted=False, batch_inserted=True, **base)
    )
    existing = delivery_summary(
        PersistedV3Delivery(rule_inserted=False, batch_inserted=False, **base)
    )

    assert persisted["status"] == "persistedAndVerified"
    # 规则已存在而 batch 本次补写: 不得报告 existingAndVerified。
    assert recovered["status"] == "recoveredAndVerified"
    assert existing["status"] == "existingAndVerified"


def _run_main_with_args(monkeypatch: pytest.MonkeyPatch, artifact_dir: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["persist_report_release_v3_delivery", "--artifact-dir", str(artifact_dir)],
    )
    script.main()


def _assert_sanitized_cli_error(
    capsys: pytest.CaptureFixture[str], artifact_dir: Path, expected_code: str
) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert set(payload) == {"code", "message", "retryable", "details"}
    assert payload["code"] == expected_code
    assert payload["details"] == []
    assert "Traceback" not in captured.err
    assert "input_value" not in captured.err
    assert str(artifact_dir) not in captured.err
    assert str(artifact_dir.parent) not in captured.err
    return payload


def test_cli_reports_sanitized_error_for_malformed_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    raw = json.loads((artifact_dir / REQUESTS_FILE).read_text(encoding="utf-8"))
    raw[0]["contractVersion"] = "1.0.0"
    (artifact_dir / REQUESTS_FILE).write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = json.loads((artifact_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["requestsFileSha256"] = hashlib.sha256(
        (artifact_dir / REQUESTS_FILE).read_bytes()
    ).hexdigest()
    (artifact_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identity["manifestSha256"] = hashlib.sha256(
        (artifact_dir / MANIFEST_FILE).read_bytes()
    ).hexdigest()
    _patch_approved_identity(monkeypatch, identity)

    with pytest.raises(SystemExit) as exit_info:
        _run_main_with_args(monkeypatch, artifact_dir)

    assert exit_info.value.code == 1
    payload = _assert_sanitized_cli_error(capsys, artifact_dir, "V3_PERSISTENCE_CONTRACT_INVALID")
    assert payload["retryable"] is False


def test_cli_reports_sanitized_error_for_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    (artifact_dir / REQUESTS_FILE).unlink()

    with pytest.raises(SystemExit) as exit_info:
        _run_main_with_args(monkeypatch, artifact_dir)

    assert exit_info.value.code == 1
    payload = _assert_sanitized_cli_error(capsys, artifact_dir, "V3_PERSISTENCE_FAILED")
    assert payload["retryable"] is False


def test_cli_reports_sanitized_error_for_wrong_manifest_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "confirmed"
    _write_delivery(artifact_dir)

    with pytest.raises(SystemExit) as exit_info:
        _run_main_with_args(monkeypatch, artifact_dir)

    assert exit_info.value.code == 1
    _assert_sanitized_cli_error(capsys, artifact_dir, "V3_PERSISTENCE_FAILED")


def test_cli_reports_sanitized_error_for_mongo_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)
    monkeypatch.setattr(script, "MongoManager", FailingMongoManager)

    with pytest.raises(SystemExit) as exit_info:
        _run_main_with_args(monkeypatch, artifact_dir)

    assert exit_info.value.code == 1
    payload = _assert_sanitized_cli_error(capsys, artifact_dir, "V3_PERSISTENCE_UNAVAILABLE")
    assert payload["retryable"] is True


def test_cli_reports_sanitized_error_for_invalid_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "confirmed"
    identity = _write_delivery(artifact_dir)
    _patch_approved_identity(monkeypatch, identity)

    from pydantic import ValidationError

    from rule_reader.core.config import Settings

    try:
        Settings(_env_file=None, mongodb_database="forbidden name")
        raise AssertionError("expected the deterministic invalid configuration to fail")
    except ValidationError as error:
        validation_error = error

    constructed: list[object] = []

    class ExplodingMongoManager:
        def __init__(self, settings: Any) -> None:
            constructed.append(settings)
            raise AssertionError("MongoManager must not be constructed when Settings fails")

    def failing_settings() -> Settings:
        raise validation_error

    monkeypatch.setattr(script, "Settings", failing_settings)
    monkeypatch.setattr(script, "MongoManager", ExplodingMongoManager)

    with pytest.raises(SystemExit) as exit_info:
        _run_main_with_args(monkeypatch, artifact_dir)

    assert exit_info.value.code == 1
    payload = _assert_sanitized_cli_error(capsys, artifact_dir, "V3_PERSISTENCE_UNAVAILABLE")
    assert payload["retryable"] is True
    # 对首次捕获的 stderr JSON 断言脱敏, 第二次 readouterr 恒为空、无检查价值。
    assert "forbidden name" not in json.dumps(payload, ensure_ascii=False)
    assert constructed == []
