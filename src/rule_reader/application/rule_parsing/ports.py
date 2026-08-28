"""Ports owned by the rule parsing application layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from rule_reader.domain.rules.audit import ProviderTokenUsage
from rule_reader.domain.rules.v2 import RuleParseResultV2


@dataclass(frozen=True, slots=True)
class CandidateGeneration:
    """Provider-neutral data accepted from one model response."""

    content: str
    provider_request_id: str
    token_usage: ProviderTokenUsage | None = None


class RuleCandidateModel(Protocol):
    @property
    def model_name(self) -> str: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def generate_candidate(
        self,
        *,
        text: str,
        candidate_schema: dict[str, Any],
        field_catalog: dict[str, Any],
        feedback: tuple[str, ...],
        previous_candidate: str | None,
    ) -> CandidateGeneration: ...


class RuleParserLifecycle(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def parse_text(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        idempotency_key: str | None = None,
    ) -> RuleParseResultV2: ...

    async def parse_to_json(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        idempotency_key: str | None = None,
        indent: int | None = 2,
    ) -> str: ...
