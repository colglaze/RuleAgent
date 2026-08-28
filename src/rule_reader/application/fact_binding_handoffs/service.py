"""Validated application service for immutable MongoDB fact handoffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from jsonschema.exceptions import (
    ValidationError as JsonSchemaValidationError,
)
from pydantic import ValidationError as PydanticValidationError

from rule_reader.application.fact_binding_handoffs.canonical import (
    canonical_payload_sha256,
    fact_binding_payload,
)
from rule_reader.application.fact_binding_handoffs.ports import (
    FactBindingHandoffConflictError,
    FactBindingHandoffContractError,
    FactBindingHandoffPersistenceError,
    FactBindingHandoffRepository,
    FactBindingHandoffRuleNotFoundError,
    FactBindingHandoffSchemaUnsupportedError,
    FactBindingHandoffVerificationError,
    PersistedFactBindingHandoffs,
    PreparedFactBindingHandoff,
    StoredFactBindingHandoff,
)
from rule_reader.application.rule_versions.ports import (
    RuleVersionPersistenceError,
    RuleVersionRepository,
    StoredRuleVersion,
)
from rule_reader.domain.rules.bindings_v2 import (
    FACT_BINDING_CONTRACT_VERSION_V2,
    FactBindingRequestV2,
    UncertaintyImpact,
    build_fact_binding_requests_v2,
)
from rule_reader.domain.rules.v2 import RuleParseResultV2
from rule_reader.domain.rules.validation_v2 import (
    SemanticValidationErrorV2,
    validate_safe_structured_payload,
)

CHECKED_IN_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "contracts" / "fact-binding-request-2.0.0.schema.json"
)


def load_checked_in_fact_binding_schema(
    path: Path = CHECKED_IN_SCHEMA_PATH,
) -> dict[str, Any]:
    """Load and validate the exact checked-in handoff JSON Schema."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FactBindingHandoffContractError(
            "Checked-in fact binding JSON Schema could not be loaded"
        ) from error
    if not isinstance(payload, dict):
        raise FactBindingHandoffContractError(
            "Checked-in fact binding JSON Schema must be an object"
        )
    schema = cast(dict[str, Any], payload)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise FactBindingHandoffContractError(
            "Checked-in fact binding JSON Schema is invalid"
        ) from error
    return schema


class FactBindingHandoffService:
    """Create handoffs only from exact, persisted RuleParseResultV2 records."""

    def __init__(
        self,
        rule_versions: RuleVersionRepository,
        handoffs: FactBindingHandoffRepository,
        schema: dict[str, Any],
    ) -> None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise FactBindingHandoffContractError("Fact binding JSON Schema is invalid") from error
        self._rule_versions = rule_versions
        self._handoffs = handoffs
        self._validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )

    async def persist(self, rule_version: str) -> PersistedFactBindingHandoffs:
        before = await self._get_rule(rule_version)
        if before is None:
            raise FactBindingHandoffRuleNotFoundError("Rule version was not found")
        if not isinstance(before.document, RuleParseResultV2):
            raise FactBindingHandoffSchemaUnsupportedError(
                "Only persisted rule schema 2.0.0 can create fact binding handoffs"
            )

        prepared = tuple(
            self._prepare(request, before.document)
            for request in build_fact_binding_requests_v2(before.document)
        )
        if not prepared:
            raise FactBindingHandoffContractError(
                "Persisted rule does not contain bindable non-derived facts"
            )

        existing = await self._handoffs.list_by_rule_version(rule_version)
        self._verify_existing_subset(prepared, existing)
        saved = await self._handoffs.save_many(prepared)
        saved_ids = [item.record.request_id for item in saved]
        if len(saved_ids) != len(prepared) or set(saved_ids) != {
            item.request_id for item in prepared
        }:
            raise FactBindingHandoffVerificationError(
                "Fact binding handoff save result does not match the deterministic export"
            )
        stored = await self._handoffs.list_by_rule_version(rule_version)

        self._verify_read_back(prepared, stored)
        after = await self._get_rule(rule_version)
        if after != before:
            raise FactBindingHandoffVerificationError(
                "Source rule version changed during fact binding handoff"
            )

        inserted_count = sum(item.inserted for item in saved)
        blocking_request_count = sum(
            any(
                uncertainty.impact is UncertaintyImpact.BLOCKING
                for uncertainty in item.payload.uncertainties
            )
            for item in stored
        )
        return PersistedFactBindingHandoffs(
            rule_version=rule_version,
            records=stored,
            inserted_count=inserted_count,
            blocking_request_count=blocking_request_count,
            source_rule_unchanged=True,
        )

    async def _get_rule(self, rule_version: str) -> StoredRuleVersion | None:
        try:
            return await self._rule_versions.get(rule_version)
        except RuleVersionPersistenceError as error:
            raise FactBindingHandoffPersistenceError(
                "Persisted rule version could not be read"
            ) from error

    def _prepare(
        self,
        request: FactBindingRequestV2,
        rule: RuleParseResultV2,
    ) -> PreparedFactBindingHandoff:
        payload = fact_binding_payload(request)
        try:
            validated = FactBindingRequestV2.model_validate(payload)
            self._validator.validate(payload)
            validate_safe_structured_payload(payload)
        except (
            PydanticValidationError,
            JsonSchemaValidationError,
            SemanticValidationErrorV2,
        ) as error:
            raise FactBindingHandoffContractError(
                "Fact binding payload failed the immutable handoff contract"
            ) from error

        expected_request_id = f"{rule.rule_version}#{validated.fact.fact_code}"
        if (
            validated.contract_version != FACT_BINDING_CONTRACT_VERSION_V2
            or validated.request_id != expected_request_id
            or validated.rule_ref.rule_version != rule.rule_version
            or validated.rule_ref.rule_id != rule.rule.rule_id
            or validated.rule_ref.source_sha256 != rule.source.sha256
        ):
            raise FactBindingHandoffContractError(
                "Fact binding payload identity does not match the persisted rule"
            )
        try:
            payload_sha256 = canonical_payload_sha256(payload)
        except (TypeError, ValueError) as error:
            raise FactBindingHandoffContractError(
                "Fact binding payload cannot be canonically serialized"
            ) from error
        return PreparedFactBindingHandoff(
            request_id=validated.request_id,
            rule_version=validated.rule_ref.rule_version,
            fact_code=validated.fact.fact_code,
            contract_version=validated.contract_version,
            payload_sha256=payload_sha256,
            payload=validated,
        )

    @staticmethod
    def _verify_existing_subset(
        expected: tuple[PreparedFactBindingHandoff, ...],
        stored: tuple[StoredFactBindingHandoff, ...],
    ) -> None:
        expected_by_id = {item.request_id: item for item in expected}
        stored_by_id = {item.request_id: item for item in stored}
        if len(expected_by_id) != len(expected) or len(stored_by_id) != len(stored):
            raise FactBindingHandoffVerificationError(
                "Fact binding handoff contains duplicate request IDs"
            )
        for request_id, record in stored_by_id.items():
            prepared = expected_by_id.get(request_id)
            if prepared is None or (
                record.rule_version != prepared.rule_version
                or record.fact_code != prepared.fact_code
                or record.contract_version != prepared.contract_version
                or record.payload_sha256 != prepared.payload_sha256
                or record.payload != prepared.payload
            ):
                raise FactBindingHandoffConflictError(
                    "Existing fact binding handoff differs from the deterministic export"
                )

    @staticmethod
    def _verify_read_back(
        expected: tuple[PreparedFactBindingHandoff, ...],
        stored: tuple[StoredFactBindingHandoff, ...],
    ) -> None:
        expected_by_id = {item.request_id: item for item in expected}
        stored_by_id = {item.request_id: item for item in stored}
        if len(expected_by_id) != len(expected) or len(stored_by_id) != len(stored):
            raise FactBindingHandoffVerificationError(
                "Fact binding handoff contains duplicate request IDs"
            )
        if expected_by_id.keys() != stored_by_id.keys():
            raise FactBindingHandoffVerificationError(
                "Stored fact binding handoff set does not match the deterministic export"
            )
        for request_id, prepared in expected_by_id.items():
            record = stored_by_id[request_id]
            if (
                record.rule_version != prepared.rule_version
                or record.fact_code != prepared.fact_code
                or record.contract_version != prepared.contract_version
                or record.payload_sha256 != prepared.payload_sha256
                or record.payload != prepared.payload
            ):
                raise FactBindingHandoffVerificationError(
                    "Stored fact binding handoff differs from the deterministic export"
                )
