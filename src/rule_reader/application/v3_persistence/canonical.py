"""Canonical V3 delivery payload serialization and hashing.

The rules are frozen by [DEV-20260906-02](../../../docs/DEV-20260906-02-v3-mongodb-persistence.md):
UTF-8, sorted keys, compact separators, Unicode preserved, NaN forbidden. Time fields never
enter a hash, so retries of the same delivery are byte-stable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from rule_reader.domain.rules.bindings_v3 import FactBindingRequestV3
from rule_reader.domain.rules.result_v3 import RuleParseResultV3

Payload = dict[str, Any]


def result_payload_v3(result: RuleParseResultV3) -> Payload:
    """Return the complete public camelCase JSON payload of one V3 rule version."""

    return result.model_dump(mode="json", by_alias=True)


def request_payload_v3(request: FactBindingRequestV3) -> Payload:
    """Return the complete public camelCase JSON payload of one fact binding request."""

    return request.model_dump(mode="json", by_alias=True)


def canonical_payload_json(payload: Payload) -> str:
    """Serialize one payload with the frozen V3 persistence canonicalization rules."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_payload_sha256(payload: Payload) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


def batch_sha256_v3(identities: Iterable[tuple[str, str]]) -> str:
    """Hash the request identities of one batch, deterministically sorted by requestId.

    ``identities`` are ``(requestId, payloadSha256)`` pairs. Sorting happens here so that
    the batch hash is independent of the caller's input order.
    """

    sorted_identities = sorted(identities, key=lambda item: item[0])
    payload = [
        {"requestId": request_id, "payloadSha256": payload_sha256}
        for request_id, payload_sha256 in sorted_identities
    ]
    return canonical_payload_sha256(payload)  # type: ignore[arg-type]
