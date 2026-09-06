"""Validated application service for immutable V3 delivery persistence (Schema v5).

The service performs every gate before the first write, then saves the rule document and
the single-document request batch insert-only, and finally re-reads both documents and
re-verifies the full closure plus unchanged legacy collection counts. The write-ahead
gates live in the pure :func:`prepare_v3_delivery` function so entry points can validate
a delivery offline, before any database is initialized.
"""

from __future__ import annotations

from collections.abc import Sequence

from rule_reader.application.v3_persistence.canonical import (
    batch_sha256_v3,
    canonical_payload_sha256,
    request_payload_v3,
    result_payload_v3,
)
from rule_reader.application.v3_persistence.ports import (
    PersistedV3Delivery,
    PreparedV3HandoffBatch,
    PreparedV3RequestWrapper,
    PreparedV3RuleVersion,
    V3HandoffBatchRepository,
    V3LegacyCollectionCounter,
    V3PersistenceContractError,
    V3PersistenceVerificationError,
    V3RuleVersionRepository,
)
from rule_reader.domain.rules.bindings_v3 import FactBindingRequestV3
from rule_reader.domain.rules.catalog_v3 import BusinessConfirmedFactCatalogV3
from rule_reader.domain.rules.readiness_v3 import build_agent2_readiness_report_v3
from rule_reader.domain.rules.result_v3 import (
    RuleParseResultV3,
    candidate_payload_sha256_v3,
    export_fact_binding_requests_v3,
)
from rule_reader.domain.rules.v3 import RuleStructureCandidateV3

# Collections whose document counts must not change during a V3 delivery persistence.
# The names are part of the frozen delivery contract; the counter port stays generic.
LEGACY_DELIVERY_COLLECTIONS = (
    "rule_versions",
    "fact_binding_handoffs",
    "rule_structure_candidates_v3",
)

READINESS_GATE_COUNT = 16


def _canonical_hash(payload: dict[str, object]) -> str:
    try:
        return canonical_payload_sha256(payload)
    except (TypeError, ValueError) as error:
        raise V3PersistenceContractError(
            "Delivery payload cannot be canonically serialized"
        ) from error


def _run_write_ahead_gates(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV3,
    result: RuleParseResultV3,
    requests: Sequence[FactBindingRequestV3],
) -> None:
    if candidate.blocking_issues:
        raise V3PersistenceContractError(
            "Candidate still carries blocking issues; V3 persistence is not allowed"
        )
    if result.status != "draft" or result.executable is not False:
        raise V3PersistenceContractError("Rule parse result must remain a non-executable draft")
    if not result.agent2_readiness_ready:
        raise V3PersistenceContractError(
            "Agent 2 readiness is not ready; V3 persistence is not allowed"
        )
    report = build_agent2_readiness_report_v3(
        candidate,
        catalog,
        result=result,
        requests=requests,
    )
    if (
        len(report.gates) != READINESS_GATE_COUNT
        or not report.ready
        or any(gate.result.value != "pass" for gate in report.gates)
    ):
        raise V3PersistenceContractError(
            "Agent 2 readiness gates are not 16/16 pass; V3 persistence is not allowed"
        )
    if result.rule_set_id != candidate.rule_set_id:
        raise V3PersistenceContractError("Result rule set does not match the candidate")
    if (
        result.catalog_ref.catalog_id != catalog.catalog_id
        or result.catalog_ref.catalog_version != catalog.catalog_version
        or result.catalog_ref.catalog_digest != catalog.catalog_digest
    ):
        raise V3PersistenceContractError(
            "Result catalog reference does not match the confirmed catalog"
        )
    if result.candidate_ref.payload_sha256 != candidate_payload_sha256_v3(candidate):
        raise V3PersistenceContractError(
            "Result candidate reference does not match the candidate payload hash"
        )
    if result.candidate_ref.rule_block_sha256 != result.source.source_sha256:
        raise V3PersistenceContractError(
            "Result candidate source hash does not close to the provenance"
        )

    try:
        re_exported = export_fact_binding_requests_v3(result, candidate, catalog)
    except ValueError as error:
        raise V3PersistenceContractError(
            "Delivery does not reproduce the deterministic fact request export"
        ) from error
    exported_by_id = {request.request_id: request for request in re_exported}
    provided_by_id = {request.request_id: request for request in requests}
    if len(provided_by_id) != len(requests) or exported_by_id != provided_by_id:
        raise V3PersistenceContractError(
            "Provided requests do not match the deterministic fact request export"
        )

    non_derived = [
        declaration
        for declaration in result.fact_declarations
        if declaration.fact.fact_kind.value != "derived"
    ]
    if len(requests) != len(non_derived):
        raise V3PersistenceContractError(
            "Request count does not match the non-derived fact declarations"
        )
    fact_codes = [request.fact.fact_code for request in requests]
    if len(set(fact_codes)) != len(fact_codes):
        raise V3PersistenceContractError("Fact binding batch contains duplicate fact codes")
    expected_codes = {
        declaration.fact.fact_code
        for declaration in result.fact_declarations
        if declaration.fact.fact_kind.value != "derived"
    }
    if set(fact_codes) != expected_codes:
        raise V3PersistenceContractError(
            "Requests do not cover exactly the non-derived fact declarations"
        )
    for request in requests:
        if request.request_id != f"{result.rule_version}#{request.fact.fact_code}":
            raise V3PersistenceContractError(
                "Request identity does not close to rule version and fact code"
            )
        if (
            request.rule_ref.rule_version != result.rule_version
            or request.contract_version != "3.0.0"
        ):
            raise V3PersistenceContractError(
                "Request rule reference or contract version does not close"
            )


def prepare_v3_delivery(
    catalog: BusinessConfirmedFactCatalogV3,
    candidate: RuleStructureCandidateV3,
    result: RuleParseResultV3,
    requests: Sequence[FactBindingRequestV3],
) -> tuple[PreparedV3RuleVersion, PreparedV3HandoffBatch]:
    """Validate a V3 delivery and build its immutable storage records without writing.

    Raises :class:`V3PersistenceContractError` before producing anything when any
    write-ahead gate fails, so callers can treat a returned pair as validated input.
    """

    _run_write_ahead_gates(catalog, candidate, result, requests)

    rule_payload = result_payload_v3(result)
    prepared_rule = PreparedV3RuleVersion(
        rule_version=result.rule_version,
        rule_set_id=result.rule_set_id,
        schema_version=result.schema_version,
        source_sha256=result.source.source_sha256,
        catalog_digest=result.catalog_ref.catalog_digest,
        candidate_payload_sha256=result.candidate_ref.payload_sha256,
        payload_sha256=_canonical_hash(rule_payload),
        status=result.status,
        executable=result.executable,
        payload=rule_payload,
    )

    wrappers: list[PreparedV3RequestWrapper] = []
    for request in requests:
        payload = request_payload_v3(request)
        wrappers.append(
            PreparedV3RequestWrapper(
                request_id=request.request_id,
                rule_version=request.rule_ref.rule_version,
                fact_code=request.fact.fact_code,
                contract_version=request.contract_version,
                payload_sha256=_canonical_hash(payload),
                payload=payload,
            )
        )
    wrappers.sort(key=lambda wrapper: wrapper.request_id)
    prepared_batch = PreparedV3HandoffBatch(
        rule_version=result.rule_version,
        contract_version=requests[0].contract_version if requests else "3.0.0",
        request_count=len(wrappers),
        request_ids=tuple(wrapper.request_id for wrapper in wrappers),
        batch_sha256=batch_sha256_v3(
            (wrapper.request_id, wrapper.payload_sha256) for wrapper in wrappers
        ),
        wrappers=tuple(wrappers),
    )
    return prepared_rule, prepared_batch


class V3PersistenceService:
    """Persist one immutable V3 rule version and its single-document request batch."""

    def __init__(
        self,
        rules: V3RuleVersionRepository,
        batches: V3HandoffBatchRepository,
        counter: V3LegacyCollectionCounter,
    ) -> None:
        self._rules = rules
        self._batches = batches
        self._counter = counter

    async def persist(
        self,
        catalog: BusinessConfirmedFactCatalogV3,
        candidate: RuleStructureCandidateV3,
        result: RuleParseResultV3,
        requests: Sequence[FactBindingRequestV3],
    ) -> PersistedV3Delivery:
        prepared_rule, prepared_batch = prepare_v3_delivery(catalog, candidate, result, requests)

        counts_before = await self._snapshot_legacy_counts()
        saved_rule = await self._rules.save_rule(prepared_rule)
        saved_batch = await self._batches.save_batch(prepared_batch)

        stored_rule = await self._rules.get_rule(prepared_rule.rule_version)
        if stored_rule is None:
            raise V3PersistenceVerificationError(
                "Stored V3 rule version could not be read back after saving"
            )
        self._assert_rule_matches(stored_rule.record, prepared_rule)
        stored_batch = await self._batches.get_batch(prepared_batch.rule_version)
        if stored_batch is None:
            raise V3PersistenceVerificationError(
                "Stored V3 handoff batch could not be read back after saving"
            )
        self._assert_batch_matches(stored_batch.record, prepared_batch)

        counts_after = await self._snapshot_legacy_counts()
        if counts_before != counts_after:
            raise V3PersistenceVerificationError(
                "Legacy collection counts changed during V3 delivery persistence"
            )

        return PersistedV3Delivery(
            rule_version=prepared_rule.rule_version,
            rule_inserted=saved_rule.inserted,
            batch_inserted=saved_batch.inserted,
            request_count=prepared_batch.request_count,
            rule_payload_sha256=prepared_rule.payload_sha256,
            batch_sha256=prepared_batch.batch_sha256,
            request_ids=prepared_batch.request_ids,
            legacy_counts_before=counts_before,
            legacy_counts_after=counts_after,
        )

    async def _snapshot_legacy_counts(self) -> dict[str, int]:
        return {name: await self._counter.count(name) for name in LEGACY_DELIVERY_COLLECTIONS}

    @staticmethod
    def _assert_rule_matches(
        stored: PreparedV3RuleVersion,
        prepared: PreparedV3RuleVersion,
    ) -> None:
        if stored != prepared:
            raise V3PersistenceVerificationError(
                "Stored V3 rule version differs from the validated delivery"
            )

    @staticmethod
    def _assert_batch_matches(
        stored: PreparedV3HandoffBatch,
        prepared: PreparedV3HandoffBatch,
    ) -> None:
        if stored != prepared:
            raise V3PersistenceVerificationError(
                "Stored V3 handoff batch differs from the validated delivery"
            )
