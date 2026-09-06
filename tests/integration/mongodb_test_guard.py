"""Offline safety guard for isolated MongoDB integration tests.

Test-only infrastructure: this module lives under ``tests/`` and is never imported by
production code. The guard is a pure function over an explicit environ mapping —
importing it never opens a connection, and no Settings/argv/default fallback exists.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from pymongo.uri_parser import parse_uri

TEST_URI_ENV_VAR = "RULEREADER_TEST_MONGODB_URI"
ALLOW_WRITE_ENV_VAR = "RULEREADER_TEST_MONGODB_ALLOW_WRITE"
ALLOW_WRITE_SENTINEL = "isolated-local-only"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Strict query-option allowlist: anything outside this set could enable topology
# discovery, proxying, or routing now or in future driver releases.
ALLOWED_OPTIONS = frozenset({"directconnection", "authsource", "authmechanism"})


class IsolatedMongoGuardError(RuntimeError):
    """Raised when the integration connection is not an explicitly isolated loopback.

    Messages are sanitized: they never contain the full URI, credentials, the database
    name, or the value of any option or environment variable.
    """

    code = "INTEGRATION_MONGODB_NOT_ISOLATED"


def resolve_isolated_test_uri(environ: Mapping[str, str] | None = None) -> str:
    """Return the explicit, loopback-only, direct-connection test URI after all guards.

    Raises :class:`IsolatedMongoGuardError` unless the environment provides the test URI
    and the exact write sentinel, every URI host is a loopback address, the query string
    only uses allowlisted options, and ``directConnection=true`` is present.
    """

    env = os.environ if environ is None else environ
    uri = env.get(TEST_URI_ENV_VAR)
    if not uri:
        raise IsolatedMongoGuardError(
            f"{TEST_URI_ENV_VAR} is not set; isolated integration requires an explicit "
            "loopback-only mongodb:// URI and must not fall back to Settings or .env"
        )
    if env.get(ALLOW_WRITE_ENV_VAR) != ALLOW_WRITE_SENTINEL:
        raise IsolatedMongoGuardError(
            f"{ALLOW_WRITE_ENV_VAR} must be set to exactly '{ALLOW_WRITE_SENTINEL}' "
            "before integration tests may write to an isolated database"
        )
    if not uri.startswith("mongodb://"):
        # mongodb+srv would trigger DNS resolution inside parse_uri; reject by scheme
        # so the guard itself never performs network activity.
        raise IsolatedMongoGuardError("test MongoDB URI must use the mongodb:// scheme")
    parsed: dict[str, Any]
    try:
        parsed = parse_uri(uri)
    except Exception as error:  # one sanitized boundary for parse failures
        raise IsolatedMongoGuardError("test MongoDB URI could not be parsed") from error
    nodelist = parsed.get("nodelist") or []
    if not nodelist:
        raise IsolatedMongoGuardError("test MongoDB URI does not contain any host")
    for host, _port in nodelist:
        normalized = str(host).strip("[]").lower()
        if normalized not in LOOPBACK_HOSTS:
            raise IsolatedMongoGuardError(
                f"test MongoDB must be loopback-only; rejected host {normalized!r}"
            )
    options: dict[str, Any] = dict(parsed.get("options") or {})
    lowered = {name.lower(): original for name, original in options.items()}
    for original_name in options:
        if original_name.lower() not in ALLOWED_OPTIONS:
            # Only the option name is echoed; values could carry sensitive data.
            raise IsolatedMongoGuardError(
                f"test MongoDB URI option {original_name!r} is not on the strict "
                "allowlist; only directConnection, authSource, and authMechanism "
                "are accepted"
            )
    if lowered.get("replicaset") is not None:
        raise IsolatedMongoGuardError("test MongoDB URI must not contain a replicaSet option")
    if lowered.get("loadbalanced") is not None:
        raise IsolatedMongoGuardError("test MongoDB URI must not contain a loadBalanced option")
    if options.get("directConnection") is not True:
        raise IsolatedMongoGuardError(
            "test MongoDB URI must set directConnection=true so the driver never "
            "performs topology discovery"
        )
    return uri
