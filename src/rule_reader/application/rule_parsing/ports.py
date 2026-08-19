"""Ports owned by the rule parsing application layer."""

from __future__ import annotations

from typing import Any, Protocol

from rule_reader.domain.rules.models import RuleParseResult


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
    ) -> str: ...


class RuleParserLifecycle(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def parse_text(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
    ) -> RuleParseResult: ...

    async def parse_to_json(
        self,
        text: str,
        *,
        source_name: str,
        relative_path: str | None = None,
        indent: int | None = 2,
    ) -> str: ...
