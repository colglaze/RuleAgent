"""Write-ahead gates and complete-delivery persistence for Rule Schema 3.1.0."""

from __future__ import annotations

from collections.abc import Sequence

from rule_reader.application.v3_persistence.canonical import (
    batch_sha256_v3,
    canonical_payload_sha256,
)
from rule_reader.application.v3_persistence.ports import (
    PreparedV3HandoffBatch,
    PreparedV3RequestWrapper,
    V3HandoffBatchRepository,
    V3LegacyCollectionCounter,
    V3PersistenceContractError,
    V3PersistenceVerificationError,
)
from rule_reader.application.v3_persistence.service import LEGACY_DELIVERY_COLLECTIONS
from rule_reader.application.v31_persistence.ports import (
    V31_DELIVERY_PURPOSE,
    CompleteDeliveryV31,
    PersistedV31Delivery,
    PreparedV31RuleVersion,
    V31RuleVersionRepository,
)
from rule_reader.domain.rules.bindings_v31 import FactBindingRequestV31
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.purpose_v31 import (
    HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION,
    DeliveryPurposeDeniedError,
    DeliveryPurposeV31,
    assert_delivery_purpose_allowed,
)
from rule_reader.domain.rules.result_v31 import (
    RuleParseResultV31,
    candidate_payload_sha256_v31,
    catalog_payload_sha256_v31,
    export_fact_binding_requests_v31,
)
from rule_reader.domain.rules.v31 import RuleStructureCandidateV31
from rule_reader.domain.rules.validation_v31 import validate_rule_structure_candidate_v31


def _hash(payload: dict[str, object]) -> str:
    try:
        return canonical_payload_sha256(payload)
    except (TypeError, ValueError) as error:
        raise V3PersistenceContractError(
            "Delivery payload cannot be canonically serialized"
        ) from error


def _run_write_ahead_gates(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV31,
    result: RuleParseResultV31,
    requests: Sequence[FactBindingRequestV31],
) -> None:
    if result.rule_version == HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION:
        raise V3PersistenceContractError("Historical 2026-09-05 delivery cannot be rewritten")
    try:
        assert_delivery_purpose_allowed(
            result.rule_version, DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION
        )
    except DeliveryPurposeDeniedError as error:
        raise V3PersistenceContractError("Delivery purpose is not allowed") from error
    if candidate.blocking_issues:
        raise V3PersistenceContractError("Candidate still carries blocking issues")
    if result.status != "draft" or result.executable is not False:
        raise V3PersistenceContractError("Rule parse result must remain a non-executable draft")
    if not result.agent2_readiness_ready:
        raise V3PersistenceContractError("Agent 2 readiness is not ready")
    validate_rule_structure_candidate_v31(candidate, catalog)
    if result.rule_set_id != candidate.rule_set_id:
        raise V3PersistenceContractError("Result rule set does not match the candidate")
    if result.catalog_ref.catalog_digest != catalog.catalog_digest:
        raise V3PersistenceContractError("Result catalog reference does not match the catalog")
    if result.candidate_ref.payload_sha256 != candidate_payload_sha256_v31(candidate):
        raise V3PersistenceContractError("Result candidate reference does not match the candidate")
    if result.source.source_sha256 != candidate.source_identity.source_file_sha256:
        raise V3PersistenceContractError("Result source file hash does not match the candidate")
    if result.source.parse_input_sha256 != candidate.source_identity.parse_input_sha256:
        raise V3PersistenceContractError("Result parse input hash does not match the candidate")
    try:
        re_exported = export_fact_binding_requests_v31(result, candidate, catalog)
    except ValueError as error:
        raise V3PersistenceContractError(
            "Delivery does not reproduce the deterministic fact request export"
        ) from error
    exported_by_id = {request.request_id: request for request in re_exported}
    provided_by_id = {request.request_id: request for request in requests}
    if exported_by_id != provided_by_id:
        raise V3PersistenceContractError(
            "Provided requests do not match the deterministic fact request export"
        )
    if len(requests) != len(result.fact_declarations):
        raise V3PersistenceContractError("Request count does not match fact declarations")


def prepare_v31_delivery(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV31,
    result: RuleParseResultV31,
    requests: Sequence[FactBindingRequestV31],
) -> tuple[PreparedV31RuleVersion, PreparedV3HandoffBatch]:
    _run_write_ahead_gates(catalog, candidate, result, requests)
    rule_payload = result.model_dump(mode="json", by_alias=True)
    catalog_payload = catalog.model_dump(mode="json", by_alias=True)
    candidate_payload = candidate.model_dump(mode="json", by_alias=True)
    prepared_rule = PreparedV31RuleVersion(
        rule_version=result.rule_version,
        rule_set_id=result.rule_set_id,
        schema_version=result.schema_version,
        source_sha256=result.source.source_sha256,
        source_file_sha256=result.source.source_sha256,
        parse_input_sha256=result.source.parse_input_sha256,
        catalog_digest=result.catalog_ref.catalog_digest,
        candidate_payload_sha256=result.candidate_ref.payload_sha256,
        catalog_payload_sha256=catalog_payload_sha256_v31(catalog),
        payload_sha256=_hash(rule_payload),
        status=result.status,
        executable=result.executable,
        purpose=V31_DELIVERY_PURPOSE,
        payload=rule_payload,
        catalog_payload=catalog_payload,
        candidate_payload=candidate_payload,
    )
    wrappers: list[PreparedV3RequestWrapper] = []
    for request in requests:
        payload = request.model_dump(mode="json", by_alias=True)
        wrappers.append(
            PreparedV3RequestWrapper(
                request_id=request.request_id,
                rule_version=request.rule_ref.rule_version,
                fact_code=request.fact.fact_code,
                contract_version=request.contract_version,
                payload_sha256=_hash(payload),
                payload=payload,
            )
        )
    wrappers.sort(key=lambda wrapper: wrapper.request_id)
    prepared_batch = PreparedV3HandoffBatch(
        rule_version=result.rule_version,
        contract_version=requests[0].contract_version if requests else "3.1.0",
        request_count=len(wrappers),
        request_ids=tuple(wrapper.request_id for wrapper in wrappers),
        batch_sha256=batch_sha256_v3(
            (wrapper.request_id, wrapper.payload_sha256) for wrapper in wrappers
        ),
        wrappers=tuple(wrappers),
    )
    return prepared_rule, prepared_batch


def _missing_parts(
    stored_rule: PreparedV31RuleVersion | None,
    stored_batch: PreparedV3HandoffBatch | None,
    prepared_rule: PreparedV31RuleVersion | None = None,
    prepared_batch: PreparedV3HandoffBatch | None = None,
) -> tuple[str, ...]:
    missing: list[str] = []
    if stored_rule is None:
        missing.extend(["rule", "catalog", "candidate", "result"])
    else:
        if not stored_rule.catalog_payload:
            missing.append("catalog")
        if not stored_rule.candidate_payload:
            missing.append("candidate")
        if not stored_rule.payload:
            missing.append("result")
        if prepared_rule is not None and stored_rule != prepared_rule:
            missing.append("rule-hash")
    if stored_batch is None:
        missing.append("batch")
    elif prepared_batch is not None and stored_batch != prepared_batch:
        missing.append("batch-hash")
    return tuple(missing)


class V31PersistenceService:
    def __init__(
        self,
        rules: V31RuleVersionRepository,
        batches: V3HandoffBatchRepository,
        counter: V3LegacyCollectionCounter,
    ) -> None:
        self._rules = rules
        self._batches = batches
        self._counter = counter

    async def persist(
        self,
        catalog: BusinessConfirmedFactCatalogV3,
        candidate: RuleStructureCandidateV31,
        result: RuleParseResultV31,
        requests: Sequence[FactBindingRequestV31],
    ) -> PersistedV31Delivery:
        prepared_rule, prepared_batch = prepare_v31_delivery(catalog, candidate, result, requests)
        counts_before = await self._snapshot_legacy_counts()
        saved_rule = await self._rules.save_rule(prepared_rule)
        saved_batch = await self._batches.save_batch(prepared_batch)
        stored_rule = await self._rules.get_rule(prepared_rule.rule_version)
        stored_batch = await self._batches.get_batch(prepared_batch.rule_version)
        missing = _missing_parts(
            None if stored_rule is None else stored_rule.record,
            None if stored_batch is None else stored_batch.record,
            prepared_rule,
            prepared_batch,
        )
        if stored_rule is None or stored_batch is None or missing:
            raise V3PersistenceVerificationError(
                "Complete 3.1.0 delivery could not be read back after saving"
            )
        counts_after = await self._snapshot_legacy_counts()
        if counts_before != counts_after:
            raise V3PersistenceVerificationError(
                "Legacy collection counts changed during 3.1.0 delivery persistence"
            )
        return PersistedV31Delivery(
            rule_version=prepared_rule.rule_version,
            rule_inserted=saved_rule.inserted,
            batch_inserted=saved_batch.inserted,
            request_count=prepared_batch.request_count,
            rule_payload_sha256=prepared_rule.payload_sha256,
            batch_sha256=prepared_batch.batch_sha256,
            catalog_payload_sha256=prepared_rule.catalog_payload_sha256,
            candidate_payload_sha256=prepared_rule.candidate_payload_sha256,
            request_ids=prepared_batch.request_ids,
            consumable=not missing,
            missing=missing,
            legacy_counts_before=counts_before,
            legacy_counts_after=counts_after,
        )

    async def get_complete_delivery(
        self,
        rule_version: str,
        purpose: DeliveryPurposeV31,
    ) -> CompleteDeliveryV31:
        assert_delivery_purpose_allowed(rule_version, purpose)
        stored_rule = await self._rules.get_rule(rule_version)
        stored_batch = await self._batches.get_batch(rule_version)
        record = None if stored_rule is None else stored_rule.record
        batch = None if stored_batch is None else stored_batch.record
        missing = _missing_parts(record, batch)
        return CompleteDeliveryV31(
            rule_version=rule_version,
            purpose=purpose.value,
            consumable=not missing,
            missing=missing,
            record=record,
            batch=batch,
        )

    async def _snapshot_legacy_counts(self) -> dict[str, int]:
        return {name: await self._counter.count(name) for name in LEGACY_DELIVERY_COLLECTIONS}
