"""Check that a checkout can reproduce its advertised public artifacts offline."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def test_contract_export_is_reproducible_from_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = importlib.import_module("scripts.export_contract_schemas")
    repository_contracts = Path(__file__).resolve().parents[2] / "contracts"
    schema_name = "fact-binding-request-2.0.0.schema.json"
    monkeypatch.setattr(exporter, "FACT_BINDING_V2_PATH", tmp_path / schema_name)
    monkeypatch.setattr(
        exporter,
        "FACT_BINDING_V3_PATH",
        tmp_path / "fact-binding-request-3.0.0.schema.json",
    )
    monkeypatch.setattr(
        exporter,
        "RULE_RESULT_V3_PATH",
        tmp_path / "rule-parse-result-3.0.0.schema.json",
    )
    monkeypatch.setattr(
        exporter,
        "FACT_CATALOG_V3_PATH",
        tmp_path / "business-confirmed-fact-catalog-3.0.0.schema.json",
    )
    monkeypatch.setattr(
        exporter,
        "RULE_STRUCTURE_V3_PATH",
        tmp_path / "rule-structure-candidate-3.0.0.schema.json",
    )
    monkeypatch.setattr(exporter, "EXAMPLES_ROOT", tmp_path / "examples")

    exporter.main()
    first = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert len(first) == 16
    for relative_path, payload in first.items():
        expected = (repository_contracts / relative_path).read_text(encoding="utf-8")
        assert json.loads(payload) == json.loads(expected)

    exporter.main()
    assert first == {
        path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.json")
    }
