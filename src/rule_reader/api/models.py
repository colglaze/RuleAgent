"""Public HTTP response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from rule_reader.domain.rules.bindings import FactBindingRequest
from rule_reader.domain.rules.versioned import RuleDocument


class RootResponse(BaseModel):
    service: str
    version: str
    docs: str


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    service: str
    version: str
    schema_version: int | None = None


class ConfigResponse(BaseModel):
    app: dict[str, Any]
    runtime: dict[str, Any]
    mongodb: dict[str, Any]
    deepseek: dict[str, Any]
    rule_parser: dict[str, Any]


class ParseRuleRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    text: str = Field(min_length=1)
    source_name: str = Field(
        default="inline.md",
        min_length=1,
        max_length=255,
        pattern=r"^[^/\\]+$",
    )
    persist: bool = False


class StoredRuleVersionResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    rule_version: str
    stored_at: datetime
    document: RuleDocument


class FactBindingRequestsResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    rule_version: str
    requests: list[FactBindingRequest]


class ParseErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    details: list[str]


class ParseErrorResponse(BaseModel):
    error: ParseErrorDetail
