"""Offline tests for the isolated MongoDB integration safety guard.

The guard is a pure function over an explicit environ mapping, so every scenario runs
without network activity and without touching real environment variables.
"""

from __future__ import annotations

import pytest
from tests.integration.mongodb_test_guard import (
    ALLOW_WRITE_ENV_VAR,
    ALLOW_WRITE_SENTINEL,
    TEST_URI_ENV_VAR,
    IsolatedMongoGuardError,
    resolve_isolated_test_uri,
)

LOOPBACK_URI = "mongodb://localhost:27017"


def _env(uri: str | None, allow_write: str | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if uri is not None:
        env[TEST_URI_ENV_VAR] = uri
    if allow_write is not None:
        env[ALLOW_WRITE_ENV_VAR] = allow_write
    return env


def test_guard_constants_are_frozen() -> None:
    assert TEST_URI_ENV_VAR == "RULEREADER_TEST_MONGODB_URI"
    assert ALLOW_WRITE_ENV_VAR == "RULEREADER_TEST_MONGODB_ALLOW_WRITE"
    assert ALLOW_WRITE_SENTINEL == "isolated-local-only"


def test_missing_uri_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="not set"):
        resolve_isolated_test_uri(_env(None, ALLOW_WRITE_SENTINEL))


def test_missing_allow_write_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="isolated-local-only"):
        resolve_isolated_test_uri(_env(LOOPBACK_URI, None))


def test_wrong_allow_write_value_is_rejected_without_echo() -> None:
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(_env(LOOPBACK_URI, "yes-please"))
    # 错误消息不得回显实际收到的环境变量值。
    assert "yes-please" not in str(error.value)


def test_srv_uri_is_rejected_without_dns_lookup() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="mongodb:// scheme"):
        resolve_isolated_test_uri(
            _env("mongodb+srv://cluster.example.com/db", ALLOW_WRITE_SENTINEL)
        )


def test_remote_host_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="loopback-only"):
        resolve_isolated_test_uri(
            _env("mongodb://remote.example.com:27017/db", ALLOW_WRITE_SENTINEL)
        )


def test_multi_node_with_remote_host_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="loopback-only"):
        resolve_isolated_test_uri(
            _env(
                "mongodb://localhost:27017,10.0.0.5:27017/db",
                ALLOW_WRITE_SENTINEL,
            )
        )


@pytest.mark.parametrize(
    "uri",
    [
        "not-a-uri",
        "mongodb://",
        "mongodb://user:pass@remote.example.com:27017/db?authSource=admin",
    ],
)
def test_unparsable_or_invalid_uri_is_rejected_and_sanitized(uri: str) -> None:
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(_env(uri, ALLOW_WRITE_SENTINEL))
    message = str(error.value)
    # 错误消息不得包含完整 URI、用户名或密码。
    assert uri not in message
    assert "user" not in message
    assert "pass" not in message


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://localhost:27017",
        "mongodb://127.0.0.1:27017/rule_reader_test_x",
        "mongodb://[::1]:27017/rule_reader_test_x",
    ],
)
def test_loopback_uris_without_direct_connection_are_rejected(uri: str) -> None:
    # 拓扑收紧: 缺少 directConnection=true 的 loopback URI 不再通过。
    with pytest.raises(IsolatedMongoGuardError, match="directConnection"):
        resolve_isolated_test_uri(_env(uri, ALLOW_WRITE_SENTINEL))


def test_authenticated_loopback_without_direct_connection_is_rejected() -> None:
    # 收紧后, 仅 authSource 不够: 缺少 directConnection=true 仍被拒绝。
    uri = "mongodb://integration-user:integration-pass@localhost:27017/db?authSource=admin"
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(_env(uri, ALLOW_WRITE_SENTINEL))
    message = str(error.value)
    assert "integration-user" not in message
    assert "integration-pass" not in message
    assert "mongodb://" not in message

    # 失败路径的错误输出不得回显凭据。
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(
            _env(
                "mongodb://integration-user:integration-pass@remote.example.com:27017/db",
                ALLOW_WRITE_SENTINEL,
            )
        )
    message = str(error.value)
    assert "integration-user" not in message
    assert "integration-pass" not in message
    assert "mongodb://" not in message


def test_missing_direct_connection_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="directConnection"):
        resolve_isolated_test_uri(_env(LOOPBACK_URI, ALLOW_WRITE_SENTINEL))


def test_direct_connection_false_is_rejected() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="directConnection"):
        resolve_isolated_test_uri(
            _env("mongodb://localhost:27017/?directConnection=false", ALLOW_WRITE_SENTINEL)
        )


def test_replica_set_is_rejected_regardless_of_value() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="replicaSet"):
        resolve_isolated_test_uri(
            _env("mongodb://localhost:27017/?replicaSet=prod", ALLOW_WRITE_SENTINEL)
        )


def test_load_balanced_is_rejected_regardless_of_value() -> None:
    with pytest.raises(IsolatedMongoGuardError, match="loadBalanced"):
        resolve_isolated_test_uri(
            _env("mongodb://localhost:27017/?loadBalanced=true", ALLOW_WRITE_SENTINEL)
        )


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "[::1]"],
)
def test_direct_connection_true_loopback_uris_pass(host: str) -> None:
    uri = f"mongodb://{host}:27017/rule_reader_test_x?directConnection=true"
    assert resolve_isolated_test_uri(_env(uri, ALLOW_WRITE_SENTINEL)) == uri


def test_authenticated_loopback_with_direct_connection_passes() -> None:
    uri = (
        "mongodb://integration-user:integration-pass@localhost:27017/db"
        "?authSource=admin&authMechanism=SCRAM-SHA-256&directConnection=true"
    )
    assert resolve_isolated_test_uri(_env(uri, ALLOW_WRITE_SENTINEL)) == uri


def test_options_outside_allowlist_are_rejected_without_echoing_values() -> None:
    # tls 是 pymongo 已知选项, 但不在门禁 allowlist 中; secretToken 这类未知选项
    # 会在 parse 层被拒绝并由脱敏边界转换为固定错误。
    with pytest.raises(IsolatedMongoGuardError, match="option") as error:
        resolve_isolated_test_uri(
            _env(
                "mongodb://localhost:27017/?directConnection=true&journal=false",
                ALLOW_WRITE_SENTINEL,
            )
        )
    message = str(error.value)
    # 错误消息不得回显 option 的实际值或完整 URI。
    assert "false" not in message
    assert "mongodb://" not in message

    with pytest.raises(IsolatedMongoGuardError, match="could not be parsed"):
        resolve_isolated_test_uri(
            _env(
                "mongodb://localhost:27017/?directConnection=true&secretToken=hunter2",
                ALLOW_WRITE_SENTINEL,
            )
        )


def test_rejected_option_message_does_not_leak_replica_set_name() -> None:
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(
            _env(
                "mongodb://localhost:27017/?directConnection=true&replicaSet=super-secret-rs",
                ALLOW_WRITE_SENTINEL,
            )
        )
    message = str(error.value)
    assert "super-secret-rs" not in message
    assert "mongodb://" not in message


def test_rejected_option_message_does_not_leak_uri_or_credentials() -> None:
    with pytest.raises(IsolatedMongoGuardError) as error:
        resolve_isolated_test_uri(
            _env(
                "mongodb://integration-user:integration-pass@localhost:27017/db"
                "?authSource=admin&directConnection=false",
                ALLOW_WRITE_SENTINEL,
            )
        )
    message = str(error.value)
    assert "integration-user" not in message
    assert "integration-pass" not in message
    assert "mongodb://" not in message
