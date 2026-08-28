from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.report_release_fixtures import historical_persisted_report_release_rule
from tests.support import valid_candidate

from rule_reader.application.fact_binding_handoffs.canonical import (
    canonical_payload_sha256,
    fact_binding_payload,
)
from rule_reader.application.fact_binding_handoffs.ports import (
    FactBindingHandoffConflictError,
    FactBindingHandoffContractError,
    FactBindingHandoffRuleNotFoundError,
    FactBindingHandoffSchemaUnsupportedError,
    FactBindingHandoffVerificationError,
    PreparedFactBindingHandoff,
    SavedFactBindingHandoff,
    StoredFactBindingHandoff,
)
from rule_reader.application.fact_binding_handoffs.service import (
    FactBindingHandoffService,
    load_checked_in_fact_binding_schema,
)
from rule_reader.application.rule_versions.ports import StoredRuleVersion
from rule_reader.domain.rules.models import (
    ParserMetadata,
    RuleCandidate,
    RuleParseResult,
    SourceMetadata,
)
from rule_reader.domain.rules.v2 import RuleParseResultV2
from rule_reader.domain.rules.validation import enrich_candidate, validate_candidate

FIXED_TIME = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


@dataclass
class FakeRuleVersionRepository:
    records: dict[str, StoredRuleVersion]
    mutate_after_first_read: bool = False
    get_calls: int = 0

    async def get(self, rule_version: str) -> StoredRuleVersion | None:
        self.get_calls += 1
        stored = self.records.get(rule_version)
        if stored is not None and self.mutate_after_first_read and self.get_calls > 1:
            return replace(stored, stored_at=stored.stored_at + timedelta(seconds=1))
        return stored


@dataclass
class FakeFactBindingHandoffRepository:
    records: dict[str, StoredFactBindingHandoff] = field(default_factory=dict)
    save_calls: int = 0

    async def save_many(
        self,
        records: tuple[PreparedFactBindingHandoff, ...],
    ) -> tuple[SavedFactBindingHandoff, ...]:
        self.save_calls += 1
        saved: list[SavedFactBindingHandoff] = []
        for item in records:
            existing = self.records.get(item.request_id)
            if existing is not None:
                if (
                    existing.payload_sha256 != item.payload_sha256
                    or existing.payload != item.payload
                ):
                    raise FactBindingHandoffConflictError("hash conflict")
                saved.append(SavedFactBindingHandoff(record=existing, inserted=False))
                continue
            stored = StoredFactBindingHandoff(
                request_id=item.request_id,
                rule_version=item.rule_version,
                fact_code=item.fact_code,
                contract_version=item.contract_version,
                payload_sha256=item.payload_sha256,
                created_at=FIXED_TIME,
                payload=item.payload,
            )
            self.records[item.request_id] = stored
            saved.append(SavedFactBindingHandoff(record=stored, inserted=True))
        return tuple(saved)

    async def list_by_rule_version(
        self,
        rule_version: str,
    ) -> tuple[StoredFactBindingHandoff, ...]:
        return tuple(
            sorted(
                (record for record in self.records.values() if record.rule_version == rule_version),
                key=lambda record: record.fact_code,
            )
        )


def _reviewed_rule() -> RuleParseResultV2:
    return historical_persisted_report_release_rule()


def _legacy_rule() -> RuleParseResult:
    candidate = RuleCandidate.model_validate(valid_candidate(rule_id="LEGACY_HANDOFF_001"))
    validate_candidate(candidate)
    return RuleParseResult(
        rule_version="LEGACY_HANDOFF_001@20260818T000000000000Z-000000000000",
        generated_at=datetime(2026, 8, 18, tzinfo=UTC),
        parser=ParserMetadata(
            parser_version="0.3.0",
            prompt_version="rule-parser-v1",
            model="legacy",
        ),
        source=SourceMetadata(
            source_name="legacy.md",
            sha256="0" * 64,
            character_count=10,
        ),
        rule=enrich_candidate(candidate),
    )


def _service(
    rule: RuleParseResultV2 | RuleParseResult,
    handoffs: FakeFactBindingHandoffRepository | None = None,
    *,
    schema: dict[str, object] | None = None,
    mutate_source: bool = False,
) -> tuple[FactBindingHandoffService, FakeFactBindingHandoffRepository]:
    stored = StoredRuleVersion(document=rule, stored_at=FIXED_TIME)
    rules = FakeRuleVersionRepository(
        records={rule.rule_version: stored},
        mutate_after_first_read=mutate_source,
    )
    resolved_handoffs = handoffs or FakeFactBindingHandoffRepository()
    service = FactBindingHandoffService(
        rules,
        resolved_handoffs,
        schema or load_checked_in_fact_binding_schema(),
    )
    return service, resolved_handoffs


@pytest.mark.asyncio
async def test_reviewed_persisted_rule_creates_33_immutable_handoffs() -> None:
    rule = _reviewed_rule()
    service, repository = _service(rule)

    first = await service.persist(rule.rule_version)
    initial_records = deepcopy(repository.records)
    second = await service.persist(rule.rule_version)

    assert len(first.records) == 33
    assert first.inserted_count == 33
    assert first.existing_count == 0
    assert first.blocking_request_count == 33
    assert first.source_rule_unchanged is True
    assert second.inserted_count == 0
    assert second.existing_count == 33
    assert repository.records == initial_records
    for record in first.records:
        payload = fact_binding_payload(record.payload)
        assert record.request_id == f"{rule.rule_version}#{record.fact_code}"
        assert record.payload.request_id == record.request_id
        assert record.contract_version == "2.0.0"
        assert record.payload_sha256 == canonical_payload_sha256(payload)
        assert any(item.impact.value == "blocking" for item in record.payload.uncertainties)


@pytest.mark.asyncio
async def test_missing_and_schema_v1_rules_are_rejected_before_handoff_write() -> None:
    handoffs = FakeFactBindingHandoffRepository()
    missing_service = FactBindingHandoffService(
        FakeRuleVersionRepository(records={}),
        handoffs,
        load_checked_in_fact_binding_schema(),
    )
    with pytest.raises(FactBindingHandoffRuleNotFoundError):
        await missing_service.persist("MISSING@20260824T000000000000Z-000000000000")

    legacy = _legacy_rule()
    legacy_service, _ = _service(legacy, handoffs)
    with pytest.raises(FactBindingHandoffSchemaUnsupportedError):
        await legacy_service.persist(legacy.rule_version)

    assert handoffs.save_calls == 0
    assert handoffs.records == {}


@pytest.mark.asyncio
async def test_checked_in_schema_failure_prevents_any_handoff_write() -> None:
    rule = _reviewed_rule()
    schema = deepcopy(load_checked_in_fact_binding_schema())
    schema["properties"]["contractVersion"]["const"] = "1.0.0"
    service, handoffs = _service(rule, schema=schema)

    with pytest.raises(FactBindingHandoffContractError):
        await service.persist(rule.rule_version)

    assert handoffs.save_calls == 0
    assert handoffs.records == {}


@pytest.mark.asyncio
async def test_same_request_id_with_different_hash_fails_without_overwrite() -> None:
    rule = _reviewed_rule()
    service, handoffs = _service(rule)
    await service.persist(rule.rule_version)
    request_id = next(iter(handoffs.records))
    original = handoffs.records[request_id]
    handoffs.records[request_id] = replace(original, payload_sha256="f" * 64)

    with pytest.raises(FactBindingHandoffConflictError):
        await service.persist(rule.rule_version)

    assert handoffs.records[request_id].payload == original.payload
    assert handoffs.records[request_id].created_at == original.created_at


@pytest.mark.asyncio
async def test_source_rule_change_is_detected_after_handoff_read_back() -> None:
    rule = _reviewed_rule()
    service, _ = _service(rule, mutate_source=True)

    with pytest.raises(
        FactBindingHandoffVerificationError,
        match="Source rule version changed during fact binding handoff",
    ):
        await service.persist(rule.rule_version)
