"""Provider-neutral audit contracts for one rule parsing run."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class AuditModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class ProviderTokenUsage(AuditModel):
    """Validated token counters returned by the model provider."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    prompt_cache_hit_tokens: int | None = Field(default=None, ge=0)
    prompt_cache_miss_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class ParseAttemptAudit(AuditModel):
    """Outcome and metering for one provider attempt."""

    attempt: int = Field(ge=1)
    backoff_seconds: float = Field(ge=0)
    outcome_code: str = Field(min_length=1, max_length=100)
    retryable: bool
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=256)
    token_usage: ProviderTokenUsage | None = None


class ParseAudit(AuditModel):
    """Safe, complete audit summary for one parsing operation."""

    request_id: UUID
    idempotency_key_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    max_attempts: int = Field(ge=1)
    attempt_count: int = Field(ge=0)
    total_backoff_seconds: float = Field(ge=0)
    attempts: list[ParseAttemptAudit]
    total_token_usage: ProviderTokenUsage | None = None

    @model_validator(mode="after")
    def validate_attempt_sequence(self) -> ParseAudit:
        if self.attempt_count != len(self.attempts):
            raise ValueError("attemptCount must equal the number of attempts")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attemptCount cannot exceed maxAttempts")
        expected = list(range(1, self.attempt_count + 1))
        actual = [item.attempt for item in self.attempts]
        if actual != expected:
            raise ValueError("attempts must use a contiguous one-based sequence")
        return self
