"""Typed, centralized application configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rule_reader.core.version import SUPPORTED_PYTHON


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Read configuration from environment variables and an optional local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RULEREADER_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="RuleReader", min_length=1, max_length=100)
    environment: Environment = Environment.DEVELOPMENT
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"
    reload: bool = False

    mongodb_uri: str = "mongodb://localhost:27017/"
    mongodb_database: str = Field(default="rule_reader", min_length=1, max_length=63)
    mongodb_server_selection_timeout_ms: int = Field(default=5000, ge=100, le=120_000)
    mongodb_connect_timeout_ms: int = Field(default=5000, ge=100, le=120_000)

    document_root: Path = Path("documents")
    rule_max_characters: int = Field(default=100_000, ge=1_000, le=1_000_000)

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: AnyHttpUrl | None = None
    deepseek_model: str | None = None
    deepseek_timeout_seconds: float = Field(default=90.0, ge=1.0, le=600.0)
    deepseek_max_retries: int = Field(default=2, ge=0, le=5)
    deepseek_max_output_tokens: int = Field(default=16_384, ge=1_024, le=65_536)

    @field_validator("mongodb_uri")
    @classmethod
    def validate_mongodb_uri(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError(
                "MongoDB URI must start with mongodb:// or mongodb+srv://; HTTP URLs are invalid"
            )
        return normalized

    @field_validator("mongodb_database")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        normalized = value.strip()
        forbidden = set('/\\ ."$*<>:|?')
        if not normalized or any(character in forbidden for character in normalized):
            raise ValueError("MongoDB database name contains forbidden characters")
        return normalized

    @field_validator(
        "deepseek_api_key",
        "deepseek_base_url",
        "deepseek_model",
        mode="before",
    )
    @classmethod
    def blank_optional_values_are_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def public_summary(self) -> dict[str, Any]:
        """Return configuration safe for logs, CLI output, and public diagnostics."""

        return {
            "app": {
                "name": self.app_name,
                "environment": self.environment.value,
                "host": self.host,
                "port": self.port,
                "log_level": self.log_level,
                "reload": self.reload,
            },
            "runtime": {
                "python_required": ".".join(str(part) for part in SUPPORTED_PYTHON),
            },
            "mongodb": {
                "database": self.mongodb_database,
                "server_selection_timeout_ms": self.mongodb_server_selection_timeout_ms,
                "connect_timeout_ms": self.mongodb_connect_timeout_ms,
            },
            "deepseek": {
                "api_key_configured": self.deepseek_api_key is not None,
                "base_url_configured": self.deepseek_base_url is not None,
                "model": self.deepseek_model,
                "timeout_seconds": self.deepseek_timeout_seconds,
                "max_retries": self.deepseek_max_retries,
                "max_output_tokens": self.deepseek_max_output_tokens,
            },
            "rule_parser": {
                "max_characters": self.rule_max_characters,
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings object."""

    return Settings()
