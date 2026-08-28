from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rule_reader.core.config import Settings


def test_default_configuration_uses_local_mongodb() -> None:
    settings = Settings(_env_file=None)

    assert settings.mongodb_uri == "mongodb://localhost:27017/"
    assert settings.mongodb_database == "rule_reader"
    assert settings.port == 8000
    assert settings.deepseek_retry_base_delay_seconds == 1.0
    assert settings.deepseek_retry_max_delay_seconds == 8.0
    assert settings.deepseek_idempotency_cache_max_entries == 64


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULEREADER_PORT", "8765")
    monkeypatch.setenv("RULEREADER_MONGODB_DATABASE", "rule_reader_test")

    settings = Settings(_env_file=None)

    assert settings.port == 8765
    assert settings.mongodb_database == "rule_reader_test"


def test_dotenv_file_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RULEREADER_PORT", raising=False)
    monkeypatch.delenv("RULEREADER_DEEPSEEK_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RULEREADER_PORT=8123\nRULEREADER_DEEPSEEK_MODEL=deepseek-test\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.port == 8123
    assert settings.deepseek_model == "deepseek-test"


def test_http_url_is_rejected_for_mongodb() -> None:
    with pytest.raises(ValidationError, match="MongoDB URI must start"):
        Settings(_env_file=None, mongodb_uri="http://localhost:27017/")


def test_public_summary_never_contains_secrets_or_uri() -> None:
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://user:password@localhost:27017/",
        deepseek_api_key="secret-key",
        deepseek_base_url="https://example.invalid",
        deepseek_model="deepseek-model",
    )

    serialized = str(settings.public_summary())

    assert "password" not in serialized
    assert "secret-key" not in serialized
    assert "mongodb://" not in serialized
    assert settings.public_summary()["deepseek"]["api_key_configured"] is True


def test_deepseek_max_retry_delay_cannot_be_less_than_base_delay() -> None:
    with pytest.raises(ValidationError, match="maximum retry delay"):
        Settings(
            _env_file=None,
            deepseek_retry_base_delay_seconds=2,
            deepseek_retry_max_delay_seconds=1,
        )
